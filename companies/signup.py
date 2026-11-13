"""Parcours d'entrée : recherche d'entreprise, puis cockpit de cette société.

La vérification email + SMS est une étape réelle, court-circuitée tant que
SIGNUP_VERIFICATION_ENABLED est faux (défaut). Aucun JSON brut d'API
n'est écrit dans la session (cookie signé, taille limitée).
"""
from __future__ import annotations

import logging
from datetime import date, datetime

from django import forms
from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.hashers import make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from django.urls import reverse

from admin_backoffice.email_templates import display_name, send_template_email
from core.public_theme import themed_redirect, themed_reverse, themed_template
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounting.services import generate_portal
from accounts.models import PendingSignup, User
from accounts.verification import (
    PhoneError,
    normalize_french_phone,
    send_phone_verification,
    send_signup_link,
)
from companies.models import Company
from companies.views import FORME_CHOICES, CompanyProfileForm
from core.demo import DEMO_EMAIL
from integrations.insee import official_card, search_entreprises

logger = logging.getLogger(__name__)

SIGNUP_SESSION_KEY = "signup_lookup"

SEARCH_MESSAGES = {
    "invalid": (
        "Saisissez le nom de la société (au moins 2 caractères), "
        "un SIREN (9 chiffres) ou un SIRET (14 chiffres)."
    ),
    "rate_limit": (
        "L'annuaire des entreprises est très sollicité en ce moment. "
        "Patientez quelques instants, puis relancez la recherche."
    ),
    "error": (
        "L'annuaire des entreprises est momentanément indisponible. "
        "Réessayez dans quelques minutes."
    ),
    "empty": (
        "Aucune société ne correspond à cette recherche. "
        "Vérifiez l'orthographe, le SIREN ou le SIRET."
    ),
}

SIREN_TAKEN = (
    "Cette société est déjà rattachée à un compte. "
    "Connectez-vous pour y accéder : elle ne peut pas être créée une seconde fois."
)


class SignupProfileForm(CompanyProfileForm):
    """Même questionnaire comptable que l'ajout de société, avec email, téléphone et mot de passe."""

    password1 = forms.CharField(
        label="Mot de passe",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        error_messages={"required": "Choisissez un mot de passe."},
    )
    password2 = forms.CharField(
        label="Confirmation du mot de passe",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        error_messages={"required": "Confirmez le mot de passe."},
    )

    def __init__(self, *args, require_password=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].required = True
        self.fields["phone"].required = True
        self.fields["email"].label = "Email"
        self.fields["phone"].label = "Téléphone"
        self.fields["phone"].widget.input_type = "tel"
        self.fields["phone"].widget.attrs.update({
            "autocomplete": "tel",
            "inputmode": "tel",
            "placeholder": "06 12 34 56 78",
        })
        self.fields["email"].widget.input_type = "email"
        self.fields["email"].widget.attrs.update({
            "autocomplete": "email",
            "placeholder": "vous@exemple.fr",
        })
        self.require_password = require_password
        if not require_password:
            self.fields.pop("password1", None)
            self.fields.pop("password2", None)
        else:
            self.fields["password1"].help_text = "8 caractères minimum. Il sert à retrouver votre cockpit."
        activities = forms.CheckboxSelectMultiple()
        activities.choices = self.fields["activites"].choices
        self.fields["activites"].widget = activities

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if email == DEMO_EMAIL:
            raise forms.ValidationError(
                "Cette adresse est réservée à la démonstration. Utilisez « Essayer la démo »."
            )
        return email

    def clean_phone(self):
        try:
            return normalize_french_phone(self.cleaned_data.get("phone") or "")
        except PhoneError as exc:
            raise forms.ValidationError(str(exc)) from exc

    def clean(self):
        cleaned = super().clean()
        if "password1" not in self.fields:
            return cleaned
        first = cleaned.get("password1") or ""
        second = cleaned.get("password2") or ""
        if first and second and first != second:
            self.add_error("password2", "Les deux mots de passe ne correspondent pas.")
            return cleaned
        if not first:
            return cleaned
        email = cleaned.get("email") or ""
        existing = User.objects.filter(email__iexact=email).first() if email else None
        if existing is None or not existing.has_usable_password():
            try:
                validate_password(first, existing)
            except ValidationError as exc:
                self.add_error("password1", exc)
        return cleaned


def _session_lookup(card: dict) -> dict:
    return {
        "siren": card["siren"],
        "data": card,
        "error": None,
        "origin": "annuaire",
        "fetched_at": timezone.now().isoformat(),
    }


def _strip_session(request):
    for key in (
        SIGNUP_SESSION_KEY,
        "signup_pending_id",
        "signup_sms_sent",
        "signup_phone_status",
        "signup_debug_url",
        "signup_debug_code",
    ):
        request.session.pop(key, None)


@require_GET
def company_search(request):
    """Résultats de l'annuaire public (nom, SIREN ou SIRET)."""
    query = (request.GET.get("q") or "").strip()
    if not query:
        return themed_redirect(request, "landing")
    results, error = search_entreprises(query)
    message = SEARCH_MESSAGES.get(error or "")
    if not error and not results:
        message = SEARCH_MESSAGES["empty"]
    return render(request, themed_template(request, "companies/search_results.html"), {
        "query": query[:80],
        "results": results,
        "error_message": message,
    })


@require_GET
def signup_start(request):
    """Mémorise la fiche officielle choisie, sans le JSON brut de l'API."""
    siren = "".join(char for char in (request.GET.get("siren") or "") if char.isdigit())
    if len(siren) != 9:
        return themed_redirect(request, "landing")
    card, error = official_card(siren)
    if error or not card:
        return render(request, themed_template(request, "companies/search_results.html"), {
            "query": siren,
            "results": [],
            "error_message": SEARCH_MESSAGES.get(error or "empty", SEARCH_MESSAGES["error"]),
        })
    lookup = _session_lookup(card)
    if request.user.is_authenticated:
        request.session["onboarding_lookup"] = lookup
        return redirect("onboarding_confirm")
    request.session[SIGNUP_SESSION_KEY] = lookup
    return themed_redirect(request, "signup_wizard")


def _wizard_initial(data: dict, user) -> dict:
    forme = data.get("forme") if data.get("forme") in dict(FORME_CHOICES) else "SARL"
    suggested = data.get("activite_suggeree")
    initial = {
        "denomination": data.get("denomination", ""),
        "forme": forme,
        "activites": [suggested] if suggested else ["artisan_autre"],
        "exercice_debut": date(date.today().year, 1, 1),
        "email": "",
        "phone": "",
    }
    if user is not None and user.is_authenticated:
        initial["email"] = user.email
        initial["phone"] = user.phone or ""
    return initial


def _build_payload(data: dict, cleaned: dict, fetched_at: str) -> dict:
    return {
        "siren": data["siren"],
        "siret": data.get("siret") or "",
        "denomination": cleaned["denomination"],
        "forme": cleaned["forme"],
        "adresse": data.get("adresse") or "",
        "code_naf": data.get("code_naf") or "",
        "categorie_juridique": data.get("categorie_juridique") or "",
        "activites": list(cleaned["activites"]),
        "regime": cleaned["regime"],
        "tva": cleaned["tva"],
        "exercice_debut": cleaned["exercice_debut"].isoformat(),
        "date_creation": data.get("date_creation") or "",
        "etat": data.get("etat") or "",
        "tranche_effectifs": data.get("tranche_effectifs") or "",
        "fetched_at": fetched_at or "",
    }


def _apply_phone(user, phone: str, phone_verified: bool):
    updates = []
    if phone and user.phone != phone:
        user.phone = phone[:20]
        updates.append("phone")
    if phone_verified and not user.phone_verified:
        user.phone_verified = True
        updates.append("phone_verified")
    if updates:
        user.save(update_fields=updates)


def _assign_password(user, *, password, password_hash, created):
    """Pose le hash Django. Ne remplace pas un mot de passe existant qui ne correspond pas."""
    if password:
        if user.has_usable_password() and not created:
            return user.check_password(password)
        user.set_password(password)
        user.save(update_fields=["password"])
        return True
    if password_hash and (created or not user.has_usable_password()):
        user.password = password_hash
        user.save(update_fields=["password"])
    return True


def complete_signup(*, email, phone, payload, phone_verified=False, owner=None, password=None):
    """Crée l'utilisateur s'il le faut, puis la société et son portail comptable.

    Retourne ((user, company), None) ou (None, "taken"|"auth"|"invalid").
    """
    siren = str(payload.get("siren") or "")
    if len(siren) != 9 or not siren.isdigit():
        return None, "invalid"
    email = (email or "").strip().lower()
    password_hash = payload.get("password_hash") or ""
    if owner is None and password:
        existing = User.objects.filter(email__iexact=email).first()
        if existing and existing.has_usable_password() and not existing.check_password(password):
            return None, "auth"
    exercice = payload.get("exercice_debut")
    if isinstance(exercice, str):
        exercice = datetime.strptime(exercice, "%Y-%m-%d").date()
    try:
        with transaction.atomic():
            if Company.objects.filter(siren=siren).exists():
                return None, "taken"
            if owner is None:
                user = User.objects.filter(email__iexact=email).first()
                created = user is None
                if created:
                    user = User.objects.create_user(email)
                if not _assign_password(
                    user,
                    password=password,
                    password_hash=password_hash,
                    created=created,
                ):
                    transaction.set_rollback(True)
                    return None, "auth"
            else:
                user = owner
            _apply_phone(user, phone, phone_verified)
            company = Company.objects.create(
                owner=user,
                siren=siren,
                denomination=(payload.get("denomination") or "")[:255],
                forme=(payload.get("forme") or "SARL")[:10],
                address=(payload.get("adresse") or "")[:255],
                phone=(phone or "")[:30],
                email=(email or "")[:254],
                code_naf=(payload.get("code_naf") or "")[:10],
                activites=list(payload.get("activites") or []),
                regime=payload["regime"],
                tva=payload["tva"],
                exercice_debut=exercice,
                source_data={
                    "source": "annuaire_entreprises",
                    "fetched_at": payload.get("fetched_at") or "",
                    "siren": siren,
                    "siret": (payload.get("siret") or "")[:14],
                },
            )
            generate_portal(company)
    except IntegrityError:
        return None, "taken"
    return (user, company), None


def _send_welcome(request, user, company):
    """Email de bienvenue : jamais bloquant pour l'ouverture du cockpit."""
    try:
        login_url = request.build_absolute_uri(themed_reverse(request, "magic_link_request"))
        send_template_email(
            "welcome",
            user.email,
            {
                "name": display_name(user),
                "email": user.email,
                "company_name": company.denomination,
                "login_url": login_url,
            },
            request=request,
        )
    except Exception:
        logger.exception("Email de bienvenue non envoyé")


def _open_cockpit(request, user, company):
    if not request.user.is_authenticated or request.user.pk != user.pk:
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    _strip_session(request)
    request.session["societe_id"] = str(company.id)
    return redirect(reverse("cockpit") + f"?societe={company.id}")


def _render_wizard(request, form, lookup, siren_taken=False):
    data = lookup.get("data") or {}
    return render(request, themed_template(request, "companies/signup_wizard.html"), {
        "form": form,
        "siren": lookup.get("siren"),
        "data": data,
        "siren_taken": siren_taken,
        "verification_enabled": settings.SIGNUP_VERIFICATION_ENABLED,
        "error_message": SIREN_TAKEN if siren_taken else None,
    })


@require_http_methods(["GET", "POST"])
def signup_wizard(request):
    """Confirme la fiche officielle, l'email, le téléphone et le régime."""
    lookup = request.session.get(SIGNUP_SESSION_KEY)
    if not lookup or not lookup.get("siren"):
        return themed_redirect(request, "landing")
    data = lookup.get("data") or {}
    siren = lookup["siren"]
    taken = Company.objects.filter(siren=siren).exists()
    if request.user.is_authenticated and Company.objects.filter(owner=request.user, siren=siren).exists():
        company = Company.objects.get(owner=request.user, siren=siren)
        return _open_cockpit(request, request.user, company)

    require_password = not request.user.is_authenticated
    if request.method == "POST" and not taken:
        form = SignupProfileForm(request.POST, require_password=require_password)
        posted_siren = "".join(char for char in (request.POST.get("siren") or "") if char.isdigit())
        if posted_siren != siren:
            form.add_error(None, "La société confirmée ne correspond plus à la recherche. Recommencez.")
        elif form.is_valid():
            cleaned = form.cleaned_data
            if Company.objects.filter(siren=siren).exists():
                return _render_wizard(request, form, lookup, siren_taken=True)
            payload = _build_payload(data, cleaned, lookup.get("fetched_at") or "")
            if request.user.is_authenticated or not settings.SIGNUP_VERIFICATION_ENABLED:
                result, err = complete_signup(
                    email=cleaned["email"],
                    phone=cleaned["phone"],
                    payload=payload,
                    owner=request.user if request.user.is_authenticated else None,
                    password=None if request.user.is_authenticated else cleaned.get("password1"),
                )
                if err == "taken":
                    return _render_wizard(request, form, lookup, siren_taken=True)
                if err == "auth":
                    form.add_error(
                        "password1",
                        "Le mot de passe ne correspond pas au compte déjà ouvert pour cette adresse.",
                    )
                    return _render_wizard(request, form, lookup, siren_taken=False)
                user, company = result
                if not request.user.is_authenticated:
                    _send_welcome(request, user, company)
                return _open_cockpit(request, user, company)
            return _begin_verification(request, form, lookup, payload, cleaned)
    else:
        form = SignupProfileForm(
            initial=_wizard_initial(data, request.user),
            require_password=require_password,
        )
    return _render_wizard(request, form, lookup, siren_taken=taken)


def _begin_verification(request, form, lookup, payload, cleaned):
    """Étape email + SMS. Le SMS reste un crochet tant qu'aucun opérateur n'est branché."""
    existing = User.objects.filter(email__iexact=cleaned["email"]).first()
    if existing and existing.has_usable_password() and not existing.check_password(cleaned["password1"]):
        form.add_error(
            "password1",
            "Le mot de passe ne correspond pas au compte déjà ouvert pour cette adresse.",
        )
        return _render_wizard(request, form, lookup, siren_taken=False)
    if not (existing and existing.has_usable_password()):
        payload = dict(payload)
        payload["password_hash"] = make_password(cleaned["password1"])
    pending = None
    try:
        raw, code, pending = PendingSignup.issue(
            email=cleaned["email"],
            phone=cleaned["phone"],
            siren=lookup["siren"],
            payload=payload,
        )
        url = send_signup_link(request, cleaned["email"], raw)
    except Exception:
        logger.exception("Envoi du lien d'inscription impossible")
        if pending is not None and pending.pk:
            pending.delete()
        form.add_error(
            None,
            "L'email de vérification n'a pas pu être envoyé. Réessayez dans un instant.",
        )
        return _render_wizard(request, form, lookup, siren_taken=False)
    sms_sent = send_phone_verification(cleaned["phone"], code)
    request.session["signup_pending_id"] = pending.pk
    request.session["signup_sms_sent"] = bool(sms_sent)
    request.session.pop("signup_phone_status", None)
    if settings.DEBUG:
        request.session["signup_debug_url"] = url
        request.session["signup_debug_code"] = code
    else:
        request.session.pop("signup_debug_url", None)
        request.session.pop("signup_debug_code", None)
    return themed_redirect(request, "signup_pending")


def _pending_from_session(request):
    pending_id = request.session.get("signup_pending_id")
    if not pending_id:
        return None
    pending = PendingSignup.objects.filter(pk=pending_id, consumed_at__isnull=True).first()
    if pending is None or pending.expires_at < timezone.now():
        return None
    return pending


@require_GET
def signup_pending(request):
    """Page d'attente : lien email envoyé, SMS en attente d'un fournisseur."""
    pending = _pending_from_session(request)
    if pending is None:
        return themed_redirect(request, "signup_wizard")
    return render(request, themed_template(request, "companies/signup_verify.html"), {
        "pending": pending,
        "sms_sent": bool(request.session.get("signup_sms_sent")),
        "phone_status": request.session.pop("signup_phone_status", ""),
        "debug_url": request.session.get("signup_debug_url", "") if settings.DEBUG else "",
        "debug_code": request.session.get("signup_debug_code", "") if settings.DEBUG else "",
    })


@require_POST
def signup_phone_check(request):
    """Contrôle le code SMS si un fournisseur en a réellement envoyé un."""
    pending = _pending_from_session(request)
    if pending is None:
        return themed_redirect(request, "signup_wizard")
    if not request.session.get("signup_sms_sent"):
        request.session["signup_phone_status"] = "unavailable"
        return themed_redirect(request, "signup_pending")
    if pending.check_phone_code(request.POST.get("code") or ""):
        pending.phone_verified = True
        pending.save(update_fields=["phone_verified"])
        request.session["signup_phone_status"] = "ok"
    else:
        request.session["signup_phone_status"] = "bad"
    return themed_redirect(request, "signup_pending")


@require_GET
def signup_verify(request, token):
    """Consomme le lien email et ouvre le cockpit de la société choisie."""
    pending = PendingSignup.lookup(token)
    if pending is None:
        return render(request, themed_template(request, "companies/signup_invalid.html"), status=410)
    payload = pending.payload or {}
    if payload.get("siren") != pending.siren:
        return render(request, themed_template(request, "companies/signup_invalid.html"), status=410)
    result, err = complete_signup(
        email=pending.email,
        phone=pending.phone,
        payload=payload,
        phone_verified=pending.phone_verified,
    )
    pending.consumed_at = timezone.now()
    pending.save(update_fields=["consumed_at"])
    if err == "taken":
        existing = Company.objects.filter(siren=pending.siren).select_related("owner").first()
        if existing and existing.owner.email.lower() == pending.email.lower():
            return _open_cockpit(request, existing.owner, existing)
        return render(request, themed_template(request, "companies/signup_taken.html"), {"siren": pending.siren})
    if result is None:
        return render(request, themed_template(request, "companies/signup_invalid.html"), status=410)
    user, company = result
    _send_welcome(request, user, company)
    return _open_cockpit(request, user, company)

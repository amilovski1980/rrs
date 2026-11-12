from datetime import date

from django import forms
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from integrations.insee import lookup_siren

from accounting.reports import cockpit_figures
from core.context import resolve_company

from django.http import HttpResponse

from .models import INVOICE_THEMES, Company

ACTIVITIES_CHOICES = [
    ("btp", "BTP"),
    ("plomberie", "Plomberie"),
    ("electricite", "Électricité"),
    ("coiffure", "Coiffure"),
    ("resto", "Restauration"),
    ("artisan_autre", "Autre artisanat"),
]

REGIME_CHOICES = [("micro", "Micro-BIC"), ("reel_simple", "Réel simplifié")]
TVA_CHOICES = [("franchise", "Franchise en base"), ("reel", "TVA (CA3/CA12)")]
FORME_CHOICES = [
    ("SARL", "SARL"),
    ("EURL", "EURL"),
    ("SAS", "SAS"),
    ("SASU", "SASU"),
    ("EI", "Entreprise individuelle"),
    ("SCI", "SCI"),
]

LOOKUP_ERRORS = {
    "not_configured": (
        "L'API Sirene INSEE n'est pas encore configurée sur cet environnement. "
        "Vous pouvez compléter les informations manuellement."
    ),
    "not_found": (
        "Ce SIREN est introuvable dans la base Sirene. Vérifiez la saisie ou "
        "complétez les informations manuellement."
    ),
    "error": (
        "L'API Sirene est momentanément indisponible. Réessayez plus tard ou "
        "complétez les informations manuellement."
    ),
}


class SirenForm(forms.Form):
    siren = forms.CharField(
        label="Numéro SIREN",
        max_length=9,
        min_length=9,
        widget=forms.TextInput(
            attrs={"inputmode": "numeric", "placeholder": "123 456 789", "autofocus": True}
        ),
    )

    def clean_siren(self):
        siren = "".join(c for c in self.cleaned_data["siren"] if c.isdigit())
        if len(siren) != 9:
            raise forms.ValidationError("Le SIREN doit contenir exactement 9 chiffres.")
        return siren


class CompanyProfileForm(forms.Form):
    denomination = forms.CharField(label="Dénomination", max_length=255)
    forme = forms.ChoiceField(label="Forme juridique", choices=FORME_CHOICES)
    activites = forms.MultipleChoiceField(
        label="Activités", choices=ACTIVITIES_CHOICES,
    )
    regime = forms.ChoiceField(label="Régime fiscal", choices=REGIME_CHOICES)
    tva = forms.ChoiceField(label="TVA", choices=TVA_CHOICES)
    exercice_debut = forms.DateField(
        label="Date de début d'exercice",
        initial=date(date.today().year, 1, 1),
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    phone = forms.CharField(label="Téléphone", max_length=30, required=False)
    email = forms.EmailField(label="Email de facturation", required=False)


def landing(request):
    """Vitrine publique : promesse produit, tarifs, CTA connexion."""
    return render(request, "landing.html")


@login_required
def cockpit(request):
    """Pilotage d'une société : chiffres, dernières écritures, factures ouvertes."""
    companies = Company.objects.filter(owner=request.user)
    selected = resolve_company(request)
    figures = cockpit_figures(selected) if selected else None
    open_invoices = []
    if selected:
        open_invoices = list(
            selected.invoices.filter(status__in=["draft", "issued", "late", "received"])[:6]
        )
    return render(request, "companies/cockpit.html", {
        "companies": companies,
        "selected": selected,
        "figures": figures,
        "open_invoices": open_invoices,
    })


@login_required
def onboarding(request):
    """Étape 1 : saisie du SIREN. Les données légales sont récupérées via INSEE."""
    form = SirenForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        siren = form.cleaned_data["siren"]
        if Company.objects.filter(owner=request.user, siren=siren).exists():
            form.add_error("siren", "Cette société est déjà dans votre cockpit.")
        else:
            data, error = lookup_siren(siren)
            if isinstance(data, dict):
                # Le cookie de session est trop petit pour le JSON brut de l'API.
                data = {key: value for key, value in data.items() if key != "raw"}
            request.session["onboarding_lookup"] = {
                "siren": siren,
                "data": data,
                "error": error,
                "fetched_at": timezone.now().isoformat(),
            }
            return redirect("onboarding_confirm")
    return render(request, "companies/onboarding.html", {"form": form})


@login_required
def onboarding_confirm(request):
    """Étape 2 : validation des données INSEE + questionnaire métier."""
    lookup = request.session.get("onboarding_lookup")
    if not lookup:
        return redirect("onboarding")

    data = lookup.get("data") or {}
    error = lookup.get("error")
    siren = lookup["siren"]

    initial = {
        "denomination": data.get("denomination", ""),
        "forme": data.get("forme") if data.get("forme") in dict(FORME_CHOICES) else "SARL",
        "activites": [data["activite_suggeree"]] if data.get("activite_suggeree") else ["artisan_autre"],
        "exercice_debut": date(date.today().year, 1, 1),
    }

    if request.method == "POST":
        form = CompanyProfileForm(request.POST)
        if form.is_valid():
            if Company.objects.filter(owner=request.user, siren=siren).exists():
                form.add_error(None, "Cette société est déjà dans votre cockpit.")
            elif Company.objects.filter(siren=siren).exists():
                form.add_error(
                    None,
                    "Ce SIREN est déjà rattaché à un autre compte. "
                    "Connectez-vous avec ce compte, ou choisissez une autre société.",
                )
            else:
                cleaned = form.cleaned_data
                if lookup.get("origin") == "annuaire":
                    source_name = "annuaire_entreprises"
                elif data:
                    source_name = "insee_sirene"
                else:
                    source_name = "manuel"
                source = {
                    "source": source_name,
                    "fetched_at": lookup.get("fetched_at"),
                    "siren": siren,
                    "siret": (data.get("siret") or "") if data else "",
                }
                try:
                    with transaction.atomic():
                        company = Company.objects.create(
                            owner=request.user,
                            siren=siren,
                            denomination=cleaned["denomination"],
                            forme=cleaned["forme"],
                            address=data.get("adresse", ""),
                            phone=cleaned.get("phone", ""),
                            email=cleaned.get("email", ""),
                            code_naf=data.get("code_naf", ""),
                            activites=list(cleaned["activites"]),
                            regime=cleaned["regime"],
                            tva=cleaned["tva"],
                            exercice_debut=cleaned["exercice_debut"],
                            source_data=source,
                        )
                        from accounting.services import generate_portal

                        generate_portal(company)
                except IntegrityError:
                    form.add_error(
                        None,
                        "Ce SIREN est déjà rattaché à un autre compte.",
                    )
                else:
                    request.session.pop("onboarding_lookup", None)
                    return redirect(reverse("cockpit") + f"?societe={company.id}")
    else:
        form = CompanyProfileForm(initial=initial)

    return render(
        request,
        "companies/onboarding_confirm.html",
        {
            "form": form,
            "siren": siren,
            "data": data,
            "error_message": LOOKUP_ERRORS.get(error) if error else None,
        },
    )


class CompanySettingsForm(forms.ModelForm):
    logo = forms.FileField(label="Logo", required=False)

    class Meta:
        model = Company
        fields = ("denomination", "forme", "address", "phone", "email", "invoice_theme")
        labels = {
            "denomination": "Dénomination",
            "forme": "Forme juridique",
            "address": "Adresse",
            "phone": "Téléphone",
            "email": "Email de facturation",
            "invoice_theme": "Modèle de facture",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["forme"].widget = forms.Select(choices=FORME_CHOICES)
        self.fields["phone"].widget.input_type = "tel"
        self.fields["phone"].widget.attrs.update(
            {"autocomplete": "tel", "inputmode": "tel"}
        )
        self.fields["email"].widget.input_type = "email"
        self.fields["email"].widget.attrs.update(
            {"autocomplete": "email", "inputmode": "email"}
        )

    def clean_logo(self):
        upload = self.cleaned_data.get("logo")
        if not upload:
            return upload
        if upload.size > 800_000:
            raise forms.ValidationError("Le logo ne doit pas dépasser 800 Ko.")
        kind = getattr(upload, "content_type", "") or ""
        if kind not in ("image/png", "image/jpeg", "image/webp"):
            raise forms.ValidationError("Utilisez un fichier PNG, JPEG ou WebP.")
        return upload


def _company_or_redirect(request):
    company = resolve_company(request)
    if company is None:
        return None, redirect("onboarding")
    return company, None


@login_required
def company_settings(request):
    """Logo, coordonnées et modèle de facture."""
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    if request.method == "POST" and request.POST.get("theme") and "denomination" not in request.POST:
        theme = request.POST.get("theme")
        if theme in dict(INVOICE_THEMES):
            company.invoice_theme = theme
            company.save(update_fields=["invoice_theme"])
        nxt = request.POST.get("next") or ""
        if not nxt.startswith("/") or nxt.startswith("//"):
            nxt = reverse("company_settings") + f"?societe={company.id}"
        return redirect(nxt)
    form = CompanySettingsForm(request.POST or None, request.FILES or None, instance=company)
    if request.method == "POST" and form.is_valid():
        company = form.save()
        if request.POST.get("remove_logo"):
            company.logo = None
            company.logo_type = ""
            company.save(update_fields=["logo", "logo_type"])
        upload = form.cleaned_data.get("logo")
        if upload:
            company.logo = upload.read()
            company.logo_type = upload.content_type
            company.save(update_fields=["logo", "logo_type"])
        return redirect(reverse("company_settings") + f"?societe={company.id}")
    return render(request, "companies/settings.html", {
        "company": company,
        "form": form,
        "themes": INVOICE_THEMES,
    })


@login_required
def company_logo(request):
    company, bounce = _company_or_redirect(request)
    if bounce or not company.logo:
        return HttpResponse(status=404)
    kind = company.logo_type or "image/png"
    response = HttpResponse(bytes(company.logo), content_type=kind)
    response["Cache-Control"] = "private, max-age=3600"
    return response


@login_required
def help_page(request):
    """Page d'aide du cockpit (contenu rédactionnel minimal)."""
    return render(request, "companies/help.html")


def legal_notice(request):
    """Mentions légales — placeholders à compléter par le propriétaire."""
    return render(request, "companies/legal_notice.html")


"""Vues du connecteur e-mail (Django templates, comme le reste du cockpit)."""

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_POST

from core.context import resolve_company

from . import oauth
from .forms import DraftValidationForm, MailboxConfigForm
from .models import MailboxConfig, SupplierInvoiceDraft
from .providers import ProviderError, ProviderNotConfigured
from .services import DraftValidationError, ignore_draft, sync_mailbox, validate_draft

logger = logging.getLogger(__name__)


def _company_or_redirect(request):
    company = resolve_company(request)
    if company is None:
        return None, redirect("onboarding")
    return company, None


@login_required
def connector_settings(request):
    """Connexion, réglages de collecte et état de la boîte de la société."""
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce

    config, _ = MailboxConfig.objects.get_or_create(company=company)
    form = MailboxConfigForm(request.POST or None, instance=config, company=company)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Paramètres du connecteur enregistrés.")
        return redirect("mailsync:settings")

    drafts_count = SupplierInvoiceDraft.objects.filter(
        company=company, status="pending"
    ).count()
    return render(
        request,
        "mailsync/settings.html",
        {
            "company": company,
            "config": config,
            "form": form,
            "drafts_count": drafts_count,
            "recent_emails": config.processed_emails.select_related("draft")[:10],
        },
    )


@login_required
def connect(request, provider_id):
    """Démarre le flux OAuth2 (redirection vers Google)."""
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    nxt = request.GET.get("next") or ""
    if nxt.startswith("/") and not nxt.startswith("//"):
        request.session["mailsync_oauth_next"] = nxt
    else:
        request.session.pop("mailsync_oauth_next", None)
    try:
        location = oauth.begin(request, provider_id)
    except (ProviderError, ProviderNotConfigured) as exc:
        messages.error(request, f"Connexion impossible : {exc}")
        return redirect(_oauth_next(request))
    return redirect(location)


def _oauth_next(request):
    nxt = request.session.pop("mailsync_oauth_next", "")
    return nxt if nxt.startswith("/") and not nxt.startswith("//") else "mailsync:settings"


@login_required
def oauth_callback(request, provider_id):
    """Retour de Google : échange du code, chiffrement et sauvegarde des jetons."""
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    if request.GET.get("error"):
        messages.error(
            request,
            "Connexion annulée ou refusée par Google. Aucun accès n'a été accordé.",
        )
        return redirect(_oauth_next(request))

    config, _ = MailboxConfig.objects.get_or_create(company=company)
    try:
        oauth.complete(
            request,
            provider_id,
            code=request.GET.get("code", ""),
            state=request.GET.get("state", ""),
            config=config,
        )
    except (ProviderError, ProviderNotConfigured) as exc:
        config.status = "error"
        config.last_error = str(exc)[:500]
        config.save(update_fields=["status", "last_error", "updated_at"])
        messages.error(request, f"Connexion impossible : {exc}")
    else:
        messages.success(
            request,
            f"Boîte {config.email_address or ''} connectée. L'envoi des factures "
            "et devis peut utiliser Gmail.",
        )
    return redirect(_oauth_next(request))


@require_POST
@login_required
def disconnect(request):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    config = get_object_or_404(MailboxConfig, company=company)
    config.clear_tokens()
    config.save(
        update_fields=[
            "access_token_enc",
            "refresh_token_enc",
            "token_expires_at",
            "granted_scopes",
            "is_active",
            "status",
            "last_error",
            "updated_at",
        ]
    )
    messages.success(request, "Boîte e-mail déconnectée. Les brouillons existants sont conservés.")
    return redirect("mailsync:settings")


@require_POST
@login_required
def sync_now(request):
    """Vérification manuelle immédiate (sans attendre le cron)."""
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    config = get_object_or_404(MailboxConfig, company=company)
    if not config.is_active or not config.has_tokens:
        messages.error(request, "Connectez d'abord une boîte e-mail.")
        return redirect("mailsync:settings")
    try:
        result = sync_mailbox(config)
    except Exception as exc:  # garde-fou : la vue ne doit jamais crasher
        logger.exception("Synchronisation manuelle en échec")
        messages.error(request, f"Synchronisation impossible : {exc}")
    else:
        if result.detail:
            messages.warning(request, f"Synchronisation : {result.summary()} — {result.detail}")
        else:
            messages.success(request, f"Synchronisation terminée : {result.summary()}.")
    return redirect("mailsync:settings")


@login_required
def draft_list(request):
    """Boîte de réception comptable : brouillons en attente + historique récent."""
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    pending = SupplierInvoiceDraft.objects.filter(
        company=company, status="pending"
    ).select_related("supplier", "journal")
    history = SupplierInvoiceDraft.objects.filter(company=company).exclude(
        status="pending"
    ).select_related("supplier")[:30]
    return render(
        request,
        "mailsync/drafts.html",
        {"company": company, "pending": pending, "history": history},
    )


@login_required
def draft_detail(request, pk):
    """Écran scindé : aperçu du justificatif à gauche, écriture à droite."""
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    draft = get_object_or_404(
        SupplierInvoiceDraft.objects.select_related("supplier", "journal"),
        pk=pk,
        company=company,
    )
    form = DraftValidationForm(instance=draft, company=company)
    return render(
        request,
        "mailsync/draft_validate.html",
        {
            "company": company,
            "draft": draft,
            "form": form,
            "has_attachment": bool(draft.attachment),
        },
    )


@login_required
@xframe_options_sameorigin
def draft_pdf(request, pk):
    """Sert le justificatif PDF avec contrôle d'appartenance à la société."""
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    draft = get_object_or_404(SupplierInvoiceDraft, pk=pk, company=company)
    if not draft.attachment:
        raise Http404("Aucun justificatif.")
    try:
        handle = draft.attachment.open("rb")
    except FileNotFoundError as exc:
        raise Http404("Justificatif introuvable sur le stockage.") from exc
    return FileResponse(handle, content_type="application/pdf")


@require_POST
@login_required
def draft_validate(request, pk):
    """Valide le brouillon : écriture ACH définitive + justificatif archivé."""
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    draft = get_object_or_404(SupplierInvoiceDraft, pk=pk, company=company)
    form = DraftValidationForm(request.POST, instance=draft, company=company)
    if not form.is_valid():
        return render(
            request,
            "mailsync/draft_validate.html",
            {
                "company": company,
                "draft": draft,
                "form": form,
                "has_attachment": bool(draft.attachment),
            },
            status=400,
        )

    # Persiste les corrections saisies, puis génère l'écriture en transaction.
    form.save()
    try:
        entry = validate_draft(
            draft,
            supplier_name=form.cleaned_data.get("supplier_name", ""),
            journal=form.cleaned_data.get("journal"),
        )
    except DraftValidationError as exc:
        messages.error(request, str(exc))
        return render(
            request,
            "mailsync/draft_validate.html",
            {
                "company": company,
                "draft": draft,
                "form": form,
                "has_attachment": bool(draft.attachment),
            },
        )

    messages.success(
        request,
        f"Écriture {entry.reference or ''} validée dans le journal "
        f"{entry.journal.code} — {entry.label}.",
    )
    return redirect("mailsync:drafts")


@require_POST
@login_required
def draft_ignore(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    draft = get_object_or_404(SupplierInvoiceDraft, pk=pk, company=company)
    ignore_draft(draft)
    messages.info(request, "Facture ignorée. Le message ne sera pas réimporté.")
    return redirect("mailsync:drafts")

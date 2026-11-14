"""Envoi des factures, devis et avoirs par email, avec la signature de l'utilisateur."""
from __future__ import annotations

import base64
from decimal import Decimal

import httpx
from django.conf import settings
from django.core.mail import EmailMessage, get_connection
from django.utils.text import get_valid_filename

from admin_backoffice.email_templates import render_email

from .pdf import render_credit_note_pdf, render_invoice_pdf, render_quote_pdf


DOCUMENT_KINDS = {
    "invoice": {
        "label": "facture",
        "note": "Le règlement est attendu selon les conditions convenues.",
        "render": render_invoice_pdf,
    },
    "quote": {
        "label": "devis",
        "note": "Ce devis reste valable selon les conditions indiquées.",
        "render": render_quote_pdf,
    },
    "credit_note": {
        "label": "avoir",
        "note": "Cet avoir sera déduit de votre prochaine facture.",
        "render": render_credit_note_pdf,
    },
}


def _euros(value) -> str:
    amount = Decimal(str(value or "0")).quantize(Decimal("0.01"))
    return f"{amount:,.2f}".replace(",", " ").replace(".", ",") + " €"


def _client_for(document, kind):
    if kind == "credit_note":
        return document.invoice.client
    return document.client


def _recipient_for(document, kind):
    """Contact principal du client, sinon son email de fiche, sinon vide."""
    client = _client_for(document, kind)
    fallback_name = ""
    if client is not None:
        fallback_name = client.name
        contact = (
            client.contacts.exclude(email="")
            .order_by("-is_primary", "last_name", "first_name")
            .first()
        )
        if contact is not None and contact.email:
            return contact.email, contact.full_name
        if client.email:
            return client.email, client.name
    if kind == "credit_note":
        fallback_name = fallback_name or document.invoice.client_name
    else:
        fallback_name = fallback_name or document.client_name
    return "", fallback_name


def _from_email(company=None) -> str:
    if company is not None:
        own = (getattr(company, "smtp_from_email", "") or "").strip()
        if own:
            return own
    try:
        from admin_backoffice.models import SiteConfiguration

        config = SiteConfiguration.objects.filter(pk=1).first()
        configured = (getattr(config, "email_from", "") or "").strip()
    except Exception:
        configured = ""
    return configured or (settings.DEFAULT_FROM_EMAIL or "").strip()


def _company_connection(company):
    """Connexion SMTP propre à la société, ou None pour le SMTP global."""
    host = (getattr(company, "smtp_host", "") or "").strip()
    if not host:
        return None
    return get_connection(
        backend="django.core.mail.backends.smtp.EmailBackend",
        host=host,
        port=getattr(company, "smtp_port", 587) or 587,
        username=(getattr(company, "smtp_username", "") or "").strip(),
        password=getattr(company, "smtp_password", "") or "",
        use_tls=bool(getattr(company, "smtp_use_tls", True)),
        fail_silently=False,
    )


def _gmail_mailbox(company):
    """Boîte Gmail OAuth déjà liée à la société, si elle peut envoyer."""
    mailbox = getattr(company, "mailbox_config", None)
    if mailbox is None or not mailbox.has_tokens:
        return None
    return mailbox


def _gmail_can_send(mailbox) -> bool:
    return bool(mailbox and "gmail.send" in (mailbox.granted_scopes or ""))


def _send_via_gmail(mailbox, message) -> str:
    """Envoie un EmailMessage via l'API Gmail (OAuth2, sans SMTP)."""
    from mailsync.tokens import ensure_access_token

    try:
        token = ensure_access_token(mailbox)
    except Exception as exc:  # noqa: BLE001 - message utilisateur explicite
        raise ValueError(
            "La connexion Gmail a expiré. Reconnectez Gmail depuis Configuration."
        ) from exc

    raw = base64.urlsafe_b64encode(message.message().as_bytes()).decode("ascii")
    try:
        response = httpx.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            headers={"Authorization": f"Bearer {token}"},
            json={"raw": raw},
            timeout=30,
        )
    except httpx.HTTPError as exc:
        raise ValueError("Gmail est injoignable. Réessayez dans un instant.") from exc
    if response.status_code >= 400:
        detail = ""
        try:
            detail = response.json().get("error", {}).get("message", "")
        except Exception:
            detail = ""
        suffix = f" ({detail[:160]})" if detail else ""
        raise ValueError(
            "Gmail a refusé l'envoi. Reconnectez Gmail ou vérifiez l'adresse "
            "d'expédition dans Configuration." + suffix
        )
    return response.json().get("id", "")


def send_document_email(document, company, user, kind: str, request=None) -> str:
    """Envoie le PDF du document au client et renvoie l'adresse utilisée.

    Lève ``ValueError`` si le client n'a aucune adresse email.
    """
    if kind not in DOCUMENT_KINDS:
        raise ValueError("Type de document inconnu.")
    details = DOCUMENT_KINDS[kind]
    recipient, recipient_name = _recipient_for(document, kind)
    if not recipient:
        raise ValueError(
            "Aucune adresse email pour ce client. Renseignez l'email de la fiche "
            "client ou d'un contact."
        )

    signature = user.signature_text(company)
    context = {
        "name": recipient_name or "Madame, Monsieur",
        "email": recipient,
        "company_name": company.denomination,
        "document_label": details["label"],
        "document_number": document.number,
        "document_amount": _euros(document.amount_ttc),
        "document_note": details["note"],
        "signature": signature,
    }
    subject, body = render_email("document_send", context=context, request=request)
    if signature and signature not in body:
        body = body.rstrip() + "\n\n" + signature

    mailbox = _gmail_mailbox(company)
    use_gmail_api = bool(
        getattr(company, "smtp_provider", "") == "gmail"
        and _gmail_can_send(mailbox)
    )
    if (
        getattr(company, "smtp_provider", "") == "gmail"
        and mailbox is not None
        and not _gmail_can_send(mailbox)
        and not (getattr(company, "smtp_password", "") or "").strip()
    ):
        raise ValueError(
            "Gmail est lié mais l'envoi n'est pas encore autorisé. Dans "
            "Configuration, cliquez sur « Autoriser l'envoi Gmail »."
        )
    if use_gmail_api:
        from_email = (
            (getattr(company, "smtp_from_email", "") or "").strip()
            or mailbox.email_address
            or ""
        )
        if not from_email:
            raise ValueError(
                "Renseignez l'adresse d'expédition Gmail dans Configuration."
            )
    else:
        from_email = _from_email(company)

    message = EmailMessage(
        subject=subject,
        body=body,
        from_email=from_email,
        to=[recipient],
        reply_to=[user.email] if user.email else None,
        connection=None if use_gmail_api else _company_connection(company),
    )
    payload = details["render"](document, company)
    filename = get_valid_filename(f"{document.number or kind}.pdf") or "document.pdf"
    message.attach(filename, payload, "application/pdf")
    if use_gmail_api:
        _send_via_gmail(mailbox, message)
    else:
        message.send()
    return recipient

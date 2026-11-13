"""Envoi des factures, devis et avoirs par email, avec la signature de l'utilisateur."""
from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.mail import EmailMessage
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


def _from_email() -> str:
    try:
        from admin_backoffice.models import SiteConfiguration

        config = SiteConfiguration.objects.filter(pk=1).first()
        configured = (getattr(config, "email_from", "") or "").strip()
    except Exception:
        configured = ""
    return configured or (settings.DEFAULT_FROM_EMAIL or "").strip()


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

    message = EmailMessage(
        subject=subject,
        body=body,
        from_email=_from_email(),
        to=[recipient],
        reply_to=[user.email] if user.email else None,
    )
    payload = details["render"](document, company)
    filename = get_valid_filename(f"{document.number or kind}.pdf") or "document.pdf"
    message.attach(filename, payload, "application/pdf")
    message.send()
    return recipient

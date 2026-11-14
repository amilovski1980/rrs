"""Facturation électronique française — génération Factur-X et dépôt API.

Le module produit :

- un XML CII (Cross Industry Invoice) conforme au profil Factur-X choisi ;
- un PDF Factur-X, c'est-à-dire le PDF de la facture avec le XML joint
  (``factur-x.xml``) et déclaré comme pièce jointe de données ;
- un dépôt vers l'API d'une plateforme agréée (ou de Chorus Pro / du PPF),
  configurée dans le back-office.

La génération est volontairement déterministe et sans appel réseau. Le dépôt
réel n'a lieu que depuis l'action « Transmettre » et seulement si la
configuration l'autorise.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from xml.sax.saxutils import escape

import httpx
from django.utils import timezone

from .models import EInvoicingSubmission
from .pdf import render_invoice_pdf
from .vat import (
    FRANCHISE_MENTION,
    REVERSE_CHARGE_MENTION,
    normalize_vat_number,
)

PROFILE_GUIDELINES = {
    "BASIC": "urn:factur-x.eu:1p0:basic",
    "EN16931": "urn:cen.eu:en16931:2017",
    "EXTENDED": "urn:factur-x.eu:1p0:extended",
}

DEFAULT_PROFILE = "EN16931"


class EInvoicingError(Exception):
    """Erreur lisible de génération ou de transmission électronique."""


def _money(value) -> str:
    return str(Decimal(str(value or 0)).quantize(Decimal("0.01")))


def _date_102(value) -> str:
    return timezone.localtime(value).strftime("%Y%m%d")


def _country_for_vat(vat: str, default: str = "FR") -> str:
    prefix = normalize_vat_number(vat)[:2]
    if len(prefix) == 2 and prefix.isalpha():
        return "GR" if prefix == "EL" else prefix
    return default


def _party(name, siren, vat, address, country="FR") -> str:
    parts = [f"<ram:Name>{escape(str(name or ''))}</ram:Name>"]
    if siren:
        scheme = "0009" if len(str(siren)) == 14 else "0002"
        parts.append(
            "<ram:SpecifiedLegalOrganization>"
            f'<ram:ID schemeID="{scheme}">{escape(str(siren))}</ram:ID>'
            "</ram:SpecifiedLegalOrganization>"
        )
    if address:
        parts.append(
            "<ram:PostalTradeAddress>"
            f"<ram:LineOne>{escape(str(address))}</ram:LineOne>"
            f"<ram:CountryID>{escape(country)}</ram:CountryID>"
            "</ram:PostalTradeAddress>"
        )
    else:
        parts.append(
            "<ram:PostalTradeAddress>"
            f"<ram:CountryID>{escape(country)}</ram:CountryID>"
            "</ram:PostalTradeAddress>"
        )
    if vat:
        parts.append(
            "<ram:SpecifiedTaxRegistration>"
            f'<ram:ID schemeID="VA">{escape(normalize_vat_number(vat))}</ram:ID>'
            "</ram:SpecifiedTaxRegistration>"
        )
    return "".join(parts)


def _invoice_lines(invoice):
    reverse = bool(invoice.reverse_charge)
    rows = []
    for line in invoice.lines.all():
        rate = Decimal("0.00") if reverse else line.vat_rate
        rows.append(
            {
                "description": line.description,
                "quantity": line.quantity,
                "unit_price": line.unit_price,
                "vat_rate": rate,
                "amount_ht": line.amount_ht,
            }
        )
    if rows:
        return rows
    return [
        {
            "description": f"Prestation — {invoice.client_name}",
            "quantity": Decimal("1"),
            "unit_price": invoice.amount_ht,
            "vat_rate": Decimal("0.00") if reverse else invoice.vat_rate,
            "amount_ht": invoice.amount_ht,
        }
    ]


def _tax_category(invoice, company, rate) -> tuple[str, str]:
    """Retourne (catégorie Factur-X, motif d'exonération éventuel)."""
    if invoice.reverse_charge:
        return "AE", REVERSE_CHARGE_MENTION
    reason = (invoice.vat_exemption_reason or "").strip()
    if getattr(company, "tva", "") == "franchise" and Decimal(str(rate)) == 0:
        return "E", reason or FRANCHISE_MENTION
    if reason:
        return "E", reason
    if Decimal(str(rate)) == 0:
        return "Z", ""
    return "S", ""


def _tax_breakdown(invoice, company, rows):
    reverse = bool(invoice.reverse_charge)
    buckets: dict[tuple[str, Decimal], dict] = {}
    for row in rows:
        rate = Decimal(str(row["vat_rate"])).quantize(Decimal("0.01"))
        category, reason = _tax_category(invoice, company, rate)
        key = (category, rate)
        bucket = buckets.setdefault(
            key,
            {"category": category, "rate": rate, "basis": Decimal("0.00"), "reason": reason},
        )
        bucket["basis"] += Decimal(str(row["amount_ht"]))
    if reverse and not buckets:
        buckets[("AE", Decimal("0.00"))] = {
            "category": "AE",
            "rate": Decimal("0.00"),
            "basis": invoice.amount_ht,
            "reason": REVERSE_CHARGE_MENTION,
        }
    if not buckets:
        category, reason = _tax_category(invoice, company, invoice.vat_rate)
        buckets[(category, Decimal(str(invoice.vat_rate)))] = {
            "category": category,
            "rate": Decimal(str(invoice.vat_rate)),
            "basis": invoice.amount_ht,
            "reason": reason,
        }
    for bucket in buckets.values():
        bucket["amount"] = (
            bucket["basis"] * bucket["rate"] / Decimal("100")
        ).quantize(Decimal("0.01"))
    return list(buckets.values())


def build_facturx_xml(invoice, company, profile: str = DEFAULT_PROFILE) -> bytes:
    """Construit le XML CII Factur-X d'une facture."""
    profile = profile if profile in PROFILE_GUIDELINES else DEFAULT_PROFILE
    rows = _invoice_lines(invoice)
    taxes = _tax_breakdown(invoice, company, rows)
    total_ht = sum((Decimal(str(row["amount_ht"])) for row in rows), Decimal("0.00"))
    total_vat = invoice.vat_amount
    total_ttc = invoice.amount_ttc
    paid = invoice.amount_paid
    remaining = invoice.amount_remaining
    due_date = timezone.localtime(invoice.created_at) + timedelta(days=30)
    issue_date = _date_102(invoice.created_at)
    buyer_vat = invoice.client_tva_intra or getattr(invoice.client, "tva_intra", "")
    buyer_siren = invoice.client_siren or getattr(invoice.client, "siren", "")
    buyer_address = getattr(invoice.client, "address", "") if invoice.client else ""

    line_xml = []
    for index, row in enumerate(rows, start=1):
        category, _reason = _tax_category(invoice, company, row["vat_rate"])
        line_xml.append(
            "<ram:IncludedSupplyChainTradeLineItem>"
            "<ram:AssociatedDocumentLineDocument>"
            f"<ram:LineID>{index}</ram:LineID>"
            "</ram:AssociatedDocumentLineDocument>"
            "<ram:SpecifiedTradeProduct>"
            f"<ram:Name>{escape(str(row['description'])[:255])}</ram:Name>"
            "</ram:SpecifiedTradeProduct>"
            "<ram:SpecifiedLineTradeAgreement>"
            "<ram:NetPriceProductTradePrice>"
            f"<ram:ChargeAmount>{_money(row['unit_price'])}</ram:ChargeAmount>"
            "</ram:NetPriceProductTradePrice>"
            "</ram:SpecifiedLineTradeAgreement>"
            "<ram:SpecifiedLineTradeDelivery>"
            f'<ram:BilledQuantity unitCode="C62">{row["quantity"]}</ram:BilledQuantity>'
            "</ram:SpecifiedLineTradeDelivery>"
            "<ram:SpecifiedLineTradeSettlement>"
            "<ram:ApplicableTradeTax>"
            "<ram:TypeCode>VAT</ram:TypeCode>"
            f"<ram:CategoryCode>{category}</ram:CategoryCode>"
            f"<ram:RateApplicablePercent>{_money(row['vat_rate'])}</ram:RateApplicablePercent>"
            "</ram:ApplicableTradeTax>"
            "<ram:SpecifiedTradeSettlementLineMonetarySummation>"
            f"<ram:LineTotalAmount>{_money(row['amount_ht'])}</ram:LineTotalAmount>"
            "</ram:SpecifiedTradeSettlementLineMonetarySummation>"
            "</ram:SpecifiedLineTradeSettlement>"
            "</ram:IncludedSupplyChainTradeLineItem>"
        )

    tax_xml = []
    for tax in taxes:
        reason_xml = (
            f"<ram:ExemptionReason>{escape(tax['reason'])}</ram:ExemptionReason>"
            if tax["reason"]
            else ""
        )
        tax_xml.append(
            "<ram:ApplicableTradeTax>"
            f"<ram:CalculatedAmount>{_money(tax['amount'])}</ram:CalculatedAmount>"
            "<ram:TypeCode>VAT</ram:TypeCode>"
            f"<ram:BasisAmount>{_money(tax['basis'])}</ram:BasisAmount>"
            f"<ram:CategoryCode>{tax['category']}</ram:CategoryCode>"
            f"<ram:RateApplicablePercent>{_money(tax['rate'])}</ram:RateApplicablePercent>"
            f"{reason_xml}"
            "</ram:ApplicableTradeTax>"
        )

    prepaid_xml = (
        f"<ram:TotalPrepaidAmount>{_money(paid)}</ram:TotalPrepaidAmount>" if paid > 0 else ""
    )
    seller_vat = company.tva_intra_number
    seller_xml = _party(
        company.denomination,
        company.siren,
        seller_vat,
        company.address,
        country="FR",
    )
    buyer_xml = _party(
        invoice.client_name,
        buyer_siren,
        buyer_vat,
        buyer_address,
        country=_country_for_vat(buyer_vat),
    )

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rsm:CrossIndustryInvoice '
        'xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100" '
        'xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100" '
        'xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100">'
        "<rsm:ExchangedDocumentContext>"
        "<ram:GuidelineSpecifiedDocumentContextParameter>"
        f"<ram:ID>{PROFILE_GUIDELINES[profile]}</ram:ID>"
        "</ram:GuidelineSpecifiedDocumentContextParameter>"
        "</rsm:ExchangedDocumentContext>"
        "<rsm:ExchangedDocument>"
        f"<ram:ID>{escape(invoice.number)}</ram:ID>"
        "<ram:TypeCode>380</ram:TypeCode>"
        f'<ram:IssueDateTime><udt:DateTimeString format="102">{issue_date}</udt:DateTimeString></ram:IssueDateTime>'
        "</rsm:ExchangedDocument>"
        "<rsm:SupplyChainTradeTransaction>"
        + "".join(line_xml)
        + "<ram:ApplicableHeaderTradeAgreement>"
        f"<ram:BuyerReference>{escape(invoice.number)}</ram:BuyerReference>"
        f"<ram:SellerTradeParty>{seller_xml}</ram:SellerTradeParty>"
        f"<ram:BuyerTradeParty>{buyer_xml}</ram:BuyerTradeParty>"
        "</ram:ApplicableHeaderTradeAgreement>"
        "<ram:ApplicableHeaderTradeDelivery/>"
        "<ram:ApplicableHeaderTradeSettlement>"
        f"<ram:PaymentReference>{escape(invoice.number)}</ram:PaymentReference>"
        "<ram:InvoiceCurrencyCode>EUR</ram:InvoiceCurrencyCode>"
        "<ram:SpecifiedTradeSettlementPaymentMeans>"
        "<ram:TypeCode>30</ram:TypeCode>"
        "</ram:SpecifiedTradeSettlementPaymentMeans>"
        + "".join(tax_xml)
        + "<ram:SpecifiedTradePaymentTerms>"
        f'<ram:DueDateDateTime><udt:DateTimeString format="102">{due_date.strftime("%Y%m%d")}</udt:DateTimeString></ram:DueDateDateTime>'
        "</ram:SpecifiedTradePaymentTerms>"
        "<ram:SpecifiedTradeSettlementHeaderMonetarySummation>"
        f"<ram:LineTotalAmount>{_money(total_ht)}</ram:LineTotalAmount>"
        f"<ram:TaxBasisTotalAmount>{_money(total_ht)}</ram:TaxBasisTotalAmount>"
        f'<ram:TaxTotalAmount currencyID="EUR">{_money(total_vat)}</ram:TaxTotalAmount>'
        f"<ram:GrandTotalAmount>{_money(total_ttc)}</ram:GrandTotalAmount>"
        f"{prepaid_xml}"
        f"<ram:DuePayableAmount>{_money(remaining)}</ram:DuePayableAmount>"
        "</ram:SpecifiedTradeSettlementHeaderMonetarySummation>"
        "</ram:ApplicableHeaderTradeSettlement>"
        "</rsm:SupplyChainTradeTransaction>"
        "</rsm:CrossIndustryInvoice>"
    )
    return xml.encode("utf-8")


def build_facturx_pdf(invoice, company, profile: str = DEFAULT_PROFILE) -> bytes:
    """PDF de la facture avec le XML Factur-X joint comme donnée métier."""
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import ArrayObject, NameObject, TextStringObject

    xml = build_facturx_xml(invoice, company, profile=profile)
    writer = PdfWriter(clone_from=PdfReader(BytesIO(render_invoice_pdf(invoice, company))))
    writer.add_attachment("factur-x.xml", xml)
    writer.add_metadata(
        {
            "/Title": f"Facture {invoice.number}",
            "/Author": company.denomination or "Road Runner Solutions",
            "/Subject": f"Factur-X {profile}",
            "/Keywords": "Factur-X, facture électronique, EN 16931",
        }
    )
    catalog = writer._root_object
    try:
        embedded = catalog["/Names"]["/EmbeddedFiles"]["/Names"]
        filespec = embedded[1]
        filespec[NameObject("/AFRelationship")] = NameObject("/Data")
        filespec[NameObject("/Desc")] = TextStringObject("Factur-X invoice data")
        catalog[NameObject("/AF")] = ArrayObject([filespec])
    except Exception:
        # Le XML reste joint même si le dictionnaire /AF ne peut pas être enrichi.
        pass
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def generate_submission(invoice, profile: str = DEFAULT_PROFILE) -> EInvoicingSubmission:
    """Génère et enregistre une version Factur-X prête à transmettre."""
    if invoice.status == "draft":
        raise EInvoicingError("Émettez la facture avant de générer sa version électronique.")
    profile = profile if profile in PROFILE_GUIDELINES else DEFAULT_PROFILE
    xml = build_facturx_xml(invoice, invoice.company, profile=profile)
    digest = hashlib.sha256(xml).hexdigest()
    submission = EInvoicingSubmission.objects.create(
        invoice=invoice,
        profile=profile,
        status="generated",
        reference=f"FE-{invoice.number}-{uuid.uuid4().hex[:8].upper()}",
        xml_payload=xml.decode("utf-8"),
        checksum=digest,
    )
    return submission


def _config():
    from admin_backoffice.models import SiteConfiguration

    return SiteConfiguration.objects.filter(pk=1).first()


def submit_submission(submission: EInvoicingSubmission) -> EInvoicingSubmission:
    """Transmet le XML à la plateforme configurée. Lève EInvoicingError si impossible."""
    config = _config()
    if config is None or not config.einvoicing_enabled:
        raise EInvoicingError(
            "La facturation électronique n'est pas activée. Renseignez-la dans le back-office."
        )
    if not (config.einvoicing_api_url or "").strip():
        raise EInvoicingError("Aucune URL d'API de facturation électronique n'est configurée.")

    headers = {"Accept": "application/json"}
    if (config.einvoicing_api_key or "").strip():
        headers["Authorization"] = f"Bearer {config.einvoicing_api_key.strip()}"
    data = {
        "reference": submission.reference,
        "invoice_number": submission.invoice.number,
        "profile": submission.profile,
        "sender_siret": config.einvoicing_sender_siret or "",
        "checksum_sha256": submission.checksum,
    }
    files = {
        "file": ("factur-x.xml", submission.xml_payload.encode("utf-8"), "application/xml"),
    }
    try:
        response = httpx.post(
            config.einvoicing_api_url.strip(),
            headers=headers,
            data=data,
            files=files,
            timeout=20,
        )
    except httpx.HTTPError as exc:
        submission.status = "error"
        submission.platform = config.einvoicing_provider
        submission.response_message = f"Connexion impossible : {exc}"
        submission.save(update_fields=["status", "platform", "response_message", "updated_at"])
        raise EInvoicingError("La plateforme de facturation est injoignable.") from exc

    submission.platform = config.einvoicing_provider
    submission.sent_at = timezone.now()
    body = response.text[:2000]
    if response.is_success:
        try:
            payload = json.loads(response.text) if response.text else {}
        except ValueError:
            payload = {}
        remote_id = str(payload.get("id") or payload.get("reference") or "").strip()
        remote_status = str(payload.get("status") or "").lower()
        submission.remote_id = remote_id[:120]
        submission.status = "accepted" if remote_status in {"accepted", "valid", "valide"} else "sent"
        submission.response_message = body
    else:
        submission.status = "error"
        submission.response_message = f"HTTP {response.status_code} — {body}"
    submission.save(
        update_fields=[
            "status",
            "platform",
            "remote_id",
            "response_message",
            "sent_at",
            "updated_at",
        ]
    )
    if submission.status == "error":
        raise EInvoicingError(
            f"La plateforme a refusé le dépôt (HTTP {response.status_code})."
        )
    return submission

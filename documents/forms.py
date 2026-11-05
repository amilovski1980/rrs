from decimal import Decimal

from django import forms

from .models import (
    Client,
    CreditNote,
    Invoice,
    InvoiceLine,
    Payment,
    Product,
    Project,
    Quote,
    QuoteLine,
)


class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = ("name", "siren", "address", "email", "phone", "notes")

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company
        self.fields["name"].label = "Nom"
        self.fields["siren"].label = "SIREN"
        self.fields["siren"].required = False
        self.fields["address"].label = "Adresse"
        self.fields["email"].label = "E-mail"
        self.fields["phone"].label = "Téléphone"
        self.fields["notes"].label = "Notes"
        self.fields["notes"].required = False

    def clean_siren(self):
        raw = "".join(c for c in (self.cleaned_data.get("siren") or "") if c.isdigit())
        if raw and len(raw) != 9:
            raise forms.ValidationError("Le SIREN doit contenir 9 chiffres, ou rester vide.")
        return raw


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ("label", "description", "unit_price", "vat_rate", "unit", "active")

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["label"].label = "Libellé"
        self.fields["description"].label = "Description"
        self.fields["description"].required = False
        self.fields["unit_price"].label = "Prix unitaire HT"
        self.fields["vat_rate"].label = "Taux de TVA (%)"
        self.fields["unit"].label = "Unité"
        self.fields["active"].label = "Actif"

    def clean_unit_price(self):
        price = self.cleaned_data["unit_price"]
        if price < 0:
            raise forms.ValidationError("Le prix ne peut pas être négatif.")
        return price

    def clean_vat_rate(self):
        rate = self.cleaned_data["vat_rate"]
        if rate < 0 or rate > 100:
            raise forms.ValidationError("Taux de TVA invalide.")
        return rate


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ("name", "client", "description", "status", "start_date", "end_date")
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].label = "Nom"
        self.fields["client"].label = "Client"
        self.fields["client"].required = False
        self.fields["description"].label = "Description"
        self.fields["description"].required = False
        self.fields["status"].label = "État"
        self.fields["start_date"].label = "Début"
        self.fields["end_date"].label = "Fin"
        if company is not None:
            self.fields["client"].queryset = Client.objects.filter(company=company)


class InvoiceForm(forms.ModelForm):
    class Meta:
        model = Invoice
        fields = ("client", "client_name", "client_siren", "project", "amount_ht", "vat_rate")

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company
        self.fields["client"].label = "Fiche client"
        self.fields["client"].required = False
        self.fields["client_name"].label = "Nom client (affiché)"
        self.fields["client_siren"].label = "SIREN client"
        self.fields["client_siren"].required = False
        self.fields["project"].label = "Projet"
        self.fields["project"].required = False
        self.fields["amount_ht"].label = "Montant HT"
        self.fields["vat_rate"].label = "Taux de TVA (%)"
        if company is not None:
            self.fields["client"].queryset = Client.objects.filter(company=company)
            self.fields["project"].queryset = Project.objects.filter(company=company)
            if company.tva != "reel" and not self.is_bound:
                self.fields["vat_rate"].initial = Decimal("0.00")

    def clean_client_siren(self):
        raw = "".join(c for c in (self.cleaned_data.get("client_siren") or "") if c.isdigit())
        if raw and len(raw) != 9:
            raise forms.ValidationError("Le SIREN client doit contenir 9 chiffres, ou rester vide.")
        return raw

    def clean_amount_ht(self):
        amount = self.cleaned_data["amount_ht"]
        if amount <= 0:
            raise forms.ValidationError("Le montant HT doit être positif.")
        return amount

    def clean_vat_rate(self):
        rate = self.cleaned_data["vat_rate"]
        if rate < 0 or rate > 100:
            raise forms.ValidationError("Taux de TVA invalide.")
        return rate

    def clean(self):
        cleaned = super().clean()
        client = cleaned.get("client")
        if client and not cleaned.get("client_name"):
            cleaned["client_name"] = client.name
        if client and client.siren and not cleaned.get("client_siren"):
            cleaned["client_siren"] = client.siren
        return cleaned


class InvoiceLineForm(forms.ModelForm):
    class Meta:
        model = InvoiceLine
        fields = ("product", "description", "quantity", "unit_price", "vat_rate")

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].label = "Catalogue"
        self.fields["product"].required = False
        self.fields["description"].label = "Désignation"
        self.fields["quantity"].label = "Quantité"
        self.fields["unit_price"].label = "Prix unitaire HT"
        self.fields["vat_rate"].label = "TVA (%)"
        if company is not None:
            self.fields["product"].queryset = Product.objects.filter(company=company, active=True)


class QuoteForm(forms.ModelForm):
    class Meta:
        model = Quote
        fields = (
            "client",
            "client_name",
            "client_siren",
            "project",
            "amount_ht",
            "vat_rate",
            "valid_until",
            "notes",
        )
        widgets = {"valid_until": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["client"].label = "Fiche client"
        self.fields["client"].required = False
        self.fields["client_name"].label = "Nom client"
        self.fields["client_siren"].label = "SIREN"
        self.fields["client_siren"].required = False
        self.fields["project"].label = "Projet"
        self.fields["project"].required = False
        self.fields["amount_ht"].label = "Montant HT"
        self.fields["vat_rate"].label = "Taux de TVA (%)"
        self.fields["valid_until"].label = "Valable jusqu'au"
        self.fields["valid_until"].required = False
        self.fields["notes"].label = "Notes"
        self.fields["notes"].required = False
        if company is not None:
            self.fields["client"].queryset = Client.objects.filter(company=company)
            self.fields["project"].queryset = Project.objects.filter(company=company)

    def clean_client_siren(self):
        raw = "".join(c for c in (self.cleaned_data.get("client_siren") or "") if c.isdigit())
        if raw and len(raw) != 9:
            raise forms.ValidationError("Le SIREN doit contenir 9 chiffres, ou rester vide.")
        return raw

    def clean_amount_ht(self):
        amount = self.cleaned_data["amount_ht"]
        if amount <= 0:
            raise forms.ValidationError("Le montant HT doit être positif.")
        return amount

    def clean(self):
        cleaned = super().clean()
        client = cleaned.get("client")
        if client and not cleaned.get("client_name"):
            cleaned["client_name"] = client.name
        if client and client.siren and not cleaned.get("client_siren"):
            cleaned["client_siren"] = client.siren
        return cleaned


class QuoteLineForm(forms.ModelForm):
    class Meta:
        model = QuoteLine
        fields = ("product", "description", "quantity", "unit_price", "vat_rate")

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].required = False
        if company is not None:
            self.fields["product"].queryset = Product.objects.filter(company=company, active=True)


class CreditNoteForm(forms.ModelForm):
    class Meta:
        model = CreditNote
        fields = ("invoice", "amount_ht", "vat_rate", "reason")

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company
        self.fields["invoice"].label = "Facture"
        self.fields["amount_ht"].label = "Montant HT"
        self.fields["vat_rate"].label = "Taux de TVA (%)"
        self.fields["reason"].label = "Motif"
        self.fields["reason"].required = False
        if company is not None:
            self.fields["invoice"].queryset = Invoice.objects.filter(company=company).exclude(
                status="draft"
            )

    def clean_amount_ht(self):
        amount = self.cleaned_data["amount_ht"]
        if amount <= 0:
            raise forms.ValidationError("Le montant HT doit être positif.")
        return amount

    def clean(self):
        cleaned = super().clean()
        invoice = cleaned.get("invoice")
        amount = cleaned.get("amount_ht")
        if invoice and amount and amount > invoice.amount_ht:
            raise forms.ValidationError(
                "Le montant de l'avoir ne peut pas dépasser le HT de la facture."
            )
        if invoice and cleaned.get("vat_rate") is None:
            cleaned["vat_rate"] = invoice.vat_rate
        return cleaned


class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = ("invoice", "amount", "method", "paid_at", "reference", "notes")
        widgets = {"paid_at": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, company=None, invoice=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company
        self.fields["invoice"].label = "Facture"
        self.fields["amount"].label = "Montant"
        self.fields["method"].label = "Mode de paiement"
        self.fields["paid_at"].label = "Date"
        self.fields["reference"].label = "Référence"
        self.fields["reference"].required = False
        self.fields["notes"].label = "Notes"
        self.fields["notes"].required = False
        if company is not None:
            qs = Invoice.objects.filter(company=company).exclude(status="draft")
            self.fields["invoice"].queryset = qs
        if invoice is not None:
            self.fields["invoice"].initial = invoice
            self.fields["invoice"].queryset = Invoice.objects.filter(pk=invoice.pk)
            if not self.is_bound:
                self.fields["amount"].initial = invoice.amount_remaining

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount <= 0:
            raise forms.ValidationError("Le montant doit être positif.")
        return amount


class PdfImportForm(forms.Form):
    pdf_file = forms.FileField(
        label="Fichier PDF",
        help_text="Facture PDF (texte extractible), 5 Mo maximum.",
    )

    def clean_pdf_file(self):
        upload = self.cleaned_data["pdf_file"]
        name = (upload.name or "").lower()
        content_type = getattr(upload, "content_type", "") or ""
        if not (name.endswith(".pdf") or "pdf" in content_type):
            raise forms.ValidationError("Seuls les fichiers PDF sont acceptés.")
        if upload.size > 5 * 1024 * 1024:
            raise forms.ValidationError("Le fichier dépasse la taille maximale de 5 Mo.")
        header = upload.read(5)
        upload.seek(0)
        if header != b"%PDF-":
            raise forms.ValidationError("Le fichier n'est pas un PDF valide.")
        return upload

from django import forms

from .models import ImportDocument


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True

    def value_from_datadict(self, data, files, name):
        if hasattr(files, "getlist"):
            values = files.getlist(name)
            if values:
                return values
        return super().value_from_datadict(data, files, name)


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault(
            "widget",
            MultipleFileInput(
                attrs={
                    "multiple": True,
                    "accept": ".pdf,.xml,.zip,image/jpeg,image/png,image/webp,image/heic,image/heif",
                }
            ),
        )
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_clean = super().clean
        if isinstance(data, (list, tuple)):
            return [single_clean(item, initial) for item in data]
        return [single_clean(data, initial)]


class ImportUploadForm(forms.Form):
    files = MultipleFileField(
        label="Documents à importer",
        help_text="PDF, XML, JPG, PNG, WEBP ou archive ZIP. Sélection multiple.",
    )
    kind_hint = forms.ChoiceField(
        label="Type de documents",
        required=False,
        choices=(
            ("", "Détection automatique"),
            ("sale_invoice", "Factures de vente"),
            ("purchase_invoice", "Factures fournisseurs"),
        ),
    )
    label = forms.CharField(
        label="Nom du lot (facultatif)",
        max_length=120,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Ex. Comptabilité 2024"}),
    )


class DocumentEditForm(forms.ModelForm):
    class Meta:
        model = ImportDocument
        fields = [
            "kind",
            "seller_name",
            "seller_siret",
            "seller_vat",
            "customer_name",
            "customer_siret",
            "customer_vat",
            "invoice_number",
            "invoice_date",
            "due_date",
            "amount_ht",
            "amount_vat",
            "amount_ttc",
            "vat_rate",
            "currency",
            "description",
        ]
        widgets = {
            "invoice_date": forms.DateInput(attrs={"type": "date"}),
            "due_date": forms.DateInput(attrs={"type": "date"}),
            "amount_ht": forms.NumberInput(attrs={"step": "0.01"}),
            "amount_vat": forms.NumberInput(attrs={"step": "0.01"}),
            "amount_ttc": forms.NumberInput(attrs={"step": "0.01"}),
            "vat_rate": forms.NumberInput(attrs={"step": "0.01"}),
        }
        labels = {
            "kind": "Type de document",
            "seller_name": "Émetteur / fournisseur",
            "seller_siret": "SIRET émetteur",
            "seller_vat": "TVA émetteur",
            "customer_name": "Client / destinataire",
            "customer_siret": "SIRET client",
            "customer_vat": "TVA client",
            "invoice_number": "N° facture d'origine",
            "invoice_date": "Date d'émission",
            "due_date": "Date d'échéance",
            "amount_ht": "Montant HT",
            "amount_vat": "TVA",
            "amount_ttc": "Montant TTC",
            "vat_rate": "Taux TVA (%)",
            "currency": "Devise",
            "description": "Libellé",
        }

    def clean(self):
        cleaned = super().clean()
        ht = cleaned.get("amount_ht") or 0
        vat = cleaned.get("amount_vat") or 0
        ttc = cleaned.get("amount_ttc") or 0
        if ttc <= 0 and ht > 0:
            cleaned["amount_ttc"] = ht + vat
        elif ht <= 0 and ttc > 0:
            cleaned["amount_ht"] = max(ttc - vat, 0)
        kind = cleaned.get("kind")
        if kind in ("sale_invoice", "purchase_invoice") and not cleaned.get("invoice_number"):
            self.add_error("invoice_number", "Le numéro d'origine est obligatoire pour ce type.")
        return cleaned

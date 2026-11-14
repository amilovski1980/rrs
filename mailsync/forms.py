from decimal import Decimal

from django import forms

from .models import MailboxConfig, SupplierInvoiceDraft


class MailboxConfigForm(forms.ModelForm):
    """Réglages de collecte et paramètres comptables par défaut."""

    class Meta:
        model = MailboxConfig
        fields = [
            "frequency_minutes",
            "folder_label",
            "journal",
            "charge_account_code",
            "vat_account_code",
            "supplier_account_root",
        ]
        widgets = {
            "folder_label": forms.TextInput(
                attrs={"placeholder": "Ex. Factures fournisseurs (vide = réception)"}
            ),
        }

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        achats = company.journals.filter(type="achats").order_by("code")
        self.fields["journal"].queryset = (
            achats if achats.exists() else company.journals.all()
        )
        self.fields["journal"].required = False
        self.fields["journal"].empty_label = "Journal ACH par défaut"
        if not self.instance.journal_id:
            default_journal = company.journals.filter(code="ACH").first()
            if default_journal is not None:
                self.initial.setdefault("journal", default_journal.pk)

    def _clean_code(self, name):
        value = (self.cleaned_data.get(name) or "").strip().upper()
        return value

    def clean_charge_account_code(self):
        return self._clean_code("charge_account_code")

    def clean_vat_account_code(self):
        return self._clean_code("vat_account_code")

    def clean_supplier_account_root(self):
        return self._clean_code("supplier_account_root")


class DraftValidationForm(forms.ModelForm):
    """Formulaire pré-rempli de l'écran de contrôle (moitié droite)."""

    supplier_name = forms.CharField(
        label="Fournisseur", max_length=200, required=True
    )

    class Meta:
        model = SupplierInvoiceDraft
        fields = [
            "supplier_name",
            "invoice_number",
            "invoice_date",
            "journal",
            "charge_account_code",
            "vat_account_code",
            "amount_ht",
            "amount_vat",
            "amount_ttc",
            "vat_rate",
        ]
        widgets = {
            "invoice_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company
        self.fields["journal"].queryset = company.journals.order_by("code")
        self.fields["journal"].required = False
        if self.instance and self.instance.pk:
            if self.instance.supplier_id:
                self.initial.setdefault("supplier_name", self.instance.supplier.name)
            elif self.instance.proposed_supplier_name:
                self.initial.setdefault(
                    "supplier_name", self.instance.proposed_supplier_name
                )
            if not self.instance.journal_id:
                default_journal = company.journals.filter(code="ACH").first()
                if default_journal is not None:
                    self.initial.setdefault("journal", default_journal.pk)

    def clean(self):
        cleaned = super().clean()
        ht = cleaned.get("amount_ht") or Decimal("0.00")
        vat = cleaned.get("amount_vat") or Decimal("0.00")
        ttc = cleaned.get("amount_ttc") or Decimal("0.00")
        if self.company.tva == "reel":
            if ht <= 0 and ttc <= 0:
                raise forms.ValidationError(
                    "Renseignez au moins le montant HT ou le montant TTC."
                )
            if ht > 0 and ttc > 0 and abs((ht + vat) - ttc) > Decimal("0.02"):
                raise forms.ValidationError(
                    "HT + TVA doit être égal au TTC (écart toléré : 0,02 €)."
                )
        elif ttc <= 0:
            raise forms.ValidationError("Renseignez le montant TTC de la facture.")
        return cleaned

    def clean_charge_account_code(self):
        return (self.cleaned_data.get("charge_account_code") or "").strip().upper()

    def clean_vat_account_code(self):
        return (self.cleaned_data.get("vat_account_code") or "").strip().upper()

from datetime import timedelta
from decimal import Decimal

from django import forms
from django.utils import timezone

from mailsync.models import Supplier

from .models import PAYMENT_METHODS, PurchaseInvoice


class PurchaseInvoiceForm(forms.ModelForm):
    class Meta:
        model = PurchaseInvoice
        fields = [
            "supplier",
            "supplier_name",
            "number",
            "invoice_date",
            "due_date",
            "amount_ht",
            "amount_vat",
            "amount_ttc",
            "vat_rate",
            "charge_account_code",
            "vat_account_code",
            "supplier_account_root",
            "description",
            "attachment",
            "notes",
        ]
        widgets = {
            "invoice_date": forms.DateInput(attrs={"type": "date"}),
            "due_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {
            "supplier": "Fournisseur existant",
            "supplier_name": "Nom du fournisseur",
            "number": "N° facture",
            "invoice_date": "Date facture",
            "due_date": "Date d'échéance",
            "amount_ht": "Montant HT",
            "amount_vat": "TVA",
            "amount_ttc": "Montant TTC",
            "vat_rate": "Taux TVA (%)",
            "charge_account_code": "Compte de charge",
            "vat_account_code": "Compte de TVA déductible",
            "supplier_account_root": "Racine fournisseur",
            "description": "Libellé",
            "attachment": "Justificatif",
            "notes": "Notes",
        }

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company
        self.fields["supplier"].queryset = Supplier.objects.filter(
            company=company, is_active=True
        ).order_by("name")
        self.fields["supplier"].required = False
        self.fields["supplier"].help_text = (
            "Laissez vide pour créer un fournisseur à la validation."
        )
        self.fields["supplier_name"].required = False
        self.fields["due_date"].help_text = (
            "Vide = date facture + délai de paiement du fournisseur."
        )
        for name in ("charge_account_code", "vat_account_code", "supplier_account_root"):
            self.fields[name].widget.attrs["autocomplete"] = "off"
        if not self.is_bound and self.instance._state.adding:
            self.fields["invoice_date"].initial = timezone.localdate()
            self.fields["due_date"].initial = timezone.localdate() + timedelta(
                days=company.payment_terms_days or 30
            )

    def clean_charge_account_code(self):
        return (self.cleaned_data.get("charge_account_code") or "606000").strip().upper()

    def clean_vat_account_code(self):
        return (self.cleaned_data.get("vat_account_code") or "445660").strip().upper()

    def clean_supplier_account_root(self):
        return (self.cleaned_data.get("supplier_account_root") or "401").strip().upper()

    def clean(self):
        cleaned = super().clean()
        supplier = cleaned.get("supplier")
        supplier_name = (cleaned.get("supplier_name") or "").strip()
        if supplier is None and not supplier_name:
            raise forms.ValidationError(
                "Choisissez un fournisseur existant ou saisissez son nom."
            )
        if supplier is not None:
            cleaned["supplier_name"] = supplier.name

        ht = cleaned.get("amount_ht") or Decimal("0.00")
        vat = cleaned.get("amount_vat") or Decimal("0.00")
        ttc = cleaned.get("amount_ttc") or Decimal("0.00")
        if ttc <= 0 and ht > 0:
            ttc = (ht + vat).quantize(Decimal("0.01"))
            cleaned["amount_ttc"] = ttc
        if ht <= 0 and ttc > 0:
            ht = (ttc - vat).quantize(Decimal("0.01"))
            cleaned["amount_ht"] = ht
        if ttc <= 0:
            raise forms.ValidationError("Renseignez au moins le montant TTC.")
        if self.company.tva == "reel" and abs((ht + vat) - ttc) > Decimal("0.02"):
            raise forms.ValidationError(
                "HT + TVA doit être égal au TTC (écart toléré : 0,02 €)."
            )

        invoice_date = cleaned.get("invoice_date")
        if invoice_date and not cleaned.get("due_date"):
            terms = (
                supplier.payment_terms_days
                if supplier is not None
                else (self.company.payment_terms_days or 30)
            )
            cleaned["due_date"] = invoice_date + timedelta(days=terms or 30)

        number = (cleaned.get("number") or "").strip()
        cleaned["number"] = number
        if supplier is not None and number:
            duplicate = PurchaseInvoice.objects.filter(
                company=self.company, supplier=supplier, number=number
            )
            if self.instance.pk:
                duplicate = duplicate.exclude(pk=self.instance.pk)
            if duplicate.exists():
                raise forms.ValidationError(
                    f"La facture {number} est déjà enregistrée pour ce fournisseur."
                )
        return cleaned


class SupplierPaymentForm(forms.Form):
    amount = forms.DecimalField(label="Montant", max_digits=12, decimal_places=2)
    method = forms.ChoiceField(label="Mode", choices=PAYMENT_METHODS)
    paid_at = forms.DateField(
        label="Date", widget=forms.DateInput(attrs={"type": "date"})
    )
    reference = forms.CharField(label="Référence", max_length=100, required=False)
    notes = forms.CharField(
        label="Notes", max_length=255, required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )

    def __init__(self, *args, invoice: PurchaseInvoice, **kwargs):
        super().__init__(*args, **kwargs)
        self.invoice = invoice
        if not self.is_bound:
            self.fields["amount"].initial = invoice.amount_remaining
            self.fields["paid_at"].initial = timezone.localdate()

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount <= 0:
            raise forms.ValidationError("Le montant doit être positif.")
        if amount > self.invoice.amount_remaining + Decimal("0.01"):
            raise forms.ValidationError(
                f"Maximum : {self.invoice.amount_remaining} €."
            )
        return amount

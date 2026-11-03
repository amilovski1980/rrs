from decimal import Decimal

from django import forms

from .models import Invoice


class InvoiceForm(forms.ModelForm):
    class Meta:
        model = Invoice
        fields = ("client_name", "client_siren", "amount_ht", "vat_rate")

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["client_name"].label = "Client"
        self.fields["client_siren"].label = "SIREN client"
        self.fields["client_siren"].required = False
        self.fields["amount_ht"].label = "Montant HT"
        self.fields["vat_rate"].label = "Taux de TVA (%)"
        if company is not None and company.tva != "reel" and not self.is_bound:
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

from django import forms

from mailsync.matching import email_domain, normalize_siret, normalize_vat

from .models import Supplier


class SupplierForm(forms.ModelForm):
    siret = forms.CharField(label="SIRET", max_length=20, required=False)

    class Meta:
        model = Supplier
        fields = [
            "name",
            "siret",
            "tva_intra",
            "email",
            "phone",
            "contact_name",
            "address",
            "iban",
            "payment_terms_days",
            "default_charge_code",
            "is_active",
            "notes",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {
            "name": "Nom du fournisseur",
            "siret": "SIRET",
            "tva_intra": "TVA intracommunautaire",
            "email": "E-mail",
            "phone": "Téléphone",
            "contact_name": "Contact",
            "address": "Adresse",
            "iban": "IBAN",
            "payment_terms_days": "Délai de paiement (jours)",
            "default_charge_code": "Compte de charge préféré",
            "is_active": "Fournisseur actif",
            "notes": "Notes",
        }

    def clean_siret(self):
        siret = normalize_siret(self.cleaned_data.get("siret") or "")
        if siret and len(siret) != 14:
            raise forms.ValidationError("Le SIRET doit contenir 14 chiffres.")
        return siret

    def clean_tva_intra(self):
        return normalize_vat(self.cleaned_data.get("tva_intra") or "")

    def clean_default_charge_code(self):
        return (self.cleaned_data.get("default_charge_code") or "").strip().upper()

    def save(self, commit=True):
        supplier = super().save(commit=False)
        supplier.email_domain = email_domain(supplier.email)
        if commit:
            supplier.save()
        return supplier

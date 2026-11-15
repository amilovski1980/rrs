from decimal import Decimal

from datetime import timedelta

from django import forms
from django.forms import inlineformset_factory
from django.forms.models import BaseInlineFormSet
from django.utils import timezone

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
    TicketDeCaisse,
    TICKET_CATEGORIES,
)


class ClientSelect(forms.Select):
    """Select de fiche client avec les coordonnées en data-attributes."""

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        client = getattr(value, "instance", None)
        if client is not None:
            option["attrs"].update({
                "data-client-name": client.name or "",
                "data-client-siren": client.siren or "",
                "data-client-tva": client.tva_intra or "",
            })
        return option


class ProductSelect(forms.Select):
    """Select catalogue avec les valeurs nécessaires au préremplissage."""

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        product = getattr(value, "instance", None)
        if product is not None:
            option["attrs"].update({
                "data-product-label": product.label or "",
                "data-product-description": product.description or "",
                "data-product-unit-price": str(product.unit_price),
                "data-product-vat-rate": str(product.vat_rate),
                "data-product-unit": product.unit or "",
            })
        return option


class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = (
            "name",
            "siren",
            "tva_intra",
            "legal_form",
            "rcs",
            "address",
            "email",
            "phone",
            "notes",
        )

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company
        self.fields["name"].label = "Nom"
        self.fields["siren"].label = "SIREN"
        self.fields["siren"].required = False
        self.fields["tva_intra"].label = "TVA intracommunautaire"
        self.fields["tva_intra"].required = False
        self.fields["tva_intra"].help_text = "Ex. FR17100408517. Vide si le client n'est pas assujetti."
        self.fields["legal_form"].label = "Forme juridique"
        self.fields["legal_form"].required = False
        self.fields["rcs"].label = "RCS"
        self.fields["rcs"].required = False
        self.fields["address"].label = "Adresse"
        self.fields["email"].label = "E-mail"
        self.fields["phone"].label = "Téléphone"
        self.fields["notes"].label = "Notes"
        self.fields["notes"].required = False
        self.fields["email"].widget.input_type = "email"
        self.fields["email"].widget.attrs.update(
            {"autocomplete": "email", "inputmode": "email"}
        )
        self.fields["phone"].widget.input_type = "tel"
        self.fields["phone"].widget.attrs.update(
            {"autocomplete": "tel", "inputmode": "tel"}
        )
        self.fields["siren"].widget.attrs.update({"inputmode": "numeric", "pattern": "[0-9]*"})

    def clean_siren(self):
        raw = "".join(c for c in (self.cleaned_data.get("siren") or "") if c.isdigit())
        if raw and len(raw) != 9:
            raise forms.ValidationError("Le SIREN doit contenir 9 chiffres, ou rester vide.")
        return raw

    def clean_tva_intra(self):
        from .vat import is_valid_vat_number, normalize_vat_number

        value = normalize_vat_number(self.cleaned_data.get("tva_intra"))
        if value and not is_valid_vat_number(value):
            raise forms.ValidationError(
                "Numéro de TVA intracommunautaire invalide (ex. FR17100408517)."
            )
        return value


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
        self.fields["unit_price"].widget.attrs.update({"inputmode": "decimal"})
        self.fields["vat_rate"].widget.attrs.update({"inputmode": "decimal"})

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
        fields = (
            "client",
            "client_name",
            "client_siren",
            "client_tva_intra",
            "project",
            "reverse_charge",
            "vat_exemption_reason",
            "due_date",
        )
        widgets = {
            "client": ClientSelect,
            "due_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company
        self.fields["client"].label = "Fiche client"
        self.fields["client"].required = False
        self.fields["client"].help_text = (
            "Sélectionnez une fiche pour préremplir le nom, le SIREN et la TVA. "
            "Sans fiche, les champs restent libres."
        )
        self.fields["client"].widget.attrs.update({"data-client-select": "1"})
        self.fields["client_name"].label = "Nom client (affiché)"
        self.fields["client_name"].required = False
        self.fields["client_name"].help_text = "Prérempli depuis la fiche client, modifiable librement."
        self.fields["client_siren"].label = "SIREN client"
        self.fields["client_siren"].required = False
        self.fields["client_siren"].help_text = "9 chiffres, ou vide."
        self.fields["client_tva_intra"].label = "TVA intracommunautaire du client"
        self.fields["client_tva_intra"].required = False
        self.fields["client_tva_intra"].help_text = (
            "Préremplie depuis la fiche client. Laissez vide si le client n'est pas assujetti."
        )
        self.fields["reverse_charge"].label = "Autoliquidation de la TVA (client UE)"
        self.fields["reverse_charge"].help_text = (
            "Cochez pour un client professionnel établi dans un autre État membre : "
            "la TVA est due par le preneur et le taux est ramené à 0 %."
        )
        self.fields["vat_exemption_reason"].label = "Mention d'exonération (facultatif)"
        self.fields["vat_exemption_reason"].required = False
        self.fields["project"].label = "Projet"
        self.fields["project"].required = False
        self.fields["due_date"].label = "Date d'échéance"
        self.fields["due_date"].required = False
        self.fields["due_date"].help_text = (
            "Vide = date de facturation + délai de paiement de la société."
        )
        self.fields["client_siren"].widget.attrs.update({"inputmode": "numeric", "pattern": "[0-9]*"})
        self.fields["client_tva_intra"].widget.attrs.update({"autocomplete": "off"})
        if company is not None:
            self.fields["client"].queryset = Client.objects.filter(company=company)
            self.fields["project"].queryset = Project.objects.filter(company=company)
            if not self.is_bound and self.instance._state.adding:
                self.fields["due_date"].initial = timezone.localdate() + timedelta(
                    days=company.payment_terms_days or 30
                )

    def clean_client_siren(self):
        raw = "".join(c for c in (self.cleaned_data.get("client_siren") or "") if c.isdigit())
        if raw and len(raw) != 9:
            raise forms.ValidationError("Le SIREN client doit contenir 9 chiffres, ou rester vide.")
        return raw

    def clean_client_tva_intra(self):
        from .vat import is_valid_vat_number, normalize_vat_number

        value = normalize_vat_number(self.cleaned_data.get("client_tva_intra"))
        if value and not is_valid_vat_number(value):
            raise forms.ValidationError(
                "Numéro de TVA intracommunautaire invalide (ex. FR17100408517)."
            )
        return value

    def _get_validation_exclusions(self):
        # Le nom est prérempli depuis la fiche client dans clean() : on évite
        # que la validation du modèle ne le déclare obligatoire avant ce remplissage.
        exclude = super()._get_validation_exclusions()
        exclude.add("client_name")
        return exclude

    def clean(self):
        cleaned = super().clean()
        client = cleaned.get("client")
        if client:
            if not cleaned.get("client_name"):
                cleaned["client_name"] = client.name
            if client.siren and not cleaned.get("client_siren"):
                cleaned["client_siren"] = client.siren
            if getattr(client, "tva_intra", "") and not cleaned.get("client_tva_intra"):
                cleaned["client_tva_intra"] = client.tva_intra
        if not (cleaned.get("client_name") or "").strip():
            self.add_error(
                "client_name",
                "Saisissez le nom du client, ou sélectionnez une fiche client.",
            )
        if cleaned.get("reverse_charge"):
            from .vat import REVERSE_CHARGE_MENTION

            # Le taux global est calculé depuis les lignes ; en autoliquidation
            # la TVA collectée reste à 0 quel que soit le taux des prestations.
            self.instance.vat_rate = Decimal("0.00")
            if not (cleaned.get("vat_exemption_reason") or "").strip():
                cleaned["vat_exemption_reason"] = REVERSE_CHARGE_MENTION
        return cleaned


class InvoiceLineForm(forms.ModelForm):
    class Meta:
        model = InvoiceLine
        fields = ("product", "description", "quantity", "unit_price", "vat_rate")
        widgets = {
            "product": ProductSelect,
            "description": forms.Textarea(
                attrs={"rows": 2, "data-multiline": "1", "aria-label": "Désignation multi-lignes"}
            ),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].label = "Produit du catalogue"
        self.fields["product"].required = False
        self.fields["product"].help_text = "Vide = ligne libre."
        self.fields["product"].widget.attrs.update({
            "data-product-select": "1",
            "aria-label": "Produit du catalogue",
        })
        self.fields["description"].label = "Désignation"
        self.fields["description"].widget.attrs.update({
            "placeholder": "Prestation, produit ou service facturé",
            "autocomplete": "off",
        })
        self.fields["quantity"].label = "Quantité"
        self.fields["quantity"].widget.attrs.update({
            "inputmode": "decimal",
            "step": "0.001",
            "min": "0.001",
            "data-line-quantity": "1",
        })
        self.fields["unit_price"].label = "Prix unitaire HT"
        self.fields["unit_price"].widget.attrs.update({
            "inputmode": "decimal",
            "step": "0.01",
            "min": "0",
            "data-line-unit-price": "1",
        })
        self.fields["vat_rate"].label = "TVA (%)"
        self.fields["vat_rate"].widget.attrs.update({
            "inputmode": "decimal",
            "step": "0.01",
            "min": "0",
            "max": "100",
            "data-line-vat-rate": "1",
        })
        if company is not None:
            self.fields["product"].queryset = Product.objects.filter(company=company, active=True)
            if company.tva != "reel" and not self.is_bound and not self.instance.pk:
                self.fields["vat_rate"].initial = Decimal("0.00")

    @property
    def is_new(self):
        """Vrai pour une ligne ajoutée à l'écran (pas encore enregistrée)."""
        return self.instance._state.adding

    def clean_quantity(self):
        quantity = self.cleaned_data.get("quantity")
        if quantity is None or quantity <= 0:
            raise forms.ValidationError("La quantité doit être supérieure à 0.")
        return quantity

    def clean_unit_price(self):
        price = self.cleaned_data.get("unit_price")
        if price is None or price < 0:
            raise forms.ValidationError("Le prix unitaire ne peut pas être négatif.")
        return price

    def clean_vat_rate(self):
        rate = self.cleaned_data.get("vat_rate")
        if rate is None or rate < 0 or rate > 100:
            raise forms.ValidationError("Le taux de TVA doit être compris entre 0 et 100.")
        return rate


class BaseInvoiceLineFormSet(BaseInlineFormSet):
    """Exige au moins une ligne, sauf sur une ancienne facture sans détail."""

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        kept = [
            form for form in self.forms
            if getattr(form, "cleaned_data", None) and not form.cleaned_data.get("DELETE")
        ]
        has_line = any(
            form.cleaned_data.get("description") or form.cleaned_data.get("product")
            for form in kept
        )
        if has_line:
            return
        # Une facture historique sans lignes peut encore être modifiée (client,
        # projet...) sans être bloquée ; une nouvelle facture doit avoir du détail.
        if not self.instance.pk or self.initial_form_count() > 0:
            raise forms.ValidationError(
                "Ajoutez au moins une ligne : produit du catalogue ou désignation libre."
            )


InvoiceLineFormSet = inlineformset_factory(
    Invoice,
    InvoiceLine,
    form=InvoiceLineForm,
    formset=BaseInvoiceLineFormSet,
    extra=2,
    can_delete=True,
)


class QuoteForm(forms.ModelForm):
    class Meta:
        model = Quote
        fields = (
            "client",
            "client_name",
            "client_siren",
            "project",
            "valid_until",
            "notes",
        )
        widgets = {
            "client": ClientSelect,
            "valid_until": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["client"].label = "Fiche client"
        self.fields["client"].required = False
        self.fields["client"].help_text = (
            "Sélectionnez une fiche pour préremplir le nom et le SIREN."
        )
        self.fields["client"].widget.attrs.update({"data-client-select": "1"})
        self.fields["client_name"].label = "Nom client"
        self.fields["client_name"].required = False
        self.fields["client_siren"].label = "SIREN"
        self.fields["client_siren"].required = False
        self.fields["project"].label = "Projet"
        self.fields["project"].required = False
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

    def clean(self):
        cleaned = super().clean()
        client = cleaned.get("client")
        if client and not cleaned.get("client_name"):
            cleaned["client_name"] = client.name
        if client and client.siren and not cleaned.get("client_siren"):
            cleaned["client_siren"] = client.siren
        if not (cleaned.get("client_name") or "").strip():
            self.add_error(
                "client_name",
                "Saisissez le nom du client, ou sélectionnez une fiche client.",
            )
        return cleaned


class QuoteLineForm(InvoiceLineForm):
    """Même comportement d'édition que les lignes de facture."""

    class Meta(InvoiceLineForm.Meta):
        model = QuoteLine


class BaseQuoteLineFormSet(BaseInlineFormSet):
    """Exige au moins une ligne pour un nouveau devis, comme une facture."""

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        kept = [
            form for form in self.forms
            if getattr(form, "cleaned_data", None) and not form.cleaned_data.get("DELETE")
        ]
        has_line = any(
            form.cleaned_data.get("description") or form.cleaned_data.get("product")
            for form in kept
        )
        if has_line:
            return
        if not self.instance.pk or self.initial_form_count() > 0:
            raise forms.ValidationError(
                "Ajoutez au moins une ligne : produit du catalogue ou désignation libre."
            )


QuoteLineFormSet = inlineformset_factory(
    Quote,
    QuoteLine,
    form=QuoteLineForm,
    formset=BaseQuoteLineFormSet,
    extra=2,
    can_delete=True,
)


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
        self.fields["amount_ht"].widget.attrs.update({"inputmode": "decimal"})
        self.fields["vat_rate"].widget.attrs.update({"inputmode": "decimal"})
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
        self.fields["amount"].widget.attrs.update({"inputmode": "decimal"})
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



class TicketDeCaisseForm(forms.ModelForm):
    """Création / édition d'un ticket de caisse — labels FR et attributs a11y."""

    class Meta:
        model = TicketDeCaisse
        fields = [
            "image",
            "date",
            "magasin",
            "montant_ttc",
            "montant_tva",
            "taux_tva",
            "categorie",
            "moyen_paiement",
            "statut",
            "notes",
        ]
        labels = {
            "image": "Justificatif (photo ou scan)",
            "date": "Date du ticket",
            "magasin": "Magasin / fournisseur",
            "montant_ttc": "Montant TTC",
            "montant_tva": "Montant TVA",
            "taux_tva": "Taux de TVA (%)",
            "categorie": "Catégorie",
            "moyen_paiement": "Moyen de paiement",
            "statut": "Statut",
            "notes": "Notes",
        }
        help_texts = {
            "image": "JPG, PNG, WEBP ou PDF — 10 Mo max. Sur mobile, utilisez « Prendre en photo ».",
            "date": "Date figurant sur le ticket (obligatoire).",
            "magasin": "Nom du magasin ou du fournisseur.",
            "montant_ttc": "Total toutes taxes comprises.",
            "montant_tva": "Montant de TVA indiqué, ou calculé à partir du taux.",
            "taux_tva": "Ex. 20, 10, 5,5. Sert aussi au calcul du HT.",
            "categorie": "Classe le ticket pour le suivi et la compta.",
            "moyen_paiement": "CB, espèces, virement…",
            "statut": "Brouillon jusqu'à validation humaine.",
            "notes": "Informations libres (référence, projet…).",
        }
        widgets = {
            "date": forms.DateInput(
                attrs={
                    "type": "date",
                    "autocomplete": "off",
                },
                format="%Y-%m-%d",
            ),
            "magasin": forms.TextInput(
                attrs={
                    "autocomplete": "organization",
                    "placeholder": "Ex. Carrefour, Total…",
                }
            ),
            "montant_ttc": forms.NumberInput(
                attrs={
                    "inputmode": "decimal",
                    "step": "0.01",
                    "min": "0",
                    "placeholder": "0,00",
                }
            ),
            "montant_tva": forms.NumberInput(
                attrs={
                    "inputmode": "decimal",
                    "step": "0.01",
                    "min": "0",
                    "placeholder": "0,00",
                }
            ),
            "taux_tva": forms.NumberInput(
                attrs={
                    "inputmode": "decimal",
                    "step": "0.01",
                    "min": "0",
                    "placeholder": "20",
                }
            ),
            "moyen_paiement": forms.TextInput(
                attrs={
                    "autocomplete": "off",
                    "placeholder": "CB, espèces…",
                    "list": "ticket-paiement-suggestions",
                }
            ),
            "notes": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "Référence, projet, commentaire…",
                }
            ),
            "image": forms.ClearableFileInput(
                attrs={
                    "accept": "image/jpeg,image/png,image/webp,application/pdf,.jpg,.jpeg,.png,.webp,.pdf",
                    "id": "id_image",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["date"].input_formats = ["%Y-%m-%d", "%d/%m/%Y"]
        self.fields["image"].required = False
        self.fields["statut"].required = False
        self.fields["magasin"].required = False
        self.fields["notes"].required = False
        self.fields["moyen_paiement"].required = False
        # Champs obligatoires pour la saisie manuelle
        self.fields["date"].required = True
        self.fields["montant_ttc"].required = True
        self.fields["categorie"].required = True

        for name, field in self.fields.items():
            css = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = (css + " form-control").strip()
            if field.help_text:
                field.widget.attrs.setdefault("aria-describedby", f"hint_{name}")
            if field.required:
                field.widget.attrs["aria-required"] = "true"
                field.label_suffix = ""

        for name in ("montant_ttc", "montant_tva", "taux_tva"):
            self.fields[name].widget.attrs.update({
                "inputmode": "decimal",
                "data-ticket-money": name,
            })

        if self.is_bound:
            for name, field in self.fields.items():
                if self.errors.get(name):
                    field.widget.attrs["aria-invalid"] = "true"
                    described = field.widget.attrs.get("aria-describedby", "")
                    err_id = f"err_{name}"
                    parts = [p for p in described.split() if p]
                    if err_id not in parts:
                        parts.append(err_id)
                    field.widget.attrs["aria-describedby"] = " ".join(parts)

    def clean_montant_ttc(self):
        amount = self.cleaned_data["montant_ttc"]
        if amount is None or amount < 0:
            raise forms.ValidationError("Le montant TTC doit être positif ou nul.")
        return amount

    def clean_montant_tva(self):
        amount = self.cleaned_data.get("montant_tva")
        if amount is not None and amount < 0:
            raise forms.ValidationError("Le montant de TVA ne peut pas être négatif.")
        return amount

    def clean_taux_tva(self):
        rate = self.cleaned_data.get("taux_tva")
        if rate is not None and (rate < 0 or rate > 100):
            raise forms.ValidationError("Le taux de TVA doit être compris entre 0 et 100.")
        return rate


class TicketUploadForm(forms.Form):
    fichier = forms.FileField(
        label="Photo ou scan du ticket",
        help_text="JPG, PNG, WEBP ou PDF — 10 Mo max.",
        widget=forms.ClearableFileInput(
            attrs={
                "accept": "image/jpeg,image/png,image/webp,application/pdf,.jpg,.jpeg,.png,.webp,.pdf",
                "id": "id_fichier",
            }
        ),
    )
    categorie = forms.ChoiceField(
        choices=[("", "Détecter automatiquement")] + list(TICKET_CATEGORIES),
        required=False,
        label="Catégorie (optionnel)",
    )

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
    TicketDeCaisse,
    TICKET_CATEGORIES,
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
        self.fields["amount_ht"].widget.attrs.update({"inputmode": "decimal"})
        self.fields["vat_rate"].widget.attrs.update({"inputmode": "decimal"})
        self.fields["client_siren"].widget.attrs.update({"inputmode": "numeric", "pattern": "[0-9]*"})
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
        self.fields["amount_ht"].widget.attrs.update({"inputmode": "decimal"})
        self.fields["vat_rate"].widget.attrs.update({"inputmode": "decimal"})
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

from decimal import Decimal

from django import forms

from .models import BankAccount, BankRule, BankTransaction


class BankAccountForm(forms.ModelForm):
    class Meta:
        model = BankAccount
        fields = [
            "label",
            "bank_name",
            "iban",
            "bic",
            "journal",
            "opening_balance",
            "is_active",
        ]
        labels = {
            "label": "Libellé du compte",
            "bank_name": "Banque",
            "iban": "IBAN",
            "bic": "BIC",
            "journal": "Journal de banque",
            "opening_balance": "Solde d'ouverture",
            "is_active": "Compte actif",
        }

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company
        journals = company.journals.filter(type="banque").order_by("code")
        self.fields["journal"].queryset = (
            journals if journals.exists() else company.journals.all()
        )
        self.fields["journal"].required = False
        self.fields["journal"].empty_label = "Journal BQ par défaut"
        if not self.instance.journal_id:
            default = company.journals.filter(code="BQ").first()
            if default is not None:
                self.initial.setdefault("journal", default.pk)


class ImportStatementForm(forms.Form):
    account = forms.ModelChoiceField(
        label="Compte bancaire", queryset=BankAccount.objects.none()
    )
    file = forms.FileField(
        label="Relevé CSV ou OFX",
        help_text="Formats acceptés : .csv, .ofx, .qfx, .txt — 10 Mo maximum.",
    )

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["account"].queryset = company.bank_accounts.filter(
            is_active=True
        ).order_by("label")

    def clean_file(self):
        upload = self.cleaned_data["file"]
        name = (upload.name or "").lower()
        if not name.endswith((".csv", ".ofx", ".qfx", ".txt")):
            raise forms.ValidationError("Choisissez un fichier CSV, OFX ou QFX.")
        if upload.size and upload.size > 10 * 1024 * 1024:
            raise forms.ValidationError("Le relevé dépasse 10 Mo.")
        return upload


class TransactionEntryForm(forms.Form):
    date = forms.DateField(
        label="Date de l'écriture", widget=forms.DateInput(attrs={"type": "date"})
    )
    label = forms.CharField(label="Libellé", max_length=200)
    reference = forms.CharField(label="Référence", max_length=50, required=False)
    counterpart_code = forms.CharField(
        label="Compte de contrepartie",
        max_length=10,
        help_text="Frais bancaires : 627000. Virement fournisseur : 401. Encaissement : 411.",
    )
    vat_account_code = forms.CharField(
        label="Compte de TVA", max_length=10, required=False
    )
    vat_amount = forms.DecimalField(
        label="TVA déductible",
        max_digits=12,
        decimal_places=2,
        required=False,
        initial=Decimal("0.00"),
    )

    def __init__(self, *args, bank_transaction: BankTransaction, rule=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.bank_transaction = bank_transaction
        if not self.is_bound:
            self.fields["date"].initial = bank_transaction.date
            self.fields["label"].initial = (
                rule.entry_label if rule and rule.entry_label else bank_transaction.label
            )[:200]
            self.fields["reference"].initial = bank_transaction.reference
            if rule and rule.counterpart_account_id:
                self.fields["counterpart_code"].initial = rule.counterpart_account.code

    def clean_counterpart_code(self):
        return (self.cleaned_data.get("counterpart_code") or "").strip().upper()

    def clean_vat_account_code(self):
        return (self.cleaned_data.get("vat_account_code") or "").strip().upper()

    def clean(self):
        cleaned = super().clean()
        vat = cleaned.get("vat_amount") or Decimal("0.00")
        amount = self.bank_transaction.absolute_amount
        if vat < 0:
            raise forms.ValidationError("La TVA ne peut pas être négative.")
        if vat > amount:
            raise forms.ValidationError("La TVA dépasse le montant de l'opération.")
        if self.bank_transaction.amount > 0:
            cleaned["vat_amount"] = Decimal("0.00")
        return cleaned


class BankRuleForm(forms.ModelForm):
    class Meta:
        model = BankRule
        fields = [
            "name",
            "label_contains",
            "counterparty_contains",
            "min_amount",
            "max_amount",
            "counterpart_account",
            "entry_label",
            "is_active",
            "priority",
        ]
        labels = {
            "name": "Nom de la règle",
            "label_contains": "Libellé contient",
            "counterparty_contains": "Tiers contient",
            "min_amount": "Montant minimum",
            "max_amount": "Montant maximum",
            "counterpart_account": "Compte de contrepartie",
            "entry_label": "Libellé de l'écriture",
            "is_active": "Règle active",
            "priority": "Priorité",
        }

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["counterpart_account"].queryset = company.accounts.order_by("code")
        self.fields["counterpart_account"].required = False

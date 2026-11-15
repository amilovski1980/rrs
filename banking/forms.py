from decimal import Decimal

from django import forms

from documents.models import Invoice
from purchases.models import PurchaseInvoice

from .models import BankAccount, BankRule, BankTransaction
from .suggestions import guess_counterpart_code, guess_reference


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
        label="Relevé CSV, OFX ou PDF",
        help_text=(
            "Formats acceptés : .csv, .ofx, .qfx, .txt, .pdf — 10 Mo maximum. "
            "Un PDF scanné est passé en OCR."
        ),
    )

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["account"].queryset = company.bank_accounts.filter(
            is_active=True
        ).order_by("label")

    def clean_file(self):
        upload = self.cleaned_data["file"]
        name = (upload.name or "").lower()
        if not name.endswith((".csv", ".ofx", ".qfx", ".txt", ".pdf")):
            raise forms.ValidationError("Choisissez un fichier CSV, OFX, QFX ou PDF.")
        if upload.size and upload.size > 10 * 1024 * 1024:
            raise forms.ValidationError("Le relevé dépasse 10 Mo.")
        return upload


class InvoiceChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return (
            f"{obj.number} — {obj.client_name} — reste "
            f"{obj.amount_remaining:.2f} €"
        )


class PurchaseInvoiceChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return (
            f"{obj.number or 'sans n°'} — {obj.supplier_name} — reste "
            f"{obj.amount_remaining:.2f} €"
        )


class TransactionEntryForm(forms.Form):
    """Rapprochement par nature : le type de mouvement pilote l'écriture."""

    RECONCILIATION_NATURES = [
        choice for choice in BankTransaction.NATURES if choice[0] != "existing"
    ]

    nature = forms.ChoiceField(
        label="Nature de l'opération",
        choices=RECONCILIATION_NATURES,
        widget=forms.Select(attrs={"data-nature-select": "1"}),
    )
    date = forms.DateField(
        label="Date de l'écriture", widget=forms.DateInput(attrs={"type": "date"})
    )
    label = forms.CharField(label="Libellé", max_length=200)
    reference = forms.CharField(
        label="Référence",
        max_length=50,
        required=False,
        help_text="Extraite automatiquement du relevé, modifiable.",
    )

    # Encaissement client
    customer_invoice = InvoiceChoiceField(
        label="Facture client",
        queryset=Invoice.objects.none(),
        required=False,
        help_text="Facultatif : sans facture, le montant est porté au compte 411.",
    )
    gross_amount = forms.DecimalField(
        label="Montant brut",
        max_digits=12,
        decimal_places=2,
        required=False,
        widget=forms.NumberInput(attrs={"step": "0.01", "inputmode": "decimal"}),
    )
    fee_amount = forms.DecimalField(
        label="Frais bancaires",
        max_digits=12,
        decimal_places=2,
        required=False,
        initial=Decimal("0.00"),
        widget=forms.NumberInput(attrs={"step": "0.01", "inputmode": "decimal"}),
    )
    fee_account_code = forms.CharField(
        label="Compte de frais",
        max_length=10,
        required=False,
        initial="627000",
        widget=forms.TextInput(
            attrs={"list": "counterpart-accounts", "autocomplete": "off"}
        ),
    )

    # Paiement fournisseur
    supplier_invoice = PurchaseInvoiceChoiceField(
        label="Facture fournisseur",
        queryset=PurchaseInvoice.objects.none(),
        required=False,
        help_text="Facultatif : sans facture, le montant est porté au compte 401.",
    )

    # Dépense / autre
    charge_account_code = forms.CharField(
        label="Compte de charge",
        max_length=10,
        required=False,
        widget=forms.TextInput(
            attrs={"list": "counterpart-accounts", "autocomplete": "off"}
        ),
    )
    counterpart_code = forms.CharField(
        label="Compte de contrepartie",
        max_length=10,
        required=False,
        widget=forms.TextInput(
            attrs={
                "list": "counterpart-accounts",
                "autocomplete": "off",
                "placeholder": "Ex. 627000",
                "data-counterpart-input": "1",
            }
        ),
    )
    vat_account_code = forms.CharField(
        label="Compte de TVA",
        max_length=10,
        required=False,
        widget=forms.TextInput(
            attrs={
                "list": "vat-accounts",
                "autocomplete": "off",
                "placeholder": "Ex. 445660",
            }
        ),
    )
    vat_amount = forms.DecimalField(
        label="TVA déductible",
        max_digits=12,
        decimal_places=2,
        required=False,
        initial=Decimal("0.00"),
        widget=forms.NumberInput(attrs={"step": "0.01", "inputmode": "decimal"}),
    )

    # Prêt
    loan_principal = forms.DecimalField(
        label="Capital remboursé",
        max_digits=12,
        decimal_places=2,
        required=False,
        widget=forms.NumberInput(attrs={"step": "0.01", "inputmode": "decimal"}),
    )
    loan_interest = forms.DecimalField(
        label="Intérêts",
        max_digits=12,
        decimal_places=2,
        required=False,
        widget=forms.NumberInput(attrs={"step": "0.01", "inputmode": "decimal"}),
    )

    # Virement interne
    transfer_account = forms.ModelChoiceField(
        label="Autre compte bancaire",
        queryset=BankAccount.objects.none(),
        required=False,
    )

    # TVA payée
    vat_payment_account_code = forms.CharField(
        label="Compte de TVA à solder",
        max_length=10,
        required=False,
        widget=forms.TextInput(
            attrs={"list": "vat-accounts", "autocomplete": "off"}
        ),
    )

    def __init__(
        self,
        *args,
        bank_transaction: BankTransaction,
        rule=None,
        company=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.bank_transaction = bank_transaction
        self.company = company or bank_transaction.company
        amount = bank_transaction.absolute_amount

        self.fields["customer_invoice"].queryset = (
            Invoice.objects.filter(
                company=self.company,
                status__in=["issued", "late", "received"],
            )
            .select_related("client", "project")
            .order_by("due_date", "number")
        )
        self.fields["supplier_invoice"].queryset = (
            PurchaseInvoice.objects.filter(company=self.company, status="approved")
            .select_related("supplier")
            .order_by("due_date", "number")
        )
        self.fields["transfer_account"].queryset = (
            self.company.bank_accounts.exclude(pk=bank_transaction.account_id)
            .order_by("label")
        )

        self.fields["nature"].initial = (
            "customer_receipt" if bank_transaction.amount > 0 else "expense"
        )
        self.fields["counterpart_code"].widget.attrs.update(
            {
                "data-other-account": "1",
            }
        )
        self.fields["charge_account_code"].widget.attrs.update(
            {
                "data-expense-account": "1",
            }
        )
        if not self.is_bound:
            label = (
                rule.entry_label if rule and rule.entry_label else bank_transaction.label
            )[:200]
            reference = guess_reference(bank_transaction)
            if rule and rule.counterpart_account_id:
                guessed_account = rule.counterpart_account.code
            else:
                guessed_account = guess_counterpart_code(bank_transaction)
            fee = Decimal("0.00")
            gross = amount
            if bank_transaction.amount > 0:
                gross = amount + fee
            for name, value in (
                ("date", bank_transaction.date),
                ("label", label),
                ("reference", reference),
                ("counterpart_code", guessed_account),
                ("charge_account_code", guessed_account),
                ("gross_amount", gross),
                ("fee_amount", fee),
                ("fee_account_code", "627000"),
                ("vat_account_code", "445660"),
                ("vat_amount", Decimal("0.00")),
                ("loan_principal", amount),
                ("loan_interest", Decimal("0.00")),
                ("vat_payment_account_code", "44571"),
            ):
                self.fields[name].initial = value
                self.initial.setdefault(name, value)
            self.initial.setdefault(
                "nature",
                "customer_receipt" if bank_transaction.amount > 0 else "expense",
            )

    def clean(self):
        cleaned = super().clean()
        nature = cleaned.get("nature")
        amount = self.bank_transaction.absolute_amount
        zero = Decimal("0.00")
        one_cent = Decimal("0.01")

        if nature == "customer_receipt":
            if self.bank_transaction.amount <= 0:
                self.add_error("nature", "Un encaissement client est une entrée d'argent.")
            fee = cleaned.get("fee_amount") or zero
            gross = cleaned.get("gross_amount") or (amount + fee)
            if fee < 0:
                self.add_error("fee_amount", "Les frais ne peuvent pas être négatifs.")
            if abs((gross - fee) - amount) > one_cent:
                self.add_error(
                    "gross_amount",
                    f"Brut ({gross} €) − frais ({fee} €) doit égaler "
                    f"le montant bancaire ({amount} €).",
                )
            invoice = cleaned.get("customer_invoice")
            if invoice and gross > invoice.amount_remaining + one_cent:
                self.add_error(
                    "gross_amount",
                    f"Dépasse le reste à encaisser ({invoice.amount_remaining} €).",
                )
            cleaned["gross_amount"] = gross
            cleaned["fee_amount"] = fee

        elif nature == "supplier_payment":
            if self.bank_transaction.amount >= 0:
                self.add_error("nature", "Un paiement fournisseur est une sortie d'argent.")
            fee = cleaned.get("fee_amount") or zero
            gross = cleaned.get("gross_amount") or (amount - fee)
            if fee < 0:
                self.add_error("fee_amount", "Les frais ne peuvent pas être négatifs.")
            if abs((gross + fee) - amount) > one_cent:
                self.add_error(
                    "gross_amount",
                    f"Payé ({gross} €) + frais ({fee} €) doit égaler "
                    f"le montant bancaire ({amount} €).",
                )
            invoice = cleaned.get("supplier_invoice")
            if invoice and gross > invoice.amount_remaining + one_cent:
                self.add_error(
                    "gross_amount",
                    f"Dépasse le reste à payer ({invoice.amount_remaining} €).",
                )
            cleaned["gross_amount"] = gross
            cleaned["fee_amount"] = fee

        elif nature == "expense":
            if self.bank_transaction.amount >= 0:
                self.add_error("nature", "Une dépense est une sortie d'argent.")
            code = (cleaned.get("charge_account_code") or "").strip().upper()
            if not code:
                self.add_error("charge_account_code", "Choisissez un compte de charge.")
            cleaned["charge_account_code"] = code
            vat = cleaned.get("vat_amount") or zero
            if vat < 0:
                self.add_error("vat_amount", "La TVA ne peut pas être négative.")
            if vat > amount:
                self.add_error("vat_amount", "La TVA dépasse le montant de l'opération.")

        elif nature == "bank_fee":
            if self.bank_transaction.amount >= 0:
                self.add_error("nature", "Les frais bancaires sont une sortie d'argent.")

        elif nature == "loan_payment":
            if self.bank_transaction.amount >= 0:
                self.add_error("nature", "Une échéance de prêt est une sortie d'argent.")
            principal = cleaned.get("loan_principal") or zero
            interest = cleaned.get("loan_interest") or zero
            if principal < 0 or interest < 0:
                self.add_error("loan_principal", "Les montants ne peuvent pas être négatifs.")
            if abs((principal + interest) - amount) > one_cent:
                self.add_error(
                    "loan_principal",
                    f"Capital ({principal} €) + intérêts ({interest} €) doit "
                    f"égaler le montant bancaire ({amount} €).",
                )

        elif nature == "internal_transfer":
            account = cleaned.get("transfer_account")
            if account is None:
                self.add_error("transfer_account", "Choisissez le compte de destination.")
            elif account.pk == self.bank_transaction.account_id:
                self.add_error("transfer_account", "Choisissez un autre compte.")

        elif nature == "vat_payment":
            if self.bank_transaction.amount >= 0:
                self.add_error("nature", "Un paiement de TVA est une sortie d'argent.")
            code = (cleaned.get("vat_payment_account_code") or "").strip().upper()
            if not code:
                self.add_error("vat_payment_account_code", "Choisissez le compte de TVA.")
            cleaned["vat_payment_account_code"] = code

        elif nature == "other":
            code = (cleaned.get("counterpart_code") or "").strip().upper()
            if not code:
                self.add_error("counterpart_code", "Choisissez un compte de contrepartie.")
            cleaned["counterpart_code"] = code
            vat = cleaned.get("vat_amount") or zero
            if self.bank_transaction.amount >= 0:
                cleaned["vat_amount"] = zero
            elif vat < 0:
                self.add_error("vat_amount", "La TVA ne peut pas être négative.")
            elif vat > amount:
                self.add_error("vat_amount", "La TVA dépasse le montant de l'opération.")

        for name in ("charge_account_code", "counterpart_code", "vat_account_code", "vat_payment_account_code", "fee_account_code"):
            if name in cleaned and cleaned[name]:
                cleaned[name] = cleaned[name].strip().upper()
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

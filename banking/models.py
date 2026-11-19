import uuid
from decimal import Decimal

from django.db import models
from django.utils import timezone


class BankAccount(models.Model):
    """Compte bancaire d'une société, rattaché au compte comptable 512."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        "companies.Company", on_delete=models.CASCADE, related_name="bank_accounts"
    )
    label = models.CharField(max_length=120, verbose_name="Libellé")
    bank_name = models.CharField(max_length=120, blank=True, verbose_name="Banque")
    iban = models.CharField(max_length=34, blank=True, verbose_name="IBAN")
    bic = models.CharField(max_length=11, blank=True, verbose_name="BIC")
    journal = models.ForeignKey(
        "accounting.Journal",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bank_accounts",
        verbose_name="Journal de banque",
    )
    ledger_account = models.ForeignKey(
        "accounting.ChartAccount",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bank_accounts",
        verbose_name="Compte comptable",
    )
    opening_balance = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Solde d'ouverture",
    )
    currency = models.CharField(max_length=3, default="EUR", verbose_name="Devise")
    is_active = models.BooleanField(default=True, verbose_name="Actif")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Compte bancaire"
        verbose_name_plural = "Comptes bancaires"
        ordering = ["label"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "iban"],
                condition=~models.Q(iban=""),
                name="uniq_compte_bancaire_iban_par_societe",
            )
        ]

    def __str__(self):
        return f"{self.label} — {self.bank_name}" if self.bank_name else self.label

    @property
    def ledger(self):
        if self.ledger_account_id:
            return self.ledger_account
        return (
            self.company.accounts.filter(code__startswith="512")
            .order_by("code")
            .first()
        )

    @property
    def balance(self):
        movements = self.transactions.aggregate(total=models.Sum("amount"))["total"]
        return ((self.opening_balance or Decimal("0.00")) + (movements or Decimal("0.00"))).quantize(
            Decimal("0.01")
        )


class BankStatement(models.Model):
    """Relevé importé (CSV/Excel/Word/OFX/PDF), conservé pour l'audit."""

    SOURCE_FORMATS = [
        ("csv", "CSV"),
        ("ofx", "OFX / QFX"),
        ("pdf", "PDF"),
        ("xlsx", "Excel (.xlsx)"),
        ("docx", "Word (.docx)"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        "companies.Company", on_delete=models.CASCADE, related_name="bank_statements"
    )
    account = models.ForeignKey(
        BankAccount, on_delete=models.CASCADE, related_name="statements"
    )
    date_start = models.DateField(null=True, blank=True)
    date_end = models.DateField(null=True, blank=True)
    opening_balance = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, blank=True
    )
    closing_balance = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, blank=True
    )
    file = models.FileField(upload_to="banking/releves/", null=True, blank=True)
    # Repli base de données : Vercel monte le code en lecture seule (/var/task),
    # donc le stockage fichier local ne peut pas recevoir le relevé.
    file_data = models.BinaryField(
        null=True,
        blank=True,
        editable=False,
        verbose_name="Fichier en base",
    )
    file_type = models.CharField(max_length=80, blank=True, verbose_name="Type MIME")
    original_filename = models.CharField(max_length=255, blank=True)
    source_format = models.CharField(max_length=8, choices=SOURCE_FORMATS, default="csv")
    row_count = models.PositiveIntegerField(default=0)
    content_hash = models.CharField(max_length=64, blank=True)
    imported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Relevé bancaire"
        verbose_name_plural = "Relevés bancaires"
        ordering = ["-imported_at"]

    def __str__(self):
        return f"{self.account.label} — {self.imported_at:%d/%m/%Y}"


class BankTransaction(models.Model):
    """Opération bancaire importée, à rapprocher d'une écriture comptable."""

    STATUSES = [
        ("unmatched", "À rapprocher"),
        ("matched", "Rapproché"),
        ("ignored", "Ignoré"),
    ]
    MATCH_TYPES = [
        ("auto", "Automatique"),
        ("manual", "Manuel"),
        ("entry", "Écriture créée"),
    ]
    NATURES = [
        ("customer_receipt", "Encaissement client"),
        ("supplier_payment", "Paiement fournisseur"),
        ("expense", "Dépense / achat"),
        ("bank_fee", "Frais bancaires"),
        ("loan_payment", "Remboursement de prêt"),
        ("internal_transfer", "Virement interne"),
        ("vat_payment", "TVA payée à l'État"),
        ("other", "Autre opération"),
        ("existing", "Écriture existante"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        "companies.Company", on_delete=models.CASCADE, related_name="bank_transactions"
    )
    account = models.ForeignKey(
        BankAccount, on_delete=models.CASCADE, related_name="transactions"
    )
    statement = models.ForeignKey(
        BankStatement,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
    )
    date = models.DateField(verbose_name="Date")
    value_date = models.DateField(null=True, blank=True, verbose_name="Date de valeur")
    label = models.CharField(max_length=255, verbose_name="Libellé")
    counterparty = models.CharField(max_length=200, blank=True, verbose_name="Tiers")
    reference = models.CharField(max_length=120, blank=True, verbose_name="Référence")
    external_id = models.CharField(max_length=120, blank=True)
    amount = models.DecimalField(
        max_digits=15, decimal_places=2, verbose_name="Montant (signé)"
    )
    currency = models.CharField(max_length=3, default="EUR")
    status = models.CharField(max_length=12, choices=STATUSES, default="unmatched")
    matched_entry = models.ForeignKey(
        "accounting.JournalEntry",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bank_transactions",
        verbose_name="Écriture rapprochée",
    )
    match_type = models.CharField(max_length=10, choices=MATCH_TYPES, blank=True)
    match_score = models.PositiveSmallIntegerField(default=0)
    nature = models.CharField(
        max_length=24, choices=NATURES, blank=True, default="", verbose_name="Nature"
    )
    fingerprint = models.CharField(max_length=64)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Opération bancaire"
        verbose_name_plural = "Opérations bancaires"
        ordering = ["-date", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["account", "fingerprint"],
                name="uniq_operation_bancaire_empreinte",
            )
        ]
        indexes = [
            models.Index(fields=["company", "status"]),
            models.Index(fields=["account", "date"]),
        ]

    def __str__(self):
        return f"{self.date:%d/%m/%Y} — {self.label} — {self.amount} €"

    @property
    def is_credit(self):
        return self.amount > 0

    @property
    def absolute_amount(self):
        return abs(self.amount)


class BankRule(models.Model):
    """Règle de reconnaissance : pré-remplit le compte de contrepartie."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        "companies.Company", on_delete=models.CASCADE, related_name="bank_rules"
    )
    name = models.CharField(max_length=120, verbose_name="Nom de la règle")
    label_contains = models.CharField(
        max_length=120, blank=True, verbose_name="Libellé contient"
    )
    counterparty_contains = models.CharField(
        max_length=120, blank=True, verbose_name="Tiers contient"
    )
    min_amount = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, blank=True, verbose_name="Montant min"
    )
    max_amount = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, blank=True, verbose_name="Montant max"
    )
    counterpart_account = models.ForeignKey(
        "accounting.ChartAccount",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bank_rules",
        verbose_name="Compte de contrepartie",
    )
    entry_label = models.CharField(
        max_length=200, blank=True, verbose_name="Libellé d'écriture"
    )
    auto_post = models.BooleanField(
        default=False,
        verbose_name="Créer et rapprocher automatiquement",
        help_text=(
            "À l'import, crée l'écriture sur le compte de contrepartie et "
            "rapproche l'opération. Sans cette option, la règle ne fait que "
            "pré-remplir le formulaire."
        ),
    )
    is_active = models.BooleanField(default=True, verbose_name="Active")
    priority = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Règle bancaire"
        verbose_name_plural = "Règles bancaires"
        ordering = ["-priority", "name"]

    def __str__(self):
        return self.name

    def matches(self, transaction) -> bool:
        if not self.is_active:
            return False
        from .utils import normalize_text

        text = normalize_text(f"{transaction.label} {transaction.counterparty}")
        if self.label_contains and normalize_text(self.label_contains) not in text:
            return False
        if self.counterparty_contains and normalize_text(
            self.counterparty_contains
        ) not in normalize_text(transaction.counterparty):
            return False
        amount = transaction.absolute_amount
        if self.min_amount is not None and amount < self.min_amount:
            return False
        if self.max_amount is not None and amount > self.max_amount:
            return False
        return True

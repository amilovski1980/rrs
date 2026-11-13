import uuid

from django.db import models


DEPARTMENTS = [
    ("service_client", "Service client"),
    ("fournisseur", "Fournisseur"),
    ("facturation", "Facturation"),
    ("direction", "Direction"),
    ("commercial", "Commercial"),
    ("technique", "Technique"),
    ("autre", "Autre"),
]


class Contact(models.Model):
    """Personne de contact d'une société, éventuellement rattachée à un client.

    Le carnet est isolé par société (tenant). Un contact peut représenter un
    service client, un fournisseur, la facturation ou toute autre équipe.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.CASCADE,
        related_name="contacts",
        verbose_name="Société",
    )
    client = models.ForeignKey(
        "documents.Client",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contacts",
        verbose_name="Fiche client",
    )
    organization = models.CharField(
        max_length=200,
        blank=True,
        verbose_name="Société / organisation",
        help_text="Renseignée automatiquement depuis la fiche client si elle est vide.",
    )
    first_name = models.CharField(max_length=80, verbose_name="Prénom")
    last_name = models.CharField(max_length=80, verbose_name="Nom")
    department = models.CharField(
        max_length=20,
        choices=DEPARTMENTS,
        default="service_client",
        verbose_name="Département",
    )
    job_title = models.CharField(max_length=120, blank=True, verbose_name="Fonction")
    email = models.EmailField(blank=True, verbose_name="E-mail")
    phone = models.CharField(max_length=30, blank=True, verbose_name="Téléphone")
    is_primary = models.BooleanField(default=False, verbose_name="Contact principal")
    notes = models.TextField(blank=True, verbose_name="Notes")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_primary", "last_name", "first_name"]
        verbose_name = "Contact"
        verbose_name_plural = "Contacts"

    def __str__(self):
        label = self.full_name
        return f"{label} — {self.organization}" if self.organization else label

    @property
    def full_name(self):
        return " ".join(
            part for part in ((self.first_name or "").strip(), (self.last_name or "").strip()) if part
        )

    def save(self, *args, **kwargs):
        if self.client_id and not (self.organization or "").strip():
            self.organization = self.client.name
        if self.is_primary and self.company_id:
            siblings = Contact.objects.filter(company_id=self.company_id, is_primary=True)
            if self.client_id:
                siblings = siblings.filter(client_id=self.client_id)
            else:
                siblings = siblings.filter(client__isnull=True)
            siblings.exclude(pk=self.pk).update(is_primary=False)
        super().save(*args, **kwargs)

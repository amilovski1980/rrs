from django.conf import settings
from django.db import migrations, models
import django.utils.timezone
import uuid


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("billing", "0003_entitlements_and_customer"),
    ]

    operations = [
        migrations.AddField(
            model_name="subscription",
            name="follow_up",
            field=models.CharField(
                blank=True,
                choices=[
                    ("", "Aucun"),
                    ("to_follow", "À relancer"),
                    ("reminded", "Relancé"),
                    ("resolved", "Régularisé"),
                ],
                default="",
                max_length=20,
                verbose_name="Suivi",
            ),
        ),
        migrations.AddField(
            model_name="subscription",
            name="staff_note",
            field=models.TextField(blank=True, default="", verbose_name="Note interne"),
        ),
        migrations.AlterField(
            model_name="subscription",
            name="status",
            field=models.CharField(
                choices=[
                    ("trialing", "Essai"),
                    ("active", "Actif"),
                    ("past_due", "Retard de paiement"),
                    ("unpaid", "Impayé"),
                    ("canceled", "Résilié"),
                ],
                default="trialing",
                max_length=12,
            ),
        ),
        migrations.CreateModel(
            name="SubscriptionInvoice",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("external_id", models.CharField(max_length=80, unique=True)),
                ("number", models.CharField(blank=True, default="", max_length=40)),
                ("amount_eur", models.DecimalField(decimal_places=2, default=0, max_digits=8)),
                ("status", models.CharField(
                    choices=[
                        ("paid", "Payée"),
                        ("open", "À payer"),
                        ("failed", "Échec"),
                        ("void", "Annulée"),
                        ("uncollectible", "Irrécouvrable"),
                        ("draft", "Brouillon"),
                    ],
                    default="open",
                    max_length=20,
                )),
                ("description", models.CharField(blank=True, default="", max_length=255)),
                ("failure_message", models.CharField(blank=True, default="", max_length=400)),
                ("hosted_url", models.CharField(blank=True, default="", max_length=500)),
                ("staff_note", models.TextField(blank=True, default="")),
                ("issued_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("paid_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("subscription", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="invoices",
                    to="billing.subscription",
                )),
                ("user", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="subscription_invoices",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={"ordering": ["-issued_at", "-created_at"]},
        ),
    ]

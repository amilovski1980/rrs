from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0002_backoffice_extensions"),
    ]

    operations = [
        migrations.AddField(
            model_name="plan",
            name="entitlements",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Matrice éditable : fonctions et modèles de facture.",
                verbose_name="Matrice de fonctions",
            ),
        ),
        migrations.AddField(
            model_name="subscription",
            name="stripe_customer_id",
            field=models.CharField(blank=True, default="", max_length=50),
        ),
    ]

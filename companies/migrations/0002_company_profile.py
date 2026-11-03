from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("companies", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="company",
            name="phone",
            field=models.CharField(blank=True, max_length=30),
        ),
        migrations.AddField(
            model_name="company",
            name="email",
            field=models.EmailField(blank=True, max_length=254),
        ),
        migrations.AddField(
            model_name="company",
            name="invoice_theme",
            field=models.CharField(
                choices=[
                    ("azur", "Azur"),
                    ("carmin", "Carmin"),
                    ("encre", "Encre"),
                    ("sauge", "Sauge"),
                ],
                default="azur",
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name="company",
            name="logo",
            field=models.BinaryField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="company",
            name="logo_type",
            field=models.CharField(blank=True, max_length=40),
        ),
    ]

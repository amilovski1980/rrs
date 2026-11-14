from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("companies", "0003_alter_company_invoice_theme"),
    ]

    operations = [
        migrations.AddField(
            model_name="company",
            name="slogan",
            field=models.CharField(blank=True, max_length=120),
        ),
    ]

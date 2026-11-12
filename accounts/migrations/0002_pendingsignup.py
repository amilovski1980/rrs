from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="PendingSignup",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("email", models.EmailField(max_length=254)),
                ("phone", models.CharField(max_length=20)),
                ("siren", models.CharField(max_length=9)),
                ("payload", models.JSONField(default=dict)),
                ("token_hash", models.CharField(max_length=64, unique=True)),
                ("phone_code_hash", models.CharField(blank=True, max_length=64)),
                ("phone_verified", models.BooleanField(default=False)),
                ("expires_at", models.DateTimeField()),
                ("consumed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
    ]

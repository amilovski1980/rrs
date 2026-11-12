from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admin_backoffice", "0002_backoffice_extensions"),
    ]

    operations = [
        migrations.AddField(
            model_name="siteconfiguration",
            name="ai_text_provider",
            field=models.CharField(
                choices=[("qwen", "Qwen (auto-hébergé)"), ("xai", "xAI / Grok")],
                default="qwen",
                max_length=12,
                verbose_name="Fournisseur du chat Aminia",
            ),
        ),
        migrations.AddField(
            model_name="siteconfiguration",
            name="llm_base_url",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Vide = variable LLM_BASE_URL.",
                max_length=255,
                verbose_name="URL de base Qwen",
            ),
        ),
        migrations.AddField(
            model_name="siteconfiguration",
            name="llm_model",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Vide = variable LLM_MODEL.",
                max_length=120,
                verbose_name="Modèle Qwen",
            ),
        ),
        migrations.AddField(
            model_name="siteconfiguration",
            name="stripe_publishable_key",
            field=models.CharField(blank=True, default="", max_length=255, verbose_name="Clé publique Stripe"),
        ),
        migrations.AddField(
            model_name="siteconfiguration",
            name="stripe_webhook_secret",
            field=models.CharField(blank=True, default="", max_length=255, verbose_name="Secret webhook Stripe"),
        ),
        migrations.AddField(
            model_name="siteconfiguration",
            name="xai_api_key",
            field=models.CharField(blank=True, default="", max_length=512, verbose_name="Clé API xAI"),
        ),
        migrations.AddField(
            model_name="siteconfiguration",
            name="xai_text_model",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Vide = variable XAI_TEXT_MODEL (grok-3 par défaut).",
                max_length=120,
                verbose_name="Modèle de chat xAI",
            ),
        ),
        migrations.AddField(
            model_name="siteconfiguration",
            name="xai_voice",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Vide = variable XAI_VOICE.",
                max_length=40,
                verbose_name="Voix xAI",
            ),
        ),
        migrations.AddField(
            model_name="siteconfiguration",
            name="xai_voice_model",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Vide = variable XAI_VOICE_MODEL.",
                max_length=120,
                verbose_name="Modèle vocal xAI",
            ),
        ),
    ]

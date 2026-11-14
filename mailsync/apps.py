from django.apps import AppConfig


class MailsyncConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "mailsync"
    verbose_name = "Connecteur e-mail comptable"

"""Fournisseurs SMS (OVH, Brevo, Twilio).

Configuration seulement : les appels HTTP ne sont pas branchés.
`dispatch_sms` est le point d'extension unique. Chaque classe `send`
porte un TODO à l'endroit où l'appel réel devra être ajouté.
"""
from __future__ import annotations

from .models import SmsMessage, SmsProviderConfig, SmsSettings, SmsTemplate

PROVIDERS = ("ovh", "brevo", "twilio")


class SmsNotImplemented(Exception):
    """L'appel HTTP du fournisseur n'est pas encore branché."""


class CredentialField:
    def __init__(self, key: str, label: str, secret: bool = True):
        self.key = key
        self.label = label
        self.secret = secret


class SmsBackend:
    code = ""
    label = ""
    credential_fields: tuple[CredentialField, ...] = ()

    def missing(self, config: SmsProviderConfig) -> list[str]:
        stored = config.credentials or {}
        absent = []
        for field in self.credential_fields:
            if not str(stored.get(field.key) or "").strip():
                absent.append(field.label)
        return absent

    def send(self, *, recipient: str, body: str, sender: str, credentials: dict) -> None:
        raise SmsNotImplemented(
            f"TODO : brancher l'appel API {self.label}. "
            "Le message est journalisé, aucun SMS n'est envoyé."
        )


class OvhSmsBackend(SmsBackend):
    code = "ovh"
    label = "OVH"
    credential_fields = (
        CredentialField("application_key", "Clé application"),
        CredentialField("application_secret", "Secret application"),
        CredentialField("consumer_key", "Clé consommateur"),
        CredentialField("service_name", "Nom du service SMS", secret=False),
    )

    def send(self, *, recipient: str, body: str, sender: str, credentials: dict) -> None:
        # TODO: POST https://eu.api.ovh.com/1.0/sms/{serviceName}/jobs
        # avec application_key, application_secret, consumer_key et sender.
        raise SmsNotImplemented(
            "TODO : brancher l'API SMS OVH. Aucun SMS n'a été envoyé."
        )


class BrevoSmsBackend(SmsBackend):
    code = "brevo"
    label = "Brevo"
    credential_fields = (
        CredentialField("api_key", "Clé API"),
    )

    def send(self, *, recipient: str, body: str, sender: str, credentials: dict) -> None:
        # TODO: POST https://api.brevo.com/v3/transactionalSMS/sms
        # en-tête api-key, corps sender / recipient / content.
        raise SmsNotImplemented(
            "TODO : brancher l'API SMS Brevo. Aucun SMS n'a été envoyé."
        )


class TwilioSmsBackend(SmsBackend):
    code = "twilio"
    label = "Twilio"
    credential_fields = (
        CredentialField("account_sid", "Account SID"),
        CredentialField("auth_token", "Auth token"),
        CredentialField("from_number", "Numéro expéditeur", secret=False),
    )

    def send(self, *, recipient: str, body: str, sender: str, credentials: dict) -> None:
        # TODO: POST https://api.twilio.com/2010-04-01/Accounts/{AccountSid}/Messages.json
        # authentification SID + token, From / To / Body.
        raise SmsNotImplemented(
            "TODO : brancher l'API SMS Twilio. Aucun SMS n'a été envoyé."
        )


REGISTRY = {
    backend.code: backend
    for backend in (OvhSmsBackend(), BrevoSmsBackend(), TwilioSmsBackend())
}


def get_backend(code: str) -> SmsBackend | None:
    return REGISTRY.get(code)


def ensure_providers() -> list[SmsProviderConfig]:
    configs = []
    for code in PROVIDERS:
        config, _ = SmsProviderConfig.objects.get_or_create(code=code)
        configs.append(config)
    return configs


def get_settings() -> SmsSettings:
    row, _ = SmsSettings.objects.get_or_create(pk=1)
    return row


def mask_secret(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if len(value) <= 4:
        return "••••"
    return "••••" + value[-4:]


def provider_card(config: SmsProviderConfig) -> dict:
    backend = get_backend(config.code)
    stored = config.credentials or {}
    fields = []
    for field in backend.credential_fields:
        raw = str(stored.get(field.key) or "")
        fields.append({
            "key": field.key,
            "label": field.label,
            "secret": field.secret,
            "filled": bool(raw.strip()),
            "mask": mask_secret(raw) if field.secret and raw.strip() else "",
            "value": "" if field.secret else raw,
        })
    return {
        "code": config.code,
        "label": backend.label,
        "enabled": config.enabled,
        "sender_name": config.sender_name,
        "configured": not backend.missing(config),
        "fields": fields,
    }


def save_provider_post(request) -> str:
    """Enregistre les trois fournisseurs et le fournisseur actif. Ne journalise aucun secret."""
    settings_row = get_settings()
    active = (request.POST.get("active_provider") or "").strip()
    if active not in PROVIDERS:
        active = ""
    settings_row.active_provider = active
    settings_row.save(update_fields=["active_provider", "updated_at"])

    for config in ensure_providers():
        backend = get_backend(config.code)
        stored = dict(config.credentials or {})
        for field in backend.credential_fields:
            posted = request.POST.get(f"{config.code}__{field.key}", "")
            posted = (posted or "").strip()
            if field.secret:
                if posted and not posted.startswith("••••"):
                    stored[field.key] = posted
            else:
                stored[field.key] = posted
        config.credentials = stored
        config.enabled = request.POST.get(f"enabled__{config.code}") == "1"
        config.sender_name = (request.POST.get(f"sender__{config.code}") or "").strip()[:32]
        config.save()

    if active and not SmsProviderConfig.objects.filter(code=active, enabled=True).exists():
        return "Réglages SMS enregistrés. Le fournisseur choisi est désactivé : aucun envoi ne partira."
    if not active:
        return "Réglages SMS enregistrés. Aucun fournisseur n'est sélectionné pour l'envoi."
    return "Réglages SMS enregistrés."


def test_provider(code: str) -> dict:
    """Contrôle la présence des identifiants. N'appelle pas le réseau."""
    backend = get_backend(code)
    if backend is None:
        return {"ok": False, "message": "Fournisseur inconnu."}
    config = SmsProviderConfig.objects.filter(code=code).first()
    if config is None:
        return {"ok": False, "message": f"Test {backend.label} : fournisseur absent."}
    missing = backend.missing(config)
    if missing:
        return {
            "ok": False,
            "message": f"Test {backend.label} : configuration incomplète ({', '.join(missing)}).",
        }
    state = "activé" if config.enabled else "désactivé"
    return {
        "ok": True,
        "message": (
            f"Test {backend.label} : identifiants enregistrés, fournisseur {state}. "
            "L'appel API réel n'est pas encore branché."
        ),
    }


def dispatch_sms(*, recipient: str, body: str, template: SmsTemplate | None = None, actor=None) -> SmsMessage:
    """Point d'entrée unique pour envoyer un SMS.

    Le fournisseur actif (OVH, Brevo ou Twilio) est résolu ici.
    Tant que `SmsBackend.send` n'est pas implémenté, le message est journalisé
    avec le statut « skipped » et aucun appel réseau n'est fait.
    """
    recipient = (recipient or "").strip()
    body = (body or "").strip()
    settings_row = SmsSettings.objects.filter(pk=1).first()
    code = (settings_row.active_provider if settings_row else "") or ""
    config = SmsProviderConfig.objects.filter(code=code).first() if code else None
    backend = get_backend(code) if code else None

    def _log(status: str, detail: str, provider: str = "") -> SmsMessage:
        return SmsMessage.objects.create(
            recipient=recipient[:32],
            body=body,
            provider=provider,
            template=template,
            status=status,
            detail=detail[:2000],
            created_by=actor if getattr(actor, "is_authenticated", False) else None,
        )

    if not recipient or not body:
        return _log("failed", "Destinataire ou message manquant.")
    if backend is None or config is None:
        return _log("skipped", "Aucun fournisseur actif. Branchez OVH, Brevo ou Twilio.")
    if not config.enabled:
        return _log("skipped", f"{backend.label} est désactivé.", provider=code)
    missing = backend.missing(config)
    if missing:
        return _log(
            "failed",
            "Configuration incomplète : " + ", ".join(missing) + ".",
            provider=code,
        )
    try:
        backend.send(
            recipient=recipient,
            body=body,
            sender=config.sender_name,
            credentials=dict(config.credentials or {}),
        )
    except SmsNotImplemented as exc:
        return _log("skipped", str(exc), provider=code)
    except Exception:
        return _log("failed", "Échec de l'envoi. Le détail technique n'est pas affiché.", provider=code)
    return _log("sent", "Envoyé.", provider=code)

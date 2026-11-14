"""Fournisseurs SMS (OVH, Brevo, Twilio).

`dispatch_sms` est le point d'entrée unique : il résout le fournisseur
actif, journalise chaque tentative et appelle l'API réelle. Les secrets ne
sont jamais renvoyés en clair ni écrits dans le journal.
"""
from __future__ import annotations

import hashlib
import json
import time

import httpx

from .models import SmsMessage, SmsProviderConfig, SmsSettings, SmsTemplate

PROVIDERS = ("ovh", "brevo", "twilio")
DEFAULT_SENDER = "RoadRunner"


class SmsSendError(Exception):
    """Échec d'envoi lisible, sans secret ni détail technique brut."""


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
        raise SmsSendError(f"{self.label} : envoi non disponible.")


def _ensure_success(response: httpx.Response, label: str) -> None:
    if response.status_code >= 400:
        raise SmsSendError(f"{label} : réponse HTTP {response.status_code}.")


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
        service = str(credentials.get("service_name") or "").strip()
        application_key = str(credentials.get("application_key") or "").strip()
        application_secret = str(credentials.get("application_secret") or "").strip()
        consumer_key = str(credentials.get("consumer_key") or "").strip()
        url = f"https://eu.api.ovh.com/1.0/sms/{service}/jobs"
        payload = {
            "sender": (sender or DEFAULT_SENDER)[:32],
            "message": body,
            "receivers": [recipient],
            "noStopClause": True,
        }
        encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        timestamp = str(int(time.time()))
        raw = "+".join(
            [application_secret, consumer_key, "POST", url, encoded, timestamp]
        )
        headers = {
            "Content-Type": "application/json",
            "X-Ovh-Application": application_key,
            "X-Ovh-Consumer": consumer_key,
            "X-Ovh-Timestamp": timestamp,
            "X-Ovh-Signature": "$1$" + hashlib.sha1(raw.encode("utf-8")).hexdigest(),
        }
        try:
            response = httpx.post(url, content=encoded.encode("utf-8"), headers=headers, timeout=20)
        except httpx.HTTPError as exc:
            raise SmsSendError("OVH : service injoignable.") from exc
        _ensure_success(response, "OVH")


class BrevoSmsBackend(SmsBackend):
    code = "brevo"
    label = "Brevo"
    credential_fields = (
        CredentialField("api_key", "Clé API"),
    )

    def send(self, *, recipient: str, body: str, sender: str, credentials: dict) -> None:
        api_key = str(credentials.get("api_key") or "").strip()
        payload = {
            "sender": (sender or DEFAULT_SENDER)[:11],
            "recipient": recipient,
            "content": body,
        }
        try:
            response = httpx.post(
                "https://api.brevo.com/v3/transactionalSMS/sms",
                headers={
                    "api-key": api_key,
                    "accept": "application/json",
                    "content-type": "application/json",
                },
                json=payload,
                timeout=20,
            )
        except httpx.HTTPError as exc:
            raise SmsSendError("Brevo : service injoignable.") from exc
        _ensure_success(response, "Brevo")


class TwilioSmsBackend(SmsBackend):
    code = "twilio"
    label = "Twilio"
    credential_fields = (
        CredentialField("account_sid", "Account SID"),
        CredentialField("auth_token", "Auth token"),
        CredentialField("from_number", "Numéro expéditeur", secret=False),
    )

    def send(self, *, recipient: str, body: str, sender: str, credentials: dict) -> None:
        account_sid = str(credentials.get("account_sid") or "").strip()
        auth_token = str(credentials.get("auth_token") or "").strip()
        from_number = str(credentials.get("from_number") or "").strip()
        url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
        try:
            response = httpx.post(
                url,
                auth=(account_sid, auth_token),
                data={
                    "From": from_number or sender,
                    "To": recipient,
                    "Body": body,
                },
                timeout=20,
            )
        except httpx.HTTPError as exc:
            raise SmsSendError("Twilio : service injoignable.") from exc
        _ensure_success(response, "Twilio")


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


def test_provider(code: str, recipient: str = "", actor=None) -> dict:
    """Teste un fournisseur.

    Sans numéro, seuls les identifiants sont contrôlés. Avec un numéro, un
    vrai SMS de test est envoyé et journalisé.
    """
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
    if recipient:
        return send_test_sms(code, recipient, actor=actor)
    state = "activé" if config.enabled else "désactivé"
    return {
        "ok": True,
        "message": (
            f"Test {backend.label} : identifiants enregistrés, fournisseur {state}. "
            "Ajoutez un numéro pour envoyer un vrai SMS de test."
        ),
    }


def send_test_sms(code: str, recipient: str, actor=None) -> dict:
    """Envoie un SMS de test avec le fournisseur demandé, même s'il n'est pas actif."""
    backend = get_backend(code)
    if backend is None:
        return {"ok": False, "message": "Fournisseur inconnu."}
    config = SmsProviderConfig.objects.filter(code=code).first()
    if config is None:
        return {"ok": False, "message": f"{backend.label} : fournisseur absent."}
    missing = backend.missing(config)
    if missing:
        return {
            "ok": False,
            "message": f"{backend.label} : configuration incomplète ({', '.join(missing)}).",
        }
    recipient = (recipient or "").strip()[:32]
    body = "Test Road Runner Solutions : votre configuration SMS fonctionne."
    try:
        backend.send(
            recipient=recipient,
            body=body,
            sender=config.sender_name,
            credentials=dict(config.credentials or {}),
        )
    except SmsSendError as exc:
        detail = str(exc)[:500]
        SmsMessage.objects.create(
            recipient=recipient,
            body=body,
            provider=code,
            status="failed",
            detail=detail,
            created_by=actor if getattr(actor, "is_authenticated", False) else None,
        )
        return {"ok": False, "message": f"Test {backend.label} : échec. {detail}"}
    except Exception:
        SmsMessage.objects.create(
            recipient=recipient,
            body=body,
            provider=code,
            status="failed",
            detail="Échec de l'envoi. Le détail technique n'est pas affiché.",
            created_by=actor if getattr(actor, "is_authenticated", False) else None,
        )
        return {"ok": False, "message": f"Test {backend.label} : échec de l'envoi."}
    SmsMessage.objects.create(
        recipient=recipient,
        body=body,
        provider=code,
        status="sent",
        detail="SMS de test envoyé.",
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )
    return {"ok": True, "message": f"Test {backend.label} : SMS envoyé au {recipient}."}


def dispatch_sms(*, recipient: str, body: str, template: SmsTemplate | None = None, actor=None) -> SmsMessage:
    """Point d'entrée unique pour envoyer un SMS.

    Le fournisseur actif (OVH, Brevo ou Twilio) est résolu ici, puis l'API
    réelle est appelée. Chaque tentative est journalisée sans secret.
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
    except SmsSendError as exc:
        return _log("failed", str(exc), provider=code)
    except Exception:
        return _log("failed", "Échec de l'envoi. Le détail technique n'est pas affiché.", provider=code)
    return _log("sent", f"Envoyé via {backend.label}.", provider=code)

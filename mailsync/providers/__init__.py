"""Registre des fournisseurs d'e-mail.

Ajouter Outlook (Microsoft Graph) plus tard : créer ``outlook.py`` avec une
classe ``OutlookAdapter(EmailProviderInterface)`` puis, ici, une ligne
``register(OutlookAdapter)``. Le reste du module est inchangé.
"""

from .base import (
    EmailProviderInterface,
    MailAttachment,
    MailMessage,
    OAuthTokens,
    ProviderAuthError,
    ProviderError,
    ProviderNotConfigured,
)
from .gmail import GmailAdapter

_REGISTRY: dict[str, type[EmailProviderInterface]] = {}


def register(provider_class: type[EmailProviderInterface]) -> None:
    _REGISTRY[provider_class.provider_id] = provider_class


def get_provider_class(provider_id: str) -> type[EmailProviderInterface]:
    try:
        return _REGISTRY[provider_id]
    except KeyError as exc:
        raise ProviderError(f"Fournisseur d'e-mail inconnu : {provider_id}") from exc


def available_providers() -> list[tuple[str, str]]:
    return [
        (provider_id, provider_class.display_name)
        for provider_id, provider_class in _REGISTRY.items()
    ]


register(GmailAdapter)

__all__ = [
    "EmailProviderInterface",
    "MailAttachment",
    "MailMessage",
    "OAuthTokens",
    "ProviderAuthError",
    "ProviderError",
    "ProviderNotConfigured",
    "available_providers",
    "get_provider_class",
    "register",
]

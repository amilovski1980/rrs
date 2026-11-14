"""Cycle de vie des jetons OAuth2 d'une boîte connectée.

Rafraîchissement paresseux : un access token n'est renouvelé qu'à l'approche
de l'expiration (marge de 2 minutes), puis chiffré et persisté.
"""

from datetime import timedelta

from django.utils import timezone

from .crypto import decrypt_text
from .providers import EmailProviderInterface, ProviderAuthError, get_provider_class

REFRESH_MARGIN = timedelta(seconds=120)


def ensure_access_token(config) -> str:
    """Retourne un access token valide, en rafraîchissant si nécessaire."""
    access_token = decrypt_text(config.access_token_enc)
    expires_at = config.token_expires_at
    if access_token and (
        expires_at is None or expires_at > timezone.now() + REFRESH_MARGIN
    ):
        return access_token

    refresh_token = decrypt_text(config.refresh_token_enc)
    if not refresh_token:
        raise ProviderAuthError(
            "Aucun refresh token disponible : reconnectez la boîte e-mail."
        )

    provider_class = get_provider_class(config.provider)
    tokens = provider_class.refresh_access_token(refresh_token)
    config.set_tokens(tokens)
    config.status = "connected"
    config.last_error = ""
    config.save(
        update_fields=[
            "access_token_enc",
            "refresh_token_enc",
            "token_expires_at",
            "granted_scopes",
            "email_address",
            "provider_account_id",
            "status",
            "last_error",
            "updated_at",
        ]
    )
    return tokens.access_token


def build_adapter(config) -> EmailProviderInterface:
    """Instancie l'adaptateur du fournisseur configuré, jeton en main."""
    provider_class = get_provider_class(config.provider)
    return provider_class(ensure_access_token(config))

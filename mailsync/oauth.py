"""Flux OAuth2 côté vues : état anti-CSRF en session, échange de code."""

import secrets

from .providers import ProviderError, get_provider_class

STATE_SESSION_KEY = "mailsync_oauth_state"


def begin(request, provider_id: str):
    """Construit la redirection vers l'écran de consentement du fournisseur."""
    provider_class = get_provider_class(provider_id)
    redirect_uri = _redirect_uri(request, provider_id)
    state = secrets.token_urlsafe(24)
    request.session[STATE_SESSION_KEY] = f"{provider_id}:{state}"
    return provider_class.authorize_url(redirect_uri, state)


def complete(request, provider_id: str, *, code: str, state: str, config) -> None:
    """Valide l'état anti-CSRF, échange le code et persiste les jetons."""
    expected = request.session.pop(STATE_SESSION_KEY, "")
    if not expected or expected != f"{provider_id}:{state}":
        raise ProviderError("État OAuth invalide ou expiré. Réessayez la connexion.")
    if not code:
        raise ProviderError("Code d'autorisation absent de la réponse du fournisseur.")

    provider_class = get_provider_class(provider_id)
    tokens = provider_class.exchange_code(code, _redirect_uri(request, provider_id))

    config.provider = provider_id
    config.set_tokens(tokens)
    config.is_active = True
    config.status = "connected"
    config.last_error = ""
    config.save()


def _redirect_uri(request, provider_id: str) -> str:
    from django.urls import reverse

    return request.build_absolute_uri(
        reverse("mailsync:oauth_callback", args=[provider_id])
    )

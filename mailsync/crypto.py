"""Chiffrement symétrique des jetons OAuth2 (Fernet).

La clé est dérivée de ``MAILSYNC_ENCRYPTION_KEY`` si elle est définie, sinon
de ``DJANGO_SECRET_KEY``. Changer la clé rend les jetons existants illisibles :
il suffit alors de reconnecter la boîte (aucune donnée comptable n'est perdue).
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _fernet() -> Fernet:
    raw = getattr(settings, "MAILSYNC_ENCRYPTION_KEY", "") or settings.SECRET_KEY
    key = base64.urlsafe_b64encode(hashlib.sha256(raw.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_text(value: str) -> str:
    """Retourne le jeton chiffré (ASCII), ou ``""`` si la valeur est vide."""
    if not value:
        return ""
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_text(token: str) -> str:
    """Déchiffre un jeton ; retourne ``""`` si la clé a changé ou est invalide."""
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError):
        return ""

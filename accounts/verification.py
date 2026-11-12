"""Vérification d'inscription : lien email, et point d'accroche SMS.

Aucun opérateur SMS n'est branché. ``send_phone_verification`` est le seul
endroit à modifier le jour où un fournisseur (OVH, Brevo SMS, etc.) existera.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import send_mail
from core.public_theme import themed_reverse

logger = logging.getLogger(__name__)


class PhoneError(ValueError):
    """Numéro inutilisable pour l'inscription."""


def normalize_french_phone(value: str) -> str:
    """Ramène un numéro français à 10 chiffres (0X XX XX XX XX, sans espaces)."""
    raw = (value or "").strip()
    if not raw:
        raise PhoneError("Indiquez un numéro de téléphone.")
    digits = "".join(char for char in raw if char.isdigit())
    if raw.startswith("+") or raw.startswith("00"):
        if digits.startswith("00"):
            digits = digits[2:]
        if digits.startswith("33") and len(digits) == 11:
            national = "0" + digits[2:]
        else:
            raise PhoneError("Utilisez un numéro français, par exemple 06 12 34 56 78.")
    elif len(digits) == 10 and digits.startswith("0"):
        national = digits
    else:
        raise PhoneError("Utilisez un numéro français à 10 chiffres.")
    if national[1] not in "123456789":
        raise PhoneError("Ce numéro de téléphone n'est pas valide.")
    return national


def send_phone_verification(phone: str, code: str) -> bool:
    """Demande l'envoi d'un code de vérification par SMS.

    TODO: brancher un fournisseur SMS. Retourner True seulement une fois
    le SMS réellement confié à l'opérateur. Le code ne doit pas être journalisé.

    Aujourd'hui aucun fournisseur n'existe : rien n'est envoyé, la fonction
    retourne False et l'inscription par lien email n'est pas bloquée.
    """
    del code  # réservé au futur connecteur ; ne pas le logger
    tail = phone[-2:] if len(phone) >= 2 else "??"
    logger.info(
        "Vérification SMS non envoyée (aucun fournisseur) — numéro se terminant par %s",
        tail,
    )
    return False


def send_signup_link(request, email: str, token: str) -> str:
    """Envoie le lien magique d'ouverture de cockpit. Retourne l'URL absolue."""
    url = request.build_absolute_uri(themed_reverse(request, "signup_verify", token=token))
    send_mail(
        subject="Confirmez votre cockpit Road Runner Solutions",
        message=(
            "Bonjour,\n\n"
            "Pour confirmer votre adresse email et ouvrir votre cockpit, "
            "utilisez ce lien (valable 60 minutes, une seule fois) :\n"
            f"{url}\n\n"
            "Si vous n'êtes pas à l'origine de cette demande, ignorez ce message.\n"
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[email],
        fail_silently=False,
    )
    return url

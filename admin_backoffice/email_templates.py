"""Modèles d'emails automatiques, personnalisables depuis le back-office.

Les textes par défaut vivent ici et restent la source de vérité tant qu'aucune
ligne ``EmailTemplate`` n'a été enregistrée pour le code concerné. Les emails
transactionnels (bienvenue, confirmation d'inscription, lien de connexion,
mot de passe) passent tous par ``send_template_email`` : une personnalisation
enregistrée dans l'administration est donc réellement utilisée à l'envoi.

Placeholders : syntaxe ``{nom_du_placeholder}``. Un placeholder inconnu est
laissé tel quel (``{inconnu}``) pour ne jamais casser un envoi.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


COMMON_PLACEHOLDERS = (
    ("app_name", "Nom de l'application (Paramètres)."),
    ("contact_email", "Email de contact de l'application."),
    ("contact_phone", "Téléphone de contact de l'application."),
    ("contact_address", "Adresse postale de l'application."),
    ("contact_block", "Bloc prêt à l'emploi : nom, email, téléphone et adresse."),
    ("site_url", "Adresse du site."),
)


@dataclass(frozen=True)
class EmailDefinition:
    code: str
    name: str
    description: str
    subject: str
    body: str
    placeholders: tuple[tuple[str, str], ...] = ()

    @property
    def all_placeholders(self) -> tuple[tuple[str, str], ...]:
        return tuple(self.placeholders) + COMMON_PLACEHOLDERS


WELCOME_BODY = """Bonjour {name},

Votre cockpit {app_name} est prêt pour {company_name}.

Connectez-vous : {login_url}

{contact_block}

À bientôt,
L'équipe {app_name}"""

SIGNUP_CONFIRMATION_BODY = """Bonjour {name},

Pour confirmer votre adresse email et ouvrir votre cockpit, utilisez ce lien
(valable 60 minutes, une seule fois) :

{signup_url}

Si vous n'êtes pas à l'origine de cette demande, ignorez ce message.

{contact_block}"""

MAGIC_LINK_BODY = """Bonjour {name},

Pour ouvrir votre cockpit, utilisez ce lien (valable 30 minutes, une seule fois) :

{magic_url}

Vous pourrez ensuite définir un mot de passe depuis votre profil.
Si vous n'êtes pas à l'origine de cette demande, ignorez ce message.

{contact_block}"""

PASSWORD_RESET_BODY = """Bonjour {name},

Vous avez demandé à définir ou à réinitialiser le mot de passe du compte {email}.

Ce lien est valable une heure :
{reset_url}

Si vous n'êtes pas à l'origine de cette demande, ignorez ce message. Votre mot de passe actuel, s'il existe, reste inchangé.

{contact_block}"""

DOCUMENT_SEND_BODY = """Bonjour {name},

Veuillez trouver ci-joint votre {document_label} {document_number} d'un montant de {document_amount} TTC.

{document_note}

Cordialement,
{signature}"""


EMAIL_DEFINITIONS = (
    EmailDefinition(
        code="welcome",
        name="Bienvenue",
        description="Envoyé après la création du compte et de la première société.",
        subject="Bienvenue sur {app_name}",
        body=WELCOME_BODY,
        placeholders=(
            ("name", "Nom ou prénom du destinataire."),
            ("email", "Adresse email du destinataire."),
            ("company_name", "Société qui vient d'être créée."),
            ("login_url", "Lien vers la page de connexion."),
        ),
    ),
    EmailDefinition(
        code="signup_confirmation",
        name="Confirmation d'inscription",
        description="Lien de vérification envoyé pendant l'inscription lorsque la vérification email est active.",
        subject="Confirmez votre cockpit {app_name}",
        body=SIGNUP_CONFIRMATION_BODY,
        placeholders=(
            ("name", "Nom ou prénom du destinataire."),
            ("email", "Adresse email du destinataire."),
            ("signup_url", "Lien de confirmation d'inscription."),
        ),
    ),
    EmailDefinition(
        code="magic_link",
        name="Lien de connexion",
        description="Lien à usage unique demandé depuis « Recevoir un lien de connexion ».",
        subject="Votre lien de connexion {app_name}",
        body=MAGIC_LINK_BODY,
        placeholders=(
            ("name", "Nom ou prénom du destinataire."),
            ("email", "Adresse email du destinataire."),
            ("magic_url", "Lien de connexion à usage unique."),
        ),
    ),
    EmailDefinition(
        code="password_reset",
        name="Mot de passe oublié / définition",
        description="Réinitialisation du mot de passe, y compris la définition initiale depuis le back-office.",
        subject="Définir votre mot de passe {app_name}",
        body=PASSWORD_RESET_BODY,
        placeholders=(
            ("name", "Nom ou prénom du destinataire."),
            ("email", "Adresse email du destinataire."),
            ("reset_url", "Lien de définition / réinitialisation du mot de passe."),
        ),
    ),
    EmailDefinition(
        code="document_send",
        name="Envoi d'un document",
        description="Facture, devis ou avoir envoyé depuis le cockpit, avec le PDF en pièce jointe.",
        subject="Votre {document_label} {document_number} — {company_name}",
        body=DOCUMENT_SEND_BODY,
        placeholders=(
            ("name", "Nom du destinataire."),
            ("email", "Adresse email du destinataire."),
            ("company_name", "Société qui envoie le document."),
            ("document_label", "Type de document : facture, devis ou avoir."),
            ("document_number", "Numéro du document."),
            ("document_amount", "Montant TTC du document."),
            ("document_note", "Phrase de contexte adaptée au type de document."),
            ("signature", "Signature de l'utilisateur connecté."),
        ),
    ),
)

DEFINITIONS_BY_CODE = {definition.code: definition for definition in EMAIL_DEFINITIONS}


def get_definition(code: str) -> EmailDefinition | None:
    return DEFINITIONS_BY_CODE.get(code)


def _config():
    try:
        from .models import SiteConfiguration

        return SiteConfiguration.objects.filter(pk=1).first()
    except Exception:
        logger.debug("Configuration indisponible pour les emails", exc_info=True)
        return None


def _contact_block(app_name: str, email: str, phone: str, address: str) -> str:
    lines = []
    if email:
        lines.append(f"Email : {email}")
    if phone:
        lines.append(f"Téléphone : {phone}")
    if address:
        lines.append(f"Adresse : {address}")
    if lines:
        lines.insert(0, app_name)
    return "\n".join(lines)


def base_context(request=None) -> dict:
    """Valeurs communes, dont les coordonnées gérées dans l'administration."""
    config = _config()
    app_name = (getattr(config, "site_name", "") or getattr(settings, "SITE_NAME", "") or "Road Runner Solutions").strip()
    email = (
        getattr(config, "contact_email", "")
        or getattr(config, "email_from", "")
        or getattr(settings, "DEFAULT_FROM_EMAIL", "")
    ).strip()
    phone = (getattr(config, "contact_phone", "") or "").strip()
    address = (getattr(config, "contact_address", "") or "").strip()
    site_url = ""
    if request is not None:
        try:
            site_url = request.build_absolute_uri("/")
        except Exception:
            site_url = ""
    return {
        "app_name": app_name,
        "contact_email": email,
        "contact_phone": phone,
        "contact_address": address,
        "contact_block": _contact_block(app_name, email, phone, address),
        "site_url": site_url,
    }


def display_name(user) -> str:
    if user is None:
        return ""
    if isinstance(user, str):
        email = user.strip()
        user = None
    else:
        full = " ".join(
            part
            for part in (
                (getattr(user, "first_name", "") or "").strip(),
                (getattr(user, "last_name", "") or "").strip(),
            )
            if part
        )
        if full:
            return full
        for field in ("name",):
            value = (getattr(user, field, "") or "").strip()
            if value:
                return value
        email = (getattr(user, "email", "") or "").strip()
    local = email.split("@", 1)[0] if email else ""
    return local.replace(".", " ").replace("_", " ").title() if local else ""


def _safe_format(text: str, context: dict) -> str:
    class _Keep(dict):
        def __missing__(self, key):
            return "{" + key + "}"

    try:
        return (text or "").format_map(_Keep(context))
    except (ValueError, IndexError):
        # Accolade isolée ou format invalide : on n'empêche jamais l'envoi.
        return text or ""


def _template_row(code: str):
    try:
        from .models import EmailTemplate

        return EmailTemplate.objects.filter(code=code).first()
    except Exception:
        logger.debug("Modèle d'email %s indisponible", code, exc_info=True)
        return None


def template_values(code: str) -> tuple[str, str, bool]:
    """Objet, corps et état de personnalisation pour un code donné."""
    definition = get_definition(code)
    if definition is None:
        raise KeyError(code)
    row = _template_row(code)
    if row is None:
        return definition.subject, definition.body, False
    return row.subject or definition.subject, row.body or definition.body, True


def render_email(code: str, context: dict | None = None, request=None) -> tuple[str, str]:
    definition = get_definition(code)
    if definition is None:
        raise KeyError(code)
    subject, body, _customized = template_values(code)
    merged = {**base_context(request), **(context or {})}
    return _safe_format(subject, merged).replace("\n", " ").strip(), _safe_format(body, merged)


def send_template_email(code: str, recipient: str, context: dict | None = None, request=None) -> int:
    """Envoie un email automatique avec le texte personnalisé ou par défaut."""
    subject, body = render_email(code, context=context, request=request)
    config = _config()
    from_email = (
        getattr(config, "email_from", "")
        or getattr(settings, "DEFAULT_FROM_EMAIL", "")
    ).strip()
    return send_mail(
        subject=subject,
        message=body,
        from_email=from_email,
        recipient_list=[recipient],
        fail_silently=False,
    )

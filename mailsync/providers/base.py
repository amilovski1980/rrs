"""Contrat commun aux fournisseurs d'e-mail (patron *Adapter*).

Le cœur du module — worker, parseurs, service de validation — ne connaît QUE
cette interface. Ajouter Outlook revient à écrire ``OutlookAdapter`` et à
l'enregistrer dans ``mailsync.providers`` : aucune autre ligne ne change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar


class ProviderError(Exception):
    """Erreur générique d'un fournisseur d'e-mail."""


class ProviderNotConfigured(ProviderError):
    """Client OAuth absent des settings (identifiants non renseignés)."""


class ProviderAuthError(ProviderError):
    """Jeton refusé, expiré ou révoqué : l'utilisateur doit reconnecter la boîte."""


@dataclass
class OAuthTokens:
    """Jetons renvoyés par le fournisseur, avant chiffrement en base."""

    access_token: str
    refresh_token: str = ""
    expires_in: int = 0
    scope: str = ""
    email: str = ""
    account_id: str = ""


@dataclass
class MailAttachment:
    """Métadonnées d'une pièce jointe (les octets sont chargés à la demande)."""

    filename: str
    content_type: str = ""
    size: int = 0
    attachment_id: str = ""
    data: bytes | None = None


@dataclass
class MailMessage:
    """Message normalisé, indépendant du fournisseur."""

    message_id: str
    thread_id: str = ""
    subject: str = ""
    from_email: str = ""
    from_name: str = ""
    received_at: datetime | None = None
    snippet: str = ""
    attachments: list[MailAttachment] = field(default_factory=list)


class EmailProviderInterface(ABC):
    """Interface que tout adaptateur (Gmail, Outlook...) doit implémenter.

    Les méthodes OAuth2 sont des ``classmethod`` : elles servent avant que
    l'utilisateur n'ait de jeton. Les méthodes de lecture sont des méthodes
    d'instance : elles utilisent le jeton d'accès fourni au constructeur.
    """

    provider_id: ClassVar[str] = ""
    display_name: ClassVar[str] = ""
    scopes: ClassVar[tuple[str, ...]] = ()
    max_messages_per_run: ClassVar[int] = 100

    def __init__(self, access_token: str):
        self.access_token = access_token

    # ------------------------------------------------------------------
    # OAuth2
    # ------------------------------------------------------------------
    @classmethod
    @abstractmethod
    def authorize_url(cls, redirect_uri: str, state: str) -> str:
        """URL de consentement vers laquelle rediriger l'utilisateur."""

    @classmethod
    @abstractmethod
    def exchange_code(cls, code: str, redirect_uri: str) -> OAuthTokens:
        """Échange un code d'autorisation contre des jetons."""

    @classmethod
    @abstractmethod
    def refresh_access_token(cls, refresh_token: str) -> OAuthTokens:
        """Renouvelle l'access token à partir du refresh token."""

    # ------------------------------------------------------------------
    # Lecture
    # ------------------------------------------------------------------
    @abstractmethod
    def fetch_account(self) -> tuple[str, str]:
        """Retourne ``(adresse_email, identifiant_compte)`` de la boîte."""

    @abstractmethod
    def list_messages(
        self, *, folder: str = "", since: datetime | None = None
    ) -> list[MailMessage]:
        """Liste les messages porteurs de pièces jointes PDF/XML.

        ``folder`` vide = boîte de réception complète. ``since`` borne la
        recherche ; l'anti-doublon définitif reste la table
        ``ProcessedEmail`` côté worker.
        """

    @abstractmethod
    def open_attachment(
        self, message: MailMessage, attachment: MailAttachment
    ) -> bytes:
        """Télécharge les octets d'une pièce jointe."""

    # ------------------------------------------------------------------
    # Archivage (optionnel)
    # ------------------------------------------------------------------
    def archive_message(self, message: MailMessage) -> None:
        """No-op par défaut.

        Gmail : nécessiterait le scope ``gmail.modify``. Le module reste en
        lecture seule tant que cette action n'est pas explicitement activée.
        """
        return None

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

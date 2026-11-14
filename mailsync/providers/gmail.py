"""Adaptateur Gmail — API REST v1 + OAuth2.

Scope unique : ``gmail.readonly``. Le module ne modifie JAMAIS la boîte
(pas de label, pas d'archivage distant) : le justificatif est archivé côté
application, dans ``SupplierInvoiceDraft.attachment``.

Documentation : https://developers.google.com/gmail/api/reference/rest
"""

from __future__ import annotations

import base64
import logging
from datetime import datetime, timezone as dt_timezone
from email.header import decode_header
from email.utils import parseaddr
from urllib.parse import urlencode

import httpx
from django.conf import settings
from django.utils import timezone

from .base import (
    EmailProviderInterface,
    MailAttachment,
    MailMessage,
    OAuthTokens,
    ProviderAuthError,
    ProviderError,
    ProviderNotConfigured,
)

logger = logging.getLogger(__name__)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
INVOICE_EXTENSIONS = (".pdf", ".xml")
REQUEST_TIMEOUT = 30


class GmailAdapter(EmailProviderInterface):
    """Implémentation Gmail du contrat ``EmailProviderInterface``."""

    provider_id = "gmail"
    display_name = "Gmail"
    scopes = ("https://www.googleapis.com/auth/gmail.readonly",)
    max_messages_per_run = 100

    # ------------------------------------------------------------------
    # Identifiants OAuth (jamais exposés au navigateur)
    # ------------------------------------------------------------------
    @classmethod
    def _client(cls) -> tuple[str, str]:
        client_id = getattr(settings, "GOOGLE_CLIENT_ID", "")
        client_secret = getattr(settings, "GOOGLE_CLIENT_SECRET", "")
        if not client_id or not client_secret:
            raise ProviderNotConfigured(
                "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET absents des settings."
            )
        return client_id, client_secret

    # ------------------------------------------------------------------
    # OAuth2
    # ------------------------------------------------------------------
    @classmethod
    def authorize_url(cls, redirect_uri: str, state: str) -> str:
        client_id, _ = cls._client()
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(cls.scopes),
            "access_type": "offline",
            # Force le consentement : Google ne renvoie un refresh token
            # qu'à la première autorisation, ou avec prompt=consent.
            "prompt": "consent",
            "state": state,
            "include_granted_scopes": "false",
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    @classmethod
    def _token_request(cls, data: dict) -> OAuthTokens:
        client_id, client_secret = cls._client()
        payload = {"client_id": client_id, "client_secret": client_secret, **data}
        try:
            response = httpx.post(TOKEN_URL, data=payload, timeout=REQUEST_TIMEOUT)
        except httpx.HTTPError as exc:
            raise ProviderError(f"Endpoint OAuth Google injoignable : {exc}") from exc
        if response.status_code >= 400:
            raise ProviderAuthError(
                f"Google a refusé la demande de jeton (HTTP {response.status_code})."
            )
        body = response.json()
        return OAuthTokens(
            access_token=body.get("access_token", ""),
            refresh_token=body.get("refresh_token", ""),
            expires_in=int(body.get("expires_in", 0) or 0),
            scope=body.get("scope", ""),
        )

    @classmethod
    def exchange_code(cls, code: str, redirect_uri: str) -> OAuthTokens:
        tokens = cls._token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            }
        )
        # Récupère l'adresse de la boîte avec le jeton tout frais.
        try:
            tokens.email, tokens.account_id = cls(tokens.access_token).fetch_account()
        except ProviderError:
            logger.warning("Profil Gmail illisible après échange de code.")
        return tokens

    @classmethod
    def refresh_access_token(cls, refresh_token: str) -> OAuthTokens:
        if not refresh_token:
            raise ProviderAuthError("Aucun refresh token Gmail : reconnectez la boîte.")
        tokens = cls._token_request(
            {"grant_type": "refresh_token", "refresh_token": refresh_token}
        )
        # Google ne renvoie pas de nouveau refresh token : on conserve l'ancien.
        if not tokens.refresh_token:
            tokens.refresh_token = refresh_token
        return tokens

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------
    def _get(self, path: str, params: dict | None = None) -> dict:
        try:
            response = httpx.get(
                f"{API_BASE}{path}",
                headers=self.headers,
                params=params or {},
                timeout=REQUEST_TIMEOUT,
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"API Gmail injoignable : {exc}") from exc
        if response.status_code == 401:
            raise ProviderAuthError("Jeton Gmail expiré ou révoqué.")
        if response.status_code == 404:
            raise ProviderError("Ressource Gmail introuvable.")
        if response.status_code >= 400:
            raise ProviderError(
                f"API Gmail : HTTP {response.status_code} — {response.text[:200]}"
            )
        return response.json()

    # ------------------------------------------------------------------
    # Lecture
    # ------------------------------------------------------------------
    def fetch_account(self) -> tuple[str, str]:
        profile = self._get("/profile")
        return profile.get("emailAddress", ""), profile.get("historyId", "")

    def list_messages(
        self, *, folder: str = "", since: datetime | None = None
    ) -> list[MailMessage]:
        query = self._search_query(folder=folder, since=since)
        messages: list[MailMessage] = []
        page_token: str | None = None
        while len(messages) < self.max_messages_per_run:
            params: dict = {"q": query, "maxResults": 50}
            if page_token:
                params["pageToken"] = page_token
            data = self._get("/messages", params=params)
            refs = data.get("messages", []) or []
            for ref in refs:
                message = self._message(ref["id"])
                if message is None:
                    continue
                # Filtre fin : Gmail ne descend qu'au jour dans la requête.
                if since and message.received_at and message.received_at < since:
                    continue
                messages.append(message)
                if len(messages) >= self.max_messages_per_run:
                    break
            page_token = data.get("nextPageToken")
            if not page_token or not refs:
                break
        return messages

    @staticmethod
    def _search_query(folder: str, since: datetime | None) -> str:
        parts = []
        folder = (folder or "").strip()
        if folder:
            parts.append(f'label:"{folder}"')
        else:
            parts.append("in:inbox")
        parts.append("has:attachment (filename:pdf OR filename:xml)")
        if since:
            parts.append(f"after:{since.astimezone(timezone.get_current_timezone()).strftime('%Y/%m/%d')}")
        return " ".join(parts)

    def _message(self, message_id: str) -> MailMessage | None:
        data = self._get(f"/messages/{message_id}", params={"format": "full"})
        payload = data.get("payload", {}) or {}
        headers = {
            (header.get("name") or "").lower(): header.get("value", "")
            for header in payload.get("headers", [])
        }
        from_name, from_email = parseaddr(self._decode(headers.get("from", "")))
        received_at = None
        internal_date = data.get("internalDate")
        if internal_date:
            received_at = datetime.fromtimestamp(
                int(internal_date) / 1000, tz=dt_timezone.utc
            )
        attachments = [
            attachment
            for attachment in self._collect_attachments(payload)
            if attachment.filename.lower().endswith(INVOICE_EXTENSIONS)
        ]
        return MailMessage(
            message_id=data.get("id", message_id),
            thread_id=data.get("threadId", ""),
            subject=self._decode(headers.get("subject", "")),
            from_email=from_email,
            from_name=from_name,
            received_at=received_at,
            snippet=data.get("snippet", ""),
            attachments=attachments,
        )

    def _collect_attachments(self, part: dict) -> list[MailAttachment]:
        found: list[MailAttachment] = []
        filename = part.get("filename") or ""
        body = part.get("body") or {}
        if filename and body.get("attachmentId"):
            found.append(
                MailAttachment(
                    filename=filename,
                    content_type=part.get("mimeType", ""),
                    size=int(body.get("size", 0) or 0),
                    attachment_id=body["attachmentId"],
                )
            )
        for child in part.get("parts", []) or []:
            found.extend(self._collect_attachments(child))
        return found

    def open_attachment(
        self, message: MailMessage, attachment: MailAttachment
    ) -> bytes:
        if attachment.data is not None:
            return attachment.data
        if not attachment.attachment_id:
            raise ProviderError(f"Pièce jointe sans identifiant : {attachment.filename}")
        data = self._get(
            f"/messages/{message.message_id}/attachments/{attachment.attachment_id}"
        )
        raw = data.get("data", "")
        padded = raw + "=" * (-len(raw) % 4)
        return base64.urlsafe_b64decode(padded)

    # ------------------------------------------------------------------
    # Utilitaires
    # ------------------------------------------------------------------
    @staticmethod
    def _decode(value: str) -> str:
        """Décode les en-têtes RFC 2047 (=?UTF-8?B?...?=)."""
        if not value:
            return ""
        chunks: list[str] = []
        for text, charset in decode_header(value):
            if isinstance(text, bytes):
                chunks.append(text.decode(charset or "utf-8", errors="replace"))
            else:
                chunks.append(text)
        return "".join(chunks)

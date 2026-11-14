"""Lecture d'un RIB (PDF ou photo) pour préremplir les coordonnées bancaires.

L'OCR est mutualisé avec les tickets de caisse : PDF texte natif, sinon OCR
Tesseract sur l'image. Aucun fichier RIB n'est conservé après l'analyse.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from documents.receipt_ocr import (
    ReceiptOcrError,
    extract_receipt_text,
    validate_upload,
)


class RibScanError(Exception):
    """Erreur lisible par l'utilisateur (fichier ou OCR)."""


@dataclass
class RibDetails:
    iban: str = ""
    bic: str = ""
    bank_name: str = ""

    @property
    def found(self) -> bool:
        return bool(self.iban or self.bic or self.bank_name)


IBAN_RE = re.compile(
    r"\b(?:IBAN\s*[:\-]?\s*)?"
    r"([A-Z]{2}\s*\d{2}(?:[\s\-]?[A-Z0-9]{4}){2,7}(?:[\s\-]?[A-Z0-9]{1,4})?)\b",
    re.IGNORECASE,
)
BIC_LABEL_RE = re.compile(
    r"(?:BIC|SWIFT)\s*[:\-]?\s*([A-Z0-9]{8,11})\b",
    re.IGNORECASE,
)
BIC_RE = re.compile(r"\b([A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?)\b", re.IGNORECASE)

BANK_BRANDS = (
    "CIC",
    "CREDIT AGRICOLE",
    "CRÉDIT AGRICOLE",
    "BNP PARIBAS",
    "SOCIETE GENERALE",
    "SOCIÉTÉ GÉNÉRALE",
    "BANQUE POPULAIRE",
    "CAISSE D'EPARGNE",
    "CAISSE D'ÉPARGNE",
    "LA BANQUE POSTALE",
    "LCL",
    "HSBC",
    "BRED",
    "CACF",
    "CREDIT MUTUEL",
    "CRÉDIT MUTUEL",
    "HELLO BANK",
    "BOURSORAMA",
    "QONTO",
    "SHINE",
)

# Confusions classiques de l'OCR dans la partie numérique d'un IBAN.
_OCR_DIGITS = str.maketrans({"O": "0", "Q": "0", "I": "1", "L": "1", "S": "5", "B": "8", "Z": "2"})


def _normalize_iban(raw: str) -> str:
    value = re.sub(r"[^A-Za-z0-9]", "", raw or "").upper()
    if not value:
        return ""
    # Corrige les lettres lues à la place de chiffres, sans toucher au pays ni
    # aux deux chiffres de contrôle.
    value = value[:4] + value[4:].translate(_OCR_DIGITS)
    return value


def _iban_is_plausible(iban: str) -> bool:
    """Structure d'IBAN : pays, clé et longueur, sans exiger la clé mod 97.

    Certains RIB de démonstration ou anciens comportent une clé de contrôle
    approximative : on ne bloque pas la saisie, mais on préfère un IBAN
    réellement valide quand l'OCR en propose plusieurs.
    """
    return 15 <= len(iban) <= 34 and iban[:2].isalpha() and iban[2:4].isdigit()


def _iban_is_valid(iban: str) -> bool:
    if not _iban_is_plausible(iban):
        return False
    rearranged = iban[4:] + iban[:4]
    try:
        numeric = "".join(
            str(int(char, 36)) for char in rearranged
        )
    except ValueError:
        return False
    return int(numeric) % 97 == 1


def format_iban(iban: str) -> str:
    compact = _normalize_iban(iban)
    return " ".join(compact[index:index + 4] for index in range(0, len(compact), 4))


def _clean_bic(raw: str) -> str:
    value = re.sub(r"[^A-Za-z0-9]", "", raw or "").upper()
    if len(value) not in (8, 11):
        return ""
    if not (value[:4].isalpha() and value[4:6].isalpha()):
        return ""
    return value


def parse_rib_text(text: str) -> RibDetails:
    """Extrait IBAN, BIC et banque d'un texte de RIB."""
    details = RibDetails()
    if not text or not text.strip():
        return details

    compact = re.sub(r"\s+", " ", text.upper())
    candidates = IBAN_RE.findall(compact)
    fallback_iban = ""
    for candidate in candidates:
        iban = _normalize_iban(candidate)
        if not _iban_is_plausible(iban):
            continue
        if _iban_is_valid(iban):
            details.iban = format_iban(iban)
            break
        if not fallback_iban:
            fallback_iban = iban
    if not details.iban and fallback_iban:
        details.iban = format_iban(fallback_iban)

    labeled = BIC_LABEL_RE.search(compact)
    if labeled:
        details.bic = _clean_bic(labeled.group(1))

    if not details.bic:
        for candidate in BIC_RE.findall(compact):
            bic = _clean_bic(candidate)
            if bic and not _looks_like_word(candidate):
                details.bic = bic
                break

    for line in (text or "").splitlines():
        upper = line.upper().strip()
        if not upper or "IBAN" in upper or "BIC" in upper or "SWIFT" in upper:
            continue
        if any(brand in upper for brand in BANK_BRANDS):
            details.bank_name = line.strip()[:120]
            break
    if not details.bank_name:
        for line in (text or "").splitlines():
            upper = line.upper().strip()
            if "BANQUE" in upper and "IBAN" not in upper and "BIC" not in upper:
                details.bank_name = line.strip()[:120]
                break

    return details


def _looks_like_word(value: str) -> bool:
    """Évite de confondre un mot OCR avec un BIC sans aucun chiffre."""
    return value.isalpha() and not any(brand in value for brand in BANK_BRANDS)


def scan_rib_upload(upload) -> RibDetails:
    """Lit un RIB envoyé en PDF, JPG, PNG ou WEBP."""
    if upload is None:
        raise RibScanError("Choisissez un fichier RIB ou prenez une photo.")
    validate_upload(upload.name, getattr(upload, "content_type", ""), upload.size)
    data = upload.read()
    try:
        text = extract_receipt_text(
            data,
            filename=upload.name,
            content_type=getattr(upload, "content_type", "") or "",
        )
    except ReceiptOcrError as exc:
        raise RibScanError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - message utilisateur, jamais de 500
        raise RibScanError(
            "Impossible de lire ce RIB. Réessayez avec une photo nette ou un PDF."
        ) from exc
    details = parse_rib_text(text)
    if not details.found:
        raise RibScanError(
            "Aucun IBAN lisible dans ce document. Saisissez les coordonnées "
            "manuellement ou reprenez la photo bien à plat."
        )
    return details

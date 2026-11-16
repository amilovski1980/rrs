"""Échéances comptables indicatives, dérivées du profil de la société.

Calendrier simplifié pour artisans (régime micro ou réel simplifié) :
TVA trimestrielle 3517S si assujetti, CFE (15/12, + déclaration initiale
l'année de création), clôture de l'exercice puis liasse fiscale. Les dates
sont indicatives et affichées comme telles dans le cockpit.
"""
from __future__ import annotations

from datetime import date, timedelta

from django.utils import timezone

KIND_LABELS = {
    "tva": "TVA",
    "cfe": "CFE",
    "cloture": "Exercice",
    "liasse": "Fiscal",
}


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:  # 29/02, etc.
        return None


def _next_annual(today: date, month: int, day: int) -> date:
    for year in (today.year, today.year + 1, today.year + 2):
        candidate = _safe_date(year, month, day)
        if candidate and candidate >= today:
            return candidate
    return date(today.year + 3, month, day) if day <= 28 else today + timedelta(days=90)


def _next_close(company, today: date) -> date | None:
    """Prochaine clôture : l'anniversaire du début d'exercice, strictement
    après la création et à venir (un exercice dure un an)."""
    start = company.exercice_debut
    if not start:
        return None
    for year in (start.year + 1, start.year + 2, start.year + 3):
        candidate = _safe_date(year, start.month, start.day)
        if candidate and candidate > start and candidate >= today:
            return candidate
    return None


def upcoming(company, today: date | None = None, count: int = 5) -> list[dict]:
    """Prochaines échéances (les `count` plus proches, toujours à venir)."""
    today = today or timezone.localdate()
    start = company.exercice_debut or date(today.year, 1, 1)
    rows: list[tuple[date, dict]] = []

    if company.tva == "reel":
        periods = (("T1", 4, 24), ("T2", 7, 24), ("T3", 10, 24), ("T4", 1, 24))
        for label, month, day in periods:
            due = _next_annual(today, month, day)
            rows.append((
                due,
                {
                    "kind": "tva",
                    "label": f"Déclaration TVA — {label}",
                    "note": "CA3 / 3517S sur impots.gouv",
                },
            ))

    rows.append((
        _next_annual(today, 12, 15),
        {"kind": "cfe", "label": "CFE — paiement de la cotisation", "note": "Avis remis fin octobre"},
    ))

    if start.year == today.year:
        rows.append((
            _safe_date(today.year, 12, 31) or date(today.year, 12, 30),
            {"kind": "cfe", "label": "CFE — déclaration initiale 1447-C", "note": "Année de création"},
        ))

    close = _next_close(company, today)
    if close:
        rows.append((
            close,
            {"kind": "cloture", "label": "Clôture de l'exercice", "note": f"Exercice ouvert le {start:%d/%m/%Y}"},
        ))
        rows.append((
            close + timedelta(days=60),
            {"kind": "liasse", "label": "Liasse fiscale (déclaration de résultats)", "note": "Dépôt à confirmer avec votre CMA / expert-comptable"},
        ))

    rows.sort(key=lambda row: row[0])
    result = []
    for due, item in rows:
        if due < today:
            continue
        days = (due - today).days
        item["date"] = due
        item["days"] = days
        item["urgent"] = days <= 14
        item["soon"] = 14 < days <= 45
        item["kind_label"] = KIND_LABELS.get(item["kind"], "")
        result.append(item)
        if len(result) >= count:
            break
    return result


def upcoming_all(
    companies, today: date | None = None, per_company: int = 2, count: int = 8
) -> list[dict]:
    """Échéances rapprochées de plusieurs sociétés, mélangées triées par date."""
    today = today or timezone.localdate()
    merged: list[tuple[date, dict]] = []
    for company in companies:
        for item in upcoming(company, today=today, count=per_company):
            item = dict(item)
            item["company"] = company
            merged.append((item["date"], item))
    merged.sort(key=lambda row: row[0])
    return [item for _, item in merged[:count]]

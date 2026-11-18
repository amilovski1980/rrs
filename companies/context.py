"""Contexte du sélecteur de société affiché dans la barre supérieure."""
from __future__ import annotations

from core.context import resolve_company


def company_switcher(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}
    from .models import Company

    companies = list(
        Company.objects.filter(owner=user).order_by("created_at")[:12]
    )
    if not companies:
        return {"top_companies": [], "top_company": None}
    _attach_deadlines(companies)
    return {
        "top_companies": companies,
        "top_company": resolve_company(request),
        "deadline_alert": deadline_alert(resolve_company(request)),
    }


def _attach_deadlines(companies):
    """Marque chaque société avec sa premiere echeance urgente (<= 14 j)."""
    from .deadlines import upcoming

    for company in companies:
        try:
            items = upcoming(company, count=1)
        except Exception:
            items = []
        if items and items[0].get("urgent"):
            company.deadline_info = {
                "label": items[0]["label"],
                "date": items[0]["date"],
                "days": items[0]["days"],
            }


def deadline_alert(company):
    """Première échéance à moins de 14 jours, pour le bandeau du shell."""
    if company is None:
        return None
    try:
        from .deadlines import upcoming

        items = upcoming(company, count=3)
    except Exception:
        return None
    for item in items:
        if item.get("urgent"):
            return {
                "label": item["label"],
                "date": item["date"],
                "days": item["days"],
                "kind": item.get("kind", ""),
            }
    return None

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
    return {
        "top_companies": companies,
        "top_company": resolve_company(request),
        "deadline_alert": deadline_alert(resolve_company(request)),
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

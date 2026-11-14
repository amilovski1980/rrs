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
    }

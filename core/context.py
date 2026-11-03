"""Société courante, partagée par le cockpit, la compta et la facturation."""


def resolve_company(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return None
    from companies.models import Company

    owned = Company.objects.filter(owner=user)
    sid = (
        request.GET.get("societe")
        or request.POST.get("societe")
        or request.session.get("societe_id")
    )
    company = owned.filter(pk=sid).first() if sid else None
    if company is None:
        company = owned.order_by("created_at").first()
    if company is not None and request.session.get("societe_id") != str(company.id):
        request.session["societe_id"] = str(company.id)
    return company


def selected_company(request):
    return {"selected": resolve_company(request)}

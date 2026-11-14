import csv

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect, render

from core.context import resolve_company

from .services import build_snapshot


def _company_or_redirect(request):
    company = resolve_company(request)
    if company is None:
        return None, redirect("onboarding")
    return company, None


@login_required
def dashboard(request):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    return render(
        request,
        "treasury/dashboard.html",
        {"company": company, "snapshot": build_snapshot(company)},
    )


@login_required
def export_forecast(request):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    snapshot = build_snapshot(company)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="tresorerie_{company.siren}.csv"'
    )
    writer = csv.writer(response, delimiter=";")
    writer.writerow(
        ["Semaine", "Encaissements", "Décaissements", "Solde prévisionnel"]
    )
    for week in snapshot.forecast.weeks:
        writer.writerow(
            [
                week["start"].strftime("%Y-%m-%d"),
                f"{week['inflow']:.2f}".replace(".", ","),
                f"{week['outflow']:.2f}".replace(".", ","),
                f"{week['balance']:.2f}".replace(".", ","),
            ]
        )
    return response

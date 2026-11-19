from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect

from core.context import resolve_company
from .services import compute_annual_account


def _company_or_redirect(request):
    company = resolve_company(request)
    if company is None:
        return None, redirect('onboarding')
    return company, None


@login_required
def annual_account_list(request):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    accounts = company.annual_accounts.all().order_by('-year')
    return render(request, 'annual_reports/list.html', {'company': company, 'accounts': accounts})


@login_required
def annual_account_detail(request, year):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    account = compute_annual_account(company, year)
    return render(request, 'annual_reports/detail.html', {'company': company, 'account': account})

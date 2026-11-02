from collections import defaultdict

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from companies.models import Company

from .forms import EntryForm, EntryLineFormSet, set_line_choices
from .models import ChartAccount, JournalEntry


def _get_company(request) -> Company:
    sid = request.GET.get("societe") or request.POST.get("societe")
    return get_object_or_404(Company, owner=request.user, pk=sid)


@login_required
def entry_create(request):
    company = _get_company(request)
    if company.journals.exists() is False:
        return redirect("onboarding")
    parent = JournalEntry(company=company, validated=True)
    form = EntryForm(request.POST or None, instance=parent, company=company)
    if request.method == "POST":
        formset = EntryLineFormSet(request.POST, instance=parent)
        set_line_choices(formset, company)
        if form.is_valid() and formset.is_valid():
            entry = form.save()
            formset.instance = entry
            formset.save()
            return redirect(reverse("ledger") + f"?societe={company.id}")
    else:
        formset = EntryLineFormSet(instance=parent)
        set_line_choices(formset, company)
    return render(
        request,
        "accounting/entry_form.html",
        {"form": form, "formset": formset, "company": company},
    )


@login_required
def ledger(request):
    """Grand livre : écritures d'une société, triées."""
    company = _get_company(request)
    entries = (
        JournalEntry.objects.filter(company=company, validated=True)
        .select_related("journal")
        .prefetch_related("lines__account")
        .order_by("date")
    )
    return render(
        request, "accounting/ledger.html", {"company": company, "entries": entries}
    )


@login_required
def balance(request):
    """Balance par compte : soldes débit/crédit."""
    company = _get_company(request)
    per_account = (
        ChartAccount.objects.filter(company=company)
        .annotate(
            total_debit=Sum("entryline__debit"),
            total_credit=Sum("entryline__credit"),
        )
        .order_by("code")
    )
    rows = []
    tot_d = tot_c = 0
    for a in per_account:
        d = a.total_debit or 0
        c = a.total_credit or 0
        solde = d - c
        if d == 0 and c == 0:
            continue
        rows.append(
            {
                "code": a.code,
                "label": a.label,
                "debit": d,
                "credit": c,
                "solde": solde,
            }
        )
        tot_d += d
        tot_c += c
    equilibrated = tot_d == tot_c
    return render(
        request,
        "accounting/balance.html",
        {"company": company, "rows": rows, "tot_d": tot_d, "tot_c": tot_c, "ok": equilibrated},
    )

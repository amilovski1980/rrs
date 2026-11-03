from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse

from core.context import resolve_company

from .forms import EntryForm, EntryLineFormSet, set_line_choices
from .models import JournalEntry
from .reports import balance_rows


def _company_or_redirect(request):
    company = resolve_company(request)
    if company is None:
        return None, redirect("onboarding")
    return company, None


@login_required
def entry_create(request):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
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
    """Grand livre : écritures validées, filtrables par journal et libellé."""
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    journal = (request.GET.get("journal") or "").strip().upper()
    query = (request.GET.get("q") or "").strip()
    entries = (
        JournalEntry.objects.filter(company=company, validated=True)
        .select_related("journal")
        .prefetch_related("lines__account")
    )
    if journal:
        entries = entries.filter(journal__code=journal)
    if query:
        entries = entries.filter(label__icontains=query)
    drafts = (
        JournalEntry.objects.filter(company=company, validated=False)
        .select_related("journal")
        .prefetch_related("lines__account")
        .order_by("-created_at")
    )
    return render(request, "accounting/ledger.html", {
        "company": company,
        "entries": entries.order_by("date", "created_at"),
        "drafts": drafts,
        "journals": company.journals.all(),
        "journal": journal,
        "query": query,
    })


@login_required
def balance(request):
    """Balance par compte : soldes débit/crédit des écritures validées."""
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    rows, total_debit, total_credit = balance_rows(company)
    return render(request, "accounting/balance.html", {
        "company": company,
        "rows": rows,
        "tot_d": total_debit,
        "tot_c": total_credit,
        "ok": total_debit == total_credit,
    })

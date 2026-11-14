from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from core.context import resolve_company

from .fec import build_fec
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
@require_POST
def entry_validate(request, pk):
    """Valide un brouillon d'écriture après contrôle de l'équilibre."""
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    entry = get_object_or_404(
        JournalEntry, pk=pk, company=company, validated=False
    )
    totals = entry.lines.aggregate(debit=Sum("debit"), credit=Sum("credit"))
    debit = totals["debit"] or 0
    credit = totals["credit"] or 0
    if not entry.lines.exists():
        messages.error(request, "Cette écriture ne contient aucune ligne.")
    elif debit != credit:
        messages.error(
            request,
            "Impossible de valider : le débit et le crédit ne sont pas équilibrés.",
        )
    else:
        entry.validated = True
        entry.save(update_fields=["validated"])
        messages.success(request, f"Écriture « {entry.label} » validée.")
    return redirect(reverse("ledger") + f"?societe={company.id}")


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
        "fec_start": date(timezone.localdate().year, 1, 1),
        "fec_end": timezone.localdate(),
    })


@login_required
def export_fec(request):
    """Export FEC tabulé de l'exercice (paramètres ``debut`` / ``fin``)."""
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    today = timezone.localdate()
    start = parse_date(request.GET.get("debut") or "") or date(today.year, 1, 1)
    end = parse_date(request.GET.get("fin") or "") or today
    if start > end:
        start, end = end, start
    payload = build_fec(company, start, end)
    response = HttpResponse(
        payload, content_type="text/tab-separated-values; charset=utf-8"
    )
    response["Content-Disposition"] = (
        f'attachment; filename="FEC_{company.siren}_{start:%Y%m%d}_{end:%Y%m%d}.txt"'
    )
    return response

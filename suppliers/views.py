from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.context import resolve_company

from .forms import SupplierForm
from .models import Supplier


def _company_or_redirect(request):
    company = resolve_company(request)
    if company is None:
        return None, redirect("onboarding")
    return company, None


def _with_unpaid(suppliers, company):
    """Attache le reste à payer de chaque fournisseur (une seule requête)."""
    from purchases.models import PurchaseInvoice

    queryset = PurchaseInvoice.objects.filter(
        company=company, status="approved"
    ).prefetch_related("payments")
    suppliers = list(
        suppliers.prefetch_related(
            Prefetch("purchase_invoices", queryset=queryset, to_attr="open_invoices")
        )
    )
    for supplier in suppliers:
        supplier.unpaid = sum(
            (invoice.amount_remaining for invoice in supplier.open_invoices),
            start=0,
        )
    return suppliers


@login_required
def supplier_list(request):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    queryset = Supplier.objects.filter(company=company)
    query = (request.GET.get("q") or "").strip()
    active = (request.GET.get("actif") or "").strip()
    if query:
        from django.db.models import Q

        queryset = queryset.filter(
            Q(name__icontains=query)
            | Q(siret__icontains=query)
            | Q(tva_intra__icontains=query)
            | Q(email__icontains=query)
        )
    if active == "1":
        queryset = queryset.filter(is_active=True)
    elif active == "0":
        queryset = queryset.filter(is_active=False)
    suppliers = _with_unpaid(queryset, company)
    return render(
        request,
        "suppliers/list.html",
        {
            "company": company,
            "suppliers": suppliers,
            "query": query,
            "active": active,
        },
    )


@login_required
def supplier_create(request):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    form = SupplierForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        supplier = form.save(commit=False)
        supplier.company = company
        supplier.created_from = "manual"
        supplier.save()
        messages.success(request, "Fournisseur créé.")
        return redirect("suppliers:detail", pk=supplier.pk)
    return render(
        request,
        "suppliers/form.html",
        {"company": company, "form": form, "supplier": None},
    )


@login_required
def supplier_edit(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    supplier = get_object_or_404(Supplier, pk=pk, company=company)
    form = SupplierForm(request.POST or None, instance=supplier)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Fournisseur mis à jour.")
        return redirect("suppliers:detail", pk=supplier.pk)
    return render(
        request,
        "suppliers/form.html",
        {"company": company, "form": form, "supplier": supplier},
    )


@login_required
def supplier_detail(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    supplier = get_object_or_404(Supplier, pk=pk, company=company)
    invoices = list(
        supplier.purchase_invoices.select_related("journal_entry")
        .prefetch_related("payments")
        .order_by("-invoice_date", "-created_at")
    )
    unpaid = sum(
        (invoice.amount_remaining for invoice in invoices if invoice.status == "approved"),
        start=0,
    )
    total = sum((invoice.amount_ttc for invoice in invoices), start=0)
    return render(
        request,
        "suppliers/detail.html",
        {
            "company": company,
            "supplier": supplier,
            "invoices": invoices,
            "unpaid": unpaid,
            "total": total,
        },
    )


@require_POST
@login_required
def supplier_toggle(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    supplier = get_object_or_404(Supplier, pk=pk, company=company)
    supplier.is_active = not supplier.is_active
    supplier.save(update_fields=["is_active", "updated_at"])
    messages.success(
        request,
        "Fournisseur activé." if supplier.is_active else "Fournisseur désactivé.",
    )
    return redirect("suppliers:detail", pk=supplier.pk)

from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import get_valid_filename
from django.views.decorators.http import require_POST

from core.context import resolve_company

from .forms import (
    BankAccountForm,
    BankRuleForm,
    ImportStatementForm,
    TransactionEntryForm,
)
from .models import BankAccount, BankRule, BankStatement, BankTransaction
from .parsers import BankParseError
from .services import (
    BankError,
    accounting_balance,
    candidate_entries,
    ensure_default_account,
    find_rule,
    import_statement,
    match_transaction,
    reconcile_bank_fee,
    reconcile_customer_receipt,
    reconcile_expense,
    reconcile_internal_transfer,
    reconcile_loan_payment,
    reconcile_other,
    reconcile_supplier_payment,
    reconcile_vat_payment,
    unmatch_transaction,
)


def _company_or_redirect(request):
    company = resolve_company(request)
    if company is None:
        return None, redirect("onboarding")
    return company, None


def _scoped(model, company, pk):
    return get_object_or_404(model, pk=pk, company=company)


@login_required
def bank_dashboard(request):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    account = ensure_default_account(company)
    accounts = list(company.bank_accounts.all())
    total_balance = sum((item.balance for item in accounts), Decimal("0.00"))
    transactions = BankTransaction.objects.filter(company=company)
    unmatched = transactions.filter(status="unmatched").count()
    matched = transactions.filter(status="matched").count()
    recent = transactions.select_related("account", "matched_entry")[:12]
    statements = company.bank_statements.select_related("account")[:5]
    return render(
        request,
        "banking/dashboard.html",
        {
            "company": company,
            "account": account,
            "accounts": accounts,
            "total_balance": total_balance,
            "unmatched": unmatched,
            "matched": matched,
            "recent": recent,
            "statements": statements,
        },
    )


@login_required
def account_list(request):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    ensure_default_account(company)
    return render(
        request,
        "banking/accounts.html",
        {"company": company, "accounts": company.bank_accounts.all()},
    )


@login_required
def account_create(request):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    form = BankAccountForm(request.POST or None, company=company)
    if request.method == "POST" and form.is_valid():
        account = form.save(commit=False)
        account.company = company
        if account.ledger_account_id is None:
            account.ledger_account = (
                company.accounts.filter(code__startswith="512").order_by("code").first()
            )
        account.save()
        messages.success(request, "Compte bancaire créé.")
        return redirect("banking:account_detail", pk=account.pk)
    return render(
        request,
        "banking/account_form.html",
        {"company": company, "form": form, "account": None},
    )


@login_required
def account_edit(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    account = _scoped(BankAccount, company, pk)
    form = BankAccountForm(request.POST or None, instance=account, company=company)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Compte bancaire mis à jour.")
        return redirect("banking:account_detail", pk=account.pk)
    return render(
        request,
        "banking/account_form.html",
        {"company": company, "form": form, "account": account},
    )


@login_required
def account_detail(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    account = _scoped(BankAccount, company, pk)
    transactions = account.transactions.select_related("matched_entry").order_by(
        "-date", "-created_at"
    )[:200]
    return render(
        request,
        "banking/account_detail.html",
        {
            "company": company,
            "account": account,
            "transactions": transactions,
            "accounting_balance": accounting_balance(account),
            "unmatched": account.transactions.filter(status="unmatched").count(),
            "statements": account.statements.all()[:10],
        },
    )


@login_required
def statement_import(request):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    ensure_default_account(company)
    form = ImportStatementForm(
        request.POST or None, request.FILES or None, company=company
    )
    if request.method == "POST" and form.is_valid():
        upload = form.cleaned_data["file"]
        account = form.cleaned_data["account"]
        try:
            result = import_statement(account, upload.read(), upload.name)
        except (BankParseError, BankError) as exc:
            messages.error(request, f"Import impossible : {exc}")
        else:
            messages.success(request, f"Relevé importé : {result.summary()}.")
            return redirect("banking:transactions")
    return render(
        request,
        "banking/import.html",
        {"company": company, "form": form},
    )


@login_required
def transaction_list(request):
    """Opérations bancaires : filtres, pagination, totaux par état affiché."""
    from django.core.paginator import Paginator
    from django.db.models import Q, Sum

    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    queryset = BankTransaction.objects.filter(company=company).select_related(
        "account", "matched_entry"
    )
    status = (request.GET.get("statut") or "").strip()
    account_id = (request.GET.get("compte") or "").strip()
    query = (request.GET.get("q") or "").strip()
    date_from = (request.GET.get("du") or "").strip()
    date_to = (request.GET.get("au") or "").strip()
    try:
        per_page = int(request.GET.get("par_page") or 25)
    except (TypeError, ValueError):
        per_page = 25
    if per_page not in (25, 50, 100, 200):
        per_page = 25
    if status:
        queryset = queryset.filter(status=status)
    if account_id:
        queryset = queryset.filter(account_id=account_id)
    if query:
        queryset = queryset.filter(
            Q(label__icontains=query)
            | Q(counterparty__icontains=query)
            | Q(reference__icontains=query)
        )
    if date_from:
        try:
            from datetime import datetime

            queryset = queryset.filter(
                date__gte=datetime.strptime(date_from, "%Y-%m-%d").date()
            )
        except ValueError:
            date_from = ""
    if date_to:
        try:
            from datetime import datetime

            queryset = queryset.filter(
                date__lte=datetime.strptime(date_to, "%Y-%m-%d").date()
            )
        except ValueError:
            date_to = ""

    matched_total = (
        queryset.aggregate(matched=Sum("amount"))["matched"] or Decimal("0.00")
    )
    paginator = Paginator(queryset, per_page)
    page_items = list(paginator.get_page(request.GET.get("page") or "1").object_list)

    status_by_code = dict(BankTransaction.STATUSES)
    state_totals = {}
    for transaction in page_items:
        code = transaction.status or "unmatched"
        entry = state_totals.setdefault(
            code, {"label": status_by_code.get(code, code), "count": 0, "amount": Decimal("0.00")}
        )
        entry["count"] += 1
        entry["amount"] += transaction.amount

    params = request.GET.copy()
    params.pop("page", None)
    base_url = request.path + "?" + params.urlencode() + "&"

    return render(
        request,
        "banking/transactions.html",
        {
            "company": company,
            "transactions": queryset,
            "page_items": page_items,
            "status": status,
            "account_id": account_id,
            "query": query,
            "date_from": date_from,
            "date_to": date_to,
            "per_page": per_page,
            "state_totals": state_totals,
            "matched_total": matched_total,
            "base_url": base_url,
            "accounts": company.bank_accounts.all(),
            "statuses": BankTransaction.STATUSES,
        },
    )


@login_required
@require_POST
def transaction_bulk(request):
    """Actions de masse sur les opérations sélectionnées : ignorer, rétablir,
    supprimer. Redirige vers la liste avec un message (les boutons du
    formulaire postent en navigation classique)."""
    from django.contrib import messages

    company, bounce = _company_or_redirect(request)
    if bounce:
        messages.error(request, "Aucune société.")
        return bounce
    back = reverse("banking:transactions") + "?societe=" + str(company.pk)
    action = (request.POST.get("action") or "").strip()
    ids = [pk for pk in request.POST.getlist("ids") if pk]
    if not ids:
        messages.error(request, "Aucune opération sélectionnée.")
        return redirect(back)
    queryset = BankTransaction.objects.filter(company=company, pk__in=ids)
    if action == "ignore":
        updated = queryset.exclude(status="ignored").update(status="ignored")
        messages.success(request, f"{updated} opération(s) ignorée(s).")
    elif action == "restore":
        updated = queryset.filter(status="ignored").update(status="unmatched")
        messages.success(request, f"{updated} opération(s) rétablie(s).")
    elif action == "delete":
        updated = queryset.delete()[1].get("banking.BankTransaction", 0)
        messages.success(request, f"{updated} opération(s) supprimée(s).")
    else:
        messages.error(request, "Action inconnue.")
    return redirect(back)


@login_required
def transaction_detail(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    bank_transaction = _scoped(BankTransaction, company, pk)
    rule = find_rule(bank_transaction)
    form = TransactionEntryForm(bank_transaction=bank_transaction, rule=rule)
    return render(
        request,
        "banking/transaction_detail.html",
        {
            "company": company,
            "transaction": bank_transaction,
            "candidates": candidate_entries(bank_transaction)[:10],
            "rule": rule,
            "form": form,
        },
    )


@require_POST
@login_required
def transaction_match(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    bank_transaction = _scoped(BankTransaction, company, pk)
    entry_id = (request.POST.get("entry_id") or "").strip()
    from accounting.models import JournalEntry

    entry = get_object_or_404(JournalEntry, pk=entry_id, company=company)
    try:
        match_transaction(bank_transaction, entry)
    except BankError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Opération rapprochée de l'écriture comptable.")
    return redirect("banking:transaction_detail", pk=bank_transaction.pk)


@login_required
def transaction_create_entry(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    bank_transaction = _scoped(BankTransaction, company, pk)
    rule = find_rule(bank_transaction)
    form = TransactionEntryForm(
        request.POST or None,
        bank_transaction=bank_transaction,
        rule=rule,
        company=company,
    )
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        common = {
            "label": data.get("label") or "",
            "reference": data.get("reference") or "",
            "entry_date": data.get("date"),
        }
        try:
            if data["nature"] == "customer_receipt":
                reconcile_customer_receipt(
                    bank_transaction,
                    invoice=data.get("customer_invoice"),
                    gross_amount=data.get("gross_amount"),
                    fee_amount=data.get("fee_amount"),
                    fee_account_code=data.get("fee_account_code") or "627000",
                    **common,
                )
            elif data["nature"] == "supplier_payment":
                reconcile_supplier_payment(
                    bank_transaction,
                    invoice=data.get("supplier_invoice"),
                    gross_amount=data.get("gross_amount"),
                    fee_amount=data.get("fee_amount"),
                    fee_account_code=data.get("fee_account_code") or "627000",
                    **common,
                )
            elif data["nature"] == "expense":
                reconcile_expense(
                    bank_transaction,
                    charge_account_code=data.get("charge_account_code"),
                    vat_account_code=data.get("vat_account_code") or "",
                    vat_amount=data.get("vat_amount") or Decimal("0.00"),
                    **common,
                )
            elif data["nature"] == "bank_fee":
                reconcile_bank_fee(bank_transaction, **common)
            elif data["nature"] == "loan_payment":
                reconcile_loan_payment(
                    bank_transaction,
                    principal=data.get("loan_principal") or Decimal("0.00"),
                    interest=data.get("loan_interest") or Decimal("0.00"),
                    **common,
                )
            elif data["nature"] == "internal_transfer":
                reconcile_internal_transfer(
                    bank_transaction,
                    other_account=data.get("transfer_account"),
                    **common,
                )
            elif data["nature"] == "vat_payment":
                reconcile_vat_payment(
                    bank_transaction,
                    vat_account_code=data.get("vat_payment_account_code") or "44571",
                    **common,
                )
            else:
                reconcile_other(
                    bank_transaction,
                    counterpart_code=data.get("counterpart_code"),
                    vat_account_code=data.get("vat_account_code") or "",
                    vat_amount=data.get("vat_amount") or Decimal("0.00"),
                    **common,
                )
        except BankError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Écriture créée et opération rapprochée.")
            return redirect("banking:transaction_detail", pk=bank_transaction.pk)

    accounts = company.accounts.order_by("code")
    bank_ledger = bank_transaction.account.ledger
    reference_suggestions = list(
        BankTransaction.objects.filter(company=company)
        .exclude(reference="")
        .order_by("-date")
        .values_list("reference", flat=True)
        .distinct()[:15]
    )
    return render(
        request,
        "banking/transaction_entry.html",
        {
            "company": company,
            "transaction": bank_transaction,
            "form": form,
            "rule": rule,
            "accounts": accounts,
            "vat_accounts": accounts.filter(code__startswith="4456"),
            "reference_suggestions": reference_suggestions,
            "bank_code": bank_ledger.code if bank_ledger else "512",
            "bank_label": bank_transaction.account.label,
        },
    )


@require_POST
@login_required
def transaction_unmatch(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    bank_transaction = _scoped(BankTransaction, company, pk)
    unmatch_transaction(bank_transaction)
    messages.info(request, "Rapprochement annulé.")
    return redirect("banking:transaction_detail", pk=bank_transaction.pk)


@require_POST
@login_required
def transaction_delete(request, pk):
    """Supprime une ligne importée, sans toucher à l'écriture comptable liée."""
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    bank_transaction = _scoped(BankTransaction, company, pk)
    label = bank_transaction.label
    bank_transaction.delete()
    messages.success(request, f"Opération « {label[:80]} » supprimée.")
    nxt = (request.POST.get("next") or "").strip()
    if not nxt.startswith("/") or nxt.startswith("//"):
        nxt = reverse("banking:transactions") + f"?societe={company.id}"
    return redirect(nxt)


@require_POST
@login_required
def transaction_ignore(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    bank_transaction = _scoped(BankTransaction, company, pk)
    if bank_transaction.status == "matched":
        messages.error(request, "Dé-rapprochez l'opération avant de l'ignorer.")
    else:
        bank_transaction.status = "ignored"
        bank_transaction.save(update_fields=["status"])
        messages.info(request, "Opération ignorée.")
    return redirect("banking:transaction_detail", pk=bank_transaction.pk)


@login_required
def rule_list(request):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    return render(
        request,
        "banking/rules.html",
        {"company": company, "rules": company.bank_rules.select_related("counterpart_account")},
    )


@login_required
def rule_create(request):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    form = BankRuleForm(request.POST or None, company=company)
    if request.method == "POST" and form.is_valid():
        rule = form.save(commit=False)
        rule.company = company
        rule.save()
        messages.success(request, "Règle bancaire créée.")
        return redirect("banking:rules")
    return render(
        request,
        "banking/rule_form.html",
        {"company": company, "form": form, "rule": None},
    )


@login_required
def rule_edit(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    rule = _scoped(BankRule, company, pk)
    form = BankRuleForm(request.POST or None, instance=rule, company=company)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Règle bancaire mise à jour.")
        return redirect("banking:rules")
    return render(
        request,
        "banking/rule_form.html",
        {"company": company, "form": form, "rule": rule},
    )


@require_POST
@login_required
def rule_toggle(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    rule = _scoped(BankRule, company, pk)
    rule.is_active = not rule.is_active
    rule.save(update_fields=["is_active"])
    messages.success(
        request, "Règle activée." if rule.is_active else "Règle désactivée."
    )
    return redirect("banking:rules")


@login_required
def statement_file(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    statement = _scoped(BankStatement, company, pk)
    filename = get_valid_filename(statement.original_filename or "releve") or "releve"
    if statement.file_data:
        response = HttpResponse(
            bytes(statement.file_data),
            content_type=statement.file_type or "application/octet-stream",
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
    if not statement.file:
        raise Http404("Aucun fichier de relevé.")
    try:
        handle = statement.file.open("rb")
    except FileNotFoundError as exc:
        raise Http404("Fichier introuvable sur le stockage.") from exc
    return FileResponse(
        handle,
        as_attachment=True,
        filename=filename,
    )

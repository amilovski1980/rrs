from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
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
    create_entry_from_transaction,
    ensure_default_account,
    find_rule,
    import_statement,
    match_transaction,
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
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    queryset = BankTransaction.objects.filter(company=company).select_related(
        "account", "matched_entry"
    )
    status = (request.GET.get("statut") or "").strip()
    account_id = (request.GET.get("compte") or "").strip()
    query = (request.GET.get("q") or "").strip()
    if status:
        queryset = queryset.filter(status=status)
    if account_id:
        queryset = queryset.filter(account_id=account_id)
    if query:
        from django.db.models import Q

        queryset = queryset.filter(
            Q(label__icontains=query)
            | Q(counterparty__icontains=query)
            | Q(reference__icontains=query)
        )
    return render(
        request,
        "banking/transactions.html",
        {
            "company": company,
            "transactions": queryset,
            "status": status,
            "account_id": account_id,
            "query": query,
            "accounts": company.bank_accounts.all(),
            "statuses": BankTransaction.STATUSES,
        },
    )


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
        request.POST or None, bank_transaction=bank_transaction, rule=rule
    )
    if request.method == "POST" and form.is_valid():
        try:
            create_entry_from_transaction(
                bank_transaction,
                counterpart_code=form.cleaned_data["counterpart_code"],
                vat_account_code=form.cleaned_data.get("vat_account_code") or "",
                vat_amount=form.cleaned_data.get("vat_amount") or Decimal("0.00"),
                label=form.cleaned_data["label"],
                reference=form.cleaned_data.get("reference") or "",
                entry_date=form.cleaned_data.get("date"),
            )
        except BankError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Écriture créée et opération rapprochée.")
            return redirect("banking:transaction_detail", pk=bank_transaction.pk)
    return render(
        request,
        "banking/transaction_entry.html",
        {
            "company": company,
            "transaction": bank_transaction,
            "form": form,
            "rule": rule,
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
    if not statement.file:
        raise Http404("Aucun fichier de relevé.")
    try:
        handle = statement.file.open("rb")
    except FileNotFoundError as exc:
        raise Http404("Fichier introuvable sur le stockage.") from exc
    return FileResponse(
        handle,
        as_attachment=True,
        filename=statement.original_filename or "releve",
    )

"""Vues du module d'import d'historique."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_POST

from billing.access import feature_on
from core.context import resolve_company

from .forms import DocumentEditForm, ImportUploadForm
from .models import ImportBatch, ImportDocument
from .services import (
    HistoricalImportError,
    add_upload,
    batch_stats,
    create_batch,
    import_document,
    import_ready_documents,
    process_batch,
    process_document,
    refresh_document_status,
)


def _company_or_redirect(request):
    company = resolve_company(request)
    if company is None:
        return None, redirect("onboarding")
    return company, None


def _plan_allowed(request):
    if feature_on(request.user, "history_import"):
        return True
    messages.info(
        request,
        "L'import d'historique est inclus dans le forfait ultime. "
        "Mettez à jour votre forfait pour l'utiliser.",
    )
    return False


def plan_required(view):
    from functools import wraps

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not _plan_allowed(request):
            return redirect("plan_upgrade")
        return view(request, *args, **kwargs)

    return wrapper


@login_required
def upload(request):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    if not _plan_allowed(request):
        return redirect("plan_upgrade")

    batch = None
    batch_id = request.GET.get("batch") or request.POST.get("batch")
    if batch_id:
        batch = ImportBatch.objects.filter(company=company, pk=batch_id).first()
    initial = {}
    type_param = (request.GET.get("type") or "").strip()
    if type_param == "sales":
        initial["kind_hint"] = "sale_invoice"
    elif type_param == "purchases":
        initial["kind_hint"] = "purchase_invoice"
    form = ImportUploadForm(
        request.POST or None, request.FILES or None, initial=initial
    )
    if request.method == "POST" and form.is_valid():
        if batch is None:
            batch = create_batch(
                company,
                request.user,
                label=form.cleaned_data.get("label") or "",
                kind_hint=form.cleaned_data.get("kind_hint") or "",
            )
        uploads = form.cleaned_data.get("files") or []
        total = 0
        errors = 0
        for upload_file in uploads:
            try:
                created = add_upload(batch, upload_file, request.user)
                total += len(created)
            except HistoricalImportError as exc:
                errors += 1
                messages.error(request, str(exc))
        if total:
            process_batch(batch, limit=2, user=request.user)
            messages.success(
                request,
                f"{total} document(s) ajouté(s). L'analyse continue automatiquement.",
            )
        elif not errors:
            messages.error(request, "Aucun document exploitable n'a été ajouté.")
        return redirect("history_import:batch", pk=batch.pk)

    recent = company.import_batches.all()[:5]
    return render(
        request,
        "history_import/upload.html",
        {"company": company, "form": form, "batch": batch, "recent": recent},
    )


@login_required
@plan_required
def batch_detail(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    batch = get_object_or_404(ImportBatch, pk=pk, company=company)
    status_filter = (request.GET.get("statut") or "").strip()
    documents = batch.documents.all()
    if status_filter:
        documents = documents.filter(status=status_filter)
    stats = batch_stats(batch)
    return render(
        request,
        "history_import/batch.html",
        {
            "company": company,
            "batch": batch,
            "documents": documents,
            "stats": stats,
            "status_filter": status_filter,
        },
    )


@require_POST
@login_required
@plan_required
def batch_process(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    batch = get_object_or_404(ImportBatch, pk=pk, company=company)
    process_batch(batch, limit=3, user=request.user)
    stats = batch_stats(batch)
    wants_json = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    if wants_json:
        return JsonResponse({"batch": str(batch.pk), **stats})
    return redirect("history_import:batch", pk=batch.pk)


@require_POST
@login_required
@plan_required
def batch_import(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    batch = get_object_or_404(ImportBatch, pk=pk, company=company)
    ids = request.POST.getlist("document_ids")
    if not ids:
        messages.info(request, "Sélectionnez au moins un document prêt.")
        return redirect("history_import:batch", pk=batch.pk)
    result = import_ready_documents(batch, ids, user=request.user)
    messages.success(
        request,
        f"{result['imported']} document(s) importé(s)"
        + (f", {result['errors']} erreur(s)." if result["errors"] else "."),
    )
    return redirect("history_import:batch", pk=batch.pk)


@login_required
@plan_required
def document_detail(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    document = get_object_or_404(ImportDocument, pk=pk, company=company)
    if request.method == "POST":
        if document.status == "imported":
            messages.error(request, "Ce document est déjà importé.")
            return redirect("history_import:document", pk=document.pk)
        form = DocumentEditForm(request.POST, instance=document)
        if form.is_valid():
            document = form.save()
            refresh_document_status(document)
            messages.success(request, "Document mis à jour.")
            return redirect("history_import:document", pk=document.pk)
    else:
        form = DocumentEditForm(instance=document)
    return render(
        request,
        "history_import/document.html",
        {
            "company": company,
            "document": document,
            "form": form,
            "is_image": document.original_name.lower().endswith(
                (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif")
            ),
            "is_pdf": document.original_name.lower().endswith(".pdf"),
        },
    )


@require_POST
@login_required
@plan_required
def document_import(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    document = get_object_or_404(ImportDocument, pk=pk, company=company)
    try:
        import_document(document, user=request.user)
    except HistoricalImportError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Document archivé dans le module concerné.")
    return redirect("history_import:document", pk=document.pk)


@require_POST
@login_required
@plan_required
def document_reanalyze(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    document = get_object_or_404(ImportDocument, pk=pk, company=company)
    document.status = "queued"
    document.save(update_fields=["status"])
    process_document(document, user=request.user)
    messages.success(request, "Document réanalysé.")
    return redirect("history_import:document", pk=document.pk)


@require_POST
@login_required
@plan_required
def document_reject(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    document = get_object_or_404(ImportDocument, pk=pk, company=company)
    if document.status == "imported":
        messages.error(request, "Un document importé ne peut pas être exclu.")
    else:
        document.status = "rejected"
        document.save(update_fields=["status", "updated_at"])
        messages.info(request, "Document exclu du lot.")
    return redirect("history_import:batch", pk=document.batch_id)


@login_required
@plan_required
@xframe_options_sameorigin
def document_file(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    document = get_object_or_404(ImportDocument, pk=pk, company=company)
    if not document.file:
        raise Http404("Fichier introuvable.")
    try:
        handle = document.file.open("rb")
    except FileNotFoundError as exc:
        raise Http404("Fichier introuvable sur le stockage.") from exc
    content_type = document.content_type or "application/octet-stream"
    return FileResponse(handle, content_type=content_type)

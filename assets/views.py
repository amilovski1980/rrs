from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from core.context import resolve_company

from .models import Asset
from .forms import AssetForm
from .services import generate_depreciation_schedule


def _company_or_redirect(request):
    company = resolve_company(request)
    if company is None:
        return None, redirect("onboarding")
    return company, None


@login_required
def asset_list(request):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    assets = Asset.objects.filter(company=company).order_by('-acquisition_date')
    return render(request, "assets/list.html", {"company": company, "assets": assets})


@login_required
def asset_create(request):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    form = AssetForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        asset = form.save(commit=False)
        asset.company = company
        asset.save()
        generate_depreciation_schedule(asset)
        messages.success(request, "Immobilisation créée avec succès.")
        return redirect(reverse("assets:list") + f"?societe={company.id}")
    return render(request, "assets/asset_form.html", {"company": company, "form": form})


@login_required
def asset_update(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    asset = get_object_or_404(Asset, pk=pk, company=company)
    form = AssetForm(request.POST or None, instance=asset)
    if request.method == "POST" and form.is_valid():
        form.save()
        generate_depreciation_schedule(asset)
        messages.success(request, "Immobilisation mise à jour.")
        return redirect(reverse("assets:list") + f"?societe={company.id}")
    return render(request, "assets/asset_form.html", {"company": company, "form": form, "asset": asset})


@login_required
def asset_delete(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    asset = get_object_or_404(Asset, pk=pk, company=company)
    asset.delete()
    messages.success(request, "Immobilisation supprimée.")
    return redirect(reverse("assets:list") + f"?societe={company.id}")

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.context import resolve_company
from documents.models import Client

from .forms import ContactForm
from .models import DEPARTMENTS, Contact


def _company_or_redirect(request):
    company = resolve_company(request)
    if company is None:
        return None, redirect("onboarding")
    return company, None


def _qs(company):
    return f"?societe={company.id}"


def _scoped(company, pk):
    return get_object_or_404(Contact, pk=pk, company=company)


@login_required
def contact_list(request):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    contacts = company.contacts.select_related("client")
    query = (request.GET.get("q") or "").strip()
    department = (request.GET.get("department") or "").strip()
    if query:
        contacts = contacts.filter(
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(organization__icontains=query)
            | Q(email__icontains=query)
            | Q(phone__icontains=query)
        )
    if department in dict(DEPARTMENTS):
        contacts = contacts.filter(department=department)
    return render(request, "contacts/list.html", {
        "company": company,
        "contacts": contacts,
        "departments": DEPARTMENTS,
        "query": query,
        "selected_department": department,
    })


@login_required
def contact_create(request):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    initial = {}
    client_id = (request.GET.get("client") or "").strip()
    if client_id:
        client = get_object_or_404(Client, pk=client_id, company=company)
        initial = {"client": client, "organization": client.name}
    form = ContactForm(request.POST or None, company=company, initial=initial)
    if request.method == "POST" and form.is_valid():
        contact = form.save(commit=False)
        contact.company = company
        contact.save()
        messages.success(request, f"Contact {contact.full_name} créé.")
        return redirect(reverse("contact_detail", args=[contact.id]) + _qs(company))
    return render(request, "contacts/form.html", {
        "company": company,
        "form": form,
    })


@login_required
def contact_edit(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    contact = _scoped(company, pk)
    form = ContactForm(request.POST or None, instance=contact, company=company)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Contact {contact.full_name} mis à jour.")
        return redirect(reverse("contact_detail", args=[contact.id]) + _qs(company))
    return render(request, "contacts/form.html", {
        "company": company,
        "form": form,
        "contact": contact,
    })


@login_required
def contact_detail(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    contact = _scoped(company, pk)
    return render(request, "contacts/detail.html", {
        "company": company,
        "contact": contact,
    })


@login_required
@require_POST
def contact_delete(request, pk):
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    contact = _scoped(company, pk)
    name = contact.full_name
    contact.delete()
    messages.success(request, f"Contact {name} supprimé.")
    return redirect(reverse("contacts") + _qs(company))

from datetime import date

from django import forms
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from integrations.insee import lookup_siren

from accounting.reports import cockpit_figures
from core.context import resolve_company

from .models import Company

ACTIVITIES_CHOICES = [
    ("btp", "BTP"),
    ("plomberie", "Plomberie"),
    ("electricite", "Électricité"),
    ("coiffure", "Coiffure"),
    ("resto", "Restauration"),
    ("artisan_autre", "Autre artisanat"),
]

REGIME_CHOICES = [("micro", "Micro-BIC"), ("reel_simple", "Réel simplifié")]
TVA_CHOICES = [("franchise", "Franchise en base"), ("reel", "TVA (CA3/CA12)")]
FORME_CHOICES = [
    ("SARL", "SARL"),
    ("EURL", "EURL"),
    ("SAS", "SAS"),
    ("SASU", "SASU"),
    ("EI", "Entreprise individuelle"),
    ("SCI", "SCI"),
]

LOOKUP_ERRORS = {
    "not_configured": (
        "L'API Sirene INSEE n'est pas encore configurée sur cet environnement. "
        "Vous pouvez compléter les informations manuellement."
    ),
    "not_found": (
        "Ce SIREN est introuvable dans la base Sirene. Vérifiez la saisie ou "
        "complétez les informations manuellement."
    ),
    "error": (
        "L'API Sirene est momentanément indisponible. Réessayez plus tard ou "
        "complétez les informations manuellement."
    ),
}


class SirenForm(forms.Form):
    siren = forms.CharField(
        label="Numéro SIREN",
        max_length=9,
        min_length=9,
        widget=forms.TextInput(
            attrs={"inputmode": "numeric", "placeholder": "123 456 789", "autofocus": True}
        ),
    )

    def clean_siren(self):
        siren = "".join(c for c in self.cleaned_data["siren"] if c.isdigit())
        if len(siren) != 9:
            raise forms.ValidationError("Le SIREN doit contenir exactement 9 chiffres.")
        return siren


class CompanyProfileForm(forms.Form):
    denomination = forms.CharField(label="Dénomination", max_length=255)
    forme = forms.ChoiceField(label="Forme juridique", choices=FORME_CHOICES)
    activites = forms.MultipleChoiceField(
        label="Activités", choices=ACTIVITIES_CHOICES,
    )
    regime = forms.ChoiceField(label="Régime fiscal", choices=REGIME_CHOICES)
    tva = forms.ChoiceField(label="TVA", choices=TVA_CHOICES)
    exercice_debut = forms.DateField(
        label="Date de début d'exercice",
        initial=date(date.today().year, 1, 1),
        widget=forms.DateInput(attrs={"type": "date"}),
    )


def landing(request):
    """Vitrine publique : promesse produit, tarifs, CTA connexion."""
    return render(request, "landing.html")


@login_required
def cockpit(request):
    """Pilotage d'une société : chiffres, dernières écritures, factures ouvertes."""
    companies = Company.objects.filter(owner=request.user)
    selected = resolve_company(request)
    figures = cockpit_figures(selected) if selected else None
    open_invoices = []
    if selected:
        open_invoices = list(
            selected.invoices.filter(status__in=["draft", "issued", "late", "received"])[:6]
        )
    return render(request, "companies/cockpit.html", {
        "companies": companies,
        "selected": selected,
        "figures": figures,
        "open_invoices": open_invoices,
    })


@login_required
def onboarding(request):
    """Étape 1 : saisie du SIREN. Les données légales sont récupérées via INSEE."""
    form = SirenForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        siren = form.cleaned_data["siren"]
        if Company.objects.filter(owner=request.user, siren=siren).exists():
            form.add_error("siren", "Cette société est déjà dans votre cockpit.")
        else:
            data, error = lookup_siren(siren)
            request.session["onboarding_lookup"] = {
                "siren": siren,
                "data": data,
                "error": error,
                "fetched_at": timezone.now().isoformat(),
            }
            return redirect("onboarding_confirm")
    return render(request, "companies/onboarding.html", {"form": form})


@login_required
def onboarding_confirm(request):
    """Étape 2 : validation des données INSEE + questionnaire métier."""
    lookup = request.session.get("onboarding_lookup")
    if not lookup:
        return redirect("onboarding")

    data = lookup.get("data") or {}
    error = lookup.get("error")
    siren = lookup["siren"]

    initial = {
        "denomination": data.get("denomination", ""),
        "forme": data.get("forme") if data.get("forme") in dict(FORME_CHOICES) else "SARL",
        "activites": [data["activite_suggeree"]] if data.get("activite_suggeree") else ["artisan_autre"],
        "exercice_debut": date(date.today().year, 1, 1),
    }

    if request.method == "POST":
        form = CompanyProfileForm(request.POST)
        if form.is_valid():
            if Company.objects.filter(owner=request.user, siren=siren).exists():
                form.add_error(None, "Cette société est déjà dans votre cockpit.")
            else:
                cleaned = form.cleaned_data
                source = {
                    "source": "insee_sirene" if data else "manuel",
                    "fetched_at": lookup.get("fetched_at"),
                    "siren": siren,
                    "raw": data.get("raw") if data else None,
                }
                company = Company.objects.create(
                    owner=request.user,
                    siren=siren,
                    denomination=cleaned["denomination"],
                    forme=cleaned["forme"],
                    address=data.get("adresse", ""),
                    code_naf=data.get("code_naf", ""),
                    activites=list(cleaned["activites"]),
                    regime=cleaned["regime"],
                    tva=cleaned["tva"],
                    exercice_debut=cleaned["exercice_debut"],
                    source_data=source,
                )
                from accounting.services import generate_portal

                generate_portal(company)

                request.session.pop("onboarding_lookup", None)
                return redirect(reverse("cockpit") + f"?societe={company.id}")
    else:
        form = CompanyProfileForm(initial=initial)

    return render(
        request,
        "companies/onboarding_confirm.html",
        {
            "form": form,
            "siren": siren,
            "data": data,
            "error_message": LOOKUP_ERRORS.get(error) if error else None,
        },
    )

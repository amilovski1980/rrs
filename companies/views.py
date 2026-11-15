from datetime import date

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from integrations.insee import lookup_siren, parse_company_query, search_entreprises

from accounting.reports import cockpit_figures
from core.context import resolve_company

from django.http import HttpResponse

from .models import INVOICE_LAYOUTS, INVOICE_LAYOUT_THEMES, INVOICE_THEMES, SMTP_PROVIDERS, Company
from .rib_scan import RibScanError, scan_rib_upload

SMTP_PRESETS = {
    "gmail": {
        "host": "smtp.gmail.com",
        "port": 587,
        "use_tls": True,
        "username_hint": "adresse@gmail.com",
        "password_hint": (
            "Mot de passe d'application Google (16 caractères), ou connexion "
            "Google ci-dessus."
        ),
    },
    "outlook": {
        "host": "smtp-mail.outlook.com",
        "port": 587,
        "use_tls": True,
        "username_hint": "adresse@outlook.fr ou @hotmail.fr",
        "password_hint": "Mot de passe du compte Microsoft (ou mot de passe d'application).",
    },
    "yahoo": {
        "host": "smtp.mail.yahoo.com",
        "port": 587,
        "use_tls": True,
        "username_hint": "adresse@yahoo.fr",
        "password_hint": "Mot de passe d'application Yahoo généré dans la sécurité du compte.",
    },
    "icloud": {
        "host": "smtp.mail.me.com",
        "port": 587,
        "use_tls": True,
        "username_hint": "adresse@icloud.com",
        "password_hint": "Mot de passe d'application Apple (sécurité du compte Apple).",
    },
    "custom": {
        "host": "",
        "port": 587,
        "use_tls": True,
        "username_hint": "adresse@votre-domaine.fr",
        "password_hint": "Mot de passe fourni par votre hébergeur ou votre domaine.",
    },
}

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

SEARCH_ERRORS = {
    "invalid": (
        "Saisissez le nom de la société (2 caractères minimum) ou un SIREN à 9 chiffres."
    ),
    "rate_limit": (
        "L'annuaire des entreprises est très sollicité en ce moment. "
        "Patientez quelques instants, puis relancez la recherche."
    ),
    "error": (
        "L'annuaire des entreprises est momentanément indisponible. "
        "Réessayez dans quelques minutes."
    ),
    "empty": (
        "Aucune société ne correspond à cette recherche. "
        "Vérifiez l'orthographe ou saisissez directement le SIREN."
    ),
}


class SirenForm(forms.Form):
    siren = forms.CharField(
        label="Nom de la société ou SIREN",
        max_length=80,
        widget=forms.TextInput(
            attrs={
                "placeholder": "Nom de la société ou 123 456 789",
                "autofocus": True,
                "autocomplete": "organization",
            }
        ),
    )

    def clean_siren(self):
        raw = " ".join((self.cleaned_data["siren"] or "").split())
        kind, normalized = parse_company_query(raw)
        if kind == "invalid":
            raise forms.ValidationError(
                "Saisissez le nom de la société (2 caractères minimum) ou un SIREN à 9 chiffres."
            )
        if kind == "siret":
            return normalized[:9]
        return normalized


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
    phone = forms.CharField(label="Téléphone", max_length=30, required=False)
    email = forms.EmailField(label="Email de facturation", required=False)


def landing(request):
    """Vitrine publique : promesse produit, forfaits, recherche de société."""
    from billing.public_pricing import pricing_context
    from core.public_theme import is_dark, themed_template, with_dark_voice

    context = pricing_context()
    if is_dark(request):
        context = with_dark_voice(context)
    return render(request, themed_template(request, "landing.html"), context)


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
def cockpit_global(request):
    """Vue inter-sociétés : chiffre d'affaires, TVA, achats et comparaisons
    de tout le portefeuille de l'utilisateur, période par période."""
    from datetime import timedelta
    from decimal import Decimal

    from django.db.models import DecimalField, ExpressionWrapper, F, Q, Sum
    from documents.models import Invoice, InvoiceLine
    from purchases.models import PurchaseInvoice

    period = (request.GET.get("periode") or "annee").lower()
    if period not in ("semaine", "mois", "annee"):
        period = "annee"
    windows = {
        "semaine": (timedelta(days=7), 7, "7 derniers jours"),
        "mois": (timedelta(days=30), 30, "30 derniers jours"),
        "annee": (timedelta(days=365), 365, "12 derniers mois"),
    }
    window, window_days, window_label = windows[period]
    today = timezone.localdate()
    start = today - window + timedelta(days=1)
    prev_start = start - window
    prev_end = start - timedelta(days=1)

    companies = list(Company.objects.filter(owner=request.user).order_by("denomination"))
    company_ids = [company.id for company in companies]
    issue_statuses = ("issued", "received", "paid", "late", "archived")
    purchase_statuses = ("approved", "paid", "archived")

    def vat_map(invoices):
        ids = [invoice.id for invoice in invoices]
        if not ids:
            return {}
        rows = (
            InvoiceLine.objects.filter(invoice_id__in=ids)
            .values("invoice_id")
            .annotate(vat=Sum(ExpressionWrapper(
                F("unit_price") * F("quantity") * F("vat_rate") / Decimal("100"),
                output_field=DecimalField(max_digits=15, decimal_places=2),
            )))
        )
        return {
            row["invoice_id"]: (row["vat"] or Decimal("0.00")).quantize(Decimal("0.01"))
            for row in rows
        }

    def fetch_invoices(window_start, window_end):
        return list(
            Invoice.objects.filter(
                company_id__in=company_ids,
                status__in=issue_statuses,
                created_at__date__gte=window_start,
                created_at__date__lte=window_end,
            ).only("id", "company_id", "client_name", "amount_ht")
        )

    def fetch_purchases(window_start, window_end):
        return list(
            PurchaseInvoice.objects.filter(
                company_id__in=company_ids,
                status__in=purchase_statuses,
            ).filter(
                Q(invoice_date__range=(window_start, window_end))
                | Q(invoice_date__isnull=True, created_at__date__range=(window_start, window_end))
            ).only("id", "company_id", "amount_ttc", "amount_vat")
        )

    def rollup(invoices, purchases, vats):
        rows = {
            company.id: {"ca": Decimal("0.00"), "vat": Decimal("0.00"),
                         "achats": Decimal("0.00"), "count": 0}
            for company in companies
        }
        for invoice in invoices:
            row = rows.setdefault(invoice.company_id, {"ca": Decimal("0.00"), "vat": Decimal("0.00"), "achats": Decimal("0.00"), "count": 0})
            vat = vats.get(invoice.id, Decimal("0.00"))
            row["ca"] += (invoice.amount_ht or Decimal("0.00")) + vat
            row["vat"] += vat
            row["count"] += 1
        for purchase in purchases:
            row = rows.setdefault(purchase.company_id, {"ca": Decimal("0.00"), "vat": Decimal("0.00"), "achats": Decimal("0.00"), "count": 0})
            row["achats"] += purchase.amount_ttc or Decimal("0.00")
        return rows

    invoices_current = fetch_invoices(start, today)
    vat_current = vat_map(invoices_current)
    purchases_current = fetch_purchases(start, today)
    rows_current = rollup(invoices_current, purchases_current, vat_current)

    invoices_prev = fetch_invoices(prev_start, prev_end)
    vat_prev = vat_map(invoices_prev)
    purchases_prev = fetch_purchases(prev_start, prev_end)
    rows_prev = rollup(invoices_prev, purchases_prev, vat_prev)

    totals = {
        "ca": sum((row["ca"] for row in rows_current.values()), Decimal("0.00")),
        "vat": sum((row["vat"] for row in rows_current.values()), Decimal("0.00")),
        "achats": sum((row["achats"] for row in rows_current.values()), Decimal("0.00")),
    }
    purchases_vat = sum(
        (purchase.amount_vat or Decimal("0.00") for purchase in purchases_current),
        Decimal("0.00"),
    )
    totals["vat_net"] = totals["vat"] - purchases_vat
    totals["count"] = len(invoices_current)

    prev_totals = {
        "ca": sum((row["ca"] for row in rows_prev.values()), Decimal("0.00")),
        "vat": sum((row["vat"] for row in rows_prev.values()), Decimal("0.00")),
        "achats": sum((row["achats"] for row in rows_prev.values()), Decimal("0.00")),
    }

    def delta(current, previous):
        if previous and previous > 0:
            value = (current - previous) / previous * Decimal("100")
            return int(round(value))
        return None

    # Série : CA et achats, bucket par bucket, avec la période précédente.
    buckets: list[dict] = []
    if period == "semaine":
        for offset in range(6, -1, -1):
            day = today - timedelta(days=offset)
            buckets.append({"label": day.strftime("%a").capitalize(), "start": day, "end": day})
    elif period == "mois":
        for offset in range(29, -1, -1):
            day = today - timedelta(days=offset)
            show_label = offset % 7 == 0 or offset == 0
            buckets.append({"label": day.strftime("%d") if not show_label else day.strftime("%d/%m"), "start": day, "end": day})
    else:
        from datetime import date as date_type

        month = today
        months: list[date_type] = []
        for _ in range(12):
            months.append(date(month.year, month.month, 1))
            year, month_num = month.year, month.month - 1
            if month_num == 0:
                year, month_num = year - 1, 12
            month = date(year, month_num, 1)
        for first_day in reversed(months):
            next_first = (first_day.replace(day=28) + timedelta(days=4)).replace(day=1)
            label = first_day.strftime("%b").capitalize()
            buckets.append({"label": label, "start": first_day, "end": min(next_first - timedelta(days=1), today)})
    current_by_bucket = [
        {"label": bucket["label"], "start": bucket["start"], "end": bucket["end"]}
        for bucket in buckets
    ]
    series = []
    for index, bucket in enumerate(buckets):
        ca = achats = ca_prev = Decimal("0.00")
        start_b, end_b = bucket["start"], bucket["end"]
        for invoice in invoices_current:
            day = timezone.localdate(invoice.created_at)
            if start_b <= day <= end_b:
                ca += (invoice.amount_ht or Decimal("0.00")) + vat_current.get(invoice.id, Decimal("0.00"))
        for purchase in purchases_current:
            day = purchase.invoice_date or timezone.localdate(purchase.created_at)
            if start_b <= day <= end_b:
                achats += purchase.amount_ttc or Decimal("0.00")
        for invoice in invoices_prev:
            day = timezone.localdate(invoice.created_at)
            if start_b <= day <= end_b:
                ca_prev += (invoice.amount_ht or Decimal("0.00")) + vat_prev.get(invoice.id, Decimal("0.00"))
        series.append({
            "label": bucket["label"],
            "ca": float(ca.quantize(Decimal("0.01"))),
            "achats": float(achats.quantize(Decimal("0.01"))),
            "ca_prev": float(ca_prev.quantize(Decimal("0.01"))),
        })

    company_rows = []
    for company in companies:
        row = rows_current.get(company.id, {"ca": Decimal("0.00"), "vat": Decimal("0.00"), "achats": Decimal("0.00"), "count": 0})
        previous = rows_prev.get(company.id, {"ca": Decimal("0.00")})
        company_rows.append({
            "company": company,
            "ca": row["ca"],
            "vat_net": row["vat"] - sum(
                (purchase.amount_vat or Decimal("0.00") for purchase in purchases_current if purchase.company_id == company.id),
                Decimal("0.00"),
            ),
            "achats": row["achats"],
            "count": row["count"],
            "delta": delta(row["ca"], previous["ca"]),
        })
    total_ca = totals["ca"] or Decimal("0.00")
    for row in company_rows:
        row["share"] = int(round(float(row["ca"] / total_ca * 100))) if total_ca > 0 else 0
        if row["delta"] is None:
            row["delta_display"] = "sans historique"
            row["delta_tone"] = "flat"
        elif row["delta"] >= 0:
            row["delta_display"] = f"▲ {row['delta']} % vs précédent"
            row["delta_tone"] = "up"
        else:
            row["delta_display"] = f"▼ {abs(row['delta'])} % vs précédent"
            row["delta_tone"] = "down"

    def delta_display(value, current=None, previous=None):
        if value is None or previous is None or previous == 0:
            return "—"
        sign = "▲" if value >= 0 else "▼"
        return f"{sign} {abs(int(value))} % vs précédente"

    chart_max = 1.0
    for point in series:
        chart_max = max(chart_max, float(point["ca"]), float(point["ca_prev"]))
    bucket_width = 720 / max(len(series), 1)
    for index, point in enumerate(series):
        point["x"] = int(round(index * bucket_width) + 2)
        point["w"] = max(6, int(round(bucket_width)) - 16)
        ca_height = int(round(point["ca"] / chart_max * 138))
        prev_height = int(round(point["ca_prev"] / chart_max * 138))
        point["ca_h"] = ca_height
        point["prev_h"] = prev_height
        point["ca_y"] = 148 - ca_height
        point["prev_y"] = 148 - prev_height

    return render(request, "companies/cockpit_global.html", {
        "companies_count": len(companies),
        "period": period,
        "window_label": window_label,
        "start": start,
        "prev_start": prev_start,
        "today": today,
        "totals": totals,
        "deltas": {
            "ca": delta_display(delta(totals["ca"], prev_totals["ca"]), totals["ca"], prev_totals["ca"]),
            "ca_up": (delta(totals["ca"], prev_totals["ca"]) or 0) >= 0 and totals["ca"] > 0,
            "vat": delta_display(delta(totals["vat"], prev_totals["vat"]), totals["vat"], prev_totals["vat"]),
            "achats": delta_display(delta(totals["achats"], prev_totals["achats"]), totals["achats"], prev_totals["achats"]),
        },
        "series": series,
        "company_rows": company_rows,
    })


@login_required
def onboarding(request):
    """Étape 1 : nom ou SIREN. Les données légales viennent de l'INSEE ou de l'annuaire."""
    form = SirenForm(request.POST or None)
    results: list[dict] = []
    search_message = ""
    query = ""
    if request.method == "POST" and form.is_valid():
        query = form.cleaned_data["siren"]
        kind, normalized = parse_company_query(query)
        if kind in {"siren", "siret"}:
            siren = normalized[:9]
            if Company.objects.filter(owner=request.user, siren=siren).exists():
                form.add_error("siren", "Cette société est déjà dans votre cockpit.")
            else:
                data, error = lookup_siren(siren)
                if isinstance(data, dict):
                    # Le cookie de session est trop petit pour le JSON brut de l'API.
                    data = {key: value for key, value in data.items() if key != "raw"}
                request.session["onboarding_lookup"] = {
                    "siren": siren,
                    "data": data,
                    "error": error,
                    "fetched_at": timezone.now().isoformat(),
                }
                return redirect("onboarding_confirm")
        else:
            results, error = search_entreprises(normalized)
            if error:
                search_message = SEARCH_ERRORS.get(error, SEARCH_ERRORS["error"])
            elif not results:
                search_message = SEARCH_ERRORS["empty"]
    return render(request, "companies/onboarding.html", {
        "form": form,
        "results": results,
        "search_message": search_message,
        "query": query,
    })


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
            elif Company.objects.filter(siren=siren).exists():
                form.add_error(
                    None,
                    "Ce SIREN est déjà rattaché à un autre compte. "
                    "Connectez-vous avec ce compte, ou choisissez une autre société.",
                )
            else:
                cleaned = form.cleaned_data
                from billing.access import company_create_block

                blocked = company_create_block(request.user)
                if blocked:
                    form.add_error(None, blocked)
                else:
                    if lookup.get("origin") == "annuaire":
                        source_name = "annuaire_entreprises"
                    elif data:
                        source_name = "insee_sirene"
                    else:
                        source_name = "manuel"
                    source = {
                        "source": source_name,
                        "fetched_at": lookup.get("fetched_at"),
                        "siren": siren,
                        "siret": (data.get("siret") or "") if data else "",
                    }
                    try:
                        with transaction.atomic():
                            company = Company.objects.create(
                                owner=request.user,
                                siren=siren,
                                denomination=cleaned["denomination"],
                                forme=cleaned["forme"],
                                address=data.get("adresse", ""),
                                phone=cleaned.get("phone", ""),
                                email=cleaned.get("email", ""),
                                code_naf=data.get("code_naf", ""),
                                activites=list(cleaned["activites"]),
                                regime=cleaned["regime"],
                                tva=cleaned["tva"],
                                exercice_debut=cleaned["exercice_debut"],
                                source_data=source,
                            )
                            from accounting.services import generate_portal

                            generate_portal(company)
                    except IntegrityError:
                        form.add_error(
                            None,
                            "Ce SIREN est déjà rattaché à un autre compte.",
                        )
                    else:
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


class CompanySettingsForm(forms.ModelForm):
    logo = forms.FileField(label="Logo", required=False)
    rib_scan = forms.FileField(
        label="Importer un RIB ou prendre une photo",
        required=False,
        widget=forms.ClearableFileInput(
            attrs={
                "accept": ".pdf,.jpg,.jpeg,.png,.webp",
                "data-rib-scan": "1",
            }
        ),
        help_text="PDF, JPG, PNG ou WEBP. L'IBAN et le BIC sont lus automatiquement.",
    )
    smtp_password = forms.CharField(
        label="Mot de passe SMTP",
        required=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="Laisser vide pour conserver le mot de passe déjà enregistré.",
    )
    payment_terms_days = forms.IntegerField(
        label="Délai de paiement (jours)",
        required=False,
        min_value=0,
        max_value=365,
        initial=30,
        help_text="Échéance par défaut des factures clients et fournisseurs.",
    )

    class Meta:
        model = Company
        fields = (
            "denomination",
            "forme",
            "address",
            "phone",
            "email",
            "slogan",
            "tva_intra",
            "invoice_theme",
            "regime",
            "tva",
            "exercice_debut",
            "payment_terms_days",
            "bank_name",
            "bank_iban",
            "bank_bic",
            "smtp_provider",
            "smtp_host",
            "smtp_port",
            "smtp_username",
            "smtp_password",
            "smtp_use_tls",
            "smtp_from_email",
        )
        labels = {
            "denomination": "Dénomination",
            "forme": "Forme juridique",
            "address": "Adresse",
            "phone": "Téléphone",
            "email": "Email de facturation",
            "slogan": "Slogan (facultatif)",
            "tva_intra": "TVA intracommunautaire",
            "invoice_theme": "Modèle de facture",
            "regime": "Régime fiscal",
            "tva": "Régime de TVA",
            "exercice_debut": "Début d'exercice",
            "payment_terms_days": "Délai de paiement (jours)",
            "bank_name": "Banque",
            "bank_iban": "IBAN",
            "bank_bic": "BIC",
            "smtp_provider": "Fournisseur e-mail",
            "smtp_host": "Serveur SMTP",
            "smtp_port": "Port SMTP",
            "smtp_username": "Utilisateur SMTP",
            "smtp_password": "Mot de passe SMTP",
            "smtp_use_tls": "Connexion SMTP sécurisée (TLS)",
            "smtp_from_email": "Expéditeur des documents",
        }
        widgets = {
            "exercice_debut": forms.DateInput(attrs={"type": "date"}),
            "smtp_port": forms.NumberInput(attrs={"min": "1", "max": "65535"}),
            "smtp_password": forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["forme"].widget = forms.Select(choices=FORME_CHOICES)
        self.fields["regime"].widget = forms.Select(choices=REGIME_CHOICES)
        self.fields["tva"].widget = forms.Select(choices=TVA_CHOICES)
        self.fields["phone"].widget.input_type = "tel"
        self.fields["phone"].widget.attrs.update(
            {"autocomplete": "tel", "inputmode": "tel"}
        )
        self.fields["email"].widget.input_type = "email"
        self.fields["email"].widget.attrs.update(
            {"autocomplete": "email", "inputmode": "email"}
        )
        self.fields["smtp_from_email"].widget.input_type = "email"
        self.fields["smtp_provider"].required = False
        self.fields["smtp_provider"].widget.attrs.update(
            {"data-smtp-provider": "1"}
        )
        # Les anciens formulaires ne postaient pas ce champ : on retombe sur
        # le port déjà enregistré (ou 587) au lieu de bloquer l'enregistrement.
        self.fields["smtp_port"].required = False
        self.fields["bank_iban"].widget.attrs.update(
            {
                "placeholder": "FR76 1027 8060 4100 0206 3428 704",
                "autocomplete": "off",
                "spellcheck": "false",
            }
        )
        self.fields["bank_bic"].widget.attrs.update(
            {
                "placeholder": "CMCIFR2A",
                "autocomplete": "off",
                "spellcheck": "false",
                "style": "text-transform:uppercase",
            }
        )
        self.fields["bank_name"].widget.attrs.update(
            {"placeholder": "CIC Île-de-France"}
        )

    def clean_bank_iban(self):
        from .rib_scan import _iban_is_plausible, _normalize_iban, format_iban

        raw = (self.cleaned_data.get("bank_iban") or "").strip()
        if not raw:
            return ""
        compact = _normalize_iban(raw)
        if not _iban_is_plausible(compact):
            raise forms.ValidationError(
                "IBAN invalide : indiquez le pays, la clé et le numéro de compte."
            )
        return format_iban(compact)

    def clean_bank_bic(self):
        value = "".join(
            char for char in (self.cleaned_data.get("bank_bic") or "").upper()
            if char.isalnum()
        )
        if value and len(value) not in (8, 11):
            raise forms.ValidationError("Le BIC doit contenir 8 ou 11 caractères.")
        return value

    def clean_smtp_port(self):
        port = self.cleaned_data.get("smtp_port")
        if port in (None, ""):
            return getattr(self.instance, "smtp_port", None) or 587
        if not 1 <= int(port) <= 65535:
            raise forms.ValidationError("Le port SMTP doit être compris entre 1 et 65535.")
        return int(port)

    def clean_smtp_password(self):
        value = (self.cleaned_data.get("smtp_password") or "").strip()
        if not value and self.instance.pk:
            return self.instance.smtp_password
        return value

    def clean_payment_terms_days(self):
        value = self.cleaned_data.get("payment_terms_days")
        return 30 if value is None else value

    def clean(self):
        cleaned = super().clean()
        provider = (
            cleaned.get("smtp_provider")
            or getattr(self.instance, "smtp_provider", "")
            or "custom"
        )
        cleaned["smtp_provider"] = provider
        preset = SMTP_PRESETS.get(provider)
        if preset and provider != "custom":
            previous = getattr(self.instance, "smtp_provider", "")
            if provider != previous or not (cleaned.get("smtp_host") or "").strip():
                cleaned["smtp_host"] = preset["host"]
                cleaned["smtp_port"] = preset["port"]
                cleaned["smtp_use_tls"] = preset["use_tls"]
        if not cleaned.get("smtp_from_email"):
            username = (cleaned.get("smtp_username") or "").strip()
            if "@" in username:
                cleaned["smtp_from_email"] = username
        return cleaned

    def clean_logo(self):
        upload = self.cleaned_data.get("logo")
        if not upload:
            return upload
        if upload.size > 800_000:
            raise forms.ValidationError("Le logo ne doit pas dépasser 800 Ko.")
        kind = getattr(upload, "content_type", "") or ""
        if kind not in ("image/png", "image/jpeg", "image/webp"):
            raise forms.ValidationError("Utilisez un fichier PNG, JPEG ou WebP.")
        return upload

    def clean_tva_intra(self):
        from documents.vat import is_valid_vat_number, normalize_vat_number

        value = normalize_vat_number(self.cleaned_data.get("tva_intra"))
        if value and not is_valid_vat_number(value):
            raise forms.ValidationError(
                "Numéro de TVA intracommunautaire invalide (ex. FR17100408517)."
            )
        return value


def _company_or_redirect(request):
    company = resolve_company(request)
    if company is None:
        return None, redirect("onboarding")
    return company, None


def _settings_extra_context(company):
    from decimal import Decimal

    mailbox = getattr(company, "mailbox_config", None)
    scopes = (getattr(mailbox, "granted_scopes", "") or "") if mailbox else ""
    linked = bool(mailbox and mailbox.has_tokens)
    return {
        "smtp_presets": SMTP_PRESETS,
        "layouts": INVOICE_LAYOUTS,
        "google_mail_linked": linked,
        "google_mail_connected": linked and "gmail.send" in scopes,
        "google_mail_email": getattr(mailbox, "email_address", "") if mailbox else "",
        "preview_date": timezone.localdate(),
        "preview_amount_ht": Decimal("295.00"),
        "preview_vat_amount": Decimal("54.50"),
        "preview_amount_ttc": Decimal("349.50"),
        "preview_lines": [
            {
                "description": "Pose de fenêtre",
                "quantity": Decimal("1.00"),
                "unit_price": Decimal("250.00"),
                "vat_rate": Decimal("20.00"),
                "amount_ht": Decimal("250.00"),
                "amount_ttc": Decimal("300.00"),
            },
            {
                "description": "Déplacement chantier",
                "quantity": Decimal("1.00"),
                "unit_price": Decimal("45.00"),
                "vat_rate": Decimal("10.00"),
                "amount_ht": Decimal("45.00"),
                "amount_ttc": Decimal("49.50"),
            },
        ],
    }


def _reconcile_invoice_layout(company) -> bool:
    """Le PDF téléchargé doit ressembler à la vignette de la couleur choisie.

    Chaque couleur a une mise en page automatique (PALETTES) : si un modèle
    figé par un choix antérieur ne correspond pas, on repasse en automatique
    (le champ invoice_layout porte l'aide « Vide = mise en page automatique
    selon la couleur choisie »). Retourne True si invoice_layout a changé.
    """
    from documents.pdf import PALETTES

    expected = (PALETTES.get(company.invoice_theme) or {}).get("layout", "")
    if company.invoice_layout and company.invoice_layout != expected:
        company.invoice_layout = ""
        return True
    return False


@login_required
def company_settings(request):
    """Logo, coordonnées et modèle de facture."""
    company, bounce = _company_or_redirect(request)
    if bounce:
        return bounce
    is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"
    if request.method == "POST" and "layout" in request.POST and "denomination" not in request.POST:
        layout = request.POST.get("layout") or ""
        if layout == "" or layout in dict(INVOICE_LAYOUTS):
            company.invoice_layout = layout
            fields = ["invoice_layout"]
            # Un modèle a une palette signature : sans cela, le PDF ne
            # ressemble pas à la vignette qui vient d'être choisie.
            signature_theme = INVOICE_LAYOUT_THEMES.get(layout)
            if signature_theme and signature_theme != company.invoice_theme:
                from billing.access import theme_allowed

                if theme_allowed(request.user, signature_theme):
                    company.invoice_theme = signature_theme
                    fields.append("invoice_theme")
            company.save(update_fields=fields)
        if is_ajax:
            return JsonResponse({
                "ok": True,
                "theme": company.invoice_theme,
                "layout": company.invoice_layout,
            })
        nxt = request.POST.get("next") or ""
        if not nxt.startswith("/") or nxt.startswith("//"):
            nxt = reverse("company_settings") + f"?societe={company.id}"
        return redirect(nxt)
    if request.method == "POST" and request.POST.get("theme") and "denomination" not in request.POST:
        theme = request.POST.get("theme")
        from billing.access import UPGRADE_MESSAGE, theme_allowed

        if theme in dict(INVOICE_THEMES) and not theme_allowed(request.user, theme):
            if is_ajax:
                return JsonResponse(
                    {"ok": False, "error": UPGRADE_MESSAGE}, status=403
                )
            messages.info(request, UPGRADE_MESSAGE)
            return redirect("plan_upgrade")
        if theme in dict(INVOICE_THEMES):
            company.invoice_theme = theme
            if _reconcile_invoice_layout(company):
                company.save(update_fields=["invoice_theme", "invoice_layout"])
            else:
                company.save(update_fields=["invoice_theme"])
        if is_ajax:
            return JsonResponse({
                "ok": True,
                "theme": company.invoice_theme,
                "layout": company.invoice_layout,
            })
        nxt = request.POST.get("next") or ""
        if not nxt.startswith("/") or nxt.startswith("//"):
            nxt = reverse("company_settings") + f"?societe={company.id}"
        return redirect(nxt)
    if request.method == "POST" and request.POST.get("scan_rib"):
        form = CompanySettingsForm(request.POST, request.FILES, instance=company)
        try:
            details = scan_rib_upload(request.FILES.get("rib_scan"))
        except RibScanError as exc:
            messages.error(request, str(exc))
        else:
            data = request.POST.copy()
            if details.iban:
                data["bank_iban"] = details.iban
            if details.bic:
                data["bank_bic"] = details.bic
            if details.bank_name:
                data["bank_name"] = details.bank_name
            form = CompanySettingsForm(data, instance=company)
            messages.success(
                request,
                "RIB lu. Vérifiez l'IBAN, le BIC et la banque puis cliquez sur Enregistrer.",
            )
        return render(request, "companies/settings.html", {
            "company": company,
            "form": form,
            "themes": INVOICE_THEMES,
            **_settings_extra_context(company),
        })

    form = CompanySettingsForm(request.POST or None, request.FILES or None, instance=company)
    if request.method == "POST" and form.is_valid():
        from billing.access import UPGRADE_MESSAGE, theme_allowed

        chosen = form.cleaned_data.get("invoice_theme")
        if chosen and not theme_allowed(request.user, chosen):
            messages.info(request, UPGRADE_MESSAGE)
            return redirect("plan_upgrade")
        company = form.save()
        if _reconcile_invoice_layout(company):
            company.save(update_fields=["invoice_layout"])
        if request.POST.get("remove_logo"):
            company.logo = None
            company.logo_type = ""
            company.save(update_fields=["logo", "logo_type"])
        upload = form.cleaned_data.get("logo")
        if upload:
            company.logo = upload.read()
            company.logo_type = upload.content_type
            company.save(update_fields=["logo", "logo_type"])
        return redirect(reverse("company_settings") + f"?societe={company.id}")
    return render(request, "companies/settings.html", {
        "company": company,
        "form": form,
        "themes": INVOICE_THEMES,
        **_settings_extra_context(company),
    })


@login_required
@login_required
def company_delete(request):
    """Supprime définitivement la société courante et ses données rattachées."""
    import logging

    company_id = request.POST.get("societe") or request.GET.get("societe")
    try:
        company = Company.objects.get(pk=company_id, owner=request.user)
    except (Company.DoesNotExist, ValidationError, TypeError):
        raise Http404("Société introuvable.")
    name = company.denomination

    # GET : l'écran de confirmation (aucune suppression sans POST explicite).
    if request.method != "POST":
        return render(request, "companies/company_delete.html", {
            "company": company,
        })
    if request.POST.get("confirm") != "supprimer":
        messages.error(request, "Cochez la confirmation avant de supprimer la société.")
        return redirect(reverse("company_settings") + f"?societe={company.id}")

    try:
        with transaction.atomic():
            if request.session.get("societe_id") == str(company.id):
                request.session.pop("societe_id", None)
            company.delete()
    except Exception as exc:
        # Aucun 500 : certaines données rattachées peuvent encore exister
        # (rapprochements, documents protégés…). Message lisible et sortie propre.
        logging.getLogger(__name__).exception(
            "Suppression de la société %s en échec", company.pk
        )
        messages.error(
            request,
            "La suppression a échoué : des éléments restent rattachés à cette "
            "société. Supprimez-les d'abord, ou contactez le support "
            f"(réf. {company.pk}).",
        )
        return redirect(reverse("company_settings") + f"?societe={company.id}")


@login_required
def company_logo(request):
    company, bounce = _company_or_redirect(request)
    if bounce or not company.logo:
        return HttpResponse(status=404)
    kind = company.logo_type or "image/png"
    response = HttpResponse(bytes(company.logo), content_type=kind)
    response["Cache-Control"] = "private, max-age=3600"
    return response


@login_required
def help_page(request):
    """Page d'aide du cockpit (contenu rédactionnel minimal)."""
    return render(request, "companies/help.html")


def legal_notice(request):
    """Mentions légales de l'éditeur Road Runner One."""
    contact = {"address": "", "phone": "", "email": ""}
    try:
        from admin_backoffice.models import SiteConfiguration

        config = SiteConfiguration.objects.filter(pk=1).first()
        if config is not None:
            contact = {
                "address": (config.contact_address or "").strip(),
                "phone": (config.contact_phone or "").strip(),
                "email": (config.contact_email or "").strip(),
            }
    except Exception:
        pass
    return render(request, "companies/legal_notice.html", {"contact": contact})


def terms_of_use(request):
    """Conditions générales d'utilisation."""
    return render(request, "companies/terms_of_use.html")


def terms_of_sale(request):
    """Conditions générales de vente (abonnements B2B)."""
    return render(request, "companies/terms_of_sale.html")


def privacy_policy(request):
    """Politique de confidentialité et droits RGPD."""
    return render(request, "companies/privacy_policy.html")

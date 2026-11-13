import re

from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from accounts.models import User
from billing.catalog import BOOL_FEATURES
from billing.models import Plan, Subscription
from companies.models import INVOICE_THEMES, Company

from .models import EmailTemplate, SiteConfiguration, SmsTemplate

SECRET_FIELDS = (
    "smtp_password",
    "stripe_secret_key",
    "stripe_publishable_key",
    "stripe_webhook_secret",
    "llm_api_key",
    "xai_api_key",
    "insee_api_key",
)


def _feature_lines(raw) -> list[str]:
    """Texte « une fonction par ligne », même si le JSON stocké n'est pas une liste de textes."""
    if isinstance(raw, str):
        items = raw.splitlines()
    elif isinstance(raw, (list, tuple)):
        items = raw
    else:
        items = []
    lines = []
    for item in items:
        if isinstance(item, (dict, list, tuple)) or item is None:
            continue
        text = str(item).strip()
        if text:
            lines.append(text)
    return lines


def _style_fields(form):
    for field in form.fields.values():
        widget = field.widget
        if isinstance(widget, forms.CheckboxInput):
            widget.attrs["class"] = "form-check"
        else:
            widget.attrs["class"] = "form-control"
        if isinstance(widget, forms.Textarea) and "rows" not in widget.attrs:
            widget.attrs["rows"] = 4


class SiteConfigurationForm(forms.ModelForm):
    class Meta:
        model = SiteConfiguration
        fields = [
            "site_name",
            "maintenance_mode",
            "contact_address",
            "contact_phone",
            "contact_email",
            "smtp_host",
            "smtp_port",
            "smtp_user",
            "smtp_password",
            "email_from",
            "stripe_secret_key",
            "stripe_publishable_key",
            "stripe_webhook_secret",
            "llm_base_url",
            "llm_model",
            "llm_api_key",
            "xai_api_key",
            "xai_text_model",
            "xai_voice_model",
            "xai_voice",
            "ai_text_provider",
            "insee_api_key",
        ]
        widgets = {
            name: forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"})
            for name in SECRET_FIELDS
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style_fields(self)
        for name in SECRET_FIELDS:
            self.fields[name].required = False
            self.fields[name].widget.attrs["class"] = "form-control"
            self.fields[name].help_text = (
                "Laisser vide pour conserver la valeur déjà enregistrée. Elle n'est jamais réaffichée."
            )

    def clean(self):
        cleaned = super().clean()
        if self.instance and self.instance.pk:
            for name in SECRET_FIELDS:
                if name in self.fields and not (cleaned.get(name) or "").strip():
                    cleaned[name] = getattr(self.instance, name) or ""
        return cleaned


class CompanyAdminForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = [
            "owner",
            "siren",
            "denomination",
            "forme",
            "address",
            "phone",
            "email",
            "regime",
            "tva",
            "invoice_theme",
        ]
        labels = {
            "owner": "Propriétaire",
            "siren": "SIREN",
            "denomination": "Dénomination",
            "forme": "Forme",
            "address": "Adresse",
            "phone": "Téléphone",
            "email": "Email",
            "regime": "Régime",
            "tva": "TVA",
            "invoice_theme": "Thème de facture",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["owner"].queryset = User.objects.order_by("email")
        _style_fields(self)

    def clean_siren(self):
        siren = re.sub(r"\s", "", self.cleaned_data.get("siren") or "")
        if not re.fullmatch(r"\d{9}", siren):
            raise forms.ValidationError("Le SIREN doit comporter 9 chiffres.")
        return siren


class PlanAdminForm(forms.ModelForm):
    features_text = forms.CharField(
        label="Fonctions incluses",
        required=False,
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text="Une fonction par ligne, affichée sur la page forfait. Exemple : Export des factures PDF.",
    )

    class Meta:
        model = Plan
        fields = [
            "code",
            "name",
            "price_eur",
            "trial_days",
            "description",
            "max_companies",
            "max_invoices_month",
            "max_ai_requests_month",
            "is_active",
            "ai_prompt",
        ]
        labels = {
            "code": "Code",
            "name": "Nom",
            "price_eur": "Prix mensuel (€)",
            "trial_days": "Jours d'essai",
            "description": "Description",
            "is_active": "Proposé aux clients",
            "ai_prompt": "Consigne de l'agent pour ce forfait",
        }
        widgets = {"ai_prompt": forms.Textarea(attrs={"rows": 8})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        raw = self.instance.features if self.instance and self.instance.pk else []
        self.fields["features_text"].initial = "\n".join(_feature_lines(raw))
        self.fields["code"].help_text = "Exemples : micro, reel, pro, starter, illimite."
        self.fields["ai_prompt"].help_text = (
            "Vide = consigne par défaut selon le code (Micro limité, Pro complet)."
        )
        from billing.access import _plan_matrix

        matrix = _plan_matrix(self.instance) if self.instance and self.instance.pk else {}
        for key, label in BOOL_FEATURES:
            field_name = f"feat_{key}"
            self.fields[field_name] = forms.BooleanField(
                label=label,
                required=False,
                initial=bool(matrix.get(key)),
            )
        selected = set(matrix.get("themes") or [])
        for code, label in INVOICE_THEMES:
            field_name = f"theme_{code}"
            self.fields[field_name] = forms.BooleanField(
                label=f"Modèle de facture {label}",
                required=False,
                initial=code in selected,
            )
        _style_fields(self)

    def save(self, commit=True):
        plan = super().save(commit=False)
        text = self.cleaned_data.get("features_text") or ""
        plan.features = [line.strip() for line in text.splitlines() if line.strip()]
        entitlements = {"custom": True}
        for key, _label in BOOL_FEATURES:
            entitlements[key] = bool(self.cleaned_data.get(f"feat_{key}"))
        entitlements["themes"] = [
            code for code, _label in INVOICE_THEMES if self.cleaned_data.get(f"theme_{code}")
        ]
        plan.entitlements = entitlements
        if commit:
            plan.save()
        return plan


class SubscriptionAdminForm(forms.ModelForm):
    class Meta:
        model = Subscription
        fields = ["user", "plan", "status", "current_period_end"]
        labels = {
            "user": "Utilisateur",
            "plan": "Forfait",
            "status": "Statut",
            "current_period_end": "Fin de période",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["user"].queryset = User.objects.order_by("email")
        self.fields["plan"].queryset = Plan.objects.order_by("price_eur", "name")
        end = self.fields["current_period_end"]
        end.required = False
        end.input_formats = ["%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"]
        end.widget = forms.DateTimeInput(
            attrs={"type": "datetime-local", "class": "form-control"},
            format="%Y-%m-%dT%H:%M",
        )
        _style_fields(self)
        end.widget.attrs["class"] = "form-control"


class UserAdminForm(forms.ModelForm):
    password1 = forms.CharField(
        label="Nouveau mot de passe",
        required=False,
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
        help_text="Laisser vide pour ne pas changer le mot de passe. L'actuel n'est jamais affiché.",
    )
    password2 = forms.CharField(
        label="Confirmation du mot de passe",
        required=False,
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
    )
    confirm_password = forms.BooleanField(
        label="Je confirme l'enregistrement de ce mot de passe",
        required=False,
    )

    class Meta:
        model = User
        fields = ["email", "phone", "phone_verified", "is_active", "is_staff", "is_superuser"]
        labels = {
            "email": "Email",
            "phone": "Téléphone",
            "phone_verified": "Téléphone vérifié",
            "is_active": "Compte actif",
            "is_staff": "Accès administration",
            "is_superuser": "Super-administrateur",
        }

    def __init__(self, *args, actor=None, **kwargs):
        self.actor = actor
        super().__init__(*args, **kwargs)
        if not actor or not actor.is_superuser:
            self.fields.pop("is_superuser", None)
        _style_fields(self)

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if not email:
            raise forms.ValidationError("L'email est obligatoire.")
        return email

    def clean(self):
        cleaned = super().clean()
        actor = self.actor
        if self.instance.pk and actor and self.instance.pk == actor.pk:
            if "is_active" in cleaned and not cleaned.get("is_active"):
                self.add_error("is_active", "Vous ne pouvez pas désactiver votre propre compte.")
            if "is_staff" in cleaned and not cleaned.get("is_staff"):
                self.add_error("is_staff", "Vous ne pouvez pas retirer votre propre accès administrateur.")
            if "is_superuser" in cleaned and not cleaned.get("is_superuser"):
                self.add_error("is_superuser", "Vous ne pouvez pas retirer votre propre droit de super-administrateur.")
        password = (cleaned.get("password1") or "").strip()
        confirm = (cleaned.get("password2") or "").strip()
        if password or confirm:
            if not cleaned.get("confirm_password"):
                self.add_error("confirm_password", "Cochez la confirmation pour enregistrer le mot de passe.")
            if password != confirm:
                self.add_error("password2", "Les deux mots de passe ne correspondent pas.")
            elif password:
                try:
                    validate_password(password, self.instance)
                except ValidationError as exc:
                    self.add_error("password1", exc)
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        password = (self.cleaned_data.get("password1") or "").strip()
        if password:
            user.set_password(password)
        elif user._state.adding:
            # L'UUID est déjà posé avant l'insert : ne pas se fier à user.pk.
            user.set_unusable_password()
        if commit:
            user.save()
        return user


class EmailTemplateForm(forms.ModelForm):
    """Objet et corps d'un email automatique, placeholders compris."""

    class Meta:
        model = EmailTemplate
        fields = ["subject", "body"]
        widgets = {
            "subject": forms.TextInput(attrs={"maxlength": 255}),
            "body": forms.Textarea(attrs={"rows": 16}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style_fields(self)
        self.fields["subject"].help_text = "Une seule ligne. Les placeholders sont remplacés à l'envoi."
        self.fields["body"].help_text = "Texte brut. Les placeholders inconnus restent affichés tels quels."

    def clean_subject(self):
        subject = " ".join((self.cleaned_data.get("subject") or "").split())
        if not subject:
            raise forms.ValidationError("L'objet est obligatoire.")
        return subject

    def clean_body(self):
        body = (self.cleaned_data.get("body") or "").strip()
        if not body:
            raise forms.ValidationError("Le corps est obligatoire.")
        return body


class SmsTemplateForm(forms.ModelForm):
    class Meta:
        model = SmsTemplate
        fields = ["code", "name", "body", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style_fields(self)


class SmsSendForm(forms.Form):
    recipient = forms.CharField(label="Destinataire", max_length=32)
    body = forms.CharField(label="Message", widget=forms.Textarea(attrs={"rows": 3}))
    template = forms.ModelChoiceField(
        label="Modèle",
        queryset=SmsTemplate.objects.none(),
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["template"].queryset = SmsTemplate.objects.filter(is_active=True)
        _style_fields(self)

    def clean_recipient(self):
        raw = re.sub(r"[^\d+]", "", self.cleaned_data.get("recipient") or "")
        if len(raw) < 8:
            raise forms.ValidationError("Indiquez un numéro d'au moins 8 chiffres.")
        return raw[:32]

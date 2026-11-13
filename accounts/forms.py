"""Formulaires de connexion et de mot de passe. Aucun secret n'est réaffiché."""
from __future__ import annotations

import unicodedata

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from admin_backoffice.email_templates import display_name, send_template_email
from core.demo import DEMO_EMAIL
from core.public_theme import themed_reverse


User = get_user_model()


def _same_email(left: str, right: str) -> bool:
    return (
        unicodedata.normalize("NFKC", left or "").casefold()
        == unicodedata.normalize("NFKC", right or "").casefold()
    )


class LoginForm(forms.Form):
    email = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(attrs={"autocomplete": "username", "placeholder": "vous@exemple.fr"}),
    )
    password = forms.CharField(
        label="Mot de passe",
        required=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )

    def clean(self):
        cleaned = super().clean()
        email = (cleaned.get("email") or "").strip().lower()
        cleaned["email"] = email
        if email and email != DEMO_EMAIL and not (cleaned.get("password") or ""):
            self.add_error("password", "Indiquez votre mot de passe.")
        return cleaned


class EmailOnlyForm(forms.Form):
    email = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(attrs={"autocomplete": "username", "placeholder": "vous@exemple.fr"}),
    )

    def clean_email(self):
        return (self.cleaned_data["email"] or "").strip().lower()


class OwnPasswordForm(forms.Form):
    """Changement pour un utilisateur connecté. Sans mot de passe actuel si le compte n'en a pas."""

    current_password = forms.CharField(
        label="Mot de passe actuel",
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )
    new_password1 = forms.CharField(
        label="Nouveau mot de passe",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="8 caractères minimum. Il est stocké haché, jamais en clair.",
    )
    new_password2 = forms.CharField(
        label="Confirmation",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        if not user.has_usable_password():
            self.fields.pop("current_password")

    def clean(self):
        cleaned = super().clean()
        if "current_password" in self.fields:
            current = cleaned.get("current_password") or ""
            if not self.user.check_password(current):
                self.add_error("current_password", "Le mot de passe actuel est incorrect.")
        first = cleaned.get("new_password1") or ""
        second = cleaned.get("new_password2") or ""
        if first and second and first != second:
            self.add_error("new_password2", "Les deux mots de passe ne correspondent pas.")
        elif first and "new_password2" not in self.errors and "current_password" not in self.errors:
            try:
                validate_password(first, self.user)
            except ValidationError as exc:
                self.add_error("new_password1", exc)
        return cleaned


class ProfileForm(forms.ModelForm):
    """Identité et signature utilisées dans les emails envoyés depuis le cockpit."""

    class Meta:
        model = User
        fields = ("first_name", "last_name", "job_title", "email_signature")
        widgets = {
            "email_signature": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "Laissez vide pour utiliser la signature automatique "
                    "(nom, fonction, société, email et téléphone).",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].label = "Prénom"
        self.fields["last_name"].label = "Nom"
        self.fields["job_title"].label = "Fonction"
        self.fields["email_signature"].label = "Signature email"
        self.fields["first_name"].widget.attrs.update({"autocomplete": "given-name"})
        self.fields["last_name"].widget.attrs.update({"autocomplete": "family-name"})
        self.fields["job_title"].widget.attrs.update({"autocomplete": "organization-title"})


class FrenchPasswordResetForm(PasswordResetForm):
    """Inclut les comptes sans mot de passe utilisable : ils doivent pouvoir en définir un."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].label = "Email"

    def get_users(self, email):
        email_field = User.get_email_field_name()
        active = User._default_manager.filter(**{
            f"{email_field}__iexact": email,
            "is_active": True,
        })
        for user in active:
            if _same_email(email, getattr(user, email_field)):
                yield user

    def save(
        self,
        domain_override=None,
        subject_template_name=None,
        email_template_name=None,
        use_https=False,
        token_generator=None,
        from_email=None,
        request=None,
        html_email_template_name=None,
        extra_email_context=None,
    ):
        """Envoie le lien avec le modèle géré dans le back-office.

        Les arguments de gabarits historiques restent acceptés pour ne pas
        casser les appels existants (vue publique, administration), mais le
        texte vient de ``EmailTemplate`` ou de son défaut documenté.
        """
        del domain_override, subject_template_name, email_template_name
        del use_https, from_email, html_email_template_name
        generator = token_generator or default_token_generator
        protocol = "https" if request is not None and request.is_secure() else "http"
        domain = request.get_host() if request is not None else "localhost"
        for user in self.get_users(self.cleaned_data["email"]):
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = generator.make_token(user)
            path = (
                themed_reverse(request, "password_reset_confirm", uidb64=uid, token=token)
                if request is not None
                else reverse("password_reset_confirm", kwargs={"uidb64": uid, "token": token})
            )
            reset_url = f"{protocol}://{domain}{path}"
            context = {
                "name": display_name(user),
                "email": user.email,
                "uid": uid,
                "token": token,
                "protocol": protocol,
                "domain": domain,
                "reset_url": reset_url,
            }
            if extra_email_context:
                context.update(extra_email_context)
            send_template_email(
                "password_reset",
                user.email,
                context,
                request=request,
            )


class FrenchSetPasswordForm(SetPasswordForm):
    error_messages = {
        **SetPasswordForm.error_messages,
        "password_mismatch": "Les deux mots de passe ne correspondent pas.",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["new_password1"].label = "Nouveau mot de passe"
        self.fields["new_password2"].label = "Confirmation"
        self.fields["new_password1"].help_text = (
            "8 caractères minimum. Il est stocké haché, jamais en clair."
        )
        self.fields["new_password1"].widget.attrs["autocomplete"] = "new-password"
        self.fields["new_password2"].widget.attrs["autocomplete"] = "new-password"

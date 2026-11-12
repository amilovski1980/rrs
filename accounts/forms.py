"""Formulaires de connexion et de mot de passe. Aucun secret n'est réaffiché."""
from __future__ import annotations

import unicodedata

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from core.demo import DEMO_EMAIL


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

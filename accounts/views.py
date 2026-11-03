from django import forms
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from core.demo import DEMO_EMAIL, seed_demo

from .models import MagicLink, User


class EmailForm(forms.Form):
    email = forms.EmailField(label="Votre email")


def open_account(email):
    """Ouvre ou retrouve le cockpit de cette adresse. Pas d'envoi de mail."""
    email = email.lower().strip()
    if email == DEMO_EMAIL:
        user, _company = seed_demo()
        return user
    user = User.objects.filter(email=email).first()
    if user is None:
        user = User.objects.create_user(email)
    return user


def magic_link_request(request):
    """Saisie de l'email : connexion immédiate au compte correspondant."""
    form = EmailForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = open_account(form.cleaned_data["email"])
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        return redirect("cockpit")
    return render(request, "accounts/magic_link_form.html", {"form": form})


def magic_link_verify(request, token):
    user = MagicLink.verify(token)
    if user is None:
        return render(request, "accounts/magic_link_invalid.html", status=410)
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return redirect("cockpit")


@login_required
@require_POST
def logout_view(request):
    from django.contrib.auth import logout

    logout(request)
    return redirect("magic_link_request")


@login_required
def profile(request):
    """Squelette de page profil (téléphone, facturation, abonnement…)."""
    return render(request, "accounts/profile.html", {"user": request.user})

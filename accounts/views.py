from django import forms
from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .models import MagicLink, User


class EmailForm(forms.Form):
    email = forms.EmailField(label=" Votre email")


def magic_link_request(request):
    """Demander un lien de connexion (pas de mot de passe)."""
    form = EmailForm(request.POST or None)
    sent = False
    dev_link = None
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"].lower().strip()
        user, _ = User.objects.get_or_create(email=email)
        raw, _link = MagicLink.issue(user, minutes=30, ip=request.META.get("REMOTE_ADDR"))
        link_url = request.build_absolute_uri(f"/compte/magic/{raw}")
        try:
            send_mail(
                subject="Votre accès Road Runner Solutions",
                message=(
                    "Connectez-vous en une fois (lien valable 30 minutes) :\n"
                    f"{link_url}\n\n"
                    "Vous n'avez pas besoin de mot de passe."
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[email],
                fail_silently=False,
            )
        except (OSError, ValueError):
            if not settings.DEBUG:
                raise
        if settings.DEBUG:
            # En dev, le lien est montré directement à l'écran (SMTP non configuré).
            dev_link = link_url
        sent = True
        form = EmailForm()
    return render(
        request,
        "accounts/magic_link_form.html",
        {"form": form, "sent": sent, "dev_link": dev_link},
    )


def magic_link_verify(request, token):
    user = MagicLink.verify(token)
    if user is None:
        return render(request, "accounts/magic_link_invalid.html", status=410)
    login(
        request, user, backend="django.contrib.auth.backends.ModelBackend"
    )
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

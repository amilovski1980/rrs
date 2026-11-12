import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import PasswordResetConfirmView, PasswordResetView
from django.core.mail import send_mail
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST
from django.views.generic import TemplateView

from core.demo import ADMIN_EMAIL, DEMO_EMAIL, seed_admin, seed_demo

from .forms import EmailOnlyForm, FrenchPasswordResetForm, FrenchSetPasswordForm, LoginForm, OwnPasswordForm
from .models import MagicLink, User

logger = logging.getLogger(__name__)


def open_account(email):
    """Ouvre le cockpit de démonstration. Les autres adresses ne sont pas créées ici."""
    email = (email or "").lower().strip()
    if email == DEMO_EMAIL:
        user, _company = seed_demo()
        return user
    return User.objects.filter(email__iexact=email).first()


def _safe_next(request, candidate: str) -> str:
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return ""


def _client_ip(request):
    ip = (request.META.get("REMOTE_ADDR") or "").strip()
    if ip and len(ip) <= 45:
        return ip
    return None


def login_view(request):
    """Connexion email + mot de passe. La démo publique reste ouverte sans mot de passe."""
    form = LoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"]
        password = form.cleaned_data.get("password") or ""
        if email == DEMO_EMAIL:
            user = open_account(email)
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            return redirect(_safe_next(request, request.POST.get("next") or "") or "cockpit")
        if email == (ADMIN_EMAIL or "").strip().lower():
            # Un ADMIN_PASSWORD d'environnement pose le premier mot de passe staff,
            # sans jamais remplacer un mot de passe déjà choisi.
            seed_admin()
        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if user is None:
            User().set_password(password)
            ok = False
        else:
            ok = user.check_password(password)
        if not ok:
            form.add_error(None, "Email ou mot de passe incorrect.")
        else:
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            return redirect(_safe_next(request, request.POST.get("next") or "") or "cockpit")
    return render(request, "accounts/magic_link_form.html", {
        "form": form,
        "next": request.GET.get("next") or "",
    })


def magic_link_email(request):
    """Lien de secours par email. La réponse ne dit pas si l'adresse existe."""
    form = EmailOnlyForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"]
        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if user is not None:
            try:
                raw, _link = MagicLink.issue(user, minutes=30, ip=_client_ip(request))
                url = request.build_absolute_uri(reverse("magic_link_verify", kwargs={"token": raw}))
                send_mail(
                    subject="Votre lien de connexion Road Runner Solutions",
                    message=(
                        "Bonjour,\n\n"
                        "Pour ouvrir votre cockpit, utilisez ce lien (valable 30 minutes, une seule fois) :\n"
                        f"{url}\n\n"
                        "Vous pourrez ensuite définir un mot de passe depuis votre profil.\n"
                        "Si vous n'êtes pas à l'origine de cette demande, ignorez ce message.\n"
                    ),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[user.email],
                    fail_silently=False,
                )
            except Exception:
                logger.exception("Lien de connexion non envoyé")
        return redirect("magic_link_email_done")
    return render(request, "accounts/magic_link_email.html", {"form": form})


def magic_link_email_done(request):
    return render(request, "accounts/magic_link_email_done.html")


def magic_link_verify(request, token):
    user = MagicLink.verify(token)
    if user is None or not user.is_active:
        return render(request, "accounts/magic_link_invalid.html", status=410)
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    if not user.has_usable_password():
        messages.info(
            request,
            "Définissez un mot de passe pour vos prochaines connexions. Vous pouvez aussi le faire plus tard.",
        )
        return redirect("profile")
    return redirect("cockpit")


@login_required
@require_POST
def logout_view(request):
    logout(request)
    return redirect("magic_link_request")


@login_required
@require_http_methods(["GET", "POST"])
def profile(request):
    form = OwnPasswordForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        request.user.set_password(form.cleaned_data["new_password1"])
        request.user.save(update_fields=["password"])
        update_session_auth_hash(request, request.user)
        messages.success(request, "Mot de passe mis à jour.")
        return redirect("profile")
    return render(request, "accounts/profile.html", {
        "user": request.user,
        "password_form": form,
        "has_password": request.user.has_usable_password(),
    })


class FrenchPasswordResetView(PasswordResetView):
    form_class = FrenchPasswordResetForm
    template_name = "accounts/password_reset_form.html"
    email_template_name = "accounts/password_reset_email.txt"
    subject_template_name = "accounts/password_reset_subject.txt"
    success_url = reverse_lazy("password_reset_done")

    def form_valid(self, form):
        try:
            form.save(
                use_https=self.request.is_secure(),
                token_generator=self.token_generator,
                from_email=self.from_email,
                email_template_name=self.email_template_name,
                subject_template_name=self.subject_template_name,
                request=self.request,
                html_email_template_name=self.html_email_template_name,
                extra_email_context=self.extra_email_context,
            )
        except Exception:
            logger.exception("Email de mot de passe non envoyé")
        return redirect(self.get_success_url())


class FrenchPasswordResetDoneView(TemplateView):
    template_name = "accounts/password_reset_done.html"


class FrenchPasswordResetConfirmView(PasswordResetConfirmView):
    form_class = FrenchSetPasswordForm
    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("password_reset_complete")


class FrenchPasswordResetCompleteView(TemplateView):
    template_name = "accounts/password_reset_complete.html"

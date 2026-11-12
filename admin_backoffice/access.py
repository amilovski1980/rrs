"""Accès réservé au personnel actif. Les clients authentifiés reçoivent 403."""
from functools import wraps

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied


def user_is_admin(user) -> bool:
    return bool(
        user
        and getattr(user, "is_authenticated", False)
        and getattr(user, "is_active", False)
        and getattr(user, "is_staff", False)
    )


def staff_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), login_url=settings.LOGIN_URL)
        if not user_is_admin(request.user):
            raise PermissionDenied("Accès réservé à l'administration.")
        return view(request, *args, **kwargs)

    return wrapped

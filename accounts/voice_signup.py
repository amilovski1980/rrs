"""VocalIA voice onboarding: email-only invitation, no company or SIREN creation."""
import json
import logging
import secrets

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from accounts.models import MagicLink, User
from admin_backoffice.email_templates import display_name, send_template_email

logger = logging.getLogger(__name__)


@csrf_exempt  # Machine-to-machine: authenticated using a separate secret.
@require_POST
def voice_signup(request):
    expected = getattr(settings, "VOCALIA_API_TOKEN", "")
    authorization = request.headers.get("Authorization", "")
    supplied = authorization.removeprefix("Bearer ").strip() if authorization.startswith("Bearer ") else ""
    if not expected or not secrets.compare_digest(supplied, expected):
        return JsonResponse({"error": "unauthorized"}, status=401)
    if len(request.body) > 4096:
        return JsonResponse({"error": "payload_too_large"}, status=413)
    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "invalid_json"}, status=400)
    if not isinstance(data, dict):
        return JsonResponse({"error": "invalid_payload"}, status=400)
    email = str(data.get("email") or "").strip().lower()
    company_name = str(data.get("company_name") or "").strip()
    if data.get("consent") is not True:
        return JsonResponse({"error": "consent_required"}, status=400)
    if len(email) > 254 or len(company_name) > 255:
        return JsonResponse({"error": "invalid_fields"}, status=400)
    try:
        validate_email(email)
    except ValidationError:
        return JsonResponse({"error": "invalid_email"}, status=400)

    # Shared cache recommended in production; prevents repeated invitations.
    from hashlib import sha256
    digest = sha256(email.encode()).hexdigest()
    throttle_key = f"vocalia:signup:{digest}"
    if not cache.add(throttle_key, "processing", timeout=60):
        return JsonResponse({"status": "already_requested"}, status=202)

    link = None
    try:
        with transaction.atomic():
            user = User.objects.filter(email__iexact=email).first()
            if user is None:
                try:
                    user = User.objects.create_user(email=email)
                except IntegrityError:
                    user = User.objects.get(email__iexact=email)
            if not user.is_active:
                return JsonResponse({"status": "request_received"}, status=202)
            raw, link = MagicLink.issue(user, minutes=30)
        url = request.build_absolute_uri(reverse("magic_link_verify", kwargs={"token": raw}))
        send_template_email(
            "magic_link", user.email,
            {"name": display_name(user), "email": user.email, "magic_url": url},
            request=request,
        )
    except Exception:
        logger.exception("VocalIA invitation could not be delivered")
        if link is not None:
            link.delete()
        cache.delete(throttle_key)
        return JsonResponse({"error": "email_delivery_failed"}, status=503)
    return JsonResponse({"status": "email_sent"}, status=202)

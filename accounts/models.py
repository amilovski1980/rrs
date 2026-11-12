import secrets
import hashlib
import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra):
        if not email:
            raise ValueError("Email requis")
        user = self.model(email=self.normalize_email(email), **extra)
        if password:
            user.set_password(password)
        else:
            # Compte historique ou invitation : pas de secret en clair, hash inutilisable.
            user.set_unusable_password()
        user.save()
        return user


class User(AbstractBaseUser, PermissionsMixin):
    """Compte identifié par email. Le mot de passe est haché par Django, jamais stocké en clair."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=20, blank=True)
    phone_verified = models.BooleanField(default=False)
    is_staff = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    def __str__(self):
        return self.email


class MagicLink(models.Model):
    """Lien de connexion signé côté serveur via hash, TTL court, usage unique."""

    purpose = models.CharField(
        max_length=20,
        choices=[("login", "connexion"), ("invite", "invitation")],
        default="login",
    )
    token_hash = models.CharField(max_length=64, unique=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="magic_links")
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    request_ip = models.GenericIPAddressField(null=True, blank=True)

    @classmethod
    def issue(cls, user, minutes=30, ip=None):
        raw = secrets.token_urlsafe(32)
        link = cls.objects.create(
            user=user,
            token_hash=hashlib.sha256(raw.encode()).hexdigest(),
            expires_at=timezone.now() + timezone.timedelta(minutes=minutes),
            request_ip=ip,
        )
        return raw, link

    @classmethod
    def verify(cls, raw_token):
        link = cls.objects.filter(
            token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
            used_at__isnull=True,
        ).first()
        if not link or link.expires_at < timezone.now():
            return None
        link.used_at = timezone.now()
        link.save(update_fields=["used_at"])
        return link.user


class PendingSignup(models.Model):
    """Inscription en attente de lien email (et, plus tard, de code SMS).

    ``payload`` ne contient que la fiche courte et les choix comptables,
    jamais la réponse brute de l'API.
    """

    email = models.EmailField()
    phone = models.CharField(max_length=20)
    siren = models.CharField(max_length=9)
    payload = models.JSONField(default=dict)
    token_hash = models.CharField(max_length=64, unique=True)
    phone_code_hash = models.CharField(max_length=64, blank=True)
    phone_verified = models.BooleanField(default=False)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @classmethod
    def issue(cls, *, email, phone, siren, payload, minutes=60):
        raw = secrets.token_urlsafe(32)
        code = f"{secrets.randbelow(1_000_000):06d}"
        pending = cls.objects.create(
            email=email,
            phone=phone,
            siren=siren,
            payload=payload,
            token_hash=hashlib.sha256(raw.encode()).hexdigest(),
            phone_code_hash=hashlib.sha256(code.encode()).hexdigest(),
            expires_at=timezone.now() + timezone.timedelta(minutes=minutes),
        )
        return raw, code, pending

    @classmethod
    def lookup(cls, raw_token):
        if not raw_token:
            return None
        pending = cls.objects.filter(
            token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
            consumed_at__isnull=True,
        ).first()
        if pending is None or pending.expires_at < timezone.now():
            return None
        return pending

    def check_phone_code(self, code: str) -> bool:
        if not code or not self.phone_code_hash:
            return False
        digest = hashlib.sha256(code.strip().encode()).hexdigest()
        return secrets.compare_digest(digest, self.phone_code_hash)

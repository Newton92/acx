# accounts/models.py
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.conf import settings
from tenancy.models import Tenant


class Role(models.Model):
    PERSONAL = 1
    WRITER = 2
    APPROVER = 3
    ADMIN = 4

    ROLE_CHOICES = (
        (PERSONAL, "Personnel entreprise"),
        (WRITER, "Personnel ACREMAC"),
        (APPROVER, "Administrateur entreprise"),
        (ADMIN, "Administrateur"),
    )

    id = models.PositiveSmallIntegerField(choices=ROLE_CHOICES, primary_key=True)

    def __str__(self):
        return self.get_id_display()


class User(AbstractUser):
    telephone = models.CharField(max_length=30, null=True, blank=True)
    departement = models.CharField(max_length=120, null=True, blank=True)
    email = models.EmailField(unique=True)
    # Si True : l'utilisateur doit changer son mot de passe à la prochaine connexion
    must_change_password = models.BooleanField(default=False)

    def __str__(self):
        full = (self.first_name + " " + self.last_name).strip()
        return full or self.username


class Membership(models.Model):
    class Status(models.TextChoices):
        INVITED = "invited", "Invité"
        ACTIVE = "active", "Actif"
        SUSPENDED = "suspended", "Suspendu"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")

    roles = models.ManyToManyField(Role, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)

    is_owner = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("tenant", "user")

    def __str__(self):
        return f"{self.user} @ {self.tenant}"



class DocumentTemplate(models.Model):
    CATEGORY_CHOICES = [
        ("amiable",   "Amiable"),
        ("juridique", "Juridique"),
        ("accord",    "Accord"),
        ("paiement",  "Paiement"),
        ("autre",     "Autre"),
    ]

    title       = models.CharField(max_length=220)
    description = models.TextField(blank=True)
    category    = models.CharField(max_length=30, choices=CATEGORY_CHOICES, default="autre")
    file        = models.FileField(upload_to="templates/documents/")
    created_by  = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="document_templates",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class AdminTenantMessage(models.Model):
    class SenderSide(models.TextChoices):
        ADMIN  = "admin",  "Super Admin"
        TENANT = "tenant", "Tenant"

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="platform_messages"
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="sent_platform_messages",
    )
    sender_side = models.CharField(max_length=10, choices=SenderSide.choices)
    content     = models.TextField(blank=True)
    file        = models.FileField(upload_to="platform_messages/", null=True, blank=True)
    is_read     = models.BooleanField(default=False)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"[{self.sender_side}] {self.tenant} — {self.created_at:%Y-%m-%d %H:%M}"


class AuditLog(models.Model):
    """
    Journal des actions d'administration (RBAC, tenants, users, etc.)
    """
    action = models.CharField(max_length=80)  # ex: MEMBERSHIP_CREATE, MEMBERSHIP_UPDATE, ...
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_actions",
    )
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )

    entity_type = models.CharField(max_length=80, blank=True, null=True)  # ex: "Membership"
    entity_id = models.PositiveIntegerField(blank=True, null=True)
    entity_label = models.CharField(max_length=255, blank=True, null=True)

    metadata = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return f"{self.action} by {self.actor} ({self.created_at})"






# ---------------------------------------------------------------------------
# Intégrations
# ---------------------------------------------------------------------------

import secrets
import hashlib


class SmsConfig(models.Model):
    """Configuration globale du provider SMS (singleton)."""

    class Provider(models.TextChoices):
        TWILIO = "twilio",  "Twilio"
        ORANGE = "orange",  "Orange API"
        MTN    = "mtn",     "MTN API"
        AWS    = "aws",     "AWS SNS"
        OTHER  = "other",   "Autre"

    provider   = models.CharField(max_length=20, choices=Provider.choices, default=Provider.OTHER)
    sender_id  = models.CharField(max_length=40, blank=True, default="")
    api_key    = models.CharField(max_length=255, blank=True, default="")
    api_secret = models.CharField(max_length=255, blank=True, default="")
    is_active  = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="sms_config_updates",
    )

    class Meta:
        verbose_name = "SMS Config"

    @classmethod
    def get_or_create_singleton(cls):
        obj = cls.objects.first()
        if not obj:
            obj = cls.objects.create()
        return obj


class TenantApiKey(models.Model):
    """Clé API générée pour un tenant afin d'accéder à l'API ACX programmatiquement."""

    tenant     = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="api_keys")
    label      = models.CharField(max_length=100)
    key_prefix = models.CharField(max_length=12)   # "acx_XXXXXXXX" affiché toujours
    key_hash   = models.CharField(max_length=64)   # SHA-256 de la clé complète
    is_active  = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="created_api_keys",
    )
    last_used_at = models.DateTimeField(null=True, blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    @classmethod
    def generate(cls, tenant, label, created_by=None):
        raw = f"acx_{secrets.token_urlsafe(32)}"
        h   = hashlib.sha256(raw.encode()).hexdigest()
        obj = cls.objects.create(
            tenant=tenant,
            label=label,
            key_prefix=raw[:12],
            key_hash=h,
            created_by=created_by,
        )
        return obj, raw  # raw affiché une seule fois

    def __str__(self):
        return f"{self.key_prefix}… ({self.tenant})"

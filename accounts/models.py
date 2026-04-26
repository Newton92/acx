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
    COUNTRY_MANAGER = 5

    ROLE_CHOICES = (
        (PERSONAL, "Personnel entreprise"),
        (WRITER, "Personnel ACREMAC"),
        (APPROVER, "Administrateur entreprise"),
        (ADMIN, "Administrateur"),
        (COUNTRY_MANAGER, "Responsable Pays"),
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


class PlatformSettings(models.Model):
    """Paramètres globaux de la plateforme (singleton)."""

    platform_name    = models.CharField(max_length=120, default="ACX Collections")
    default_currency = models.CharField(max_length=3, default="XAF")
    default_language = models.CharField(max_length=5, default="fr",
                                        choices=[("fr", "Français"), ("en", "English")])
    timezone         = models.CharField(max_length=60, default="Africa/Douala")
    support_email    = models.EmailField(blank=True, default="")
    updated_at       = models.DateTimeField(auto_now=True)
    updated_by       = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="platform_settings_updates",
    )

    class Meta:
        verbose_name = "Platform Settings"

    @classmethod
    def get_or_create_singleton(cls):
        obj = cls.objects.first()
        if not obj:
            obj = cls.objects.create()
        return obj


# ---------------------------------------------------------------------------
# Mail entrant — configuration IMAP + interception
# ---------------------------------------------------------------------------

class MailInboxConfig(models.Model):
    """Configuration IMAP d'un tenant pour recevoir les mails de ses clients."""

    tenant = models.OneToOneField(
        Tenant, on_delete=models.CASCADE, related_name="mail_inbox_config"
    )
    imap_host = models.CharField(max_length=255)
    imap_port = models.PositiveSmallIntegerField(default=993)
    imap_user = models.CharField(max_length=255)
    imap_password = models.CharField(max_length=500)
    use_ssl = models.BooleanField(default=True)
    mailbox = models.CharField(max_length=100, default="INBOX")
    is_active = models.BooleanField(default=True)
    last_polled_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"IMAP {self.imap_user} ({self.tenant})"


class MailSource(models.Model):
    """Expéditeur autorisé (client / domaine) pour le mail entrant d'un tenant."""

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="mail_sources"
    )
    client_name = models.CharField(max_length=255, blank=True)
    email_or_domain = models.CharField(max_length=255)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("tenant", "email_or_domain")]
        ordering = ["client_name", "email_or_domain"]

    def __str__(self):
        label = self.client_name or self.email_or_domain
        return f"{label} ({self.tenant})"

    @property
    def is_domain(self):
        return "@" not in self.email_or_domain


class IncomingMail(models.Model):
    """Mail intercepté via IMAP pour un tenant."""

    class Status(models.TextChoices):
        PENDING = "pending", "En attente"
        DISPATCHED = "dispatched", "Dispatché"
        PROCESSED = "processed", "Traité"
        REJECTED = "rejected", "Rejeté"

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="incoming_mails"
    )
    mail_source = models.ForeignKey(
        MailSource, on_delete=models.SET_NULL, null=True, blank=True, related_name="mails"
    )
    message_id = models.CharField(max_length=500, unique=True)
    from_email = models.EmailField()
    from_name = models.CharField(max_length=255, blank=True)
    subject = models.CharField(max_length=998, blank=True)
    body_text = models.TextField(blank=True)
    body_html = models.TextField(blank=True)
    received_at = models.DateTimeField()

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name="assigned_mails",
    )
    assigned_country = models.CharField(max_length=2, blank=True)
    dispatched_at = models.DateTimeField(null=True, blank=True)
    dispatched_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name="dispatched_mails",
    )
    dispatch_note = models.TextField(blank=True)
    case = models.ForeignKey(
        "cases.Case", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="incoming_mails",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-received_at"]

    def __str__(self):
        return f"[{self.status}] {self.from_email} — {self.subject[:60]}"


class MailAttachment(models.Model):
    """Pièce jointe d'un mail intercepté."""

    mail = models.ForeignKey(
        IncomingMail, on_delete=models.CASCADE, related_name="attachments"
    )
    filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=120, blank=True)
    size = models.PositiveIntegerField(default=0)
    file = models.FileField(upload_to="mail_attachments/")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.filename} ({self.mail_id})"

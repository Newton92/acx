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
    # Optionnel mais recommandé si tu veux login par email plus tard
    email = models.EmailField(unique=True)

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





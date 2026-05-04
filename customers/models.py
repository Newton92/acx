from django.conf import settings
from django.db import models
from tenancy.models import Tenant


class Customer(models.Model):
    """
    Customer = Client du tenant (l'entreprise qui confie des dossiers de recouvrement).
    Ce peut être un assureur-crédit, une banque, ou toute entreprise partenaire.
    Le client n'est pas nécessairement le créancier réel — voir le modèle Creditor.
    Portail client optionnel (portal_enabled).
    """
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="customers")

    name = models.CharField(max_length=200)
    code = models.CharField(max_length=60, blank=True, null=True)  # optionnel
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=40, blank=True, null=True)
    country = models.CharField(max_length=2, blank=True, null=True)  # ISO2
    city = models.CharField(max_length=120, blank=True, null=True)
    address = models.CharField(max_length=255, blank=True, null=True)

    status = models.CharField(max_length=20, default="active")  # MVP: active/suspended
    metadata = models.JSONField(blank=True, null=True)

    # ✅ AJOUTS (portail client)
    portal_enabled = models.BooleanField(default=False)

    # ✅ AJOUT (audit simple)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_customers",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]
        unique_together = ("tenant", "name")

    def __str__(self):
        return f"{self.name} ({self.tenant})"


class Creditor(models.Model):
    """
    Créancier : l'entité à qui la dette est réellement due par le débiteur.
    Peut être identique au Client (Customer) ou différent.

    Exemple : un assureur-crédit (Client) peut gérer des dossiers dont le créancier
    réel est l'entreprise assurée. Dans ce cas, Client ≠ Créancier.
    Si le champ `client` est renseigné, le créancier est rattaché à ce client.
    """

    class Type(models.TextChoices):
        COMPANY = "company", "Entreprise"
        INDIVIDUAL = "individual", "Particulier"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="creditors")

    name = models.CharField(max_length=200)
    code = models.CharField(max_length=60, blank=True, null=True)
    type = models.CharField(max_length=12, choices=Type.choices, default=Type.COMPANY)

    # Lien optionnel vers le client donneur d'ordre
    # (null = créancier autonome, sans client intermédiaire)
    client = models.ForeignKey(
        Customer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="creditors",
    )

    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=40, blank=True, null=True)
    country = models.CharField(max_length=2, blank=True, null=True)  # ISO2
    city = models.CharField(max_length=120, blank=True, null=True)
    address = models.CharField(max_length=255, blank=True, null=True)
    tax_id = models.CharField(max_length=80, blank=True, null=True)

    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True, default="")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_creditors",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "name"], name="uniq_creditor_tenant_name"),
        ]

    def __str__(self):
        return f"{self.name} ({self.tenant})"


class CustomerMembership(models.Model):
    """
    Lien User ↔ Customer (portail client)
    Permet au client de gérer ses propres utilisateurs, rôles et accès.
    """
    class Status(models.TextChoices):
        INVITED = "invited", "Invité"
        ACTIVE = "active", "Actif"
        SUSPENDED = "suspended", "Suspendu"

    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        MANAGER = "manager", "Manager"
        VIEWER = "viewer", "Viewer"

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="customer_memberships")

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.VIEWER)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)

    is_primary_contact = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("customer", "user")
        ordering = ["-id"]

    def __str__(self):
        return f"{self.user} @ {self.customer}"

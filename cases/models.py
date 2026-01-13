# cases/models.py

from django.conf import settings
from django.db import models
from django.utils import timezone

from customers.models import Customer
from tenancy.models import Tenant


class Portfolio(models.Model):
    """
    Portefeuille: regroupe des dossiers.
    Améliorations: gouvernance, priorisation, code, audit, archivage.
    """

    class Priority(models.TextChoices):
        LOW = "low", "Faible"
        MEDIUM = "medium", "Moyenne"
        HIGH = "high", "Élevée"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="portfolios")

    # Métier
    name = models.CharField(max_length=160)
    code = models.CharField(max_length=40, blank=True, null=True)  # ex: PF-001
    category = models.CharField(max_length=80, blank=True, null=True)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    default_currency = models.CharField(max_length=3, blank=True, null=True)  # ex: XAF

    description = models.TextField(blank=True, null=True)
    internal_notes = models.TextField(blank=True, null=True)

    # Gouvernance
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="owned_portfolios",
    )

    is_active = models.BooleanField(default=True)

    # Soft lifecycle
    archived_at = models.DateTimeField(blank=True, null=True)

    # Audit
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_portfolios",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_portfolios",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "name"], name="uniq_portfolio_tenant_name"),
            models.UniqueConstraint(fields=["tenant", "code"], name="uniq_portfolio_tenant_code"),
        ]
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.tenant})"

    def archive(self, actor=None):
        self.archived_at = timezone.now()
        self.is_active = False
        if actor:
            self.updated_by = actor
        self.save(update_fields=["archived_at", "is_active", "updated_by", "updated_at"])


class Debtor(models.Model):
    """
    Débiteur (personne/entreprise) associé à un dossier.
    """

    class Type(models.TextChoices):
        INDIVIDUAL = "individual", "Particulier"
        COMPANY = "company", "Entreprise"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="debtors")
    type = models.CharField(max_length=12, choices=Type.choices, default=Type.INDIVIDUAL)

    # identité
    full_name = models.CharField(max_length=200)
    national_id = models.CharField(max_length=80, blank=True, null=True)  # CNI/Passport/RCCM...
    tax_id = models.CharField(max_length=80, blank=True, null=True)

    # contacts
    phone = models.CharField(max_length=40, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    address = models.CharField(max_length=255, blank=True, null=True)
    city = models.CharField(max_length=120, blank=True, null=True)
    country = models.CharField(max_length=2, blank=True, null=True)  # ISO2

    metadata = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    CREATED_VIA_CHOICES = [
        ("tenant", "Tenant"),
        ("customer_portal", "Customer Portal"),
    ]

    created_via = models.CharField(
        max_length=30,
        choices=CREATED_VIA_CHOICES,
        default="tenant",
        db_index=True,
    )

    source_customer = models.ForeignKey(
        "customers.Customer",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="portal_debtors",
        db_index=True,
    )

    class Meta:
        ordering = ["full_name"]

    def __str__(self):
        return self.full_name


class Case(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Ouvert"
        IN_PROGRESS = "in_progress", "En cours"
        ON_HOLD = "on_hold", "En attente"
        CLOSED = "closed", "Clôturé"

    class Priority(models.TextChoices):
        LOW = "low", "Faible"
        MEDIUM = "medium", "Moyenne"
        HIGH = "high", "Élevée"
        URGENT = "urgent", "Urgente"

    # ✅ AJOUT: pour limiter les modifications côté client
    class CreatedSource(models.TextChoices):
        TENANT = "tenant", "Tenant"
        CUSTOMER = "customer", "Customer"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="cases")
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="cases_cus")

    portfolio = models.ForeignKey(Portfolio, on_delete=models.SET_NULL, null=True, blank=True, related_name="cases")
    debtor = models.ForeignKey(Debtor, on_delete=models.PROTECT, related_name="cases")

    reference = models.CharField(max_length=40)  # unique par tenant (ex: ACX-000012)
    title = models.CharField(max_length=220)

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)

    currency = models.CharField(max_length=3, blank=True, null=True)
    original_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    balance_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    due_date = models.DateField(blank=True, null=True)
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(blank=True, null=True)

    # ✅ Assigné côté TENANT (agent interne)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_cases",
    )

    # ✅ Assigné côté CLIENT (employé local)
    customer_assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="customer_assigned_cases",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_cases",
    )

    created_source = models.CharField(
        max_length=12,
        choices=CreatedSource.choices,
        default=CreatedSource.TENANT
    )

    metadata = models.JSONField(blank=True, null=True)

    class Meta:
        unique_together = ("tenant", "reference")
        ordering = ["-id"]

    def __str__(self):
        return f"{self.reference} - {self.title}"


class CaseNote(models.Model):
    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="notes")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return f"Note #{self.id} on {self.case}"


class CaseDocument(models.Model):
    class DocType(models.TextChoices):
        CONTRACT = "contract", "Contrat"
        INVOICE = "invoice", "Facture"
        LETTER = "letter", "Courrier"
        ID = "id", "Pièce d'identité"
        OTHER = "other", "Autre"

    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="cases")
    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="documents")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    title = models.CharField(max_length=220)
    doc_type = models.CharField(max_length=20, choices=DocType.choices, default=DocType.OTHER)

    file = models.FileField(upload_to="cases/documents/")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return f"{self.title} ({self.case.reference})"


class CaseMessage(models.Model):
    """
    Messages partagés Client <-> Tenant autour d'un Case.
    """
    class Visibility(models.TextChoices):
        SHARED = "shared", "Shared (Client & Tenant)"
        INTERNAL = "internal", "Internal (Tenant only)"  # non visible côté client portal

    case = models.ForeignKey("cases.Case", on_delete=models.CASCADE, related_name="messages")
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="case_messages")

    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    author_side = models.CharField(max_length=12, choices=[("customer", "Customer"), ("tenant", "Tenant")], db_index=True)

    body = models.TextField()

    visibility = models.CharField(max_length=12, choices=Visibility.choices, default=Visibility.SHARED, db_index=True)

    # utiles pour Inbox / tri
    action_required = models.BooleanField(default=False, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]
        indexes = [
            models.Index(fields=["customer", "-id"]),
            models.Index(fields=["case", "-id"]),
            models.Index(fields=["visibility", "-id"]),
        ]

    def __str__(self):
        return f"Msg#{self.id} case={self.case_id} side={self.author_side}"


class CaseMessageAttachment(models.Model):
    message = models.ForeignKey(CaseMessage, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to="cases/messages/")
    filename = models.CharField(max_length=255, blank=True, null=True)
    content_type = models.CharField(max_length=120, blank=True, null=True)
    size = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return self.filename or f"Attachment#{self.id}"


class CaseMessageRead(models.Model):
    """
    Tracking "lu" pour un utilisateur donné.
    """
    message = models.ForeignKey(CaseMessage, on_delete=models.CASCADE, related_name="reads")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("message", "user")
        indexes = [
            models.Index(fields=["user", "-read_at"]),
            models.Index(fields=["message", "user"]),
        ]

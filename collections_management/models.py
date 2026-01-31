# collections_management/models.py

from decimal import Decimal

from django.apps import apps
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
from rest_framework.exceptions import ValidationError


def get_model_ref(setting_name: str, default: str) -> str:
    return getattr(settings, setting_name, default)


TENANT_MODEL = get_model_ref("ACX_TENANT_MODEL", "tenancy.Tenant")
PORTFOLIO_MODEL = get_model_ref("ACX_PORTFOLIO_MODEL", "portfolios.Portfolio")
DEBTOR_MODEL = get_model_ref("ACX_DEBTOR_MODEL", "debtors.Debtor")


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class CollectionCaseStatus(models.TextChoices):
    NEW = "new", "New"
    IN_REVIEW = "in_review", "In review"
    PREVENTIVE = "preventive", "Preventive"
    AMICABLE = "amicable", "Amicable"
    PRE_LEGAL = "pre_legal", "Pre-legal"
    LEGAL = "legal", "Legal"
    DISPUTED = "disputed", "Disputed"
    SETTLED = "settled", "Settled"
    CLOSED = "closed", "Closed"
    WRITE_OFF = "write_off", "Write-off"


class CollectionPriority(models.TextChoices):
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"


class CollectionActionType(models.TextChoices):
    CALL = "call", "Call"
    SMS = "sms", "SMS"
    EMAIL = "email", "Email"
    VISIT = "visit", "Visit"
    LETTER = "letter", "Letter"
    NEGOTIATION = "negotiation", "Negotiation"
    NOTICE = "notice", "Formal notice"
    LAWYER = "lawyer", "Transfer to lawyer"
    OTHER = "other", "Other"


class CollectionActionOutcome(models.TextChoices):
    REACHED = "reached", "Reached"
    NOT_REACHED = "not_reached", "Not reached"
    PROMISE = "promise", "Payment promise"
    REFUSED = "refused", "Refused"
    WRONG_NUMBER = "wrong_number", "Wrong number"
    RESCHEDULED = "rescheduled", "Rescheduled"
    PARTIAL_PAYMENT = "partial_payment", "Partial payment"
    FULL_PAYMENT = "full_payment", "Full payment"
    DISPUTE = "dispute", "Dispute"
    OTHER = "other", "Other"


class CollectionCase(TimeStampedModel):
    """
    Dossier de recouvrement (unité centrale).
    """
    tenant = models.ForeignKey(TENANT_MODEL, on_delete=models.CASCADE, related_name="collection_cases")
    reference = models.CharField(max_length=32, db_index=True)  # ex: COL-2026-000123

    portfolio = models.ForeignKey(
        PORTFOLIO_MODEL,
        on_delete=models.PROTECT,
        related_name="collection_cases",
        null=True,
        blank=True
    )
    debtor = models.ForeignKey(
        DEBTOR_MODEL,
        on_delete=models.PROTECT,
        related_name="collection_cases",
        null=True,
        blank=True
    )

    status = models.CharField(
        max_length=20,
        choices=CollectionCaseStatus.choices,
        default=CollectionCaseStatus.NEW,
        db_index=True
    )
    priority = models.CharField(
        max_length=10,
        choices=CollectionPriority.choices,
        default=CollectionPriority.MEDIUM,
        db_index=True
    )

    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_collection_cases",
    )

    # Montants
    principal_amount = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(0)]
    )
    interest_amount = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(0)]
    )
    penalty_amount = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(0)]
    )
    fees_amount = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(0)]
    )
    total_paid_amount = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(0)]
    )

    due_date = models.DateField(null=True, blank=True, db_index=True)

    next_action_type = models.CharField(max_length=20, choices=CollectionActionType.choices, null=True, blank=True)
    next_action_date = models.DateField(null=True, blank=True, db_index=True)

    notes = models.TextField(blank=True, default="")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_collection_cases",
    )

    class Meta:
        unique_together = (("tenant", "reference"),)
        indexes = [
            models.Index(fields=["tenant", "status", "priority"]),
            models.Index(fields=["tenant", "next_action_date"]),
        ]

    @property
    def total_due(self) -> Decimal:
        return self.principal_amount + self.interest_amount + self.penalty_amount + self.fees_amount

    @property
    def balance(self) -> Decimal:
        return self.total_due - self.total_paid_amount

    @property
    def is_overdue(self) -> bool:
        if not self.next_action_date:
            return False
        return self.next_action_date < timezone.localdate()

    def __str__(self) -> str:
        return f"{self.reference} ({self.status})"


class CollectionAction(TimeStampedModel):
    tenant = models.ForeignKey(TENANT_MODEL, on_delete=models.CASCADE, related_name="collection_actions")
    case = models.ForeignKey(CollectionCase, on_delete=models.CASCADE, related_name="actions")

    action_type = models.CharField(max_length=20, choices=CollectionActionType.choices, db_index=True)
    outcome = models.CharField(max_length=20, choices=CollectionActionOutcome.choices, null=True, blank=True, db_index=True)

    summary = models.CharField(max_length=240, blank=True, default="")
    details = models.TextField(blank=True, default="")

    action_date = models.DateTimeField(default=timezone.now, db_index=True)

    # Prochaine action proposée par l’agent
    next_action_type = models.CharField(max_length=20, choices=CollectionActionType.choices, null=True, blank=True)
    next_action_date = models.DateField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_collection_actions",
    )

    class Meta:
        indexes = [
            models.Index(fields=["tenant", "case", "action_date"]),
            models.Index(fields=["tenant", "action_type"]),
        ]

    def __str__(self) -> str:
        return f"{self.case.reference} - {self.action_type}"


class PaymentPromise(TimeStampedModel):
    tenant = models.ForeignKey(TENANT_MODEL, on_delete=models.CASCADE, related_name="payment_promises")
    case = models.ForeignKey(CollectionCase, on_delete=models.CASCADE, related_name="promises")

    amount = models.DecimalField(max_digits=18, decimal_places=2, validators=[MinValueValidator(0)])
    promised_date = models.DateField(db_index=True)

    status = models.CharField(
        max_length=20,
        choices=[
            ("pending", "Pending"),
            ("kept", "Kept"),
            ("broken", "Broken"),
            ("cancelled", "Cancelled"),
        ],
        default="pending",
        db_index=True,
    )
    notes = models.TextField(blank=True, default="")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_payment_promises",
    )

    class Meta:
        indexes = [models.Index(fields=["tenant", "status", "promised_date"])]


class Payment(TimeStampedModel):
    tenant = models.ForeignKey(TENANT_MODEL, on_delete=models.CASCADE, related_name="payments")
    case = models.ForeignKey(CollectionCase, on_delete=models.CASCADE, related_name="payments")

    amount = models.DecimalField(max_digits=18, decimal_places=2, validators=[MinValueValidator(0)])
    paid_at = models.DateTimeField(default=timezone.now, db_index=True)

    method = models.CharField(
        max_length=30,
        choices=[
            ("cash", "Cash"),
            ("bank_transfer", "Bank transfer"),
            ("mobile_money", "Mobile money"),
            ("cheque", "Cheque"),
            ("card", "Card"),
            ("other", "Other"),
        ],
        default="other",
    )
    reference = models.CharField(max_length=64, blank=True, default="")
    notes = models.TextField(blank=True, default="")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_payments",
    )

    class Meta:
        indexes = [
            models.Index(fields=["tenant", "paid_at"]),
            models.Index(fields=["tenant", "method"]),
        ]


# -------------------------------------------------------------------
# ✅ Tenant resolver ACX (ROBUSTE) - remplace l'import fragile accounts.models
# -------------------------------------------------------------------

def get_active_tenant(request):
    # 1) si tu as déjà un middleware qui injecte request.tenant
    tenant = getattr(request, "tenant", None)
    if tenant:
        return tenant

    # 2) sinon, on récupère via la membership active
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return None

    # 3) resolve Membership sans import en dur (accounts ou tenancy)
    Membership = None
    for app_label in ("accounts", "tenancy"):
        try:
            Membership = apps.get_model(app_label, "Membership")
            if Membership:
                break
        except Exception:
            continue

    if not Membership:
        return None

    try:
        m = (
            Membership.objects
            .select_related("tenant")
            .filter(user=user, status="active")
            .order_by("-id")
            .first()
        )
        return m.tenant if m else None
    except Exception:
        return None


class TenantScopedViewSetMixin:
    """
    Force le scope tenant pour list/retrieve + impose tenant pour create.
    """
    def get_tenant(self):
        tenant = get_active_tenant(self.request)
        if not tenant:
            raise ValidationError({"tenant": "Tenant context missing for this request."})
        return tenant

    def get_queryset(self):
        qs = super().get_queryset()
        try:
            return qs.filter(tenant=self.get_tenant())
        except Exception:
            return qs

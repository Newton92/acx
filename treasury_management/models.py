
#treasury_management/models.py
from __future__ import annotations

from decimal import Decimal
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class TreasuryAccount(models.Model):
    """
    Compte de trésorerie minimaliste (banque / caisse / mobile money) par tenant.
    Sert à journaliser les entrées/sorties réelles qui transitent par ACX.

    ⚠️ Ce n'est pas un plan comptable complet : uniquement trésorerie (entrées/sorties),
    aligné sur une approche iMX "transactionnel / dossier".
    """

    class Type(models.TextChoices):
        BANK = "bank", "Banque"
        CASH = "cash", "Caisse"
        MOBILE_MONEY = "mobile_money", "Mobile Money"
        OTHER = "other", "Autre"

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="treasury_accounts")

    name = models.CharField(max_length=120)
    type = models.CharField(max_length=20, choices=Type.choices, default=Type.BANK)
    currency = models.CharField(max_length=3, default="XAF")
    is_default = models.BooleanField(default=False)

    # Optionnel (banque, IBAN, opérateur, etc.)
    metadata = models.JSONField(blank=True, null=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_treasury_accounts"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_default", "name"]
        constraints = [
            # Un seul compte par défaut par (tenant, devise)
            models.UniqueConstraint(
                fields=["tenant", "currency"],
                condition=Q(is_default=True),
                name="uniq_default_treasury_account_per_currency",
            )
        ]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Assure l'unicité du default (confort métier)
        if self.is_default:
            TreasuryAccount.objects.filter(tenant=self.tenant, currency=self.currency, is_default=True).exclude(pk=self.pk).update(
                is_default=False
            )

    def __str__(self) -> str:
        return f"{self.name} ({self.tenant})"


class TreasuryMovement(models.Model):
    """
    Journal minimaliste des entrées/sorties.
    - IN  : encaissement (argent entre sur un compte ACX)
    - OUT : décaissement (reversement client, remboursement, sortie)

    Source:
    - payment: entrée liée à un Payment recouvrement
    - remittance: sortie liée à une remise client
    - manual: ajustement manuel
    """

    class Direction(models.TextChoices):
        IN = "in", "Entrée"
        OUT = "out", "Sortie"

    class Status(models.TextChoices):
        PENDING = "pending", "En attente"
        CONFIRMED = "confirmed", "Confirmé"
        CANCELLED = "cancelled", "Annulé"

    class Source(models.TextChoices):
        PAYMENT = "payment", "Paiement"
        REMITTANCE = "remittance", "Reversement client"
        MANUAL = "manual", "Manuel"
        OTHER = "other", "Autre"

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="treasury_movements")

    account = models.ForeignKey(TreasuryAccount, on_delete=models.PROTECT, related_name="movements")
    direction = models.CharField(max_length=10, choices=Direction.choices)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.CONFIRMED)

    amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    currency = models.CharField(max_length=3, default="XAF")

    value_date = models.DateTimeField(default=timezone.now)

    label = models.CharField(max_length=255, blank=True, default="")
    reference = models.CharField(max_length=120, blank=True, default="")

    # Dimensions (facultatives mais utiles)
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, null=True, blank=True, related_name="treasury_movements")
    case = models.ForeignKey("collections_management.CollectionCase", on_delete=models.PROTECT, null=True, blank=True, related_name="treasury_movements")
    payment = models.ForeignKey("collections_management.Payment", on_delete=models.PROTECT, null=True, blank=True, related_name="treasury_movements")
    remittance = models.ForeignKey("treasury_management.RemittanceBatch", on_delete=models.PROTECT, null=True, blank=True, related_name="treasury_movements")

    source = models.CharField(max_length=20, choices=Source.choices, default=Source.MANUAL)

    # Idempotence (évite doublons si la même opération est rejouée)
    source_key = models.CharField(max_length=120, blank=True, null=True)

    notes = models.TextField(blank=True, default="")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_treasury_movements"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-value_date", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "source_key"], condition=Q(source_key__isnull=False), name="uniq_treasury_source_key"),
        ]

    def __str__(self) -> str:
        return f"{self.tenant} {self.direction} {self.amount} {self.currency} ({self.account})"


class RemittanceBatch(models.Model):
    """
    Reversement client (remise) : décaissement vers un Customer.
    Minimaliste mais pro :
    - statut (draft/validated/paid/cancelled)
    - total
    - référence de paiement / virement
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Brouillon"
        VALIDATED = "validated", "Validé"
        PAID = "paid", "Payé"
        CANCELLED = "cancelled", "Annulé"

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="remittances")
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="remittances")

    account = models.ForeignKey(TreasuryAccount, on_delete=models.PROTECT, related_name="remittances")

    currency = models.CharField(max_length=3, default="XAF")
    amount_total = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    reference = models.CharField(max_length=120, blank=True, default="")
    notes = models.TextField(blank=True, default="")

    paid_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_remittances"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self) -> str:
        return f"Remittance {self.id} {self.customer} {self.amount_total} {self.currency}"


class RemittanceLine(models.Model):
    """
    Ligne de remise (optionnelle mais utile) : rattache la remise aux paiements.
    Permet d'éviter de "reverser deux fois" le même paiement.
    """

    remittance = models.ForeignKey(RemittanceBatch, on_delete=models.CASCADE, related_name="lines")
    payment = models.ForeignKey("collections_management.Payment", on_delete=models.PROTECT, related_name="remittance_lines")
    case = models.ForeignKey("collections_management.CollectionCase", on_delete=models.PROTECT, null=True, blank=True, related_name="remittance_lines")

    amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    notes = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["remittance", "payment"], name="uniq_remittance_payment"),
        ]

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from django.db import transaction
from django.utils import timezone

from .models import TreasuryAccount, TreasuryMovement, RemittanceBatch, RemittanceLine


def get_default_account(*, tenant, currency: str = "XAF") -> TreasuryAccount | None:
    return (
        TreasuryAccount.objects.filter(tenant=tenant, currency=currency, is_default=True)
        .order_by("-id")
        .first()
    )


@transaction.atomic
def record_payment_inflow(
    *,
    tenant,
    payment,
    treasury_account: TreasuryAccount | None = None,
    confirmed: bool = True,
) -> TreasuryMovement | None:
    """
    Crée un mouvement IN si l'argent transite réellement par ACX.

    ⚠️ Le paiement "direct client" ne doit PAS créer un mouvement de trésorerie.
    On s'appuie sur payment.received_by si le champ existe.
    Si le champ n'existe pas encore: on suppose ACX (inflow) seulement si treasury_account est fourni.
    """
    received_by = getattr(payment, "received_by", None)
    currency = (
        getattr(payment, "currency", None)
        or getattr(getattr(payment, "case", None), "currency", None)
        or "XAF"
    )

    # Si on a le champ, on respecte la règle métier
    if received_by in ("customer_direct", "client", "customer"):
        return None

    # Sinon, si on n'a pas de treasury_account -> on ne crée rien (pas de devinette)
    if treasury_account is None:
        treasury_account = getattr(payment, "treasury_account", None) or get_default_account(
            tenant=tenant, currency=currency
        )

    if treasury_account is None:
        # Pas de compte => pas de mouvement (on laisse le paiement exister, mais pas de journal trésorerie)
        return None

    # Dimensions
    case = getattr(payment, "case", None)

    # Client du tenant (Customer / créancier).
    # Dans ACX, CollectionCase.debtor → customers.Customer (ACX_DEBTOR_MODEL).
    # CollectionCase n'a pas de champ "customer", on lit donc "debtor".
    customer = (
        getattr(payment, "customer", None)
        or getattr(case, "customer", None)   # si le modèle évolue
        or getattr(case, "debtor", None)     # chemin ACX actuel
    )

    portfolio = getattr(case, "portfolio", None) if case else None
    if customer is None and portfolio is not None:
        customer = getattr(portfolio, "customer", None)

    amount = getattr(payment, "amount", None) or Decimal("0.00")
    paid_at = getattr(payment, "paid_at", None) or timezone.now()

    source_key = f"payment:{payment.id}"

    mv, created = TreasuryMovement.objects.get_or_create(
        tenant=tenant,
        source_key=source_key,
        defaults={
            "account": treasury_account,
            "direction": TreasuryMovement.Direction.IN,
            "status": TreasuryMovement.Status.CONFIRMED if confirmed else TreasuryMovement.Status.PENDING,
            "amount": amount,
            "currency": currency,
            "value_date": paid_at,
            "label": "Encaissement (paiement)",
            "reference": getattr(payment, "reference", "") or "",
            "customer": customer,
            "case": case,
            "payment": payment,
            "source": TreasuryMovement.Source.PAYMENT,
            "notes": getattr(payment, "notes", "") or "",
            "created_by": getattr(payment, "created_by", None),
        },
    )
    if not created:
        # Mise à jour minimale si ré-exécuté (idempotent)
        updates: list[str] = []
        if mv.amount != amount:
            mv.amount = amount
            updates.append("amount")
        if mv.value_date != paid_at:
            mv.value_date = paid_at
            updates.append("value_date")
        if mv.customer_id != getattr(customer, "id", None):
            mv.customer = customer
            updates.append("customer")
        if mv.case_id != getattr(case, "id", None):
            mv.case = case
            updates.append("case")
        if updates:
            mv.save(update_fields=updates)
    return mv


@transaction.atomic
def create_manual_movement(
    *,
    tenant,
    account: TreasuryAccount,
    direction: str,
    amount: Decimal,
    currency: str | None = None,
    value_date=None,
    label: str = "",
    reference: str = "",
    customer=None,
    case=None,
    status: str = TreasuryMovement.Status.CONFIRMED,
    notes: str = "",
    created_by=None,
    source_key: str | None = None,
) -> TreasuryMovement:
    """
    Crée un mouvement manuel (IN/OUT).

    - Si source_key est fourni : idempotent (get_or_create).
    - Sinon : création simple.
    """
    value_date = value_date or timezone.now()
    currency = currency or getattr(account, "currency", None) or "XAF"

    defaults = {
        "account": account,
        "direction": direction,
        "status": status,
        "amount": amount,
        "currency": currency,
        "value_date": value_date,
        "label": label or ("Entrée manuelle" if direction == TreasuryMovement.Direction.IN else "Sortie manuelle"),
        "reference": reference or "",
        "customer": customer,
        "case": case,
        "payment": None,
        "remittance": None,
        "source": TreasuryMovement.Source.MANUAL,
        "notes": notes or "",
        "created_by": created_by,
    }

    if source_key:
        mv, created = TreasuryMovement.objects.get_or_create(
            tenant=tenant,
            source_key=source_key,
            defaults=defaults,
        )
        if not created:
            # sync minimal
            updates: list[str] = []
            for f in ("account", "direction", "status", "amount", "currency", "value_date", "label", "reference", "customer", "case", "notes"):
                if getattr(mv, f) != defaults[f]:
                    setattr(mv, f, defaults[f])
                    updates.append(f)
            if updates:
                mv.save(update_fields=updates)
        return mv

    return TreasuryMovement.objects.create(tenant=tenant, source_key=None, **defaults)


@transaction.atomic
def create_transfer(
    *,
    tenant,
    from_account: TreasuryAccount,
    to_account: TreasuryAccount,
    amount: Decimal,
    currency: str | None = None,
    value_date=None,
    reference: str = "",
    notes: str = "",
    created_by=None,
    transfer_key: str | None = None,
) -> tuple[TreasuryMovement, TreasuryMovement, str]:
    """
    Transfert interne : génère 2 mouvements idempotents :
    - OUT sur from_account
    - IN sur to_account

    La clé de transfert est utilisée pour créer deux source_key distincts:
    - transfer:{key}:out
    - transfer:{key}:in
    """
    if transfer_key is None:
        transfer_key = uuid4().hex

    value_date = value_date or timezone.now()

    currency = currency or getattr(from_account, "currency", None) or "XAF"

    out_key = f"transfer:{transfer_key}:out"
    in_key = f"transfer:{transfer_key}:in"

    out_mv, _ = TreasuryMovement.objects.get_or_create(
        tenant=tenant,
        source_key=out_key,
        defaults={
            "account": from_account,
            "direction": TreasuryMovement.Direction.OUT,
            "status": TreasuryMovement.Status.CONFIRMED,
            "amount": amount,
            "currency": currency,
            "value_date": value_date,
            "label": f"Transfert vers {to_account.name}",
            "reference": reference or "",
            "customer": None,
            "case": None,
            "payment": None,
            "remittance": None,
            "source": getattr(TreasuryMovement.Source, "TRANSFER", TreasuryMovement.Source.OTHER),
            "notes": notes or "",
            "created_by": created_by,
        },
    )

    in_mv, _ = TreasuryMovement.objects.get_or_create(
        tenant=tenant,
        source_key=in_key,
        defaults={
            "account": to_account,
            "direction": TreasuryMovement.Direction.IN,
            "status": TreasuryMovement.Status.CONFIRMED,
            "amount": amount,
            "currency": currency,
            "value_date": value_date,
            "label": f"Transfert depuis {from_account.name}",
            "reference": reference or "",
            "customer": None,
            "case": None,
            "payment": None,
            "remittance": None,
            "source": getattr(TreasuryMovement.Source, "TRANSFER", TreasuryMovement.Source.OTHER),
            "notes": notes or "",
            "created_by": created_by,
        },
    )

    return out_mv, in_mv, transfer_key


@transaction.atomic
def create_remittance_draft(
    *, tenant, customer, account: TreasuryAccount, currency: str = "XAF", created_by=None, notes: str = ""
) -> RemittanceBatch:
    return RemittanceBatch.objects.create(
        tenant=tenant,
        customer=customer,
        account=account,
        currency=currency,
        status=RemittanceBatch.Status.DRAFT,
        notes=notes or "",
        created_by=created_by,
    )


@transaction.atomic
def add_payment_to_remittance(
    *, remittance: RemittanceBatch, payment, amount: Decimal | None = None, notes: str = ""
) -> RemittanceLine:
    case = getattr(payment, "case", None)
    if amount is None:
        amount = getattr(payment, "amount", None) or Decimal("0.00")

    line, _ = RemittanceLine.objects.get_or_create(
        remittance=remittance,
        payment=payment,
        defaults={
            "case": case,
            "amount": amount,
            "notes": notes or "",
        },
    )
    # recalcul total
    remittance.amount_total = sum((l.amount for l in remittance.lines.all()), Decimal("0.00"))
    remittance.save(update_fields=["amount_total", "updated_at"])
    return line


@transaction.atomic
def mark_remittance_paid(
    *, remittance: RemittanceBatch, reference: str = "", paid_at=None, created_by=None
) -> TreasuryMovement:
    """
    Marque une remise payée et génère le mouvement OUT.
    """
    if remittance.status == RemittanceBatch.Status.PAID:
        # déjà payée : mouvement déjà généré via source_key
        mv = TreasuryMovement.objects.filter(
            tenant=remittance.tenant, source_key=f"remittance:{remittance.id}"
        ).first()
        return mv

    remittance.status = RemittanceBatch.Status.PAID
    remittance.reference = reference or remittance.reference
    remittance.paid_at = paid_at or timezone.now()
    remittance.save(update_fields=["status", "reference", "paid_at", "updated_at"])

    source_key = f"remittance:{remittance.id}"

    mv, _ = TreasuryMovement.objects.get_or_create(
        tenant=remittance.tenant,
        source_key=source_key,
        defaults={
            "account": remittance.account,
            "direction": TreasuryMovement.Direction.OUT,
            "status": TreasuryMovement.Status.CONFIRMED,
            "amount": remittance.amount_total,
            "currency": remittance.currency,
            "value_date": remittance.paid_at,
            "label": "Reversement client",
            "reference": remittance.reference or "",
            "customer": remittance.customer,
            "case": None,
            "payment": None,
            "remittance": remittance,
            "source": TreasuryMovement.Source.REMITTANCE,
            "notes": remittance.notes or "",
            "created_by": created_by,
        },
    )
    return mv

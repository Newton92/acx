from decimal import Decimal
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import CollectionCase, Payment, CollectionAction


@transaction.atomic
def apply_payment_to_case(payment: Payment) -> None:
    case: CollectionCase = payment.case
    case.total_paid_amount = (case.total_paid_amount or Decimal("0.00")) + payment.amount

    if case.balance <= Decimal("0.00"):
        case.status = "settled"
        case.next_action_date = None
        case.next_action_type = None

    case.save(update_fields=["total_paid_amount", "status", "next_action_date", "next_action_type", "updated_at"])


@transaction.atomic
def apply_action_to_case(action: CollectionAction) -> None:
    case: CollectionCase = action.case

    if action.next_action_date:
        case.next_action_date = action.next_action_date
        case.next_action_type = action.next_action_type

    if action.outcome == "dispute":
        case.status = "disputed"

    case.save(update_fields=["next_action_date", "next_action_type", "status", "updated_at"])


def recompute_case_balances(collection_case):
    # principal + interest + penalty + fees - paid
    totals = collection_case.payments.aggregate(
        paid=Sum("amount")
    )
    paid = totals["paid"] or 0

    principal = collection_case.principal_amount or 0
    interest = collection_case.interest_amount or 0
    penalty = collection_case.penalty_amount or 0
    fees = collection_case.fees_amount or 0

    total_due = principal + interest + penalty + fees
    balance = total_due - paid
    if balance < 0:
        balance = 0

    collection_case.paid_amount = paid
    collection_case.balance_amount = balance
    collection_case.last_activity_at = timezone.now()
    collection_case.save(update_fields=["paid_amount", "balance_amount", "last_activity_at"])
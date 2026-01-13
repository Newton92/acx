from decimal import Decimal
from django.db import transaction
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

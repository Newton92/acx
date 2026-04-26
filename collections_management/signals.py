from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Payment, CollectionAction
from .services import apply_payment_to_case, apply_action_to_case


@receiver(post_save, sender=Payment)
def on_payment_saved(sender, instance: Payment, created: bool, **kwargs):
    if created:
        apply_payment_to_case(instance)


@receiver(post_save, sender=CollectionAction)
def on_action_saved(sender, instance: CollectionAction, created: bool, **kwargs):
    if created:
        apply_action_to_case(instance)
        _notify_country_managers(instance)


def _notify_country_managers(action: CollectionAction) -> None:
    """Notifie le responsable pays et le owner quand un agent pose une action."""
    try:
        from cases.models import Case
        from accounts.utils_notifications import notify_country_action

        core_case = (
            Case.objects
            .filter(tenant_id=action.tenant_id, reference=action.case.reference)
            .select_related("debtor")
            .first()
        )
        if not core_case or not core_case.debtor or not core_case.debtor.country:
            return

        action_labels = {
            "call": "Appel téléphonique",
            "sms": "SMS",
            "email": "Email",
            "visit": "Visite terrain",
            "letter": "Courrier",
            "negotiation": "Négociation",
            "notice": "Mise en demeure",
            "lawyer": "Transfert avocat",
            "other": "Autre",
        }

        notify_country_action(
            tenant=action.tenant,
            country_code=core_case.debtor.country,
            actor=action.created_by,
            action_type_label=action_labels.get(action.action_type, action.action_type),
            case_ref=action.case.reference,
            debtor_name=core_case.debtor.full_name,
        )
    except Exception:
        pass

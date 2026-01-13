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

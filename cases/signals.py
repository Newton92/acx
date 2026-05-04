# cases/signals.py
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver

from cases.models import Case
from cases.email_notifications import TRACKED_FIELDS, send_case_change_notifications


@receiver(pre_save, sender=Case)
def case_pre_save(sender, instance, **kwargs):
    """Capture les champs modifiés avant la sauvegarde."""
    if not instance.pk:
        return
    try:
        old = Case.objects.get(pk=instance.pk)
    except Case.DoesNotExist:
        return

    changes = {}
    for field in TRACKED_FIELDS:
        old_val = getattr(old, field, None)
        new_val = getattr(instance, field, None)
        if old_val != new_val:
            changes[field] = {"old": old_val, "new": new_val}

    instance._pending_changes = changes


@receiver(post_save, sender=Case)
def case_post_save(sender, instance, created, **kwargs):
    """Après sauvegarde : envoie les notifications si des champs ont changé."""
    if created:
        return

    changes = getattr(instance, "_pending_changes", {})
    if not changes:
        return

    actor = getattr(instance, "_updated_by", None)
    if actor:
        actor_name = getattr(actor, "get_full_name", lambda: "")() or getattr(actor, "username", str(actor))
    else:
        actor_name = "Un agent"

    send_case_change_notifications(instance.pk, changes, actor_name)

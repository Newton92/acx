# accounts/utils_notifications.py
from django.conf import settings
from django.core.mail import send_mail


def notify_country_action(tenant, country_code: str, actor, action_type_label: str,
                           case_ref: str, debtor_name: str) -> None:
    """
    Notifie le responsable pays + le owner du tenant quand un agent pose une action
    sur un dossier appartenant au périmètre de ce pays.
    """
    from .models import TenantCountry, Membership

    try:
        tc = TenantCountry.objects.select_related("manager").get(
            tenant=tenant, country_code=country_code.upper()
        )
    except TenantCountry.DoesNotExist:
        return

    actor_name = str(actor) if actor else "Un agent"
    subject = f"[ACX] Action agent — {tc.country_name} — Dossier {case_ref}"
    body = (
        f"L'agent {actor_name} a effectué une action sur le dossier {case_ref}.\n\n"
        f"Débiteur  : {debtor_name}\n"
        f"Pays      : {tc.country_name} ({country_code.upper()})\n"
        f"Action    : {action_type_label}\n\n"
        f"Connectez-vous à ACX Collections pour consulter le détail.\n\n"
        f"---\nACX Collections — notification automatique"
    )

    recipients: set[str] = set()

    if tc.manager and tc.manager != actor and tc.manager.email:
        recipients.add(tc.manager.email)

    owner = Membership.objects.filter(
        tenant=tenant, is_owner=True
    ).select_related("user").first()
    if owner and owner.user != actor and owner.user.email:
        recipients.add(owner.user.email)

    if recipients:
        send_mail(
            subject, body,
            getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@acx.app"),
            list(recipients),
            fail_silently=True,
        )

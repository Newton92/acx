#accounts/tenant_context.py

from accounts.models import Membership


def get_active_tenant_for_user(user):
    """
    Retourne le tenant actif (via Membership ACTIVE), priorité owner.
    """
    qs = (
        Membership.objects.filter(user=user, status=Membership.Status.ACTIVE)
        .select_related("tenant")
    )
    m = qs.filter(is_owner=True).first() or qs.first()
    return m.tenant if m else None

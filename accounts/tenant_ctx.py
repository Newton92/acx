# accounts/tenant_ctx.py
from accounts.models import Membership, Role

def get_active_membership(user):
    # ✅ protège contre AnonymousUser
    if not user or not getattr(user, "is_authenticated", False):
        return None

    qs = (
        Membership.objects.filter(user=user, status=Membership.Status.ACTIVE)
        .select_related("tenant")
        .prefetch_related("roles")
    )

    # priorité owner
    m = qs.filter(is_owner=True).first() or qs.first()
    return m

def get_active_tenant(user):
    m = get_active_membership(user)
    return m.tenant if m and m.tenant else None

def role_ids(membership):
    if not membership:
        return set()
    return set(membership.roles.values_list("id", flat=True))

def is_tenant_admin(membership):
    if not membership:
        return False
    if membership.is_owner:
        return True
    ids = role_ids(membership)
    return (Role.ADMIN in ids) or (Role.APPROVER in ids)

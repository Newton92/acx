# accounts/permissions.py
from rest_framework.permissions import BasePermission
from accounts.models import Membership, Role

class IsPlatformSuperAdmin(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_superuser)

class IsTenantAdminOrSuperAdmin(BasePermission):
    """
    Autorisé si:
    - superuser plateforme
    - OU tenant-admin sur ce tenant (via Membership.roles ou is_owner)
    """
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_superuser:
            return True

        tenant_id = view.kwargs.get("pk") or view.kwargs.get("tenant_pk") or request.data.get("tenant")
        if not tenant_id:
            return False

        qs = Membership.objects.filter(tenant_id=tenant_id, user=request.user)
        if not qs.exists():
            return False

        m = qs.first()
        return m.is_owner or m.roles.filter(id=Role.TENANT_ADMIN).exists()


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
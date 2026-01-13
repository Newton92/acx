# cases/permissions.py
from rest_framework.permissions import BasePermission
from accounts.tenant_ctx import get_active_membership, is_tenant_admin, role_ids
from accounts.models import Role


class IsTenantMember(BasePermission):
    def has_permission(self, request, view):
        u = request.user
        # ✅ évite AnonymousUser -> crash
        if not u or not u.is_authenticated:
            return False

        m = get_active_membership(u)
        return bool(m and m.tenant)


class CanManageCases(BasePermission):
    """
    Règle simple MVP :
    - Tenant admin (owner/admin/approver) : full access
    - Role WRITER (2) : CRUD dossiers + notes/docs
    - Role PERSONAL (1) : lecture + dossiers assignés (enrichi plus tard)
    """

    def has_permission(self, request, view):
        u = request.user
        # ✅ évite AnonymousUser -> crash
        if not u or not u.is_authenticated:
            return False

        m = get_active_membership(u)
        if not (m and m.tenant):
            return False

        if is_tenant_admin(m):
            return True

        ids = role_ids(m)
        return Role.WRITER in ids or Role.PERSONAL in ids

    def has_object_permission(self, request, view, obj):
        u = request.user
        # ✅ évite AnonymousUser -> crash
        if not u or not u.is_authenticated:
            return False

        # obj est Case ou objet lié (case.tenant)
        m = get_active_membership(u)
        if not (m and m.tenant):
            return False

        if obj.tenant_id != m.tenant_id:
            return False

        if is_tenant_admin(m):
            return True

        ids = role_ids(m)
        if Role.WRITER in ids:
            return True

        # PERSONAL: lecture seulement, ou dossiers assignés pour modification
        if Role.PERSONAL in ids:
            if request.method in ("GET", "HEAD", "OPTIONS"):
                return True
            return getattr(obj, "assigned_to_id", None) == u.id

        return False

# accounts/api.py
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.models import Membership
from customers.models import CustomerMembership


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def me(request):
    if request.method == "PATCH":
        u = request.user
        u.first_name = request.data.get("first_name", u.first_name)
        u.last_name  = request.data.get("last_name",  u.last_name)
        email = (request.data.get("email") or "").strip()
        if email:
            u.email = email
        u.save(update_fields=["first_name", "last_name", "email"])
        return Response({"detail": "Profil mis à jour."})

    u = request.user

    active_tenant = None
    active_membership = None

    qs = (
        Membership.objects.filter(user=u, status=Membership.Status.ACTIVE)
        .select_related("tenant")
        .prefetch_related("roles")
    )

    m = qs.filter(is_owner=True).first() or qs.first()

    if m and m.tenant:
        active_tenant = {"id": m.tenant.id, "name": m.tenant.name}
        active_membership = {
            "tenant_id": m.tenant.id,
            "status": m.status,
            "is_owner": m.is_owner,
            "role_ids": list(m.roles.values_list("id", flat=True)),
        }

    # ✅ Customer memberships (portail client)
    cqs = (
        CustomerMembership.objects
        .filter(user=u, status=CustomerMembership.Status.ACTIVE)
        .select_related("customer", "customer__tenant")
    )
    cm = cqs.filter(is_primary_contact=True).first() or cqs.first()

    active_customer = None
    active_customer_membership = None
    if cm and cm.customer:
        c = cm.customer
        active_customer = {
            "id": c.id,
            "name": c.name,
            "tenant_id": c.tenant_id,
            "portal_enabled": c.portal_enabled,
        }
        active_customer_membership = {
            "customer_id": c.id,
            "role": cm.role,
            "status": cm.status,
            "is_primary_contact": cm.is_primary_contact,
        }

    actor = "none"
    if active_tenant and active_customer:
        actor = "both"
    elif active_tenant:
        actor = "tenant"
    elif active_customer:
        actor = "customer"

    return Response({
        "id": u.id,
        "username": u.username,
        "email": u.email,
        "first_name": u.first_name,
        "last_name": u.last_name,
        "is_superuser": u.is_superuser,
        "is_staff": u.is_staff,
        "is_active": u.is_active,
        "must_change_password": u.must_change_password,

        "active_tenant": active_tenant,
        "active_membership": active_membership,

        "active_customer": active_customer,
        "active_customer_membership": active_customer_membership,

        "actor": actor,
    })

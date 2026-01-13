from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from accounts.models import Membership, Role, AuditLog
from accounts.api.tenant_access import get_active_membership, is_tenant_admin
from accounts.api.serializers_tenant_users import (
    TenantUserSerializer,
    TenantUserCreateSerializer,
)

User = get_user_model()


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def tenant_users(request):
    """
    GET  : liste les utilisateurs du tenant actif (membership ACTIVE)
    POST : crée un User + Membership dans le tenant actif
    """
    membership = get_active_membership(request.user)
    if not membership or not membership.tenant:
        return Response(
            {"detail": "No active tenant for this user."},
            status=status.HTTP_403_FORBIDDEN
        )

    tenant = membership.tenant

    # --- GET ---
    if request.method == "GET":
        user_ids = Membership.objects.filter(
            tenant=tenant,
            status=Membership.Status.ACTIVE
        ).values_list("user_id", flat=True)

        qs = User.objects.filter(id__in=user_ids).order_by("username")
        return Response(TenantUserSerializer(qs, many=True).data)

    # --- POST ---
    if not is_tenant_admin(membership):
        return Response({"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)

    ser = TenantUserCreateSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    data = ser.validated_data

    with transaction.atomic():
        user = User(
            username=data["username"],
            email=data["email"],
            first_name=(data.get("first_name") or "").strip(),
            last_name=(data.get("last_name") or "").strip(),
            telephone=(data.get("telephone") or "").strip() or None,
            departement=(data.get("departement") or "").strip() or None,
            is_active=True,
        )

        raw_password = (data.get("password") or "").strip()
        if raw_password:
            user.set_password(raw_password)
        else:
            user.set_unusable_password()

        user.save()

        new_membership = Membership.objects.create(
            tenant=tenant,
            user=user,
            status=Membership.Status.ACTIVE,
            is_owner=False,
        )

        # Assigner roles si fournis
        role_ids = data.get("role_ids") or []
        if role_ids:
            roles = Role.objects.filter(id__in=role_ids)
            new_membership.roles.set(roles)

        # Audit log (optionnel mais vous l’avez déjà)
        AuditLog.objects.create(
            action="TENANT_USER_CREATE",
            actor=request.user,
            tenant=tenant,
            entity_type="User",
            entity_id=user.id,
            entity_label=str(user),
            metadata={
                "created_user_username": user.username,
                "created_user_email": user.email,
                "assigned_role_ids": role_ids,
            },
        )

    return Response(TenantUserSerializer(user).data, status=status.HTTP_201_CREATED)

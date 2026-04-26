import re

from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from accounts.models import Membership, Role, AuditLog, UserCountryAssignment

_USERNAME_RE = re.compile(r'^[\w.@+\-]+$')

User = get_user_model()


def _get_active_membership(user):
    qs = (
        Membership.objects.filter(user=user, status=Membership.Status.ACTIVE)
        .select_related("tenant")
        .prefetch_related("roles")
    )
    return qs.filter(is_owner=True).first() or qs.first()


def _is_tenant_admin(membership: Membership) -> bool:
    if not membership:
        return False
    if membership.is_owner:
        return True
    role_ids = set(membership.roles.values_list("id", flat=True))
    return (Role.ADMIN in role_ids) or (Role.APPROVER in role_ids)


def _get_target_membership(tenant, user_id: int):
    return (
        Membership.objects.select_related("tenant", "user")
        .prefetch_related("roles")
        .filter(tenant=tenant, user_id=user_id)
        .first()
    )


def _user_payload(u: User, m: Membership | None):
    return {
        "id": u.id,
        "username": u.username,
        "email": u.email,
        "first_name": u.first_name,
        "last_name": u.last_name,
        "telephone": getattr(u, "telephone", None),
        "departement": getattr(u, "departement", None),
        "is_active": u.is_active,

        "membership": None if not m else {
            "id": m.id,
            "status": m.status,
            "is_owner": m.is_owner,
            "role_ids": list(m.roles.values_list("id", flat=True)),
        }
    }


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def tenant_users(request):
    """
    GET  /tenant/users/  : liste users du tenant actif (tous memberships)
    POST /tenant/users/  : crée user + membership ACTIVE dans le tenant actif
    """
    actor_m = _get_active_membership(request.user)
    if not actor_m or not actor_m.tenant:
        return Response({"detail": "No active tenant for this user."}, status=status.HTTP_403_FORBIDDEN)

    tenant = actor_m.tenant

    if request.method == "GET":
        memberships = (
            Membership.objects.filter(tenant=tenant)
            .select_related("user")
            .prefetch_related("roles")
            .order_by("user__username")
        )
        country_code = request.query_params.get("country", "").strip().upper()
        if country_code:
            assigned_user_ids = UserCountryAssignment.objects.filter(
                tenant=tenant,
                country__country_code__iexact=country_code,
            ).values_list("user_id", flat=True)
            memberships = memberships.filter(user_id__in=assigned_user_ids)
        return Response([_user_payload(m.user, m) for m in memberships])

    # POST
    if not _is_tenant_admin(actor_m):
        return Response({"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)

    payload = request.data or {}
    username = (payload.get("username") or "").strip()
    email = (payload.get("email") or "").strip()
    first_name = (payload.get("first_name") or "").strip()
    last_name = (payload.get("last_name") or "").strip()
    telephone = (payload.get("telephone") or "").strip() or None
    departement = (payload.get("departement") or "").strip() or None
    password = (payload.get("password") or "").strip()
    role_ids = payload.get("role_ids") or []

    if not username or not email:
        return Response({"detail": "username and email are required."}, status=status.HTTP_400_BAD_REQUEST)
    if User.objects.filter(username=username).exists():
        return Response({"detail": "Username already exists."}, status=status.HTTP_400_BAD_REQUEST)
    if User.objects.filter(email=email).exists():
        return Response({"detail": "Email already exists."}, status=status.HTTP_400_BAD_REQUEST)

    with transaction.atomic():
        u = User(
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name,
            telephone=telephone,
            departement=departement,
            is_active=True,
        )
        if password:
            u.set_password(password)
        else:
            u.set_unusable_password()
        u.save()

        m = Membership.objects.create(
            tenant=tenant,
            user=u,
            status=Membership.Status.ACTIVE,
            is_owner=False,
        )

        if role_ids:
            roles = Role.objects.filter(id__in=role_ids)
            m.roles.set(roles)

        AuditLog.objects.create(
            action="TENANT_USER_CREATE",
            actor=request.user,
            tenant=tenant,
            entity_type="User",
            entity_id=u.id,
            entity_label=str(u),
            metadata={"role_ids": role_ids},
        )

    return Response(_user_payload(u, m), status=status.HTTP_201_CREATED)


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def tenant_user_update(request, user_id: int):
    """
    PATCH /tenant/users/<id>/ : update profil user (nom, email, tel, dept)
    """
    actor_m = _get_active_membership(request.user)
    if not actor_m or not actor_m.tenant:
        return Response({"detail": "No active tenant for this user."}, status=status.HTTP_403_FORBIDDEN)
    if not _is_tenant_admin(actor_m):
        return Response({"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)

    tenant = actor_m.tenant
    target_m = _get_target_membership(tenant, user_id)
    if not target_m:
        return Response({"detail": "User not found in tenant."}, status=status.HTTP_404_NOT_FOUND)

    u = target_m.user
    payload = request.data or {}

    # ── Username — unicité globale + format ───────────────────────────
    new_username = (payload.get("username") or "").strip()
    if new_username and new_username != u.username:
        if not _USERNAME_RE.match(new_username):
            return Response(
                {"field": "username", "detail": "Caractères autorisés : lettres, chiffres, @, ., +, -, _"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(new_username) > 150:
            return Response(
                {"field": "username", "detail": "150 caractères maximum."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if User.objects.exclude(pk=u.pk).filter(username__iexact=new_username).exists():
            return Response(
                {"field": "username", "detail": "Ce nom d'utilisateur est déjà utilisé par un autre compte."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        u.username = new_username

    # ── Champs profil ─────────────────────────────────────────────────
    for field in ["first_name", "last_name", "telephone", "departement"]:
        if field in payload:
            setattr(u, field, payload.get(field) or "")

    if "email" in payload:
        email = (payload.get("email") or "").strip()
        if not email:
            return Response({"detail": "Email cannot be empty."}, status=status.HTTP_400_BAD_REQUEST)
        if User.objects.exclude(id=u.id).filter(email=email).exists():
            return Response({"detail": "Email already exists."}, status=status.HTTP_400_BAD_REQUEST)
        u.email = email

    # ── Mot de passe ──────────────────────────────────────────────────
    new_password = (payload.get("password") or "").strip()
    if new_password:
        u.set_password(new_password)

    u.save()

    AuditLog.objects.create(
        action="TENANT_USER_UPDATE",
        actor=request.user,
        tenant=tenant,
        entity_type="User",
        entity_id=u.id,
        entity_label=str(u),
        metadata={"fields": list(payload.keys())},
    )

    return Response(_user_payload(u, target_m))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def tenant_user_toggle_active(request, user_id: int):
    """
    POST /tenant/users/<id>/toggle-active/ : active/inactive (is_active)
    """
    actor_m = _get_active_membership(request.user)
    if not actor_m or not actor_m.tenant:
        return Response({"detail": "No active tenant for this user."}, status=status.HTTP_403_FORBIDDEN)
    if not _is_tenant_admin(actor_m):
        return Response({"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)

    tenant = actor_m.tenant
    target_m = _get_target_membership(tenant, user_id)
    if not target_m:
        return Response({"detail": "User not found in tenant."}, status=status.HTTP_404_NOT_FOUND)

    u = target_m.user

    # sécurité: éviter de désactiver soi-même si owner
    if u.id == request.user.id and target_m.is_owner:
        return Response({"detail": "Cannot deactivate the tenant owner."}, status=status.HTTP_400_BAD_REQUEST)

    u.is_active = not u.is_active
    u.save()

    AuditLog.objects.create(
        action="TENANT_USER_TOGGLE_ACTIVE",
        actor=request.user,
        tenant=tenant,
        entity_type="User",
        entity_id=u.id,
        entity_label=str(u),
        metadata={"is_active": u.is_active},
    )

    return Response(_user_payload(u, target_m))


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def tenant_user_membership_update(request, user_id: int):
    """
    PATCH /tenant/users/<id>/membership/ : update roles + status (optionnel)
    payload:
      - role_ids: number[]
      - status: invited|active|suspended
    """
    actor_m = _get_active_membership(request.user)
    if not actor_m or not actor_m.tenant:
        return Response({"detail": "No active tenant for this user."}, status=status.HTTP_403_FORBIDDEN)
    if not _is_tenant_admin(actor_m):
        return Response({"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)

    tenant = actor_m.tenant
    target_m = _get_target_membership(tenant, user_id)
    if not target_m:
        return Response({"detail": "User not found in tenant."}, status=status.HTTP_404_NOT_FOUND)

    payload = request.data or {}

    if "role_ids" in payload:
        role_ids = payload.get("role_ids") or []
        roles = Role.objects.filter(id__in=role_ids)
        target_m.roles.set(roles)

    if "status" in payload:
        st = payload.get("status")
        valid = {Membership.Status.INVITED, Membership.Status.ACTIVE, Membership.Status.SUSPENDED}
        if st not in valid:
            return Response({"detail": "Invalid status."}, status=status.HTTP_400_BAD_REQUEST)
        # sécurité: ne pas suspendre le owner
        if target_m.is_owner and st != Membership.Status.ACTIVE:
            return Response({"detail": "Cannot change status of tenant owner."}, status=status.HTTP_400_BAD_REQUEST)
        target_m.status = st
        target_m.save()

    AuditLog.objects.create(
        action="TENANT_MEMBERSHIP_UPDATE",
        actor=request.user,
        tenant=tenant,
        entity_type="Membership",
        entity_id=target_m.id,
        entity_label=str(target_m),
        metadata={"payload": payload},
    )

    return Response(_user_payload(target_m.user, target_m))


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def tenant_user_remove(request, user_id: int):
    """
    DELETE /tenant/users/<id>/remove/ : retire l'utilisateur du tenant (delete membership)
    """
    actor_m = _get_active_membership(request.user)
    if not actor_m or not actor_m.tenant:
        return Response({"detail": "No active tenant for this user."}, status=status.HTTP_403_FORBIDDEN)
    if not _is_tenant_admin(actor_m):
        return Response({"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)

    tenant = actor_m.tenant
    target_m = _get_target_membership(tenant, user_id)
    if not target_m:
        return Response({"detail": "User not found in tenant."}, status=status.HTTP_404_NOT_FOUND)

    if target_m.is_owner:
        return Response({"detail": "Cannot remove tenant owner."}, status=status.HTTP_400_BAD_REQUEST)

    AuditLog.objects.create(
        action="TENANT_MEMBERSHIP_REMOVE",
        actor=request.user,
        tenant=tenant,
        entity_type="Membership",
        entity_id=target_m.id,
        entity_label=str(target_m),
        metadata={"removed_user_id": user_id},
    )

    target_m.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)

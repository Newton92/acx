# accounts/views_countries.py
from django.db import IntegrityError

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import TenantCountry, UserCountryAssignment, Membership


def _tenant(request):
    m = request.user.memberships.select_related("tenant").first()
    return m.tenant if m else None


def _serialize(c: TenantCountry) -> dict:
    return {
        "id": c.id,
        "country_code": c.country_code,
        "country_name": c.country_name,
        "is_active": c.is_active,
        "manager": {
            "id": c.manager.id,
            "username": c.manager.username,
            "full_name": str(c.manager),
            "email": c.manager.email,
        } if c.manager else None,
        "created_at": c.created_at.isoformat(),
    }


# ─── Pays du tenant ───────────────────────────────────────────────────────────

@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def tenant_countries(request):
    tenant = _tenant(request)
    if not tenant:
        return Response({"detail": "Tenant introuvable."}, status=400)

    if request.method == "GET":
        qs = TenantCountry.objects.filter(tenant=tenant).select_related("manager")
        return Response([_serialize(c) for c in qs])

    # POST — ajouter un pays
    code = (request.data.get("country_code") or "").upper().strip()
    name = (request.data.get("country_name") or "").strip()
    if not code or not name:
        return Response({"detail": "country_code et country_name sont obligatoires."}, status=400)

    try:
        country = TenantCountry.objects.create(
            tenant=tenant,
            country_code=code,
            country_name=name,
            is_active=request.data.get("is_active", True),
        )
        return Response(_serialize(country), status=201)
    except IntegrityError:
        return Response({"detail": "Ce pays est déjà configuré."}, status=409)


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def tenant_country_detail(request, country_id):
    tenant = _tenant(request)
    try:
        country = TenantCountry.objects.select_related("manager").get(
            id=country_id, tenant=tenant
        )
    except TenantCountry.DoesNotExist:
        return Response(status=404)

    if request.method == "DELETE":
        country.delete()
        return Response(status=204)

    # PATCH
    data = request.data
    if "country_name" in data:
        country.country_name = data["country_name"]
    if "is_active" in data:
        country.is_active = bool(data["is_active"])
    country.save()
    return Response(_serialize(country))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def tenant_country_set_manager(request, country_id):
    """Désigner ou retirer le responsable d'un pays."""
    tenant = _tenant(request)
    try:
        country = TenantCountry.objects.select_related("manager").get(
            id=country_id, tenant=tenant
        )
    except TenantCountry.DoesNotExist:
        return Response(status=404)

    user_id = request.data.get("user_id")  # None ou int → retrait
    if not user_id:
        country.manager = None
    else:
        try:
            membership = Membership.objects.select_related("user").get(
                tenant=tenant, user_id=user_id
            )
            country.manager = membership.user
        except Membership.DoesNotExist:
            return Response({"detail": "Utilisateur introuvable dans ce tenant."}, status=400)

    country.save()
    return Response(_serialize(country))


# ─── Pays assignés à un utilisateur ──────────────────────────────────────────

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def user_country_list(request, user_id):
    tenant = _tenant(request)
    assignments = UserCountryAssignment.objects.filter(
        user_id=user_id, tenant=tenant
    ).select_related("country", "country__manager")
    return Response([_serialize(a.country) for a in assignments])


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def user_country_save(request, user_id):
    """Remplace les pays assignés à un utilisateur par la liste fournie."""
    tenant = _tenant(request)

    try:
        Membership.objects.get(tenant=tenant, user_id=user_id)
    except Membership.DoesNotExist:
        return Response({"detail": "Utilisateur introuvable dans ce tenant."}, status=400)

    country_ids = request.data.get("country_ids", [])

    valid_ids = set(
        TenantCountry.objects.filter(tenant=tenant, id__in=country_ids).values_list("id", flat=True)
    )

    UserCountryAssignment.objects.filter(user_id=user_id, tenant=tenant).delete()
    UserCountryAssignment.objects.bulk_create(
        [UserCountryAssignment(user_id=user_id, tenant=tenant, country_id=cid) for cid in valid_ids],
        ignore_conflicts=True,
    )

    updated = UserCountryAssignment.objects.filter(
        user_id=user_id, tenant=tenant
    ).select_related("country", "country__manager")
    return Response([_serialize(a.country) for a in updated])


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def user_country_assign_all(request, user_id):
    """Assigne tous les pays actifs du tenant à un utilisateur."""
    tenant = _tenant(request)

    try:
        Membership.objects.get(tenant=tenant, user_id=user_id)
    except Membership.DoesNotExist:
        return Response({"detail": "Utilisateur introuvable dans ce tenant."}, status=400)

    all_countries = TenantCountry.objects.filter(tenant=tenant, is_active=True)

    UserCountryAssignment.objects.filter(user_id=user_id, tenant=tenant).delete()
    UserCountryAssignment.objects.bulk_create(
        [UserCountryAssignment(user_id=user_id, tenant=tenant, country=c) for c in all_countries],
        ignore_conflicts=True,
    )

    updated = UserCountryAssignment.objects.filter(
        user_id=user_id, tenant=tenant
    ).select_related("country", "country__manager")
    return Response([_serialize(a.country) for a in updated])

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.models import Membership


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request):
    u = request.user

    active_tenant = None

    qs = Membership.objects.filter(
        user=u,
        status=Membership.Status.ACTIVE,
    ).select_related("tenant")

    m = qs.filter(is_owner=True).first() or qs.first()
    if m and m.tenant:
        active_tenant = {"id": m.tenant.id, "name": m.tenant.name}

    return Response({
        "id": u.id,
        "username": u.username,
        "email": u.email,
        "first_name": u.first_name,
        "last_name": u.last_name,
        "is_superuser": u.is_superuser,
        "is_staff": u.is_staff,
        "is_active": u.is_active,
        "active_tenant": active_tenant,
    })

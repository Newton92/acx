from rest_framework.viewsets import ModelViewSet

from accounts.models import Role, Membership
from .models import Tenant
from .serializers import TenantSerializer
from .permissions import IsSuperUser
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

class TenantViewSet(ModelViewSet):
    queryset = Tenant.objects.all().order_by("-created_at")
    serializer_class = TenantSerializer
    permission_classes = [IsAuthenticated, IsSuperUser]







class SuperAdminOnly(IsAuthenticated):
    def has_permission(self, request, view):
        ok = super().has_permission(request, view)
        if not ok:
            return False
        # read autorisé à tous les authentifiés? -> à toi de choisir
        # Ici: superadmin pour tout
        return bool(request.user and request.user.is_superuser)



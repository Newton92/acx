# accounts/jwt_views.py
from rest_framework_simplejwt.views import TokenObtainPairView
from .jwt_serializers import (
    EmailOrUsernameTokenObtainPairSerializer,
    TenantTokenObtainPairSerializer,
    CustomerPortalTokenObtainPairSerializer,
)


class EmailOrUsernameTokenObtainPairView(TokenObtainPairView):
    """Login agent/admin tenant (username ou email)."""
    serializer_class = EmailOrUsernameTokenObtainPairSerializer


class TenantTokenObtainPairView(TokenObtainPairView):
    """Login agent/admin tenant (username standard)."""
    serializer_class = TenantTokenObtainPairSerializer


class CustomerPortalTokenObtainPairView(TokenObtainPairView):
    """Login exclusif portail client — bloque admins et agents sans CustomerMembership."""
    serializer_class = CustomerPortalTokenObtainPairSerializer

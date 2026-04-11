# acx/urls.py
from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from accounts.api import me
from accounts.views import MembershipViewSet
from accounts.jwt_views import (
    EmailOrUsernameTokenObtainPairView,
    TenantTokenObtainPairView,
    CustomerPortalTokenObtainPairView,
)
from django.conf import settings
from django.conf.urls.static import static
router = DefaultRouter()
router.register(r"memberships", MembershipViewSet, basename="memberships")

urlpatterns = [
    path("admin/", admin.site.urls),

    # Auth — agents/admins tenant (username ou email)
    path("api/auth/token/", TenantTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/email/", EmailOrUsernameTokenObtainPairView.as_view(), name="token_obtain_pair_email"),
    path("api/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/auth/me/", me, name="auth_me"),

    # Auth — portail client exclusif (bloque admins/agents sans CustomerMembership)
    path("api/auth/client-portal/token/", CustomerPortalTokenObtainPairView.as_view(), name="client_portal_token"),




    # API modules
    path("api/", include("tenancy.urls")),
    path("api/", include("accounts.urls")),
    path("api/", include("cases.urls")),
    path("api/", include("customers.urls")),
    path("api/", include("collections_management.urls")),
    path("api/", include("treasury_management.urls")),

    # Memberships API (router)
    path("api/", include(router.urls)),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
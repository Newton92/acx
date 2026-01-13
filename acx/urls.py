# acx/urls.py
from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from accounts.api import me
from accounts.views import MembershipViewSet
from accounts.jwt_views import EmailOrUsernameTokenObtainPairView  # ✅ ajout
from django.conf import settings
from django.conf.urls.static import static
router = DefaultRouter()
router.register(r"memberships", MembershipViewSet, basename="memberships")

from cases.views_customer_portal_messages import (
    CustomerPortalInboxView,
    CustomerPortalCaseMessagesView,
    CustomerPortalMessageReadView,
    CustomerPortalCaseMessageDetailView,
)

urlpatterns = [
    path("admin/", admin.site.urls),

    # Auth
    path("api/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/email/", EmailOrUsernameTokenObtainPairView.as_view(), name="token_obtain_pair_email"),  # ✅ ajout
    path("api/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/auth/me/", me, name="auth_me"),




    # API modules
    path("api/", include("tenancy.urls")),
    path("api/", include("accounts.urls")),
    path("api/", include("cases.urls")),
    path("api/", include("customers.urls")),
    path("api/", include("collections_management.urls")),

    # Memberships API (router)
    path("api/", include(router.urls)),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
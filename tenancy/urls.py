#tenancy/urls.py
from rest_framework.routers import DefaultRouter
from .views import TenantViewSet
from .dashboard import admin_dashboard_stats
from django.urls import path, include

router = DefaultRouter()
router.register(r"tenants", TenantViewSet, basename="tenant")


urlpatterns = [
    path("", include(router.urls)),
    path("admin-dashboard/", admin_dashboard_stats, name="admin_dashboard_stats"),
]
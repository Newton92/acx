#tenancy/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import TenantViewSet, TenantLicenseView, TenantExportView
from .dashboard import admin_dashboard_stats

router = DefaultRouter()
router.register(r"tenants", TenantViewSet, basename="tenant")

urlpatterns = [
    path("", include(router.urls)),
    path("admin-dashboard/", admin_dashboard_stats, name="admin_dashboard_stats"),
    path("tenants/<int:pk>/license/", TenantLicenseView.as_view(), name="tenant-license"),
    path("tenants/<int:pk>/export/",  TenantExportView.as_view(),  name="tenant-export"),
]

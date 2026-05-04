# customers/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .portal_views import customer_portal_me, CustomerPortalCaseViewSet
from .views import CustomerViewSet, CreditorViewSet

router = DefaultRouter()
router.register(r"customers", CustomerViewSet, basename="customers")
router.register(r"creditors", CreditorViewSet, basename="creditors")

portal_router = DefaultRouter()
portal_router.register(r"customer-portal/cases", CustomerPortalCaseViewSet, basename="customer-portal-cases")

urlpatterns = [
    path("", include(router.urls)),
    path("customer-portal/me/", customer_portal_me, name="customer-portal-me"),
    path("", include(portal_router.urls)),
]

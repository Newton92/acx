#treasury_management/urls.py

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import TreasuryAccountViewSet, TreasuryMovementViewSet, RemittanceBatchViewSet

router = DefaultRouter()
router.register(r"treasury-accounts", TreasuryAccountViewSet, basename="treasury-account")
router.register(r"treasury-movements", TreasuryMovementViewSet, basename="treasury-movement")
router.register(r"remittances", RemittanceBatchViewSet, basename="remittance")

urlpatterns = [
    path("", include(router.urls)),
]

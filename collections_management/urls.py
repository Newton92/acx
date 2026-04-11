# collections_management/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    CollectionCaseViewSet,
    CollectionActionViewSet,
    PaymentPromiseViewSet,
    PaymentViewSet,
    CollectionEmailViewSet,
)

router = DefaultRouter()

# Routes "canon"
router.register(r"collection-cases", CollectionCaseViewSet, basename="collection-case")
router.register(r"collection-actions", CollectionActionViewSet, basename="collection-action")
router.register(r"payment-promises", PaymentPromiseViewSet, basename="payment-promise")
router.register(r"payments", PaymentViewSet, basename="payment")
router.register(r"collection-emails", CollectionEmailViewSet, basename="collection-email")

# ✅ Aliases (utile si ton front a déjà des routes /collection-payments, etc.)
router.register(r"collection-payment-promises", PaymentPromiseViewSet, basename="collection-payment-promise")
router.register(r"collection-payments", PaymentViewSet, basename="collection-payment")

urlpatterns = [
    path("", include(router.urls)),
]

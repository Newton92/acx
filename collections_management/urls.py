from rest_framework.routers import DefaultRouter
from .views import CollectionCaseViewSet, CollectionActionViewSet, PaymentPromiseViewSet, PaymentViewSet

router = DefaultRouter()
router.register(r"collection-cases", CollectionCaseViewSet, basename="collection-case")
router.register(r"collection-actions", CollectionActionViewSet, basename="collection-action")
router.register(r"payment-promises", PaymentPromiseViewSet, basename="payment-promise")
router.register(r"payments", PaymentViewSet, basename="payment")

urlpatterns = router.urls

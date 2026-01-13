# cases/urls.py
from rest_framework.routers import DefaultRouter
from cases.views import PortfolioViewSet, DebtorViewSet, CaseViewSet

router = DefaultRouter()
router.register(r"portfolios", PortfolioViewSet, basename="portfolios")
router.register(r"debtors", DebtorViewSet, basename="debtors")
router.register(r"cases", CaseViewSet, basename="cases")

urlpatterns = router.urls

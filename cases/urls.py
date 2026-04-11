# cases/urls.py
from django.urls import path
from rest_framework.routers import DefaultRouter
from cases.views import PortfolioViewSet, DebtorViewSet, CaseViewSet, TenantCaseNoteDetailView

router = DefaultRouter()
router.register(r"portfolios", PortfolioViewSet, basename="portfolios")
router.register(r"debtors", DebtorViewSet, basename="debtors")
router.register(r"cases", CaseViewSet, basename="cases")

urlpatterns = router.urls + [
    path(
        "cases/<int:case_id>/notes/<int:note_id>/",
        TenantCaseNoteDetailView.as_view(),
        name="tenant-case-note-detail",
    ),
]

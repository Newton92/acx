"""tenancy/views.py — Tenant CRUD (super admin) + License + Export CSV."""

import csv
import io
import zipfile
import datetime

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet

from .models import Tenant, TenantLicense
from .serializers import TenantSerializer, TenantLicenseSerializer
from .permissions import IsSuperUser


# ── Tenant CRUD ────────────────────────────────────────────────────────────

class TenantViewSet(ModelViewSet):
    queryset = Tenant.objects.all().order_by("-created_at")
    serializer_class = TenantSerializer
    permission_classes = [IsAuthenticated, IsSuperUser]


class SuperAdminOnly(IsAuthenticated):
    def has_permission(self, request, view):
        ok = super().has_permission(request, view)
        return ok and bool(request.user and request.user.is_superuser)


# ── Licence ────────────────────────────────────────────────────────────────

class TenantLicenseView(APIView):
    """
    GET  /api/tenants/{id}/license/   → lecture licence
    POST /api/tenants/{id}/license/   → création ou remplacement
    PATCH /api/tenants/{id}/license/  → mise à jour partielle
    """
    permission_classes = [IsAuthenticated, IsSuperUser]

    def _get_tenant(self, pk):
        return get_object_or_404(Tenant, pk=pk)

    def get(self, request, pk):
        tenant = self._get_tenant(pk)
        try:
            lic = tenant.license
        except TenantLicense.DoesNotExist:
            return Response(None, status=status.HTTP_200_OK)
        return Response(TenantLicenseSerializer(lic).data)

    def post(self, request, pk):
        tenant = self._get_tenant(pk)
        # Upsert : si une licence existe déjà on la met à jour
        try:
            lic = tenant.license
            ser = TenantLicenseSerializer(lic, data=request.data, partial=False)
        except TenantLicense.DoesNotExist:
            ser = TenantLicenseSerializer(data=request.data)

        ser.is_valid(raise_exception=True)
        lic = ser.save(tenant=tenant, created_by=request.user)
        return Response(TenantLicenseSerializer(lic).data, status=status.HTTP_200_OK)

    def patch(self, request, pk):
        tenant = self._get_tenant(pk)
        try:
            lic = tenant.license
        except TenantLicense.DoesNotExist:
            return Response({"detail": "Aucune licence."}, status=status.HTTP_404_NOT_FOUND)
        ser = TenantLicenseSerializer(lic, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(TenantLicenseSerializer(lic).data)

    def delete(self, request, pk):
        tenant = self._get_tenant(pk)
        try:
            tenant.license.delete()
        except TenantLicense.DoesNotExist:
            pass
        return Response(status=status.HTTP_204_NO_CONTENT)


# ── Export CSV ─────────────────────────────────────────────────────────────

class TenantExportView(APIView):
    """
    GET /api/tenants/{id}/export/
    Retourne un ZIP contenant les données du tenant en CSV.
    """
    permission_classes = [IsAuthenticated, IsSuperUser]

    def get(self, request, pk):
        tenant = get_object_or_404(Tenant, pk=pk)
        buf = io.BytesIO()

        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("cases.csv",            self._export_cases(tenant))
            zf.writestr("debtors.csv",          self._export_debtors(tenant))
            zf.writestr("portfolios.csv",       self._export_portfolios(tenant))
            zf.writestr("customers.csv",        self._export_customers(tenant))
            zf.writestr("payments.csv",         self._export_payments(tenant))
            zf.writestr("collection_actions.csv", self._export_actions(tenant))
            zf.writestr("treasury_movements.csv", self._export_treasury(tenant))
            zf.writestr("users.csv",            self._export_users(tenant))

        buf.seek(0)
        slug = tenant.slug or f"tenant_{tenant.id}"
        date = timezone.now().strftime("%Y%m%d")
        resp = HttpResponse(buf.read(), content_type="application/zip")
        resp["Content-Disposition"] = f'attachment; filename="export_{slug}_{date}.zip"'
        return resp

    # ── helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _csv(headers, rows) -> str:
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(headers)
        w.writerows(rows)
        return out.getvalue()

    def _export_cases(self, tenant) -> str:
        try:
            from cases.models import Case
            qs = Case.objects.filter(tenant=tenant).select_related("debtor", "portfolio", "assigned_to")
            headers = ["id", "reference", "title", "status", "priority", "currency",
                       "original_amount", "balance_amount", "due_date",
                       "debtor", "portfolio", "assigned_to", "opened_at"]
            rows = [
                [c.id, c.reference, c.title, c.status, c.priority, c.currency or "",
                 c.original_amount, c.balance_amount, c.due_date or "",
                 str(c.debtor) if c.debtor else "",
                 c.portfolio.name if c.portfolio else "",
                 c.assigned_to.username if c.assigned_to else "",
                 c.opened_at.isoformat()]
                for c in qs
            ]
            return self._csv(headers, rows)
        except Exception:
            return self._csv(["error"], [["cases export unavailable"]])

    def _export_debtors(self, tenant) -> str:
        try:
            from cases.models import Debtor
            qs = Debtor.objects.filter(tenant=tenant)
            headers = ["id", "full_name", "email", "phone", "address", "city", "country", "created_at"]
            rows = [
                [d.id, getattr(d, "full_name", str(d)),
                 getattr(d, "email", "") or "", getattr(d, "phone", "") or "",
                 getattr(d, "address", "") or "", getattr(d, "city", "") or "",
                 getattr(d, "country", "") or "", d.created_at.isoformat()]
                for d in qs
            ]
            return self._csv(headers, rows)
        except Exception:
            return self._csv(["error"], [["debtors export unavailable"]])

    def _export_portfolios(self, tenant) -> str:
        try:
            from cases.models import Portfolio
            qs = Portfolio.objects.filter(tenant=tenant).select_related("owner")
            headers = ["id", "name", "code", "category", "priority", "default_currency",
                       "is_active", "owner", "created_at"]
            rows = [
                [p.id, p.name, p.code or "", p.category or "", p.priority,
                 p.default_currency or "",
                 p.is_active,
                 p.owner.username if p.owner else "",
                 p.created_at.isoformat()]
                for p in qs
            ]
            return self._csv(headers, rows)
        except Exception:
            return self._csv(["error"], [["portfolios export unavailable"]])

    def _export_customers(self, tenant) -> str:
        try:
            from customers.models import Customer
            qs = Customer.objects.filter(tenant=tenant)
            headers = ["id", "name", "code", "email", "phone", "country", "status", "created_at"]
            rows = [
                [c.id, getattr(c, "name", str(c)),
                 getattr(c, "code", ""), getattr(c, "email", ""),
                 getattr(c, "phone", ""), getattr(c, "country", ""),
                 getattr(c, "status", ""), c.created_at.isoformat()]
                for c in qs
            ]
            return self._csv(headers, rows)
        except Exception:
            return self._csv(["error"], [["customers export unavailable"]])

    def _export_payments(self, tenant) -> str:
        try:
            from collections_management.models import Payment
            qs = Payment.objects.filter(tenant=tenant).select_related("case")
            headers = ["id", "case_reference", "amount", "currency", "method",
                       "received_by", "reference", "paid_at", "created_at"]
            rows = [
                [p.id,
                 p.case.reference if p.case else "",
                 p.amount, getattr(p, "currency", ""),
                 p.method, p.received_by or "",
                 p.reference or "", p.paid_at.isoformat() if p.paid_at else "",
                 p.created_at.isoformat()]
                for p in qs
            ]
            return self._csv(headers, rows)
        except Exception:
            return self._csv(["error"], [["payments export unavailable"]])

    def _export_actions(self, tenant) -> str:
        try:
            from collections_management.models import CollectionAction
            qs = CollectionAction.objects.filter(tenant=tenant).select_related("case")
            headers = ["id", "case_reference", "action_type", "outcome", "summary",
                       "performed_at", "created_at"]
            rows = [
                [a.id,
                 a.case.reference if hasattr(a, "case") and a.case else "",
                 getattr(a, "action_type", ""), getattr(a, "outcome", ""),
                 getattr(a, "summary", ""),
                 getattr(a, "performed_at", a.created_at).isoformat(),
                 a.created_at.isoformat()]
                for a in qs
            ]
            return self._csv(headers, rows)
        except Exception:
            return self._csv(["error"], [["actions export unavailable"]])

    def _export_treasury(self, tenant) -> str:
        try:
            from treasury_management.models import TreasuryMovement
            qs = TreasuryMovement.objects.filter(tenant=tenant).select_related("account")
            headers = ["id", "account", "direction", "status", "amount", "currency",
                       "value_date", "label", "reference", "source", "created_at"]
            rows = [
                [m.id,
                 m.account.name if m.account else "",
                 m.direction, m.status, m.amount, m.currency,
                 m.value_date.isoformat() if m.value_date else "",
                 m.label or "", m.reference or "", m.source or "",
                 m.created_at.isoformat()]
                for m in qs
            ]
            return self._csv(headers, rows)
        except Exception:
            return self._csv(["error"], [["treasury export unavailable"]])

    def _export_users(self, tenant) -> str:
        try:
            from accounts.models import Membership
            qs = Membership.objects.filter(tenant=tenant).select_related("user").prefetch_related("roles")
            headers = ["user_id", "username", "email", "first_name", "last_name",
                       "is_active", "membership_status", "is_owner", "roles"]
            rows = [
                [m.user.id, m.user.username, m.user.email,
                 m.user.first_name, m.user.last_name, m.user.is_active,
                 m.status, m.is_owner,
                 "|".join(str(r.id) for r in m.roles.all())]
                for m in qs
            ]
            return self._csv(headers, rows)
        except Exception:
            return self._csv(["error"], [["users export unavailable"]])

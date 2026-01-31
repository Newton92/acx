# collections_management/views.py

from django.apps import apps
from django.db import IntegrityError, transaction
from django.db.models import Prefetch

from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError, PermissionDenied
from rest_framework.filters import OrderingFilter
from rest_framework.response import Response

from django_filters.rest_framework import DjangoFilterBackend

from .filters import CollectionCaseFilter
from .models import CollectionCase, CollectionAction, PaymentPromise, Payment
from .serializers import (
    CollectionCaseSerializer,
    CollectionActionSerializer,
    PaymentPromiseSerializer,
    PaymentSerializer,
)
from .serializers_timeline import CollectionCaseTimelineSerializer


# -------------------------------------------------------------------
# ✅ Tenant resolver ACX (robuste, sans import fragile)
# -------------------------------------------------------------------

def resolve_tenant_from_request(request):
    # 1) si middleware a injecté request.tenant
    tenant = getattr(request, "tenant", None)
    if tenant:
        return tenant

    # 2) user connecté obligatoire
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return None

    # 3) chercher Membership dans plusieurs apps (accounts / tenancy)
    Membership = None
    for app_label in ("accounts", "tenancy"):
        try:
            Membership = apps.get_model(app_label, "Membership")
            if Membership:
                break
        except Exception:
            continue

    if not Membership:
        return None

    m = (
        Membership.objects
        .select_related("tenant")
        .filter(user=user, status="active")
        .order_by("-id")
        .first()
    )
    return m.tenant if m else None


# -------------------------------------------------------------------
# Permissions (placeholder)
# -------------------------------------------------------------------

class IsTenantMember(permissions.BasePermission):
    """
    Placeholder (marché) : remplace par votre RBAC ACX.
    """
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)


# -------------------------------------------------------------------
# Mixin tenant scope
# -------------------------------------------------------------------

class TenantScopedQuerysetMixin:
    """
    Toujours scoper par tenant.
    """

    def get_tenant(self):
        tenant = resolve_tenant_from_request(self.request)
        if not tenant:
            raise PermissionDenied("Tenant context missing for this request.")
        return tenant

    def filter_by_tenant(self, qs):
        tenant = self.get_tenant()
        return qs.filter(tenant=tenant)

    def perform_create(self, serializer):
        tenant = self.get_tenant()
        serializer.save(tenant=tenant, created_by=self.request.user)


# -------------------------------------------------------------------
# CollectionCase
# -------------------------------------------------------------------

class CollectionCaseViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = CollectionCaseSerializer
    permission_classes = [IsTenantMember]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = CollectionCaseFilter
    ordering_fields = ["created_at", "updated_at", "next_action_date", "priority", "status"]
    ordering = ["-updated_at"]

    queryset = CollectionCase.objects.all()

    def get_queryset(self):
        return self.filter_by_tenant(CollectionCase.objects.all())

    def create(self, request, *args, **kwargs):
        """
        ✅ Création idempotente sur (tenant, reference).
        - si (tenant, reference) existe déjà => renvoie l'existant (200)
        - sinon => crée (201)
        """
        tenant = self.get_tenant()

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vd = serializer.validated_data

        reference = vd.get("reference")
        if not reference:
            raise ValidationError({"reference": "reference is required"})

        updatable_fields = [
            "portfolio",
            "debtor",
            "status",
            "priority",
            "assigned_to",
            "principal_amount",
            "interest_amount",
            "penalty_amount",
            "fees_amount",
            "total_paid_amount",
            "due_date",
            "next_action_type",
            "next_action_date",
            "notes",
        ]

        try:
            with transaction.atomic():
                obj, created = CollectionCase.objects.get_or_create(
                    tenant=tenant,
                    reference=reference,
                    defaults={
                        **{k: vd.get(k) for k in updatable_fields if k in vd},
                        "created_by": request.user,
                    },
                )
        except IntegrityError:
            obj = CollectionCase.objects.get(tenant=tenant, reference=reference)
            created = False

        if not created:
            changed = []
            for k in updatable_fields:
                if k in vd and vd.get(k) is not None:
                    if getattr(obj, k) != vd.get(k):
                        setattr(obj, k, vd.get(k))
                        changed.append(k)
            if changed:
                obj.save(update_fields=changed + ["updated_at"])

        out = self.get_serializer(obj).data
        return Response(out, status=201 if created else 200)

    @action(detail=True, methods=["get"], url_path="timeline")
    def timeline(self, request, pk=None):
        """
        Timeline "marché": 1 call pour alimenter la page détail dossier.
        GET /api/collection-cases/<id>/timeline/?limit_actions=50

        ✅ Fix: ne pas slicer dans Prefetch queryset (sinon Django crash).
        On slice en Python après le prefetch.
        """
        limit_actions = request.query_params.get("limit_actions")
        try:
            limit_actions = int(limit_actions) if limit_actions else 50
        except ValueError:
            limit_actions = 50

        tenant = self.get_tenant()

        # ✅ Prefetch SANS SLICE
        qs = (
            CollectionCase.objects
            .filter(tenant=tenant, pk=pk)
            .select_related("assigned_to", "portfolio", "debtor")
            .prefetch_related(
                Prefetch(
                    "actions",
                    queryset=CollectionAction.objects
                    .filter(tenant=tenant)
                    .order_by("-action_date")
                    .select_related("created_by"),
                    to_attr="pref_actions",
                ),
                Prefetch(
                    "promises",
                    queryset=PaymentPromise.objects
                    .filter(tenant=tenant)
                    .order_by("-promised_date")
                    .select_related("created_by"),
                    to_attr="pref_promises",
                ),
                Prefetch(
                    "payments",
                    queryset=Payment.objects
                    .filter(tenant=tenant)
                    .order_by("-paid_at")
                    .select_related("created_by"),
                    to_attr="pref_payments",
                ),
            )
        )

        case = qs.first()
        if not case:
            return Response({"detail": "Not found."}, status=404)

        actions = list(getattr(case, "pref_actions", []))[:limit_actions]
        promises = list(getattr(case, "pref_promises", []))
        payments = list(getattr(case, "pref_payments", []))

        payload = {
            "case": case,
            "actions": actions,
            "promises": promises,
            "payments": payments,
            "totals": {
                "total_due": str(case.total_due),
                "total_paid": str(case.total_paid_amount),
                "balance": str(case.balance),
                "is_overdue": str(case.is_overdue).lower(),
                "status": case.status,
                "priority": case.priority,
            },
        }

        data = CollectionCaseTimelineSerializer(payload).data
        return Response(data)


# -------------------------------------------------------------------
# CollectionAction
# -------------------------------------------------------------------

class CollectionActionViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = CollectionActionSerializer
    permission_classes = [IsTenantMember]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    ordering_fields = ["action_date", "created_at"]
    ordering = ["-action_date"]

    def get_queryset(self):
        qs = CollectionAction.objects.select_related("case")
        qs = self.filter_by_tenant(qs)
        case_id = self.request.query_params.get("case")
        if case_id:
            qs = qs.filter(case_id=case_id)
        return qs

    def perform_create(self, serializer):
        tenant = self.get_tenant()
        case = serializer.validated_data.get("case")
        if case and case.tenant_id != tenant.id:
            raise ValidationError({"case": "Case does not belong to current tenant."})
        serializer.save(tenant=tenant, created_by=self.request.user)


# -------------------------------------------------------------------
# PaymentPromise
# -------------------------------------------------------------------

class PaymentPromiseViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = PaymentPromiseSerializer
    permission_classes = [IsTenantMember]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    ordering_fields = ["promised_date", "created_at"]
    ordering = ["-promised_date"]

    def get_queryset(self):
        qs = PaymentPromise.objects.select_related("case")
        qs = self.filter_by_tenant(qs)
        case_id = self.request.query_params.get("case")
        if case_id:
            qs = qs.filter(case_id=case_id)
        return qs

    def perform_create(self, serializer):
        tenant = self.get_tenant()
        case = serializer.validated_data.get("case")
        if case and case.tenant_id != tenant.id:
            raise ValidationError({"case": "Case does not belong to current tenant."})
        serializer.save(tenant=tenant, created_by=self.request.user)


# -------------------------------------------------------------------
# Payment
# -------------------------------------------------------------------

class PaymentViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = PaymentSerializer
    permission_classes = [IsTenantMember]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    ordering_fields = ["paid_at", "created_at"]
    ordering = ["-paid_at"]

    def get_queryset(self):
        qs = Payment.objects.select_related("case")
        qs = self.filter_by_tenant(qs)
        case_id = self.request.query_params.get("case")
        if case_id:
            qs = qs.filter(case_id=case_id)
        return qs

    def perform_create(self, serializer):
        tenant = self.get_tenant()
        case = serializer.validated_data.get("case")
        if case and case.tenant_id != tenant.id:
            raise ValidationError({"case": "Case does not belong to current tenant."})
        serializer.save(tenant=tenant, created_by=self.request.user)

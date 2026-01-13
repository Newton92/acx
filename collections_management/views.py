from django.db.models import Prefetch
from django.shortcuts import render

# Create your views here.
from rest_framework import permissions, viewsets
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter
from rest_framework.response import Response

from .filters import CollectionCaseFilter
from .models import CollectionCase, CollectionAction, PaymentPromise, Payment
from .serializers import (
    CollectionCaseSerializer,
    CollectionActionSerializer,
    PaymentPromiseSerializer,
    PaymentSerializer,
)
from .serializers_timeline import CollectionCaseTimelineSerializer


class IsTenantMember(permissions.BasePermission):
    """
    Placeholder (marché) : remplace par votre RBAC ACX.
    """
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)


class TenantScopedQuerysetMixin:
    """
    IMPORTANT: adapte get_tenant() selon ton ACX.

    Cas 1: middleware met request.tenant => return request.tenant
    Cas 2: tenant via membership => return request.user.membership.tenant (ou active membership)
    """
    def get_tenant(self):
        tenant = getattr(self.request, "tenant", None)
        if tenant:
            return tenant

        # fallback "soft" (à adapter)
        membership = getattr(self.request.user, "membership", None)
        if membership and getattr(membership, "tenant", None):
            return membership.tenant

        return None

    def filter_by_tenant(self, qs):
        tenant = self.get_tenant()
        if tenant is None:
            return qs.none()
        return qs.filter(tenant=tenant)

    def perform_create(self, serializer):
        tenant = self.get_tenant()
        serializer.save(tenant=tenant, created_by=self.request.user)


class CollectionCaseViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = CollectionCaseSerializer
    permission_classes = [IsTenantMember]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = CollectionCaseFilter
    ordering_fields = ["created_at", "updated_at", "next_action_date", "priority", "status"]
    ordering = ["-updated_at"]

    @action(detail=True, methods=["get"], url_path="timeline")
    def timeline(self, request, pk=None):
        """
        Timeline "marché": 1 call pour alimenter la page détail dossier.
        GET /api/collection-cases/<id>/timeline/?limit_actions=50
        """
        limit_actions = request.query_params.get("limit_actions")
        try:
            limit_actions = int(limit_actions) if limit_actions else 50
        except ValueError:
            limit_actions = 50

        tenant = self.get_tenant()
        if tenant is None:
            return Response({"detail": "Tenant not resolved."}, status=400)

        # Query dossier + prefetch optimisés
        qs = (
            CollectionCase.objects
            .filter(tenant=tenant, pk=pk)
            .select_related("assigned_to", "portfolio", "debtor")
            .prefetch_related(
                Prefetch(
                    "actions",
                    queryset=CollectionAction.objects.filter(tenant=tenant).order_by("-action_date")[:limit_actions]
                    .select_related("created_by")
                ),
                Prefetch(
                    "promises",
                    queryset=PaymentPromise.objects.filter(tenant=tenant).order_by("-promised_date")
                    .select_related("created_by")
                ),
                Prefetch(
                    "payments",
                    queryset=Payment.objects.filter(tenant=tenant).order_by("-paid_at")
                    .select_related("created_by")
                ),
            )
        )

        case = qs.first()
        if not case:
            return Response({"detail": "Not found."}, status=404)

        payload = {
            "case": case,
            "actions": list(case.actions.all()),
            "promises": list(case.promises.all()),
            "payments": list(case.payments.all()),
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


    def get_queryset(self):
        return self.filter_by_tenant(CollectionCase.objects.all())


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

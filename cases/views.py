# cases/views.py
from django.db import transaction
from django.db.models import Q
from django.db.models import Count, Q, F
from django.utils import timezone

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, ValidationError

from accounts.models import AuditLog
from accounts.tenant_ctx import get_active_tenant, is_tenant_admin
from accounts.permissions import get_active_membership

from cases.models import Portfolio, Debtor, Case, CaseNote, CaseDocument
from cases.serializers import (
    PortfolioSerializer,
    DebtorSerializer,
    CaseSerializer,
    CaseNoteSerializer,
    CaseDocumentSerializer,
)


class TenantScopedViewSet(viewsets.ModelViewSet):
    """
    Base ViewSet: applique le tenant scoping via get_active_tenant(user).
    """
    permission_classes = [IsAuthenticated]

    def get_tenant(self):
        return get_active_tenant(self.request.user)

    def tenant_filter(self, qs):
        tenant = self.get_tenant()
        return qs.filter(tenant=tenant) if tenant else qs.none()


class PortfolioViewSet(TenantScopedViewSet):
    serializer_class = PortfolioSerializer

    def get_queryset(self):
        today = timezone.now().date()

        qs = self.tenant_filter(
            Portfolio.objects.select_related("owner")
            .annotate(
                owner_username=F("owner__username"),
                cases_count=Count("cases", distinct=True),
                open_cases_count=Count(
                    "cases",
                    filter=Q(cases__status__in=["open", "in_progress", "on_hold"]),
                    distinct=True,
                ),
                overdue_cases_count=Count(
                    "cases",
                    filter=Q(cases__due_date__lt=today) & ~Q(cases__status="closed"),
                    distinct=True,
                ),
            )
        )

        # filtres optionnels
        is_active = self.request.query_params.get("is_active")
        if is_active in ("true", "false"):
            qs = qs.filter(is_active=(is_active == "true"))

        priority = (self.request.query_params.get("priority") or "").strip()
        if priority in ("low", "medium", "high"):
            qs = qs.filter(priority=priority)

        q = (self.request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(name__icontains=q)

        return qs.order_by("name")

    def perform_create(self, serializer):
        tenant = self.get_tenant()
        obj = serializer.save(
            tenant=tenant,
            created_by=self.request.user if self.request.user.is_authenticated else None,
            updated_by=self.request.user if self.request.user.is_authenticated else None,
        )

        AuditLog.objects.create(
            action="PORTFOLIO_CREATE",
            actor=self.request.user,
            tenant=tenant,
            entity_type="Portfolio",
            entity_id=obj.id,
            entity_label=obj.name,
        )

    def perform_update(self, serializer):
        tenant = self.get_tenant()
        obj = serializer.save(
            updated_by=self.request.user if self.request.user.is_authenticated else None
        )

        AuditLog.objects.create(
            action="PORTFOLIO_UPDATE",
            actor=self.request.user,
            tenant=tenant,
            entity_type="Portfolio",
            entity_id=obj.id,
            entity_label=obj.name,
        )

    def perform_destroy(self, instance):
        # Suppression: uniquement tenant admin
        m = get_active_membership(self.request.user)
        if not is_tenant_admin(m):
            raise PermissionDenied("Not allowed.")

        tenant = instance.tenant
        label = instance.name
        entity_id = instance.id

        # ✅ ta demande: supprimer et mettre portfolio=null sur les cases
        # (si ta FK est SET_NULL, ce n’est pas obligatoire, mais c’est plus explicite)
        instance.cases.update(portfolio=None)

        instance.delete()

        AuditLog.objects.create(
            action="PORTFOLIO_DELETE",
            actor=self.request.user,
            tenant=tenant,
            entity_type="Portfolio",
            entity_id=entity_id,
            entity_label=label,
        )




class DebtorViewSet(TenantScopedViewSet):
    serializer_class = DebtorSerializer

    def get_queryset(self):
        qs = self.tenant_filter(Debtor.objects.all())

        q = (self.request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(full_name__icontains=q)

        return qs.order_by("full_name")

    def perform_create(self, serializer):
        tenant = self.get_tenant()
        obj = serializer.save(tenant=tenant)

        AuditLog.objects.create(
            action="DEBTOR_CREATE",
            actor=self.request.user,
            tenant=tenant,
            entity_type="Debtor",
            entity_id=obj.id,
            entity_label=obj.full_name,
        )

    def perform_update(self, serializer):
        tenant = self.get_tenant()
        obj = serializer.save()

        AuditLog.objects.create(
            action="DEBTOR_UPDATE",
            actor=self.request.user,
            tenant=tenant,
            entity_type="Debtor",
            entity_id=obj.id,
            entity_label=obj.full_name,
        )

    def perform_destroy(self, instance):
        # Suppression: uniquement tenant admin
        m = get_active_membership(self.request.user)
        if not is_tenant_admin(m):
            raise PermissionDenied("Not allowed.")

        tenant = instance.tenant
        label = instance.full_name
        entity_id = instance.id
        instance.delete()

        AuditLog.objects.create(
            action="DEBTOR_DELETE",
            actor=self.request.user,
            tenant=tenant,
            entity_type="Debtor",
            entity_id=entity_id,
            entity_label=label,
        )


class CaseViewSet(TenantScopedViewSet):
    serializer_class = CaseSerializer
    queryset = Case.objects.select_related("tenant", "debtor", "portfolio", "assigned_to", "customer")

    def get_queryset(self):
        qs = self.tenant_filter(self.queryset)

        # filtres simples
        status_q = self.request.query_params.get("status")
        if status_q:
            qs = qs.filter(status=status_q)

        assigned_to = self.request.query_params.get("assigned_to")
        if assigned_to:
            qs = qs.filter(assigned_to_id=assigned_to)

        # ✅ filtre portefeuille
        portfolio_id = self.request.query_params.get("portfolio")
        if portfolio_id:
            qs = qs.filter(portfolio_id=portfolio_id)

        # ✅ recherche propre (sans casser tenant filter)
        q = (self.request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(title__icontains=q)
                | Q(reference__icontains=q)
                | Q(debtor__full_name__icontains=q)
            )

        return qs.order_by("-id")

    def perform_create(self, serializer):
        tenant = self.get_tenant()

        with transaction.atomic():
            obj = serializer.save(
                tenant=tenant,
                created_by=self.request.user,
            )
            AuditLog.objects.create(
                action="CASE_CREATE",
                actor=self.request.user,
                tenant=tenant,
                entity_type="Case",
                entity_id=obj.id,
                entity_label=obj.reference,
                metadata={"status": obj.status, "priority": obj.priority},
            )

    def perform_update(self, serializer):
        tenant = self.get_tenant()
        obj = serializer.save()

        AuditLog.objects.create(
            action="CASE_UPDATE",
            actor=self.request.user,
            tenant=tenant,
            entity_type="Case",
            entity_id=obj.id,
            entity_label=obj.reference,
        )

    def perform_destroy(self, instance):
        # Suppression: uniquement tenant admin
        m = get_active_membership(self.request.user)
        if not is_tenant_admin(m):
            raise PermissionDenied("Not allowed.")

        tenant = instance.tenant
        ref = instance.reference
        entity_id = instance.id
        instance.delete()

        AuditLog.objects.create(
            action="CASE_DELETE",
            actor=self.request.user,
            tenant=tenant,
            entity_type="Case",
            entity_id=entity_id,
            entity_label=ref,
        )

    @action(detail=True, methods=["GET", "POST"], url_path="notes")
    def notes(self, request, pk=None):
        case = self.get_object()

        if request.method == "GET":
            qs = case.notes.select_related("author").all().order_by("-id")
            return Response(CaseNoteSerializer(qs, many=True).data)

        ser = CaseNoteSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)

        note = CaseNote.objects.create(
            case=case,
            author=request.user,
            body=ser.validated_data["body"],
        )

        AuditLog.objects.create(
            action="CASE_NOTE_CREATE",
            actor=request.user,
            tenant=case.tenant,
            entity_type="CaseNote",
            entity_id=note.id,
            entity_label=case.reference,
        )

        return Response(CaseNoteSerializer(note).data, status=status.HTTP_201_CREATED)

    @action(
        detail=True,
        methods=["GET", "POST"],
        url_path="documents",
        parser_classes=[MultiPartParser, FormParser, JSONParser],
    )
    def documents(self, request, pk=None):
        case = self.get_object()

        if request.method == "GET":
            qs = case.documents.select_related("uploaded_by").all().order_by("-id")
            return Response(CaseDocumentSerializer(qs, many=True, context={"request": request}).data)

        ser = CaseDocumentSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)

        doc = CaseDocument.objects.create(
            case=case,
            customer=case.customer,
            uploaded_by=request.user,
            title=ser.validated_data["title"],
            doc_type=ser.validated_data.get("doc_type", CaseDocument.DocType.OTHER),
            file=ser.validated_data["file"],
        )

        AuditLog.objects.create(
            action="CASE_DOCUMENT_CREATE",
            actor=request.user,
            tenant=case.tenant,
            entity_type="CaseDocument",
            entity_id=doc.id,
            entity_label=case.reference,
            metadata={"title": doc.title, "doc_type": doc.doc_type},
        )

        return Response(
            CaseDocumentSerializer(doc, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )






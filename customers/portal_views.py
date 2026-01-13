# customers/portal_views.py
from django.db import transaction
from django.db.models import Q

from rest_framework import viewsets, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, ValidationError

from cases.models import Case, CaseNote
from cases.serializers import CaseSerializer, CaseNoteSerializer

from .customer_context import get_active_customer_for_user, get_active_customer_membership


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def customer_portal_me(request):
    cm = get_active_customer_membership(request.user)
    if not cm or not cm.customer:
        raise PermissionDenied("No active customer membership.")

    c = cm.customer
    if not c.portal_enabled:
        raise PermissionDenied("Customer portal disabled.")

    return Response({
        "customer": {
            "id": c.id,
            "name": c.name,
            "code": c.code,
            "portal_enabled": c.portal_enabled,
            "tenant_id": c.tenant_id,
        },
        "membership": {
            "id": cm.id,
            "role": cm.role,
            "status": cm.status,
            "is_primary_contact": cm.is_primary_contact,
        }
    })


class CustomerPortalCaseViewSet(viewsets.ModelViewSet):
    """
    ViewSet portail client, scoping: cases appartenant au customer actif.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = CaseSerializer

    queryset = Case.objects.select_related("tenant", "debtor", "portfolio", "assigned_to", "customer")

    # champs modifiables côté client (MVP)
    CLIENT_EDITABLE_FIELDS = {"title", "priority", "due_date", "metadata"}

    def get_customer(self):
        c = get_active_customer_for_user(self.request.user)
        if not c:
            raise PermissionDenied("No active customer.")
        if not c.portal_enabled:
            raise PermissionDenied("Customer portal disabled.")
        return c

    def get_serializer_context(self):
        """
        Important : on injecte tenant=customer.tenant pour que CaseSerializer.validate
        puisse vérifier debtor/portfolio par tenant.
        """
        ctx = super().get_serializer_context()
        customer = self.get_customer()
        ctx["tenant"] = customer.tenant
        return ctx

    def get_queryset(self):
        customer = self.get_customer()
        qs = self.queryset.filter(customer=customer)

        status_q = self.request.query_params.get("status")
        if status_q:
            qs = qs.filter(status=status_q)

        q = (self.request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(title__icontains=q)
                | Q(reference__icontains=q)
                | Q(debtor__full_name__icontains=q)
            )

        return qs.order_by("-id")

    def perform_create(self, serializer):
        """
        Création dossier par client (optionnel).
        On force tenant & customer & created_source=CUSTOMER.
        """
        customer = self.get_customer()

        with transaction.atomic():
            serializer.save(
                tenant=customer.tenant,
                customer=customer,
                created_by=self.request.user,
                created_source=Case.CreatedSource.CUSTOMER,
            )

    def update(self, request, *args, **kwargs):
        # on force PATCH seulement (MVP)
        raise PermissionDenied("Use PATCH for partial updates only.")

    def partial_update(self, request, *args, **kwargs):
        case = self.get_object()

        if case.created_source != Case.CreatedSource.CUSTOMER:
            raise PermissionDenied("You cannot edit this case (not created by customer).")
        if case.created_by_id != request.user.id:
            raise PermissionDenied("You cannot edit a case you did not create.")

        incoming = set(request.data.keys())
        forbidden = incoming - self.CLIENT_EDITABLE_FIELDS
        if forbidden:
            raise ValidationError({"detail": f"Forbidden fields: {', '.join(sorted(forbidden))}."})

        return super().partial_update(request, *args, **kwargs)

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
        return Response(CaseNoteSerializer(note).data, status=status.HTTP_201_CREATED)

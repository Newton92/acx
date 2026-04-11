# collections_management/views.py

from __future__ import annotations

import re

from decimal import Decimal

from django.apps import apps
from django.db import IntegrityError, transaction
from django.db.models import Prefetch

from rest_framework import permissions, viewsets
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError, PermissionDenied
from rest_framework.filters import OrderingFilter
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class CollectionPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200
    page_query_param = "page"

from django_filters.rest_framework import DjangoFilterBackend

from .filters import CollectionCaseFilter
from .models import CollectionCase, CollectionAction, PaymentPromise, Payment, CollectionEmail
from .serializers import (
    CollectionCaseSerializer,
    CollectionActionSerializer,
    PaymentPromiseSerializer,
    PaymentSerializer,
    CollectionEmailSerializer,
)
from .serializers_timeline import CollectionCaseTimelineSerializer
from .services import apply_action_to_case, recompute_case_balances, sync_treasury_for_payment, send_acx_email, attach_outlook_eml


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

        ✅ Amélioration: calcule Total payé / Solde depuis les paiements prefetched,
        donc l'affichage reste correct même si un champ dénormalisé est temporairement désynchronisé.
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

        paid_total = sum((p.amount for p in payments), Decimal("0.00"))
        balance = case.total_due - paid_total
        if balance < Decimal("0.00"):
            balance = Decimal("0.00")

        payload = {
            "case": case,
            "actions": actions,
            "promises": promises,
            "payments": payments,
            "totals": {
                "total_due": str(case.total_due),
                "total_paid": str(paid_total),
                "balance": str(balance),
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
    pagination_class = CollectionPagination
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    ordering_fields = ["action_date", "created_at"]
    ordering = ["-action_date"]

    def get_queryset(self):
        qs = CollectionAction.objects.select_related("case", "case__debtor", "created_by")
        qs = self.filter_by_tenant(qs)

        case_id = self.request.query_params.get("case")
        if case_id:
            qs = qs.filter(case_id=case_id)

        action_type = self.request.query_params.get("action_type")
        if action_type:
            qs = qs.filter(action_type=action_type)

        q = (self.request.query_params.get("q") or "").strip()
        if q:
            from django.db.models import Q
            qs = qs.filter(
                Q(summary__icontains=q) |
                Q(details__icontains=q) |
                Q(case__reference__icontains=q) |
                Q(case__debtor__full_name__icontains=q) |
                Q(case__debtor__name__icontains=q)
            )

        date_from = self.request.query_params.get("date_from")
        if date_from:
            qs = qs.filter(action_date__date__gte=date_from)

        date_to = self.request.query_params.get("date_to")
        if date_to:
            qs = qs.filter(action_date__date__lte=date_to)

        return qs

    def perform_create(self, serializer):
        tenant = self.get_tenant()
        case = serializer.validated_data.get("case")
        if case and case.tenant_id != tenant.id:
            raise ValidationError({"case": "Case does not belong to current tenant."})

        action_obj = serializer.save(tenant=tenant, created_by=self.request.user)

        # ✅ clé pour "Prochaine action" + statut litige
        apply_action_to_case(action_obj)

    def perform_update(self, serializer):
        action_obj = serializer.save()
        apply_action_to_case(action_obj)


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

        promise = serializer.save(tenant=tenant, created_by=self.request.user)

        # ✅ Métier: une promesse en attente est une "prochaine action" (suivi / relance)
        if promise.status == "pending" and promise.promised_date:
            cc = promise.case
            # on renseigne la date; type de relance par défaut si vide
            cc.next_action_date = promise.promised_date
            cc.next_action_type = cc.next_action_type or "call"
            cc.save(update_fields=["next_action_date", "next_action_type", "updated_at"])


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

        received_by = serializer.validated_data.get("received_by") or "acx"
        ta = serializer.validated_data.get("treasury_account")

        # Si un compte est fourni, il doit appartenir au tenant
        if received_by != "customer_direct" and ta is not None and getattr(ta, "tenant_id", None) != tenant.id:
            raise ValidationError({"treasury_account": "Invalid treasury account for this tenant."})

        # Si ACX encaisse et pas de compte => tente compte par défaut (si treasury_management installé)
        if received_by != "customer_direct" and ta is None:
            try:
                from treasury_management.services import get_default_account
                ta = get_default_account(tenant=tenant, currency="XAF")
            except Exception:
                ta = None

        # Créer le paiement (serializer fait déjà le recompute_case_balances)
        if received_by != "customer_direct" and ta is not None:
            payment = serializer.save(tenant=tenant, created_by=self.request.user, treasury_account=ta)
        else:
            payment = serializer.save(tenant=tenant, created_by=self.request.user)

        # Sync trésorerie (mouvement IN si ACX, sinon annulation)
        # require_account=False => ne bloque pas la création si aucun compte n'est configuré (tu peux passer True si tu veux forcer)
        sync_treasury_for_payment(payment, tenant=tenant, require_account=False)

    def perform_update(self, serializer):
        tenant = self.get_tenant()
        payment = serializer.save()

        # Si ACX encaisse et compte vide => tente défaut
        if getattr(payment, "received_by", None) != "customer_direct" and getattr(payment, "treasury_account", None) is None:
            try:
                from treasury_management.services import get_default_account
                ta = get_default_account(tenant=tenant, currency="XAF")
            except Exception:
                ta = None
            if ta is not None:
                payment.treasury_account = ta
                payment.save(update_fields=["treasury_account", "updated_at"])

        sync_treasury_for_payment(payment, tenant=tenant, require_account=False)

    def perform_destroy(self, instance):
        tenant = self.get_tenant()
        case = instance.case

        # Trésorerie : annule le mouvement lié au paiement et détache la FK payment
        # pour éviter un blocage si TreasuryMovement.payment est PROTECT.
        try:
            from treasury_management.models import TreasuryMovement
            TreasuryMovement.objects.filter(tenant=tenant, source_key=f"payment:{instance.id}").update(
                status=TreasuryMovement.Status.CANCELLED,
                payment=None,
            )
        except Exception:
            pass

        try:
            instance.delete()
        except Exception as e:
            # Exemple : si le paiement est déjà inclus dans une remise (RemittanceLine.payment PROTECT)
            raise ValidationError({"detail": f"Cannot delete payment: {str(e)}"})

        recompute_case_balances(case, sync_core_case=True)

# -------------------------------------------------------------------
# CollectionEmail (preuves Outlook / emails attachés)
# -------------------------------------------------------------------

class CollectionEmailViewSet(TenantScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = CollectionEmailSerializer
    permission_classes = [IsTenantMember]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    ordering_fields = ["sent_at", "created_at", "updated_at"]
    ordering = ["-sent_at", "-created_at"]

    queryset = CollectionEmail.objects.all()

    def get_queryset(self):
        qs = self.filter_by_tenant(CollectionEmail.objects.all())
        case_id = self.request.query_params.get("case")
        if case_id:
            qs = qs.filter(case_id=case_id)
        action_id = self.request.query_params.get("action")
        if action_id:
            qs = qs.filter(action_id=action_id)
        return qs

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["request"] = self.request
        return ctx

    @action(
        detail=False,
        methods=["POST"],
        url_path="attach",
        parser_classes=[MultiPartParser, FormParser, JSONParser],
    )
    def attach(self, request):
        '''
        POST /api/collection-emails/attach/
        Form-data:
        - case (required): CollectionCase id
        - action (optional): CollectionAction id (pour attacher à une action email existante)
        - file (required): .eml (export Outlook)
        - notes (optional)
        - direction (optional): outbound|inbound (default outbound)
        - source (optional): outlook|other (default outlook)
        '''
        tenant = self.get_tenant()

        case_id = request.data.get("case") or request.data.get("case_id")
        if not case_id:
            raise ValidationError({"case": "case is required"})

        try:
            case_id = int(case_id)
        except Exception:
            raise ValidationError({"case": "case must be an integer id"})

        case = CollectionCase.objects.filter(tenant=tenant, id=case_id).first()
        if not case:
            raise ValidationError({"case": "Case not found for current tenant."})

        action_id = request.data.get("action") or request.data.get("action_id")
        action_obj = None
        if action_id:
            try:
                action_id = int(action_id)
            except Exception:
                raise ValidationError({"action": "action must be an integer id"})
            action_obj = CollectionAction.objects.filter(tenant=tenant, id=action_id, case=case).first()
            if not action_obj:
                raise ValidationError({"action": "Action not found for current tenant/case."})
            if action_obj.action_type != "email":
                raise ValidationError({"action": "Action must be of type 'email'."})

        f = request.FILES.get("file") or request.FILES.get("eml")
        if not f:
            raise ValidationError({"file": "file (.eml) is required"})

        filename = (getattr(f, "name", "") or "").lower()
        if not filename.endswith(".eml"):
            raise ValidationError({"file": "Only .eml files are supported (export Outlook)."})


        direction = (request.data.get("direction") or "outbound").strip().lower()
        source = (request.data.get("source") or "outlook").strip().lower()
        notes = (request.data.get("notes") or "").strip()

        email_obj, action_obj2 = attach_outlook_eml(
            tenant=tenant,
            case=case,
            eml_file=f,
            created_by=request.user,
            action=action_obj,
            direction=direction,
            source=source,
            notes=notes,
            create_action_if_missing=True,
        )

        data = self.get_serializer(email_obj).data
        data["timeline_action_id"] = action_obj2.id
        return Response(data, status=201)

    @action(
        detail=False,
        methods=["POST"],
        url_path="send",
        parser_classes=[MultiPartParser, FormParser, JSONParser],
    )
    def send(self, request):
        """
        POST /api/collection-emails/send/
        Form-data:
        - case (required): CollectionCase id
        - to (required): "a@x.com,b@y.com" (ou JSON list)
        - cc (optional), bcc (optional)
        - subject (optional)
        - body_text / body_html (optional)
        - from_address (optional)
        - notes (optional)
        - action (optional): CollectionAction id (type=email) à réutiliser
        - attachments (optional): multiples fichiers "attachments"
        """
        tenant = self.get_tenant()

        case_id = request.data.get("case") or request.data.get("case_id")
        if not case_id:
            raise ValidationError({"case": "case is required"})
        try:
            case_id = int(case_id)
        except Exception:
            raise ValidationError({"case": "case must be an integer id"})

        case = CollectionCase.objects.filter(tenant=tenant, id=case_id).first()
        if not case:
            raise ValidationError({"case": "Case not found for current tenant."})

        action_id = request.data.get("action") or request.data.get("action_id")
        action_obj = None
        if action_id:
            try:
                action_id = int(action_id)
            except Exception:
                raise ValidationError({"action": "action must be an integer id"})
            action_obj = CollectionAction.objects.filter(tenant=tenant, id=action_id, case=case).first()
            if not action_obj:
                raise ValidationError({"action": "Action not found for current tenant/case."})
            if action_obj.action_type != "email":
                raise ValidationError({"action": "Action must be of type 'email'."})

        def _parse_emails(v):
            if v is None:
                return []
            if isinstance(v, (list, tuple)):
                return [str(x).strip() for x in v if str(x).strip()]
            s = str(v).strip()
            if not s:
                return []
            # JSON list ?
            if s.startswith("[") and s.endswith("]"):
                try:
                    import json
                    arr = json.loads(s)
                    if isinstance(arr, list):
                        return [str(x).strip() for x in arr if str(x).strip()]
                except Exception:
                    pass
            # split
            parts = re.split(r"[;,]", s)
            return [p.strip() for p in parts if p.strip()]

        to = _parse_emails(request.data.get("to"))
        if not to:
            raise ValidationError({"to": "to is required (one or more emails)."})

        cc = _parse_emails(request.data.get("cc"))
        bcc = _parse_emails(request.data.get("bcc"))
        subject = (request.data.get("subject") or "").strip()
        body_text = (request.data.get("body_text") or request.data.get("body") or "").strip()
        body_html = (request.data.get("body_html") or "").strip()
        from_address = (request.data.get("from_address") or "").strip() or None
        notes = (request.data.get("notes") or "").strip()

        files = request.FILES.getlist("attachments") or []
        email_obj, action_obj2 = send_acx_email(
            tenant=tenant,
            case=case,
            to=to,
            cc=cc,
            bcc=bcc,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            from_address=from_address,
            notes=notes,
            created_by=request.user,
            action=action_obj,
            attachments=files,
        )

        data = self.get_serializer(email_obj).data
        data["timeline_action_id"] = action_obj2.id
        return Response(data, status=201)

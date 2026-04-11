from __future__ import annotations

from decimal import Decimal
from typing import Optional

from django.apps import apps
from django.db import models
from django.db.models import Q
from django.utils import timezone
from rest_framework import permissions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter


class TreasuryPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200
    page_query_param = "page"

from .models import TreasuryAccount, TreasuryMovement, RemittanceBatch
from .serializers import (
    TreasuryAccountSerializer,
    TreasuryMovementSerializer,
    RemittanceBatchSerializer,
    RemittanceLineSerializer,
)
from .services import (
    create_manual_movement,
    create_transfer,
    create_remittance_draft,
    add_payment_to_remittance,
    mark_remittance_paid,
)


# -------------------- Tenant resolution --------------------

def resolve_tenant_from_request(request):
    tenant = getattr(request, "tenant", None)
    if tenant:
        return tenant

    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return None

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
        Membership.objects.select_related("tenant")
        .filter(user=user, status="active")
        .order_by("-id")
        .first()
    )
    return m.tenant if m else None


class IsTenantMember(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)


class TenantScopedMixin:
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


# -------------------- Helpers (safe filtering) --------------------

def _safe_has_field(model, field_name: str) -> bool:
    try:
        model._meta.get_field(field_name)
        return True
    except Exception:
        return False


def _safe_has_relation(model, field_name: str) -> bool:
    try:
        f = model._meta.get_field(field_name)
        return bool(getattr(f, "is_relation", False) and getattr(f, "related_model", None))
    except Exception:
        return False


def _safe_has_path(model, parts: list[str]) -> bool:
    """
    Returns True if model has the nested field path (FK traversals), e.g. ['case','debtor','full_name'].
    This avoids FieldError when the schema differs between deployments.
    """
    m = model
    for i, p in enumerate(parts):
        if not _safe_has_field(m, p):
            return False
        if i == len(parts) - 1:
            return True
        # not last -> must be a relation
        if not _safe_has_relation(m, p):
            return False
        f = m._meta.get_field(p)
        m = f.related_model
    return True


def _parse_dt(value: Optional[str], *, end: bool = False):
    """
    Parse a date/datetime from query params.
    - Accepts ISO datetime (with or without timezone) or YYYY-MM-DD.
    - If end=True and only a date is provided, we return start of next day (to use with __lt).
    """
    if not value:
        return None
    value = value.strip()
    if not value:
        return None

    dt = None
    # Try ISO datetime first
    try:
        # fromisoformat does not accept trailing Z, normalize
        normalized = value.replace("Z", "+00:00")
        dt = timezone.datetime.fromisoformat(normalized)
    except Exception:
        dt = None

    if dt is None:
        # Try YYYY-MM-DD
        try:
            d = timezone.datetime.strptime(value, "%Y-%m-%d")
            dt = d
            if end:
                dt = dt + timezone.timedelta(days=1)
        except Exception:
            return None

    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


def _money_sum_expr(direction: str):
    return models.Sum(
        models.Case(
            models.When(direction=direction, then=models.F("amount")),
            default=models.Value(0),
            output_field=models.DecimalField(max_digits=18, decimal_places=2),
        )
    )


def _money_signed_expr():
    return models.Sum(
        models.Case(
            models.When(direction=TreasuryMovement.Direction.IN, then=models.F("amount")),
            models.When(direction=TreasuryMovement.Direction.OUT, then=-models.F("amount")),
            default=models.Value(0),
            output_field=models.DecimalField(max_digits=18, decimal_places=2),
        )
    )


def _search_debtor_fields(base_model, token: str) -> Q:
    paths = [
        ["case", "debtor", "full_name"],
        ["case", "debtor", "name"],
        ["case", "debtor", "display_name"],
        ["case", "debtor", "first_name"],
        ["case", "debtor", "last_name"],
        ["case", "debtor", "phone"],
    ]
    q = Q()
    for parts in paths:
        if _safe_has_path(base_model, parts):
            lookup = "__".join(parts) + "__icontains"
            q |= Q(**{lookup: token})
    return q


def _search_customer_fields(base_model, token: str) -> Q:
    paths = [
        ["customer", "full_name"],
        ["customer", "name"],
        ["customer", "display_name"],
        ["customer", "company_name"],
        ["customer", "first_name"],
        ["customer", "last_name"],
        ["customer", "phone"],
        ["customer", "email"],
    ]
    q = Q()
    for parts in paths:
        if _safe_has_path(base_model, parts):
            lookup = "__".join(parts) + "__icontains"
            q |= Q(**{lookup: token})
    return q


def _search_portfolio_customer_fields(base_model, token: str) -> Q:
    """
    Some deployments may attach the creditor/customer on case.portfolio.customer OR case.portfolio.client OR case.portfolio.owner.
    We try all combinations safely.
    """
    portfolio_rel = ["case", "portfolio"]
    if not _safe_has_path(base_model, portfolio_rel):
        return Q()

    rel_candidates = ["customer", "client", "owner"]
    name_fields = ["full_name", "name", "display_name", "company_name", "first_name", "last_name", "phone", "email"]

    q = Q()
    for rel in rel_candidates:
        for nf in name_fields:
            parts = ["case", "portfolio", rel, nf]
            if _safe_has_path(base_model, parts):
                lookup = "__".join(parts) + "__icontains"
                q |= Q(**{lookup: token})
    return q


def _apply_text_search(qs, token: str):
    token = (token or "").strip()
    if not token:
        return qs

    base_model = qs.model
    q = Q()

    # simple fields
    for path in ("label", "reference", "notes", "currency"):
        if _safe_has_field(base_model, path):
            q |= Q(**{f"{path}__icontains": token})

    # relations
    if _safe_has_path(base_model, ["account", "name"]):
        q |= Q(account__name__icontains=token)

    if _safe_has_path(base_model, ["case", "reference"]):
        q |= Q(case__reference__icontains=token)
    if _safe_has_path(base_model, ["case", "case_number"]):
        q |= Q(case__case_number__icontains=token)

    if _safe_has_path(base_model, ["payment", "reference"]):
        q |= Q(payment__reference__icontains=token)
    if _safe_has_path(base_model, ["payment", "notes"]):
        q |= Q(payment__notes__icontains=token)

    # debtor / customer
    q |= _search_debtor_fields(base_model, token)
    q |= _search_customer_fields(base_model, token)
    q |= _search_portfolio_customer_fields(base_model, token)

    return qs.filter(q)


# -------------------- ViewSets --------------------

class TreasuryAccountViewSet(TenantScopedMixin, viewsets.ModelViewSet):
    serializer_class = TreasuryAccountSerializer
    permission_classes = [IsTenantMember]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    ordering_fields = ["name", "currency", "is_default", "created_at"]
    ordering = ["-is_default", "name"]

    queryset = TreasuryAccount.objects.all()

    def get_queryset(self):
        return self.filter_by_tenant(TreasuryAccount.objects.all())


class TreasuryMovementViewSet(TenantScopedMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = TreasuryMovementSerializer
    permission_classes = [IsTenantMember]
    pagination_class = TreasuryPagination
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    ordering_fields = ["value_date", "created_at", "amount"]
    ordering = ["-value_date", "-id"]

    queryset = TreasuryMovement.objects.all()

    def get_queryset(self):
        qs = self.filter_by_tenant(
            TreasuryMovement.objects.select_related("account", "customer", "case", "case__debtor", "payment", "remittance")
        )

        # basic filters
        account_id = self.request.query_params.get("account")
        if account_id:
            qs = qs.filter(account_id=account_id)

        customer_id = self.request.query_params.get("customer")
        if customer_id:
            qs = qs.filter(customer_id=customer_id)

        case_id = self.request.query_params.get("case")
        if case_id:
            qs = qs.filter(case_id=case_id)

        direction = self.request.query_params.get("direction")
        if direction:
            qs = qs.filter(direction=direction)

        status = self.request.query_params.get("status")
        if status:
            qs = qs.filter(status=status)

        source = self.request.query_params.get("source")
        if source:
            qs = qs.filter(source=source)

        # richer filters (text)
        q = self.request.query_params.get("q")
        if q:
            qs = _apply_text_search(qs, q)

        debtor_id = self.request.query_params.get("debtor")
        if debtor_id and _safe_has_path(qs.model, ["case", "debtor"]):
            qs = qs.filter(case__debtor_id=debtor_id)

        debtor_q = self.request.query_params.get("debtor_q")
        if debtor_q:
            dq = _search_debtor_fields(qs.model, debtor_q.strip())
            if dq:
                qs = qs.filter(dq)

        customer_q = self.request.query_params.get("customer_q")
        if customer_q:
            cq = _search_customer_fields(qs.model, customer_q.strip()) | _search_portfolio_customer_fields(qs.model, customer_q.strip())
            if cq:
                qs = qs.filter(cq)

        case_q = self.request.query_params.get("case_q")
        if case_q:
            token = case_q.strip()
            if token:
                or_q = Q()
                if _safe_has_path(qs.model, ["case", "reference"]):
                    or_q |= Q(case__reference__icontains=token)
                if _safe_has_path(qs.model, ["case", "case_number"]):
                    or_q |= Q(case__case_number__icontains=token)
                if or_q:
                    qs = qs.filter(or_q)

        # date range (inclusive end)
        date_from = _parse_dt(self.request.query_params.get("date_from"), end=False)
        if date_from:
            qs = qs.filter(value_date__gte=date_from)

        date_to = _parse_dt(self.request.query_params.get("date_to"), end=True)
        if date_to:
            qs = qs.filter(value_date__lt=date_to)

        return qs

    # -------- Summary / KPIs --------

    @action(detail=False, methods=["get"], url_path="summary")
    def summary(self, request):
        """
        Returns totals and per-account balances for the filtered queryset.
        Useful for dashboards & account cards without fetching the whole paginated list.
        """
        qs = self.get_queryset()

        # Default to confirmed (safe for accounting)
        confirmed_only = request.query_params.get("confirmed_only")
        if confirmed_only in ("1", "true", "True", "yes", "on", None, ""):
            # When not provided, we default to confirmed_only=True to be consistent with accounting views
            qs = qs.filter(status=TreasuryMovement.Status.CONFIRMED)

        # totals per currency
        totals = []
        for row in (
            qs.values("currency")
            .annotate(
                total_in=_money_sum_expr(TreasuryMovement.Direction.IN),
                total_out=_money_sum_expr(TreasuryMovement.Direction.OUT),
                net=_money_signed_expr(),
                count=models.Count("id"),
            )
            .order_by("currency")
        ):
            totals.append(
                {
                    "currency": row["currency"],
                    "total_in": str(row["total_in"] or 0),
                    "total_out": str(row["total_out"] or 0),
                    "net": str(row["net"] or 0),
                    "count": int(row["count"] or 0),
                }
            )

        # balances per account (+ currency)
        account_balances = []
        for row in (
            qs.values("account_id", "currency")
            .annotate(
                total_in=_money_sum_expr(TreasuryMovement.Direction.IN),
                total_out=_money_sum_expr(TreasuryMovement.Direction.OUT),
                balance=_money_signed_expr(),
                count=models.Count("id"),
                last_value_date=models.Max("value_date"),
            )
            .order_by("currency", "account_id")
        ):
            account_balances.append(
                {
                    "account": row["account_id"],
                    "currency": row["currency"],
                    "total_in": str(row["total_in"] or 0),
                    "total_out": str(row["total_out"] or 0),
                    "balance": str(row["balance"] or 0),
                    "count": int(row["count"] or 0),
                    "last_value_date": row["last_value_date"],
                }
            )

        return Response({"totals": totals, "account_balances": account_balances})

    @action(detail=False, methods=["get"], url_path="customer-suggestions")
    def customer_suggestions(self, request):
        """
        Suggestions for selecting a creditor/customer (useful for remittances).
        Based on existing treasury movements.
        """
        tenant = self.get_tenant()
        qs = TreasuryMovement.objects.filter(tenant=tenant).exclude(customer__isnull=True)
        qs = qs.filter(status=TreasuryMovement.Status.CONFIRMED)

        # optional search
        q = (request.query_params.get("q") or "").strip()
        if q:
            cq = _search_customer_fields(TreasuryMovement, q) | _search_portfolio_customer_fields(TreasuryMovement, q)
            if cq:
                qs = qs.filter(cq)

        # aggregate
        rows = list(
            qs.values("customer_id")
            .annotate(
                total_in=_money_sum_expr(TreasuryMovement.Direction.IN),
                total_out=_money_sum_expr(TreasuryMovement.Direction.OUT),
                balance=_money_signed_expr(),
                count=models.Count("id"),
                last_value_date=models.Max("value_date"),
            )
            .order_by("-last_value_date")[:50]
        )

        # load customers for names
        CustomerModel = TreasuryMovement._meta.get_field("customer").remote_field.model
        cust_ids = [r["customer_id"] for r in rows if r.get("customer_id")]
        customers = CustomerModel.objects.filter(pk__in=cust_ids)
        name_map = {}
        for c in customers:
            name = None
            for attr in ("full_name", "name", "display_name", "company_name"):
                val = getattr(c, attr, None)
                if val:
                    name = val
                    break
            if not name:
                first = getattr(c, "first_name", None) or ""
                last = getattr(c, "last_name", None) or ""
                name = (f"{first} {last}").strip() or str(c)
            name_map[getattr(c, "id")] = name

        out = []
        for r in rows:
            out.append(
                {
                    "id": r["customer_id"],
                    "name": name_map.get(r["customer_id"]) or f"#{r['customer_id']}",
                    "total_in": str(r["total_in"] or 0),
                    "total_out": str(r["total_out"] or 0),
                    "balance": str(r["balance"] or 0),
                    "count": int(r["count"] or 0),
                    "last_value_date": r["last_value_date"],
                }
            )

        return Response(out)

    @action(detail=False, methods=["get"], url_path="debtor-suggestions")
    def debtor_suggestions(self, request):
        """
        Suggestions for selecting a debtor (from case debtors linked to treasury movements).
        """
        tenant = self.get_tenant()
        qs = TreasuryMovement.objects.filter(tenant=tenant).exclude(case__isnull=True)

        q = (request.query_params.get("q") or "").strip()
        if q:
            dq = _search_debtor_fields(TreasuryMovement, q)
            if dq:
                qs = qs.filter(dq)

        limit = request.query_params.get("limit")
        try:
            limit_n = int(limit) if limit else 50
        except Exception:
            limit_n = 50
        limit_n = max(1, min(limit_n, 200))

        # distinct debtor ids from case FK
        if not _safe_has_path(TreasuryMovement, ["case", "debtor"]):
            return Response([])

        rows = list(
            qs.exclude(case__debtor__isnull=True)
            .values("case__debtor_id")
            .annotate(count=models.Count("id"))
            .order_by("-count")[: limit_n]
        )

        try:
            DebtorModel = TreasuryMovement._meta.get_field("case").remote_field.model._meta.get_field("debtor").remote_field.model
        except Exception:
            return Response([])

        debtor_ids = [r["case__debtor_id"] for r in rows if r.get("case__debtor_id")]
        debtors = DebtorModel.objects.filter(pk__in=debtor_ids)
        name_map = {}
        for d in debtors:
            name = None
            for attr in ("full_name", "name", "display_name"):
                val = getattr(d, attr, None)
                if val:
                    name = val
                    break
            if not name:
                first = getattr(d, "first_name", None) or ""
                last = getattr(d, "last_name", None) or ""
                name = (f"{first} {last}").strip() or str(d)
            name_map[getattr(d, "id")] = name

        out = [{"id": did, "label": name_map.get(did) or f"#{did}"} for did in debtor_ids if did]
        return Response(out)

    # -------- Creation actions (manual & transfer) --------

    class ManualMovementCreateSerializer(serializers.Serializer):
        account = serializers.IntegerField()
        direction = serializers.ChoiceField(choices=[("in", "in"), ("out", "out")])
        amount = serializers.DecimalField(max_digits=18, decimal_places=2)
        currency = serializers.CharField(required=False, allow_blank=True)
        value_date = serializers.DateTimeField(required=False)
        label = serializers.CharField(required=False, allow_blank=True)
        reference = serializers.CharField(required=False, allow_blank=True)
        notes = serializers.CharField(required=False, allow_blank=True)

        # optional dimensions
        customer = serializers.IntegerField(required=False, allow_null=True)
        case = serializers.IntegerField(required=False, allow_null=True)
        payment = serializers.IntegerField(required=False, allow_null=True)
        remittance = serializers.IntegerField(required=False, allow_null=True)

    @action(detail=False, methods=["post"], url_path="manual")
    def create_manual(self, request):
        tenant = self.get_tenant()
        s = self.ManualMovementCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data

        account = TreasuryAccount.objects.filter(pk=data["account"], tenant=tenant).first()
        if not account:
            raise ValidationError({"account": "Invalid account for this tenant."})

        # Resolve FK objects (service expects objects, not ids)
        customer = None
        if data.get("customer"):
            try:
                Customer = apps.get_model("customers", "Customer")
                customer = Customer.objects.filter(pk=data["customer"], tenant=tenant).first()
            except Exception:
                pass

        case = None
        if data.get("case"):
            try:
                Case = apps.get_model("cases", "Case")
                case = Case.objects.filter(pk=data["case"], tenant=tenant).first()
            except Exception:
                pass

        mv = create_manual_movement(
            tenant=tenant,
            account=account,
            direction=data["direction"],
            amount=data["amount"],
            currency=data.get("currency") or account.currency,
            value_date=data.get("value_date"),
            label=data.get("label") or "",
            reference=data.get("reference") or "",
            notes=data.get("notes") or "",
            customer=customer,
            case=case,
            created_by=request.user,
        )
        return Response(TreasuryMovementSerializer(mv).data, status=201)

    class TransferSerializer(serializers.Serializer):
        from_account = serializers.IntegerField()
        to_account = serializers.IntegerField()
        amount = serializers.DecimalField(max_digits=18, decimal_places=2)
        currency = serializers.CharField(required=False, allow_blank=True)
        value_date = serializers.DateTimeField(required=False)
        label = serializers.CharField(required=False, allow_blank=True)
        reference = serializers.CharField(required=False, allow_blank=True)
        notes = serializers.CharField(required=False, allow_blank=True)

    @action(detail=False, methods=["post"], url_path="transfer")
    def transfer(self, request):
        tenant = self.get_tenant()
        s = self.TransferSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data

        from_acc = TreasuryAccount.objects.filter(pk=data["from_account"], tenant=tenant).first()
        to_acc = TreasuryAccount.objects.filter(pk=data["to_account"], tenant=tenant).first()
        if not from_acc:
            raise ValidationError({"from_account": "Invalid source account for this tenant."})
        if not to_acc:
            raise ValidationError({"to_account": "Invalid destination account for this tenant."})
        if from_acc.id == to_acc.id:
            raise ValidationError({"to_account": "Destination must be different from source account."})

        out_mv, in_mv, transfer_key = create_transfer(
            tenant=tenant,
            from_account=from_acc,
            to_account=to_acc,
            amount=data["amount"],
            currency=data.get("currency") or from_acc.currency,
            value_date=data.get("value_date"),
            reference=data.get("reference") or "",
            notes=data.get("notes") or "",
            created_by=request.user,
        )
        return Response(
            {
                "out": TreasuryMovementSerializer(out_mv).data if out_mv else None,
                "in": TreasuryMovementSerializer(in_mv).data if in_mv else None,
                "transfer_key": transfer_key,
            },
            status=201,
        )


class RemittanceBatchViewSet(TenantScopedMixin, viewsets.ModelViewSet):
    serializer_class = RemittanceBatchSerializer
    permission_classes = [IsTenantMember]
    pagination_class = TreasuryPagination
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    ordering_fields = ["id", "created_at", "amount_total", "status"]
    ordering = ["-id"]

    queryset = RemittanceBatch.objects.all()

    def get_queryset(self):
        qs = self.filter_by_tenant(
            RemittanceBatch.objects.select_related("customer", "account").prefetch_related("lines", "lines__payment", "lines__case")
        )

        customer_id = self.request.query_params.get("customer")
        if customer_id:
            qs = qs.filter(customer_id=customer_id)

        status = self.request.query_params.get("status")
        if status:
            qs = qs.filter(status=status)

        q = (self.request.query_params.get("q") or "").strip()
        if q:
            or_q = Q(reference__icontains=q) | Q(notes__icontains=q)
            if q.isdigit():
                or_q |= Q(id=int(q))
            for parts in (
                ["customer", "full_name"],
                ["customer", "name"],
                ["customer", "display_name"],
                ["customer", "company_name"],
                ["customer", "first_name"],
                ["customer", "last_name"],
                ["customer", "phone"],
                ["customer", "email"],
            ):
                if _safe_has_path(RemittanceBatch, parts):
                    or_q |= Q(**{("__".join(parts) + "__icontains"): q})
            qs = qs.filter(or_q)

        return qs

    # -------- Remittance workflow --------

    @action(detail=False, methods=["post"], url_path="draft")
    def create_draft(self, request):
        tenant = self.get_tenant()
        customer_id = request.data.get("customer")
        account_id = request.data.get("account")
        currency = request.data.get("currency", "XAF")
        notes = request.data.get("notes", "")

        if not customer_id:
            raise ValidationError({"customer": "customer is required"})
        if not account_id:
            raise ValidationError({"account": "account is required"})

        Customer = apps.get_model("customers", "Customer")
        customer = Customer.objects.filter(pk=customer_id, tenant=tenant).first()
        if not customer:
            raise ValidationError({"customer": "Invalid customer for this tenant."})

        account = TreasuryAccount.objects.filter(pk=account_id, tenant=tenant).first()
        if not account:
            raise ValidationError({"account": "Invalid account for this tenant."})

        obj = create_remittance_draft(
            tenant=tenant,
            customer=customer,
            account=account,
            currency=currency,
            created_by=request.user,
            notes=notes,
        )
        return Response(self.get_serializer(obj).data, status=201)

    @action(detail=True, methods=["post"], url_path="add-payment")
    def add_payment(self, request, pk=None):
        tenant = self.get_tenant()
        rem = self.get_queryset().filter(pk=pk).first()
        if not rem:
            return Response({"detail": "Not found."}, status=404)

        payment_id = request.data.get("payment")
        amount = request.data.get("amount")
        notes = request.data.get("notes", "")

        if not payment_id:
            raise ValidationError({"payment": "payment is required"})

        Payment = apps.get_model("collections_management", "Payment")
        payment = Payment.objects.filter(pk=payment_id, tenant=tenant).select_related("case").first()
        if not payment:
            raise ValidationError({"payment": "Invalid payment for this tenant."})

        amt = None
        if amount is not None and str(amount).strip() != "":
            try:
                amt = Decimal(str(amount))
            except Exception:
                raise ValidationError({"amount": "Invalid amount"})

        line = add_payment_to_remittance(remittance=rem, payment=payment, amount=amt, notes=notes)
        return Response(RemittanceLineSerializer(line).data, status=201)

    @action(detail=True, methods=["post"], url_path="mark-paid")
    def mark_paid(self, request, pk=None):
        tenant = self.get_tenant()
        rem = self.get_queryset().filter(pk=pk).first()
        if not rem:
            return Response({"detail": "Not found."}, status=404)

        reference = request.data.get("reference", "")
        mv = mark_remittance_paid(remittance=rem, reference=reference, created_by=request.user)
        return Response({"remittance": self.get_serializer(rem).data, "movement_id": mv.id if mv else None})

    # -------- Eligible payments (for UI) --------

    @action(detail=True, methods=["post"], url_path="validate")
    def validate(self, request, pk=None):
        rem = self.get_queryset().filter(pk=pk).first()
        if not rem:
            return Response({"detail": "Not found."}, status=404)
        if rem.status not in (RemittanceBatch.Status.DRAFT,):
            raise ValidationError({"status": f"Cannot validate a remittance with status '{rem.status}'."})
        rem.status = RemittanceBatch.Status.VALIDATED
        rem.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(rem).data)

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        rem = self.get_queryset().filter(pk=pk).first()
        if not rem:
            return Response({"detail": "Not found."}, status=404)
        if rem.status == RemittanceBatch.Status.PAID:
            raise ValidationError({"status": "Cannot cancel a remittance that has already been paid."})
        rem.status = RemittanceBatch.Status.CANCELLED
        rem.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(rem).data)

    @action(detail=False, methods=["get"], url_path="eligible-payments")
    def eligible_payments(self, request):
        """
        List payments that:
        - have generated an IN treasury movement (source=payment) => means the money passed by ACX
        - are NOT already linked to a remittance line
        Optional filters:
        - customer=<id>
        - q=<text> (case ref / debtor / payment ref)
        - limit=<int>
        """
        tenant = self.get_tenant()
        customer_id = request.query_params.get("customer")
        q = (request.query_params.get("q") or "").strip()
        limit = request.query_params.get("limit")
        try:
            limit_n = int(limit) if limit else 50
        except Exception:
            limit_n = 50
        limit_n = max(1, min(limit_n, 200))

        mv_qs = (
            TreasuryMovement.objects.filter(
                tenant=tenant,
                source=TreasuryMovement.Source.PAYMENT,
                direction=TreasuryMovement.Direction.IN,
                status=TreasuryMovement.Status.CONFIRMED,
            )
            .exclude(payment__isnull=True)
            .select_related("customer", "case", "payment", "case__debtor")
            .order_by("-value_date")
        )

        if customer_id:
            mv_qs = mv_qs.filter(customer_id=customer_id)

        if q:
            mv_qs = _apply_text_search(mv_qs, q)

        payment_ids = list(mv_qs.values_list("payment_id", flat=True).distinct()[: (limit_n * 5)])
        if not payment_ids:
            return Response([])

        Payment = apps.get_model("collections_management", "Payment")
        pay_qs = (
            Payment.objects.filter(tenant=tenant, id__in=payment_ids)
            .filter(remittance_lines__isnull=True)  # not already remitted
            .select_related("case", "case__debtor")
            .order_by("-paid_at", "-id")
        )

        mv_map = {}
        for mv in mv_qs:
            pid = getattr(mv, "payment_id", None)
            if pid and pid not in mv_map:
                mv_map[pid] = mv

        def _debtor_name(case):
            debtor = getattr(case, "debtor", None) if case else None
            if not debtor:
                return None
            for attr in ("full_name", "name", "display_name", "label"):
                val = getattr(debtor, attr, None)
                if val:
                    return val
            first = getattr(debtor, "first_name", None) or ""
            last = getattr(debtor, "last_name", None) or ""
            nm = (f"{first} {last}").strip()
            return nm or str(debtor)

        def _customer_name(cust):
            if not cust:
                return None
            for attr in ("full_name", "name", "display_name", "company_name"):
                val = getattr(cust, attr, None)
                if val:
                    return val
            first = getattr(cust, "first_name", None) or ""
            last = getattr(cust, "last_name", None) or ""
            nm = (f"{first} {last}").strip()
            return nm or str(cust)

        out = []
        for p in pay_qs[:limit_n]:
            case = getattr(p, "case", None)
            mv = mv_map.get(getattr(p, "id"))
            cust = getattr(mv, "customer", None) if mv else None
            currency = getattr(p, "currency", None) or getattr(case, "currency", None) or "XAF"

            out.append(
                {
                    "id": getattr(p, "id"),
                    "amount": str(getattr(p, "amount", 0) or 0),
                    "currency": currency,
                    "paid_at": getattr(p, "paid_at", None),
                    "reference": getattr(p, "reference", None) or "",
                    "case_id": getattr(case, "id", None) if case else None,
                    "case_reference": getattr(case, "reference", None) or getattr(case, "case_number", None) or (str(case) if case else None),
                    "debtor_name": _debtor_name(case),
                    "customer_id": getattr(cust, "id", None) if cust else None,
                    "customer_name": _customer_name(cust),
                }
            )

        return Response(out)
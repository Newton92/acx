from __future__ import annotations

from django.apps import apps
from rest_framework import serializers

from .models import TreasuryAccount, TreasuryMovement, RemittanceBatch, RemittanceLine


def _customer_display(customer) -> str | None:
    """Best-effort display name for a Customer instance."""
    if not customer:
        return None

    # Common fields (we keep this defensive because Customer schema may vary)
    for attr in ("full_name", "name", "company_name", "display_name", "title"):
        v = getattr(customer, attr, None)
        if isinstance(v, str) and v.strip():
            return v.strip()

    try:
        s = str(customer)
        return s if s and s.strip() else None
    except Exception:
        return None


def _resolve_customer_from_portfolio(portfolio):
    """Try to resolve a customer object from a portfolio-like object."""
    if not portfolio:
        return None
    # Most common naming
    for attr in ("customer", "client", "owner"):
        try:
            v = getattr(portfolio, attr, None)
        except Exception:
            v = None
        if v:
            return v
    return None


class TreasuryAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = TreasuryAccount
        fields = [
            "id",
            "tenant",
            "name",
            "type",
            "currency",
            "is_default",
            "metadata",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["tenant", "created_by", "created_at", "updated_at"]


class TreasuryMovementSerializer(serializers.ModelSerializer):
    account_name = serializers.SerializerMethodField()
    account_currency = serializers.SerializerMethodField()
    case_reference = serializers.SerializerMethodField()
    customer_name = serializers.SerializerMethodField()
    debtor_name = serializers.SerializerMethodField()
    source_label = serializers.SerializerMethodField()
    direction_label = serializers.SerializerMethodField()
    status_label = serializers.SerializerMethodField()

    def get_account_name(self, obj) -> str | None:
        acc = getattr(obj, "account", None)
        return getattr(acc, "name", None) if acc else None

    def get_account_currency(self, obj) -> str | None:
        acc = getattr(obj, "account", None)
        return getattr(acc, "currency", None) if acc else None

    def get_case_reference(self, obj) -> str | None:
        case = getattr(obj, "case", None)
        return getattr(case, "reference", None) or getattr(case, "case_number", None) if case else None

    def get_debtor_name(self, obj) -> str | None:
        case = getattr(obj, "case", None)
        if not case:
            return None
        debtor = getattr(case, "debtor", None)
        if not debtor:
            return None
        for attr in ("full_name", "name", "display_name", "label"):
            val = getattr(debtor, attr, None)
            if val:
                return val
        first = getattr(debtor, "first_name", None) or ""
        last = getattr(debtor, "last_name", None) or ""
        name = (f"{first} {last}").strip()
        return name or str(debtor)

    def _resolve_customer_from_case(self, obj):
        """
        Best-effort customer resolution even if obj.customer is NULL.

        Why?
        Some legacy movements might have been created without setting `customer`.
        We still want the journal to show the client and allow the UI to display it.
        """
        # 1) direct FK
        customer = getattr(obj, "customer", None)
        if customer:
            return customer

        # 2) via collection case -> portfolio
        case = getattr(obj, "case", None)
        portfolio = getattr(case, "portfolio", None) if case else None
        customer = _resolve_customer_from_portfolio(portfolio)
        if customer:
            return customer

        # 3) via core Case model (cases.Case) using reference (if available)
        ref = getattr(case, "reference", None) if case else None
        tenant = getattr(obj, "tenant", None)
        if ref and tenant:
            try:
                CoreCase = apps.get_model("cases", "Case")
                core = (
                    CoreCase.objects.filter(tenant=tenant, reference=ref)
                    .select_related("portfolio")
                    .first()
                )
                if core:
                    # Some schemas may store customer directly on core case
                    customer = getattr(core, "customer", None) or getattr(core, "client", None)
                    if customer:
                        return customer
                    customer = _resolve_customer_from_portfolio(getattr(core, "portfolio", None))
                    if customer:
                        return customer
            except Exception:
                # Do not crash serialization
                return None

        return None

    def get_customer_name(self, obj) -> str | None:
        customer = self._resolve_customer_from_case(obj)
        return _customer_display(customer)

    def get_source_label(self, obj) -> str:
        try:
            return obj.get_source_display()
        except Exception:
            return getattr(obj, "source", "") or ""

    def get_direction_label(self, obj) -> str:
        try:
            return obj.get_direction_display()
        except Exception:
            return getattr(obj, "direction", "") or ""

    def get_status_label(self, obj) -> str:
        try:
            return obj.get_status_display()
        except Exception:
            return getattr(obj, "status", "") or ""

    class Meta:
        model = TreasuryMovement
        fields = [
            "id",
            "tenant",
            "account",
            "account_name",
            "account_currency",
            "direction",
            "direction_label",
            "status",
            "status_label",
            "amount",
            "currency",
            "value_date",
            "label",
            "reference",
            "customer",
            "customer_name",
            "debtor_name",
            "case",
            "case_reference",
            "payment",
            "remittance",
            "source",
            "source_label",
            "source_key",
            "notes",
            "created_by",
            "created_at",
        ]
        read_only_fields = ["tenant", "created_by", "created_at"]


class RemittanceLineSerializer(serializers.ModelSerializer):
    # Champs dérivés pour un meilleur affichage côté front
    payment_reference = serializers.SerializerMethodField()
    payment_paid_at = serializers.SerializerMethodField()
    payment_amount = serializers.SerializerMethodField()
    payment_currency = serializers.SerializerMethodField()

    case_reference = serializers.SerializerMethodField()
    debtor_name = serializers.SerializerMethodField()

    def get_payment_reference(self, obj: RemittanceLine):
        p = getattr(obj, "payment", None)
        if not p:
            return None
        ref = getattr(p, "reference", None) or getattr(p, "external_reference", None)
        return ref or f"#{getattr(p, 'id', '')}"

    def get_payment_paid_at(self, obj: RemittanceLine):
        p = getattr(obj, "payment", None)
        return getattr(p, "paid_at", None) if p else None

    def get_payment_amount(self, obj: RemittanceLine):
        p = getattr(obj, "payment", None)
        return getattr(p, "amount", None) if p else None

    def get_payment_currency(self, obj: RemittanceLine):
        p = getattr(obj, "payment", None)
        if p and getattr(p, "currency", None):
            return getattr(p, "currency", None)
        case = getattr(obj, "case", None) or getattr(getattr(obj, "payment", None), "case", None)
        return getattr(case, "currency", None) if case else None

    def get_case_reference(self, obj: RemittanceLine):
        case = getattr(obj, "case", None) or getattr(getattr(obj, "payment", None), "case", None)
        if not case:
            return None
        return getattr(case, "reference", None) or getattr(case, "case_number", None) or str(case)

    def get_debtor_name(self, obj: RemittanceLine):
        case = getattr(obj, "case", None) or getattr(getattr(obj, "payment", None), "case", None)
        debtor = getattr(case, "debtor", None) if case else None
        if not debtor:
            return None
        for attr in ("full_name", "name", "display_name", "label"):
            val = getattr(debtor, attr, None)
            if val:
                return val
        first = getattr(debtor, "first_name", None) or ""
        last = getattr(debtor, "last_name", None) or ""
        name = (f"{first} {last}").strip()
        return name or str(debtor)

    class Meta:
        model = RemittanceLine
        fields = [
            "id",
            "remittance",
            "payment",
            "case",
            "amount",
            "notes",
            "created_at",
            # Derived
            "payment_reference",
            "payment_paid_at",
            "payment_amount",
            "payment_currency",
            "case_reference",
            "debtor_name",
        ]
        read_only_fields = ["created_at"]


class RemittanceBatchSerializer(serializers.ModelSerializer):
    customer_name = serializers.SerializerMethodField()
    account_name = serializers.SerializerMethodField()
    lines = RemittanceLineSerializer(many=True, read_only=True)

    def get_customer_name(self, obj) -> str | None:
        return _customer_display(getattr(obj, "customer", None))

    def get_account_name(self, obj) -> str | None:
        acc = getattr(obj, "account", None)
        return getattr(acc, "name", None) if acc else None

    class Meta:
        model = RemittanceBatch
        fields = [
            "id",
            "tenant",
            "customer",
            "customer_name",
            "account",
            "account_name",
            "currency",
            "amount_total",
            "status",
            "reference",
            "notes",
            "paid_at",
            "created_by",
            "created_at",
            "updated_at",
            "lines",
        ]
        read_only_fields = ["tenant", "amount_total", "created_by", "created_at", "updated_at"]

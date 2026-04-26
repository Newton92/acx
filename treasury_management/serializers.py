from __future__ import annotations

from django.apps import apps
from django.conf import settings as django_settings
from rest_framework import serializers

from .models import TreasuryAccount, TreasuryMovement, RemittanceBatch, RemittanceLine

# ACX_DEBTOR_MODEL == "customers.Customer" signifie que CollectionCase.debtor
# pointe vers customers.Customer (le créancier/client du tenant), PAS le vrai débiteur.
_DEBTOR_IS_CUSTOMER = (
    getattr(django_settings, "ACX_DEBTOR_MODEL", "") == "customers.Customer"
)


def _customer_display(customer) -> str | None:
    """Best-effort display name for a Customer instance."""
    if not customer:
        return None

    for attr in ("full_name", "name", "company_name", "display_name", "title"):
        v = getattr(customer, attr, None)
        if isinstance(v, str) and v.strip():
            return v.strip()

    try:
        s = str(customer)
        return s if s and s.strip() else None
    except Exception:
        return None


def _debtor_display(debtor) -> str | None:
    """Best-effort display name for a Debtor instance (person owing money)."""
    if not debtor:
        return None
    for attr in ("full_name", "name", "display_name", "label"):
        val = getattr(debtor, attr, None)
        if val:
            return val
    first = getattr(debtor, "first_name", None) or ""
    last  = getattr(debtor, "last_name",  None) or ""
    name  = f"{first} {last}".strip()
    return name or str(debtor)


def _resolve_customer_from_portfolio(portfolio):
    """Try to resolve a customer object from a portfolio-like object."""
    if not portfolio:
        return None
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

    def _get_core_case(self, obj):
        """
        Charge cases.Case via la référence du CollectionCase lié.
        Résultat mis en cache sur l'instance pour éviter deux requêtes par ligne.
        """
        if getattr(obj, "_acx_core_case_loaded", False):
            return getattr(obj, "_acx_core_case", None)
        obj._acx_core_case_loaded = True

        case = getattr(obj, "case", None)
        ref  = getattr(case, "reference", None) if case else None
        tenant = getattr(obj, "tenant", None)

        if not ref or not tenant:
            obj._acx_core_case = None
            return None

        try:
            CoreCase = apps.get_model("cases", "Case")
            core = (
                CoreCase.objects.filter(tenant=tenant, reference=ref)
                .select_related("debtor", "portfolio")
                .first()
            )
            obj._acx_core_case = core
            return core
        except Exception:
            obj._acx_core_case = None
            return None

    def get_customer_name(self, obj) -> str | None:
        # 1) FK directe sur le mouvement (bien renseignée)
        customer = getattr(obj, "customer", None)
        if customer:
            return _customer_display(customer)

        # 2) CollectionCase.debtor pointe vers customers.Customer dans ACX
        if _DEBTOR_IS_CUSTOMER:
            case = getattr(obj, "case", None)
            debtor_as_customer = getattr(case, "debtor", None) if case else None
            if debtor_as_customer:
                return _customer_display(debtor_as_customer)

        # 3) Via cases.Case.customer (fallback)
        core = self._get_core_case(obj)
        if core:
            customer = getattr(core, "customer", None) or getattr(core, "client", None)
            if customer:
                return _customer_display(customer)
            customer = _resolve_customer_from_portfolio(getattr(core, "portfolio", None))
            if customer:
                return _customer_display(customer)

        return None

    def get_debtor_name(self, obj) -> str | None:
        # Le vrai débiteur (personne qui doit l'argent) est sur cases.Case.debtor.
        # CollectionCase.debtor pointe vers customers.Customer dans cette config ACX,
        # donc on NE lit PAS case.debtor ici.
        core = self._get_core_case(obj)
        if core:
            return _debtor_display(getattr(core, "debtor", None))
        return None

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

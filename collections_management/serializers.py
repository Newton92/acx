# collections_management/serializers.py
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from django.db import transaction
from rest_framework import serializers

from .models import CollectionCase, CollectionAction, PaymentPromise, Payment, CollectionEmail, CollectionEmailAttachment
from .services import recompute_case_balances


def _dump_meta(meta: Dict[str, Any]) -> str:
    # Stockage robuste dans un TextField (details/notes)
    return json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True)


def _try_load_json(s: str) -> Optional[Dict[str, Any]]:
    s = (s or "").strip()
    if not s:
        return None
    try:
        v = json.loads(s)
        return v if isinstance(v, dict) else None
    except Exception:
        return None


class CollectionCaseSerializer(serializers.ModelSerializer):
    total_due = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)
    balance = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)

    # Lecture dénormalisée
    customer_name = serializers.CharField(source="customer.name", read_only=True, default=None)
    creditor_name = serializers.SerializerMethodField(read_only=True)

    def get_creditor_name(self, obj):
        if obj.creditor_id:
            return obj.creditor.name
        return obj.customer.name if obj.customer_id else None

    class Meta:
        model = CollectionCase
        fields = [
            "id",
            "tenant",
            "reference",
            "customer",
            "customer_name",
            "creditor",
            "creditor_name",
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
            "total_due",
            "balance",
            "due_date",
            "next_action_type",
            "next_action_date",
            "notes",
            "created_by",
            "created_at",
            "updated_at",
            "is_overdue",
        ]
        read_only_fields = ["tenant", "created_by", "created_at", "updated_at"]


class CollectionActionSerializer(serializers.ModelSerializer):
    # ✅ Permet au front d'envoyer tous les paramètres structurés (appel/sms/email/etc.)
    meta = serializers.JSONField(required=False, write_only=True)

    # Champs dénormalisés pour les vues liste
    details_json          = serializers.SerializerMethodField(read_only=True)
    case_reference        = serializers.SerializerMethodField(read_only=True)
    debtor_name           = serializers.SerializerMethodField(read_only=True)
    created_by_username   = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = CollectionAction
        fields = [
            "id",
            "tenant",
            "case",
            "case_reference",
            "debtor_name",
            "action_type",
            "outcome",
            "summary",
            "details",
            "details_json",
            "meta",
            "action_date",
            "next_action_type",
            "next_action_date",
            "created_by",
            "created_by_username",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["tenant", "created_by", "created_at", "updated_at"]

    def get_details_json(self, obj: CollectionAction):
        return _try_load_json(getattr(obj, "details", "") or "")

    def get_case_reference(self, obj: CollectionAction) -> str | None:
        case = getattr(obj, "case", None)
        if not case:
            return None
        return getattr(case, "reference", None) or getattr(case, "case_number", None)

    def get_debtor_name(self, obj: CollectionAction) -> str | None:
        case = getattr(obj, "case", None)
        debtor = getattr(case, "debtor", None) if case else None
        if not debtor:
            return None
        for attr in ("full_name", "name", "display_name", "label"):
            val = getattr(debtor, attr, None)
            if val:
                return val
        first = getattr(debtor, "first_name", None) or ""
        last = getattr(debtor, "last_name", None) or ""
        return (f"{first} {last}").strip() or str(debtor)

    def get_created_by_username(self, obj: CollectionAction) -> str | None:
        user = getattr(obj, "created_by", None)
        if not user:
            return None
        return getattr(user, "username", None) or getattr(user, "email", None)

    def validate(self, attrs):
        # Fusion meta -> details si meta fourni
        meta = attrs.pop("meta", None)
        if meta is not None:
            if not isinstance(meta, dict):
                raise serializers.ValidationError({"meta": "meta must be a JSON object."})

            details = (attrs.get("details") or "").strip()
            meta_dump = _dump_meta(meta)

            if not details:
                attrs["details"] = meta_dump
            else:
                # On conserve le texte existant + attache meta
                attrs["details"] = f"{details}\n\nMETA:\n{meta_dump}"

        return attrs


class PaymentPromiseSerializer(serializers.ModelSerializer):
    # ✅ paramètres additionnels (canal, promesse faite par, etc.) stockés dans notes
    meta = serializers.JSONField(required=False, write_only=True)

    notes_json = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = PaymentPromise
        fields = [
            "id",
            "tenant",
            "case",
            "amount",
            "promised_date",
            "status",
            "notes",
            "notes_json",
            "meta",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["tenant", "created_by", "created_at", "updated_at"]

    def get_notes_json(self, obj: PaymentPromise):
        return _try_load_json(getattr(obj, "notes", "") or "")

    def validate(self, attrs):
        meta = attrs.pop("meta", None)
        if meta is not None:
            if not isinstance(meta, dict):
                raise serializers.ValidationError({"meta": "meta must be a JSON object."})

            notes = (attrs.get("notes") or "").strip()
            meta_dump = _dump_meta(meta)

            if not notes:
                attrs["notes"] = meta_dump
            else:
                attrs["notes"] = f"{notes}\n\nMETA:\n{meta_dump}"

        return attrs


class PaymentSerializer(serializers.ModelSerializer):
    """
    ⚠️ IMPORTANT :
    - Dans ta version actuelle, PaymentSerializer est défini DEUX FOIS.
      Le 2ᵉ écrase le 1er => le recompute ne se fait pas.
    - Ici: on garde un SEUL PaymentSerializer, avec meta + recalcul des agrégats.
    """

    # ✅ paramètres additionnels (référence externe, banque, opérateur, etc.) stockés dans notes
    meta = serializers.JSONField(required=False, write_only=True)
    notes_json = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Payment
        fields = [
            "id",
            "tenant",
            "case",
            "amount",
            "paid_at",
            "method",
            "received_by",
            "treasury_account",
            "reference",
            "notes",
            "notes_json",
            "meta",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["tenant", "created_by", "created_at", "updated_at"]

    def get_notes_json(self, obj: Payment):
        return _try_load_json(getattr(obj, "notes", "") or "")

    def validate(self, attrs):
        meta = attrs.pop("meta", None)
        if meta is not None:
            if not isinstance(meta, dict):
                raise serializers.ValidationError({"meta": "meta must be a JSON object."})

            notes = (attrs.get("notes") or "").strip()
            meta_dump = _dump_meta(meta)

            if not notes:
                attrs["notes"] = meta_dump
            else:
                attrs["notes"] = f"{notes}\n\nMETA:\n{meta_dump}"

        # --- Trésorerie (entrée/sortie) ---
        received_by = attrs.get("received_by") or (getattr(self.instance, "received_by", None) if self.instance else None) or "acx"
        if received_by == "customer_direct":
            # Paiement direct chez le client => aucun compte de trésorerie
            attrs["treasury_account"] = None
        else:
            ta = attrs.get("treasury_account")
            if ta is not None:
                # On tente d'inférer le tenant via request.tenant ou via case.tenant
                tenant = None
                req = self.context.get("request")
                if req is not None:
                    tenant = getattr(req, "tenant", None)
                if tenant is None:
                    c = attrs.get("case") or (getattr(self.instance, "case", None) if self.instance else None)
                    tenant = getattr(c, "tenant", None)

                if tenant is not None and getattr(ta, "tenant_id", None) != getattr(tenant, "id", None):
                    raise serializers.ValidationError({"treasury_account": "Invalid treasury account for this tenant."})

        return attrs

    def create(self, validated_data):
        with transaction.atomic():
            payment = super().create(validated_data)
            recompute_case_balances(payment.case, sync_core_case=True)
        return payment

    def update(self, instance, validated_data):
        with transaction.atomic():
            payment = super().update(instance, validated_data)
            recompute_case_balances(payment.case, sync_core_case=True)
        return payment

class CollectionEmailAttachmentSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = CollectionEmailAttachment
        fields = ["id", "filename", "content_type", "size", "file_url", "created_at"]
        read_only_fields = fields

    def get_file_url(self, obj: CollectionEmailAttachment):
        request = self.context.get("request")
        f = getattr(obj, "file", None)
        if not f:
            return None
        if request:
            return request.build_absolute_uri(f.url)
        return f.url


class CollectionEmailSerializer(serializers.ModelSerializer):
    raw_eml_url = serializers.SerializerMethodField()
    attachments = CollectionEmailAttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = CollectionEmail
        fields = [
            "id",
            "tenant",
            "case",
            "action",
            "direction",
            "source",
            "status",
            "provider",
            "provider_message_id",
            "error_message",
            "from_address",
            "to",
            "cc",
            "bcc",
            "subject",
            "sent_at",
            "message_id",
            "raw_eml_url",
            "body_text",
            "body_html",
            "notes",
            "attachments",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["tenant", "created_by", "created_at", "updated_at"]

    def get_raw_eml_url(self, obj: CollectionEmail):
        request = self.context.get("request")
        f = getattr(obj, "raw_eml", None)
        if not f:
            return None
        if request:
            return request.build_absolute_uri(f.url)
        return f.url

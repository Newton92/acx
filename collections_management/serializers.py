from __future__ import annotations

import json
from typing import Any, Dict, Optional

from django.db import transaction
from rest_framework import serializers

from .models import CollectionCase, CollectionAction, PaymentPromise, Payment
from .services import recompute_case_balances


class PaymentSerializer(serializers.ModelSerializer):
    def create(self, validated_data):
        with transaction.atomic():
            payment = super().create(validated_data)
            recompute_case_balances(payment.case)
        return payment


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

    class Meta:
        model = CollectionCase
        fields = [
            "id",
            "tenant",
            "reference",
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
    # Ils seront persistés dans "details" (TextField) sous forme JSON.
    meta = serializers.JSONField(required=False, write_only=True)

    # Optionnel : expose une vue JSON si "details" contient du JSON
    details_json = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = CollectionAction
        fields = [
            "id",
            "tenant",
            "case",
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
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["tenant", "created_by", "created_at", "updated_at"]

    def get_details_json(self, obj: CollectionAction):
        return _try_load_json(getattr(obj, "details", "") or "")

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

        return attrs

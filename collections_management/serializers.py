from rest_framework import serializers
from .models import CollectionCase, CollectionAction, PaymentPromise, Payment


class CollectionCaseSerializer(serializers.ModelSerializer):
    total_due = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)
    balance = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)

    class Meta:
        model = CollectionCase
        fields = [
            "id","tenant","reference","portfolio","debtor",
            "status","priority","assigned_to",
            "principal_amount","interest_amount","penalty_amount","fees_amount",
            "total_paid_amount","total_due","balance",
            "due_date","next_action_type","next_action_date","notes",
            "created_by","created_at","updated_at","is_overdue",
        ]
        read_only_fields = ["tenant","created_by","created_at","updated_at"]


class CollectionActionSerializer(serializers.ModelSerializer):
    class Meta:
        model = CollectionAction
        fields = [
            "id","tenant","case",
            "action_type","outcome","summary","details","action_date",
            "next_action_type","next_action_date",
            "created_by","created_at","updated_at",
        ]
        read_only_fields = ["tenant","created_by","created_at","updated_at"]


class PaymentPromiseSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentPromise
        fields = [
            "id","tenant","case","amount","promised_date","status","notes",
            "created_by","created_at","updated_at",
        ]
        read_only_fields = ["tenant","created_by","created_at","updated_at"]


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = [
            "id","tenant","case","amount","paid_at","method","reference","notes",
            "created_by","created_at","updated_at",
        ]
        read_only_fields = ["tenant","created_by","created_at","updated_at"]

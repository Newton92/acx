from rest_framework import serializers

from accounts.models import Role, Membership
from .models import Tenant, TenantLicense


class TenantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = "__all__"
        read_only_fields = ("id", "slug", "created_at", "updated_at")

    def validate_country(self, value):
        if value and len(value) != 2:
            raise serializers.ValidationError("country must be ISO2 (e.g. TD, FR).")
        return value.upper() if value else value

    def validate_currency(self, value):
        return value.upper() if value else value

    def validate_locale(self, value):
        return value.lower() if value else value


class TenantLiteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = ["id", "name", "slug", "status"]


class TenantLicenseSerializer(serializers.ModelSerializer):
    is_expired     = serializers.SerializerMethodField()
    days_remaining = serializers.SerializerMethodField()

    def get_is_expired(self, obj) -> bool:
        return obj.is_expired

    def get_days_remaining(self, obj):
        return obj.days_remaining

    class Meta:
        model = TenantLicense
        fields = [
            "id", "tenant", "plan", "starts_at", "expires_at",
            "is_active", "notes",
            "is_expired", "days_remaining",
            "created_by", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "tenant", "is_expired", "days_remaining",
            "created_by", "created_at", "updated_at",
        ]

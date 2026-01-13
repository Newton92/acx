from rest_framework import serializers

from accounts.models import Role, Membership
from .models import Tenant

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


from rest_framework import serializers
from .models import Tenant

class TenantLiteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = ["id", "name", "slug", "status"]


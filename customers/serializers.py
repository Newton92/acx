# customers/serializers.py
from django.apps import apps
from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import Customer, CustomerMembership, Creditor

User = get_user_model()


class CustomerPortalMeSerializer(serializers.Serializer):
    customer = serializers.SerializerMethodField()
    institute = serializers.SerializerMethodField()
    user = serializers.SerializerMethodField()
    membership = serializers.SerializerMethodField()

    def get_customer(self, m: CustomerMembership):
        c = m.customer
        return {
            "id": c.id,
            "name": getattr(c, "name", None),
            "code": getattr(c, "code", None),
            "portal_enabled": getattr(c, "portal_enabled", True),
            "tenant_id": getattr(c, "tenant_id", None),
        }

    def get_institute(self, m: CustomerMembership):
        """
        Institute = Tenant (ACREMAC / institution).
        Supporte:
        - customer.tenant (FK)
        - customer.tenant_id (int) => lookup Tenant
        """
        c = m.customer

        # 1) Si FK existe: customer.tenant
        tenant_obj = getattr(c, "tenant", None)
        if tenant_obj is not None:
            return {
                "id": getattr(tenant_obj, "id", None),
                "name": getattr(tenant_obj, "name", None),
            }

        # 2) Sinon lookup via tenant_id
        tenant_id = getattr(c, "tenant_id", None)
        if not tenant_id:
            return {"id": None, "name": None}

        # ⚠️ adapte "tenancy" si ton app s'appelle autrement
        Tenant = apps.get_model("tenancy", "Tenant")

        t = Tenant.objects.filter(id=tenant_id).only("id", "name").first()
        return {
            "id": t.id if t else tenant_id,
            "name": getattr(t, "name", None),
        }

    def get_user(self, m: CustomerMembership):
        u = m.user
        return {
            "id": u.id,
            "username": getattr(u, "username", None),
            "email": getattr(u, "email", None),
            "first_name": getattr(u, "first_name", None),
            "last_name": getattr(u, "last_name", None),
        }

    def get_membership(self, m: CustomerMembership):
        return {
            "id": m.id,
            "role": getattr(m, "role", None),
            "status": getattr(m, "status", None),
            "is_primary_contact": getattr(m, "is_primary_contact", False),
        }

class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = [
            "id",
            "tenant",
            "name",
            "code",
            "email",
            "phone",
            "country",
            "city",
            "address",
            "status",
            "metadata",
            "portal_enabled",
            "created_by",
            "created_at",
        ]
        read_only_fields = ["id", "tenant", "created_by", "created_at"]


class CreditorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Creditor
        fields = [
            "id",
            "tenant",
            "name",
            "code",
            "type",
            "email",
            "phone",
            "country",
            "city",
            "address",
            "tax_id",
            "is_active",
            "notes",
            "created_by",
            "created_at",
        ]
        read_only_fields = ["id", "tenant", "created_by", "created_at"]


class CustomerMembershipSerializer(serializers.ModelSerializer):
    user_label = serializers.SerializerMethodField()
    user_email = serializers.EmailField(source="user.email", read_only=True)
    user_username = serializers.CharField(source="user.username", read_only=True)
    user_first_name = serializers.CharField(source="user.first_name", read_only=True)
    user_last_name = serializers.CharField(source="user.last_name", read_only=True)
    user_is_active = serializers.BooleanField(source="user.is_active", read_only=True)

    user_telephone = serializers.CharField(source="user.telephone", read_only=True)
    user_departement = serializers.CharField(source="user.departement", read_only=True)

    class Meta:
        model = CustomerMembership
        fields = [
            "id",
            "customer",
            "user",
            "user_label",
            "user_email",
            "user_username",
            "user_first_name",
            "user_last_name",
            "user_is_active",
            "user_telephone",
            "user_departement",
            "role",
            "status",
            "is_primary_contact",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "user_label",
            "user_email",
            "user_username",
            "user_first_name",
            "user_last_name",
            "user_is_active",
            "user_telephone",
            "user_departement",
        ]

    def get_user_label(self, obj):
        u = obj.user
        full = (f"{u.first_name} {u.last_name}").strip()
        return full or u.username or u.email


class CustomerMembershipUpdateSerializer(serializers.Serializer):
    # membership
    role = serializers.ChoiceField(choices=CustomerMembership.Role.choices, required=False)
    status = serializers.ChoiceField(choices=CustomerMembership.Status.choices, required=False)
    is_primary_contact = serializers.BooleanField(required=False)

    # user
    email = serializers.EmailField(required=False)
    username = serializers.CharField(required=False)
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)
    telephone = serializers.CharField(required=False, allow_blank=True)
    departement = serializers.CharField(required=False, allow_blank=True)
    is_active = serializers.BooleanField(required=False)

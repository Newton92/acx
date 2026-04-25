# accounts/serializers.py
from django.contrib.auth import get_user_model
from rest_framework import serializers
from .models import Membership, Role, AuditLog, DocumentTemplate
from tenancy.models import Tenant
User = get_user_model()

class TenantLiteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = ["id", "name", "slug", "status"]

class UserLiteSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username", "email", "first_name", "last_name", "full_name"]

    def get_full_name(self, obj):
        return (f"{obj.first_name} {obj.last_name}").strip() or obj.username



class UserSerializer(serializers.ModelSerializer):
    tenants = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id", "username", "email", "first_name", "last_name",
            "telephone", "departement", "is_active", "is_staff", "is_superuser",
            "must_change_password", "tenants",
        ]
        read_only_fields = ["id"]

    def get_tenants(self, obj):
        return [
            {"id": m.tenant.id, "name": m.tenant.name, "status": m.status}
            for m in obj.memberships.select_related("tenant").all()
        ]

class UserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)

    class Meta:
        model = User
        fields = [
            "id", "username", "email", "first_name", "last_name",
            "telephone", "departement", "password",
            "is_active", "is_staff", "is_superuser",
        ]

    def create(self, validated_data):
        password = validated_data.pop("password")
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user



class RoleSerializer(serializers.ModelSerializer):
    label = serializers.CharField(source="get_id_display", read_only=True)

    class Meta:
        model = Role
        fields = ["id", "label"]


class MembershipSerializer(serializers.ModelSerializer):
    tenant = TenantLiteSerializer(read_only=True)
    user   = UserLiteSerializer(read_only=True)
    roles  = serializers.SerializerMethodField()

    class Meta:
        model = Membership
        fields = ["id", "tenant", "user", "roles", "status", "is_owner", "created_at"]
        read_only_fields = ["id", "created_at"]

    def get_roles(self, obj):
        return list(obj.roles.values_list("id", flat=True))

    def create(self, validated_data):
        roles = validated_data.pop("roles", [])
        tenant = validated_data["tenant"]
        user = validated_data["user"]

        membership, created = Membership.objects.get_or_create(
            tenant=tenant,
            user=user,
            defaults=validated_data,
        )

        # Si ça existe déjà, on met à jour ce que tu veux mettre à jour
        if not created:
            for k, v in validated_data.items():
                setattr(membership, k, v)
            membership.save()

        if roles is not None:
            membership.roles.set(roles)

        return membership

class MembershipWriteSerializer(serializers.ModelSerializer):
    tenant = serializers.PrimaryKeyRelatedField(queryset=Tenant.objects.all())
    user = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())
    roles = serializers.PrimaryKeyRelatedField(queryset=Role.objects.all(), many=True, required=False)

    class Meta:
        model = Membership
        fields = ["id", "tenant", "user", "roles", "status", "is_owner", "created_at"]
        read_only_fields = ["id", "created_at"]



User = get_user_model()

class ActorLiteSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username", "email", "full_name"]

    def get_full_name(self, obj):
        full = (obj.first_name + " " + obj.last_name).strip()
        return full or obj.username


class TenantLiteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = ["id", "name", "slug"]


class AuditLogSerializer(serializers.ModelSerializer):
    actor = ActorLiteSerializer(read_only=True)
    tenant = TenantLiteSerializer(read_only=True)

    class Meta:
        model = AuditLog
        fields = [
            "id",
            "action",
            "entity_type",
            "entity_id",
            "entity_label",
            "tenant",
            "actor",
            "metadata",
            "created_at",
        ]


class DocumentTemplateSerializer(serializers.ModelSerializer):
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)
    file_url  = serializers.SerializerMethodField()
    file_name = serializers.SerializerMethodField()

    class Meta:
        model  = DocumentTemplate
        fields = [
            "id", "title", "description", "category",
            "file", "file_url", "file_name",
            "created_by", "created_by_username",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_by", "created_by_username", "created_at", "updated_at"]
        extra_kwargs = {"file": {"write_only": True, "required": False}}

    def get_file_url(self, obj):
        request = self.context.get("request")
        if obj.file and request:
            return request.build_absolute_uri(obj.file.url)
        return None

    def get_file_name(self, obj):
        return obj.file.name.split("/")[-1] if obj.file else None
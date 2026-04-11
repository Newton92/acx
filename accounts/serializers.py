# accounts/serializers.py
from django.contrib.auth import get_user_model
from rest_framework import serializers
from .models import Membership, Role, AuditLog
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
    class Meta:
        model = User
        fields = [
            "id", "username", "email", "first_name", "last_name",
            "telephone", "departement", "is_active", "is_staff", "is_superuser",
            "must_change_password",
        ]
        read_only_fields = ["id", "is_staff", "is_superuser"]

class UserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)

    class Meta:
        model = User
        fields = ["id", "username", "email", "first_name", "last_name", "telephone", "departement", "password"]

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
    class Meta:
        model = Membership
        fields = ["id", "tenant", "user", "roles", "status", "is_owner", "created_at"]
        read_only_fields = ["id", "created_at"]

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
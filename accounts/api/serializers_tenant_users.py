from django.contrib.auth import get_user_model
from rest_framework import serializers

User = get_user_model()


class TenantUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email", "first_name", "last_name", "is_active"]


class TenantUserCreateSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    telephone = serializers.CharField(max_length=30, required=False, allow_blank=True)
    departement = serializers.CharField(max_length=120, required=False, allow_blank=True)

    # MVP: on peut créer avec mot de passe OU laisser inutilisable (invitation plus tard)
    password = serializers.CharField(required=False, allow_blank=True, write_only=True)

    # Optionnel: roles à donner au membership à la création (ids: 1/2/3/4)
    role_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False
    )

    def validate_username(self, value):
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("Username already exists.")
        return value

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("Email already exists.")
        return value

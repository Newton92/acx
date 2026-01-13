# accounts/jwt_serializers.py
from django.contrib.auth import authenticate, get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

User = get_user_model()


class EmailOrUsernameTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Variante JWT: accepte `identifier` (email ou username) + password.
    N'affecte pas le login tenant existant (username/password).
    """
    identifier = serializers.CharField()

    def validate(self, attrs):
        identifier = (attrs.get("identifier") or "").strip()
        password = attrs.get("password")

        if not identifier or not password:
            raise serializers.ValidationError("identifier and password are required")

        # 1) tente username
        user = authenticate(
            request=self.context.get("request"),
            username=identifier,
            password=password,
        )

        # 2) tente email
        if user is None:
            try:
                u = User.objects.get(email__iexact=identifier)
            except User.DoesNotExist:
                u = None

            if u is not None:
                # authenticate() attend toujours username=...
                user = authenticate(
                    request=self.context.get("request"),
                    username=u.username,
                    password=password,
                )

        if user is None:
            raise serializers.ValidationError("No active account found with the given credentials")

        # IMPORTANT: on pose self.user pour SimpleJWT
        self.user = user
        return super().validate({"username": user.username, "password": password})

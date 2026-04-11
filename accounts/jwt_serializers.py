# accounts/jwt_serializers.py
from django.contrib.auth import authenticate, get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

User = get_user_model()


def _authenticate_user(identifier: str, password: str, context: dict):
    """
    Résout un utilisateur depuis son username ou email + password.
    Retourne l'objet User authentifié et actif, ou None.
    """
    # 1) Essai direct par username
    user = authenticate(
        request=context.get("request"),
        username=identifier,
        password=password,
    )
    # 2) Essai par email
    if user is None:
        try:
            u = User.objects.get(email__iexact=identifier)
        except User.DoesNotExist:
            u = None
        if u is not None:
            user = authenticate(
                request=context.get("request"),
                username=u.username,
                password=password,
            )
    return user


def _check_tenant_access(user):
    """
    Lève une ValidationError si l'utilisateur n'a pas accès à l'interface tenant.
    Règle : être superuser OU avoir au moins un Membership actif dans un tenant.
    """
    if user.is_superuser:
        return
    has_membership = user.memberships.filter(status="active").exists()
    if not has_membership:
        raise serializers.ValidationError(
            "Ce compte n'a pas accès à l'interface agent. "
            "Veuillez utiliser la page de connexion du portail client."
        )


def _check_portal_access(user):
    """
    Lève une ValidationError si l'utilisateur n'a pas accès au portail client.
    Règle : NI superuser NI staff, ET avoir un CustomerMembership actif avec portail activé.
    """
    if user.is_superuser or user.is_staff:
        raise serializers.ValidationError(
            "Les comptes administrateurs ne peuvent pas accéder au portail client. "
            "Veuillez utiliser la page de connexion principale."
        )

    from customers.models import CustomerMembership
    cm = (
        CustomerMembership.objects
        .filter(user=user, status=CustomerMembership.Status.ACTIVE)
        .select_related("customer")
        .first()
    )

    if cm is None:
        raise serializers.ValidationError(
            "Ce compte n'a pas accès au portail client. "
            "Contactez votre administrateur."
        )

    if not cm.customer.portal_enabled:
        raise serializers.ValidationError(
            "Le portail client n'est pas activé pour votre organisation. "
            "Contactez votre administrateur."
        )


# ---------------------------------------------------------------------------
# Serializer 1 : Login agent/admin tenant  (username + password)
# Endpoint : POST /api/auth/token/
# ---------------------------------------------------------------------------

class TenantTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Login pour agents et admins tenant.
    Accepte username (ou email dans le champ username) + password.
    Bloque les utilisateurs portail-seulement.
    """

    def validate(self, attrs):
        identifier = (attrs.get(self.username_field) or "").strip()
        password = attrs.get("password", "")

        if not identifier or not password:
            raise serializers.ValidationError("Identifiant et mot de passe requis.")

        user = _authenticate_user(identifier, password, self.context)

        if user is None:
            raise serializers.ValidationError(
                "Aucun compte actif trouvé avec ces identifiants."
            )

        _check_tenant_access(user)

        self.user = user
        # On passe le username résolu à la base (qui génère les tokens)
        attrs[self.username_field] = user.username
        return super().validate(attrs)


# ---------------------------------------------------------------------------
# Serializer 2 : Login agent/admin tenant  (identifier = email ou username)
# Endpoint : POST /api/auth/token/email/
# ---------------------------------------------------------------------------

class EmailOrUsernameTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Variante : accepte `identifier` (email ou username) à la place de username.
    Bloque aussi les utilisateurs portail-seulement.
    """
    identifier = serializers.CharField()

    def validate(self, attrs):
        identifier = (attrs.get("identifier") or "").strip()
        password = attrs.get("password", "")

        if not identifier or not password:
            raise serializers.ValidationError("identifier et password requis.")

        user = _authenticate_user(identifier, password, self.context)

        if user is None:
            raise serializers.ValidationError(
                "Aucun compte actif trouvé avec ces identifiants."
            )

        _check_tenant_access(user)

        self.user = user
        return super().validate({"username": user.username, "password": password})


# ---------------------------------------------------------------------------
# Serializer 3 : Login portail client exclusif
# Endpoint : POST /api/auth/client-portal/token/
# ---------------------------------------------------------------------------

class CustomerPortalTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Login exclusif pour le portail client.
    Accepte username ou email.
    Bloque les superadmins, staff, et agents sans CustomerMembership actif.
    Inclut must_change_password dans les claims JWT et dans la réponse.
    """

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["must_change_password"] = bool(getattr(user, "must_change_password", False))
        return token

    def validate(self, attrs):
        identifier = (attrs.get(self.username_field) or "").strip()
        password = attrs.get("password", "")

        if not identifier or not password:
            raise serializers.ValidationError("Identifiant et mot de passe requis.")

        user = _authenticate_user(identifier, password, self.context)

        if user is None:
            raise serializers.ValidationError(
                "Aucun compte actif trouvé avec ces identifiants."
            )

        _check_portal_access(user)

        self.user = user
        attrs[self.username_field] = user.username
        data = super().validate(attrs)
        # Expose must_change_password directement dans la réponse JSON
        data["must_change_password"] = bool(getattr(user, "must_change_password", False))
        return data

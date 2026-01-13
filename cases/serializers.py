# cases/serializers.py
from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from accounts.tenant_context import get_active_tenant_for_user
from cases.models import Portfolio, Debtor, Case, CaseNote, CaseDocument

User = get_user_model()


def get_request_tenant(serializer: serializers.Serializer):
    """
    Récupère le tenant de façon robuste :
    1) serializer.context["tenant"] (portail client)
    2) request.tenant (si middleware un jour)
    3) get_active_tenant_for_user(request.user) (tenant-side actuel)
    """
    tenant = serializer.context.get("tenant")
    if tenant is not None:
        return tenant

    request = serializer.context.get("request")
    if request is None:
        return None

    t = getattr(request, "tenant", None)
    if t is not None:
        return t

    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        return get_active_tenant_for_user(user)

    return None


class PortfolioSerializer(serializers.ModelSerializer):
    # KPIs (annotated fields)
    cases_count = serializers.IntegerField(read_only=True)
    open_cases_count = serializers.IntegerField(read_only=True)
    overdue_cases_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Portfolio
        fields = [
            "id",
            "name",
            "code",
            "category",
            "priority",
            "default_currency",
            "description",
            "internal_notes",
            "owner",
            "is_active",
            "archived_at",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
            # KPIs
            "cases_count",
            "open_cases_count",
            "overdue_cases_count",
        ]
        read_only_fields = [
            "id",
            "archived_at",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
            "cases_count",
            "open_cases_count",
            "overdue_cases_count",
        ]

    def validate_name(self, value: str):
        value = (value or "").strip()
        if not value:
            raise ValidationError("Le nom du portefeuille est obligatoire.")
        return value

    def validate_code(self, value: str | None):
        if value is None:
            return None
        v = value.strip()
        return v or None

    def validate_default_currency(self, value: str | None):
        if value is None:
            return None
        v = value.strip().upper()
        return v or None


class DebtorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Debtor
        fields = [
            "id",
            "type",
            "full_name",
            "national_id",
            "tax_id",
            "phone",
            "email",
            "address",
            "city",
            "country",
            "metadata",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def validate_full_name(self, value: str):
        value = (value or "").strip()
        if not value:
            raise ValidationError("Le nom du débiteur est obligatoire.")
        return value


class CaseSerializer(serializers.ModelSerializer):
    # ---- READ (nested objects) ----
    debtor = DebtorSerializer(read_only=True)
    portfolio = PortfolioSerializer(read_only=True)

    assigned_to_username = serializers.CharField(source="assigned_to.username", read_only=True)

    # ---- WRITE (ids) ----
    debtor_id = serializers.PrimaryKeyRelatedField(
        source="debtor",
        queryset=Debtor.objects.all(),
        write_only=True,
    )

    portfolio_id = serializers.PrimaryKeyRelatedField(
        source="portfolio",
        queryset=Portfolio.objects.all(),
        write_only=True,
        required=False,
        allow_null=True,
    )

    assigned_to_id = serializers.PrimaryKeyRelatedField(
        source="assigned_to",
        queryset=User.objects.all(),
        required=False,
        allow_null=True,
        write_only=True,
    )

    class Meta:
        model = Case
        fields = [
            "id",
            "reference",
            "title",
            "status",
            "priority",
            "currency",
            "original_amount",
            "balance_amount",
            "due_date",
            "opened_at",
            "closed_at",
            "portfolio",
            "portfolio_id",
            "debtor",
            "debtor_id",
            "assigned_to_id",
            "assigned_to_username",
            "metadata",
            # ✅ utile portail client / audit (si présent dans le modèle)
            "created_source",
        ]
        read_only_fields = ["id", "opened_at", "created_source"]

    def validate(self, attrs):
        tenant = get_request_tenant(self)
        if tenant is None:
            raise ValidationError("Tenant non détecté sur la requête/contexte.")

        debtor = attrs.get("debtor")
        if debtor and getattr(debtor, "tenant_id", None) != tenant.id:
            raise ValidationError({"debtor_id": "Ce débiteur n'appartient pas à votre tenant."})

        portfolio = attrs.get("portfolio")
        if portfolio is not None and getattr(portfolio, "tenant_id", None) != tenant.id:
            raise ValidationError({"portfolio_id": "Ce portefeuille n'appartient pas à votre tenant."})

        return attrs

    def create(self, validated_data):
        request = self.context.get("request")

        # ✅ on n'écrase pas si tenant fourni par serializer.save(tenant=...)
        if "tenant" not in validated_data:
            tenant = get_request_tenant(self)
            if tenant is None:
                raise ValidationError("Tenant non détecté sur la requête/contexte.")
            validated_data["tenant"] = tenant

        user = getattr(request, "user", None) if request else None
        if user and user.is_authenticated:
            validated_data.setdefault("created_by", user)

        return super().create(validated_data)

    def update(self, instance, validated_data):
        return super().update(instance, validated_data)


class CaseNoteSerializer(serializers.ModelSerializer):
    author_username = serializers.CharField(source="author.username", read_only=True)

    class Meta:
        model = CaseNote
        fields = ["id", "case", "author", "author_username", "body", "created_at"]
        read_only_fields = ["id", "case", "created_at", "author", "author_username"]

    def create(self, validated_data):
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        if user and user.is_authenticated:
            validated_data["author"] = user
        return super().create(validated_data)


class CaseDocumentSerializer(serializers.ModelSerializer):
    uploaded_by_username = serializers.CharField(source="uploaded_by.username", read_only=True)
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = CaseDocument
        fields = [
            "id",
            "case",
            "title",
            "doc_type",
            "file",
            "file_url",
            "uploaded_by",
            "uploaded_by_username",
            "created_at",
        ]
        read_only_fields = ["id", "case", "created_at", "uploaded_by", "uploaded_by_username", "file_url"]

    def get_file_url(self, obj):
        request = self.context.get("request")
        if not obj.file:
            return None
        if request:
            return request.build_absolute_uri(obj.file.url)
        return obj.file.url

    def create(self, validated_data):
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        if user and user.is_authenticated:
            validated_data["uploaded_by"] = user
        return super().create(validated_data)


class CustomerPortalDebtorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Debtor
        fields = [
            "id", "type", "full_name", "phone", "email",
            "address", "city", "country", "metadata",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class CustomerPortalUserSerializer(serializers.Serializer):
    """
    Représentation minimale d’un user local côté client portal.
    Tu peux baser ça sur ton modèle réel (Membership client portal),
    mais ici on standardise le format renvoyé au front.
    """
    id = serializers.IntegerField()
    username = serializers.CharField()
    first_name = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    email = serializers.EmailField(required=False, allow_null=True, allow_blank=True)

    role = serializers.CharField()
    status = serializers.CharField()
    created_at = serializers.DateTimeField(required=False)
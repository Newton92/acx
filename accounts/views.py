from django.core.mail import send_mail, EmailMultiAlternatives
from django.template import context
from django.template.loader import render_to_string

from django.utils.html import strip_tags
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated

from django.contrib.auth import get_user_model
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Membership, Role
from accounts.permissions import IsPlatformSuperAdmin, IsTenantAdminOrSuperAdmin
from accounts.serializers import (
    UserSerializer, UserCreateSerializer,
    MembershipSerializer, RoleSerializer, MembershipWriteSerializer
)
from tenancy.models import Tenant


from accounts.models import AuditLog, Membership, Role
from accounts.serializers import AuditLogSerializer
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken
from .security_serializers import SessionSerializer

User = get_user_model()

class SuperAdminOnly(IsAuthenticated):
    def has_permission(self, request, view):
        ok = super().has_permission(request, view)
        return ok and bool(request.user and request.user.is_superuser)

class UserViewSet(viewsets.ModelViewSet):
    """
    Gestion des utilisateurs plateforme (super admin only).
    """
    queryset = User.objects.prefetch_related("memberships__tenant").all().order_by("-id")
    permission_classes = [IsPlatformSuperAdmin]

    def get_serializer_class(self):
        if self.action == "create":
            return UserCreateSerializer
        return UserSerializer

    @action(detail=True, methods=["post"], url_path="reset-password")
    def reset_password(self, request, pk=None):
        """
        POST /api/users/{id}/reset-password/
        Body: { "password": "Good123" }
        Mot de passe souple (min 6 cars, pas de validateur Django).
        Positionne must_change_password=True.
        """
        user = self.get_object()
        password = (request.data.get("password") or "").strip()

        if len(password) < 6:
            return Response(
                {"detail": "Le mot de passe doit contenir au moins 6 caractères."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(password)
        user.is_active = True          # réactive le compte si suspendu
        user.save(update_fields=["password", "is_active"])

        # Applique must_change_password si la migration est en place
        try:
            user.must_change_password = True
            user.save(update_fields=["must_change_password"])
        except Exception:
            pass  # migration pas encore appliquée — ignoré

        AuditLog.objects.create(
            action="USER_PASSWORD_RESET",
            actor=request.user,
            entity_type="User",
            entity_id=user.id,
            entity_label=str(user),
        )

        return Response({"detail": "Mot de passe réinitialisé. L'utilisateur devra le changer à la prochaine connexion."})

    @action(detail=False, methods=["post"], url_path="change-password",
            permission_classes=[IsAuthenticated])
    def change_password(self, request):
        """
        POST /api/users/change-password/
        Body: { "new_password": "...", "confirm_password": "..." }
        Accessible par n'importe quel utilisateur authentifié.
        Efface must_change_password après succès.
        """
        user = request.user
        new_pwd     = (request.data.get("new_password")     or "").strip()
        confirm_pwd = (request.data.get("confirm_password") or "").strip()

        if len(new_pwd) < 8:
            return Response(
                {"detail": "Le nouveau mot de passe doit contenir au moins 8 caractères."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if new_pwd != confirm_pwd:
            return Response(
                {"detail": "Les mots de passe ne correspondent pas."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(new_pwd)
        user.must_change_password = False
        user.save(update_fields=["password", "must_change_password"])

        AuditLog.objects.create(
            action="USER_PASSWORD_CHANGED",
            actor=user,
            entity_type="User",
            entity_id=user.id,
            entity_label=str(user),
        )

        return Response({"detail": "Mot de passe mis à jour avec succès."})


class RoleViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Role.objects.all().order_by("id")
    serializer_class = RoleSerializer
    permission_classes = [IsPlatformSuperAdmin]


class TenantMembershipViewSet(viewsets.ViewSet):
    """
    Endpoints:
      GET  /api/tenants/{pk}/memberships/
      POST /api/tenants/{pk}/memberships/
    """
    permission_classes = [IsTenantAdminOrSuperAdmin]

    def get_tenant(self, pk):
        return Tenant.objects.get(pk=pk)

    def list(self, request, pk=None):
        tenant = self.get_tenant(pk)
        qs = Membership.objects.filter(tenant=tenant).select_related("user").prefetch_related("roles")
        data = MembershipSerializer(qs, many=True).data
        return Response(data)

    def create(self, request, pk=None):
        tenant = self.get_tenant(pk)
        serializer = MembershipSerializer(data=request.data, context={"tenant": tenant})
        serializer.is_valid(raise_exception=True)
        membership = serializer.save()
        return Response(MembershipSerializer(membership).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["patch"], url_path=r"(?P<membership_id>\d+)")
    def update_one(self, request, pk=None, membership_id=None):
        tenant = self.get_tenant(pk)
        m = Membership.objects.get(id=membership_id, tenant=tenant)
        roles = request.data.get("roles", None)

        # patch fields
        for field in ["status", "is_owner"]:
            if field in request.data:
                setattr(m, field, request.data[field])

        m.save()

        if roles is not None:
            m.roles.set(Role.objects.filter(id__in=roles))

        return Response(MembershipSerializer(m).data)

    @action(detail=False, methods=["delete"], url_path=r"(?P<membership_id>\d+)")
    def delete_one(self, request, pk=None, membership_id=None):
        tenant = self.get_tenant(pk)
        Membership.objects.filter(id=membership_id, tenant=tenant).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

class SuperAdminOnly(IsAuthenticated):
    def has_permission(self, request, view):
        ok = super().has_permission(request, view)
        return ok and bool(request.user and request.user.is_superuser)


class MembershipViewSet(viewsets.ModelViewSet):
    queryset = Membership.objects.select_related("tenant", "user").prefetch_related("roles").all()
    serializer_class = MembershipSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["tenant", "user", "status"]

    def create(self, request, *args, **kwargs):
        data = request.data.copy()

        # Tolérance: accepter tenant_id / user_id si front envoie ça
        if "tenant" not in data and "tenant_id" in data:
            data["tenant"] = data["tenant_id"]
        if "user" not in data and "user_id" in data:
            data["user"] = data["user_id"]

        if not data.get("tenant"):
            raise ValidationError({"tenant": "Champ requis. Envoyez tenant (id) ou utilisez tenant_id."})
        if not data.get("user"):
            raise ValidationError({"user": "Champ requis. Envoyez user (id) ou utilisez user_id."})

        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(serializer.data, status=201)



class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AuditLog.objects.select_related("actor", "tenant")
    serializer_class = AuditLogSerializer
    permission_classes = [SuperAdminOnly]



class SessionViewSet(viewsets.ViewSet):
    """
    Endpoints:
      GET    /api/sessions/
      DELETE /api/sessions/{jti}/
      POST   /api/sessions/revoke-all/
    """
    permission_classes = [SuperAdminOnly]

    def list(self, request):
        # Outstanding refresh tokens non blacklisted
        blacklisted_ids = BlacklistedToken.objects.values_list("token_id", flat=True)
        qs = OutstandingToken.objects.exclude(id__in=blacklisted_ids).order_by("-created_at")

        # On expose une forme simple pour le front
        data = []
        for tok in qs:
            data.append(
                {
                    "id": tok.jti,
                    "ip": None,
                    "user_agent": None,
                    "last_seen": tok.created_at,
                }
            )
        return Response(SessionSerializer(data, many=True).data)

    def destroy(self, request, pk=None):
        # pk = jti
        try:
            tok = OutstandingToken.objects.get(jti=pk)
        except OutstandingToken.DoesNotExist:
            return Response({"detail": "Session not found."}, status=status.HTTP_404_NOT_FOUND)

        BlacklistedToken.objects.get_or_create(token=tok)

        # Audit
        AuditLog.objects.create(
            action="SESSION_REVOKE",
            actor=request.user,
            tenant=None,
            entity_type="OutstandingToken",
            entity_id=tok.id,
            entity_label=tok.jti,
            metadata={"user_id": tok.user_id},
        )

        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["post"], url_path="revoke-all")
    def revoke_all(self, request):
        blacklisted_ids = set(BlacklistedToken.objects.values_list("token_id", flat=True))
        qs = OutstandingToken.objects.exclude(id__in=blacklisted_ids)

        count = 0
        for tok in qs:
            BlacklistedToken.objects.get_or_create(token=tok)
            count += 1

        AuditLog.objects.create(
            action="SESSION_REVOKE_ALL",
            actor=request.user,
            tenant=None,
            entity_type="OutstandingToken",
            entity_id=None,
            entity_label=None,
            metadata={"count": count},
        )

        return Response({"revoked": count})


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.data.get("refresh")
            token = RefreshToken(refresh_token)
            token.blacklist()
        except Exception:
            pass

        return Response(status=status.HTTP_204_NO_CONTENT)

from django.conf import settings



from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.utils.timezone import now


def testmail(
        subject="Test email ACX",
        template_name="emails/account_created.html",
        context=None,
        recipient_list=None,
    ):
    if not isinstance(subject, str):
        subject = str(subject)  # évite que request casse le subject

    if context is None:
        context = {
            "full_name": "Issa PEROU",
            "login_url": "http://localhost:3000/login",
            "year": now().year,
        }

    if recipient_list is None:
        recipient_list = ["ngssalapel@gmail.com"]

    html_content = render_to_string(template_name, context)
    text_content = strip_tags(html_content)

    email = EmailMultiAlternatives(
        subject=subject,
        body=text_content,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=recipient_list,
    )
    email.attach_alternative(html_content, "text/html")
    email.send(fail_silently=False)




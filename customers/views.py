# customers/views.py
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db import transaction
from rest_framework.views import APIView

from rest_framework.viewsets import ModelViewSet
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework import status

from accounts.tenant_context import get_active_tenant_for_user
from .models import Customer, CustomerMembership
from .serializers import (
    CustomerSerializer,
    CustomerMembershipSerializer,
    CustomerMembershipUpdateSerializer, CustomerPortalMeSerializer,
)

User = get_user_model()


def _generate_temp_password(length: int = 12) -> str:
    # Simple + robuste: lettres + chiffres (pas de caractères ambigus)
    import secrets
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


class CustomerViewSet(ModelViewSet):
    serializer_class = CustomerSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        tenant = get_active_tenant_for_user(self.request.user)
        if not tenant:
            return Customer.objects.none()
        return Customer.objects.filter(tenant=tenant)

    def perform_create(self, serializer):
        tenant = get_active_tenant_for_user(self.request.user)
        if not tenant:
            raise PermissionDenied("No active tenant.")
        serializer.save(tenant=tenant, created_by=self.request.user)

    # ✅ /api/customers/{id}/memberships/
    @action(detail=True, methods=["GET", "POST"], url_path="memberships")
    def memberships(self, request, pk=None):
        customer: Customer = self.get_object()

        if request.method == "GET":
            qs = customer.memberships.select_related("user").all().order_by("-id")
            return Response(CustomerMembershipSerializer(qs, many=True).data)

        ser = CustomerMembershipSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)

        user = ser.validated_data["user"]
        if hasattr(user, "is_active") and not user.is_active:
            raise ValidationError({"user": "User is inactive."})

        with transaction.atomic():
            obj, created = CustomerMembership.objects.get_or_create(
                customer=customer,
                user=user,
                defaults={
                    "role": ser.validated_data.get("role", CustomerMembership.Role.VIEWER),
                    "status": ser.validated_data.get("status", CustomerMembership.Status.ACTIVE),
                    "is_primary_contact": ser.validated_data.get("is_primary_contact", False),
                },
            )
            if not created:
                obj.role = ser.validated_data.get("role", obj.role)
                obj.status = ser.validated_data.get("status", obj.status)
                obj.is_primary_contact = ser.validated_data.get("is_primary_contact", obj.is_primary_contact)
                obj.save()

        return Response(CustomerMembershipSerializer(obj).data, status=status.HTTP_201_CREATED)

    # ✅ /api/customers/{id}/memberships/{membership_id}/
    @action(detail=True, methods=["PATCH", "DELETE"], url_path=r"memberships/(?P<membership_id>\d+)")
    def membership_detail(self, request, pk=None, membership_id=None):
        customer: Customer = self.get_object()

        try:
            m = customer.memberships.select_related("user").get(id=membership_id)
        except CustomerMembership.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        if request.method == "DELETE":
            m.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)

        ser = CustomerMembershipUpdateSerializer(data=request.data, partial=True, context={"request": request})
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        with transaction.atomic():
            # ---- 1) membership ----
            if "role" in data:
                m.role = data["role"]
            if "status" in data:
                m.status = data["status"]
            if "is_primary_contact" in data:
                m.is_primary_contact = data["is_primary_contact"]
            m.save()

            # ---- 2) user ----
            u = m.user
            user_updates = {}

            if "email" in data:
                new_email = data["email"]
                if User.objects.exclude(id=u.id).filter(email__iexact=new_email).exists():
                    raise ValidationError({"email": "This email is already used."})
                user_updates["email"] = new_email

            if "username" in data:
                new_username = data["username"]
                if User.objects.exclude(id=u.id).filter(username__iexact=new_username).exists():
                    raise ValidationError({"username": "This username is already used."})
                user_updates["username"] = new_username

            if "first_name" in data:
                user_updates["first_name"] = data["first_name"]
            if "last_name" in data:
                user_updates["last_name"] = data["last_name"]

            if "telephone" in data and hasattr(u, "telephone"):
                user_updates["telephone"] = data["telephone"]
            if "departement" in data and hasattr(u, "departement"):
                user_updates["departement"] = data["departement"]

            if "is_active" in data:
                user_updates["is_active"] = data["is_active"]

            if user_updates:
                for k, v in user_updates.items():
                    setattr(u, k, v)
                u.save()

        m.refresh_from_db()
        return Response(CustomerMembershipSerializer(m).data, status=status.HTTP_200_OK)

    # ✅ /api/customers/{id}/memberships/{membership_id}/reset-password/
    @action(detail=True, methods=["POST"], url_path=r"memberships/(?P<membership_id>\d+)/reset-password")
    def membership_reset_password(self, request, pk=None, membership_id=None):
        customer: Customer = self.get_object()

        try:
            m = customer.memberships.select_related("user").get(id=membership_id)
        except CustomerMembership.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        u = m.user
        if not u.email:
            raise ValidationError({"email": "User has no email."})

        temp_password = _generate_temp_password(12)

        with transaction.atomic():
            u.set_password(temp_password)
            u.save(update_fields=["password"])

        # URL portail client (tu peux la mettre en settings/env)
        # Ex: FRONTEND_CLIENT_PORTAL_LOGIN_URL="https://acx.app/fr/client/login"
        login_url = getattr(settings, "FRONTEND_CLIENT_PORTAL_LOGIN_URL", None) or ""

        subject = "ACX - Nouveau mot de passe (Portail Client)"
        lines = [
            f"Bonjour {u.first_name or u.username or ''},".strip(),
            "",
            f"Votre mot de passe a été réinitialisé pour le Portail Client : {customer.name}",
            "",
            f"URL de connexion : {login_url}" if login_url else "URL de connexion : (non configurée)",
            f"Identifiant : {u.email}",
            f"Mot de passe temporaire : {temp_password}",
            "",
            "Veuillez modifier ce mot de passe après connexion.",
            "",
            "Cordialement,",
            "ACX",
        ]
        body = "\n".join(lines)

        send_mail(
            subject=subject,
            message=body,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=[u.email],
            fail_silently=False,
        )

        return Response(
            {
                "detail": "Password reset. Email sent.",
                "temporary_password": temp_password,
            },
            status=status.HTTP_200_OK,
        )


class CustomerPortalMeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        # ✅ CustomerMembership n'a que customer, user (pas tenant)
        membership = (
            CustomerMembership.objects
            .select_related("customer", "user", "customer__tenant")  # ✅ si FK tenant existe
            .filter(user=user)
            .order_by("-id")
            .first()
        )

        print(membership)

        if not membership:
            return Response(
                {"detail": "No active customer membership for this user."},
                status=status.HTTP_403_FORBIDDEN,
            )

        customer = membership.customer
        if not customer:
            return Response(
                {"detail": "Customer not found for membership."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # ✅ optionnel : si tu as customer.portal_enabled
        if hasattr(customer, "portal_enabled") and not customer.portal_enabled:
            return Response(
                {"detail": "Customer portal is not enabled."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # ✅ optionnel : si membership.status existe
        if hasattr(membership, "status") and membership.status in ("suspended", "disabled"):
            return Response(
                {"detail": "Account is suspended."},
                status=status.HTTP_403_FORBIDDEN,
            )

        data = CustomerPortalMeSerializer(membership).data
        return Response(data, status=status.HTTP_200_OK)
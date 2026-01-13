# customers/views_customer_portal_support.py
from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, NotFound, ValidationError

from customers.models import CustomerMembership
from customers.models_support import SupportTicket, SupportTicketMessage, SupportTicketAttachment
from customers.serializers_support import (
    SupportTicketSerializer,
    SupportTicketCreateSerializer,
    SupportTicketPatchSerializer,
    SupportTicketMessageSerializer,
)

# ---------------- CP context ----------------

def _cp_context(request):
    membership = (
        CustomerMembership.objects
        .select_related("customer", "user", "customer__tenant")
        .filter(user=request.user)
        .order_by("-id")
        .first()
    )
    if not membership:
        raise PermissionDenied("No active customer membership for this user.")

    customer = membership.customer
    if not customer:
        raise PermissionDenied("Customer not found for membership.")

    if hasattr(customer, "portal_enabled") and not customer.portal_enabled:
        raise PermissionDenied("Customer portal is not enabled.")

    if hasattr(membership, "status") and membership.status in ("suspended", "disabled"):
        raise PermissionDenied("Account is suspended.")

    tenant = getattr(customer, "tenant", None)
    if not tenant:
        raise PermissionDenied("No tenant found for this customer.")

    return membership, customer, tenant


# ---------------- Upload Security (same spirit as Messages) ----------------

ALLOWED_EXT = {
    ".pdf",
    ".png", ".jpg", ".jpeg", ".webp", ".gif",
    ".doc", ".docx",
    ".xls", ".xlsx",
    ".ppt", ".pptx",
    ".txt", ".csv",
}

FORBIDDEN_EXT = {
    ".svg", ".zip", ".rar", ".7z",
    ".exe", ".bat", ".cmd", ".msi", ".sh",
    ".js", ".ts", ".tsx", ".py", ".php", ".java", ".sql", ".html", ".css",
}

def _max_file_mb():
    return int(getattr(settings, "ACX_CP_MAX_FILE_MB", 10))

def _max_total_mb():
    return int(getattr(settings, "ACX_CP_MAX_TOTAL_MB", 20))

def _validate_files(files):
    max_file = _max_file_mb() * 1024 * 1024
    max_total = _max_total_mb() * 1024 * 1024
    total = 0

    for f in files:
        name = (getattr(f, "name", "") or "").lower().strip()
        size = int(getattr(f, "size", 0) or 0)

        total += size
        if size <= 0:
            raise ValidationError({"files": f"Empty file not allowed: {name}"})
        if size > max_file:
            raise ValidationError({"files": f"File too large: {name} (max {_max_file_mb()}MB)"})
        if total > max_total:
            raise ValidationError({"files": f"Total upload too large (max {_max_total_mb()}MB)"})

        dot = name.rfind(".")
        ext = name[dot:] if dot >= 0 else ""
        if ext in FORBIDDEN_EXT:
            raise ValidationError({"files": f"File type not allowed: {name}"})
        if ext not in ALLOWED_EXT:
            raise ValidationError({"files": f"File type not allowed: {name}"})


# ---------------- Recipients logic ----------------
# ✅ Tenant admins + ACX superadmins
# - Tenant admins: depends on your RBAC. We provide best default + easy hook.
# - ACX superadmins: is_superuser==True OR group/role.

def _get_platform_superadmins():
    User = CustomerMembership._meta.get_field("user").related_model
    # safest: django superusers
    return User.objects.filter(is_superuser=True, is_active=True).exclude(email__isnull=True).exclude(email__exact="")

def _get_tenant_admins(tenant):
    """
    Adapt to your RBAC:
    - preferred: Membership model (tenancy/accounts) with roles 'tenant_admin' or is_owner
    If you already have a Membership model, plug it here.
    """
    try:
        from accounts.models import Membership  # if exists in your project
        qs = Membership.objects.select_related("user").filter(tenant=tenant)
        if hasattr(Membership, "status"):
            qs = qs.filter(status="active")
        # role ids to consider as tenant admin
        admin_role_ids = getattr(settings, "ACX_TENANT_ADMIN_ROLE_IDS", ["tenant_admin"])
        if hasattr(Membership, "roles"):
            qs = qs.filter(Q(is_owner=True) | Q(roles__id__in=admin_role_ids)).distinct()
        else:
            qs = qs.filter(is_owner=True)
        return [m.user for m in qs if m.user and getattr(m.user, "email", None)]
    except Exception:
        return []

def _emails(users):
    out = set()
    for u in users:
        email = (getattr(u, "email", "") or "").strip().lower()
        if email:
            out.add(email)
    return sorted(out)

def _send_support_email(subject, body, recipients):
    if not recipients:
        return
    send_mail(
        subject=subject,
        message=body,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        recipient_list=recipients,
        fail_silently=True,
    )

def _notify_ticket_created(ticket: SupportTicket, first_msg: SupportTicketMessage):
    tenant_admins = _get_tenant_admins(ticket.tenant)
    platform_admins = list(_get_platform_superadmins())
    recipients = _emails(tenant_admins + platform_admins)

    preview = (first_msg.body or "").strip()
    if len(preview) > 200:
        preview = preview[:197] + "..."

    base = getattr(settings, "FRONTEND_CLIENT_PORTAL_BASE_URL", "").rstrip("/")
    link = f"{base}/client/support/{ticket.id}" if base else ""

    subject = f"ACX Support • New ticket #{ticket.id} • {ticket.subject}"
    lines = [
        f"Tenant: {ticket.tenant}",
        f"Customer: {ticket.customer.name}",
        f"Category: {ticket.category}",
        f"Priority: {ticket.priority}",
        f"Case ID: {ticket.case_id or '-'}",
        "",
        f"From: @{first_msg.author.username if first_msg.author else '—'} (customer)",
        "",
        preview,
        "",
    ]
    if link:
        lines.append(f"Open: {link}")
    _send_support_email(subject, "\n".join(lines), recipients)

def _notify_ticket_message(ticket: SupportTicket, msg: SupportTicketMessage):
    """
    Pro notifications:
    - if customer writes: notify tenant admins + platform admins
    - if tenant/platform writes: notify customer members (active) + platform admins (optional)
    """
    membership, customer, tenant = None, ticket.customer, ticket.tenant

    platform_admins = list(_get_platform_superadmins())
    tenant_admins = _get_tenant_admins(tenant)

    preview = (msg.body or "").strip()
    if len(preview) > 200:
        preview = preview[:197] + "..."

    base = getattr(settings, "FRONTEND_CLIENT_PORTAL_BASE_URL", "").rstrip("/")
    link = f"{base}/client/support/{ticket.id}" if base else ""

    if msg.side == SupportTicketMessage.Side.CUSTOMER:
        recipients = _emails(tenant_admins + platform_admins)
        subject = f"ACX Support • Ticket #{ticket.id} • New customer message"
        lines = [
            f"Ticket: #{ticket.id} - {ticket.subject}",
            f"Customer: {customer.name}",
            "",
            f"From: @{msg.author.username if msg.author else '—'} (customer)",
            "",
            preview,
            "",
        ]
        if link:
            lines.append(f"Open: {link}")
        _send_support_email(subject, "\n".join(lines), recipients)
        return

    # tenant or platform message -> notify customer members
    cms = CustomerMembership.objects.select_related("user").filter(customer=customer)
    if hasattr(CustomerMembership, "status"):
        cms = cms.filter(status="active")
    customer_users = [m.user for m in cms if m.user and getattr(m.user, "email", None)]

    recipients = _emails(customer_users)  # + platform_admins if you want
    subject = f"ACX Support • Ticket #{ticket.id} • New update"
    lines = [
        f"Ticket: #{ticket.id} - {ticket.subject}",
        "",
        f"From: @{msg.author.username if msg.author else '—'} ({msg.side})",
        "",
        preview,
        "",
    ]
    if link:
        lines.append(f"Open: {link}")
    _send_support_email(subject, "\n".join(lines), recipients)


# ---------------- Views ----------------

class CustomerPortalSupportTicketsView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        membership, customer, tenant = _cp_context(request)

        q = (request.query_params.get("q") or "").strip()
        status_q = (request.query_params.get("status") or "").strip()

        qs = SupportTicket.objects.filter(customer=customer, tenant=tenant).select_related("created_by")

        if q:
            qs = qs.filter(Q(subject__icontains=q) | Q(id__icontains=q))
        if status_q:
            qs = qs.filter(status=status_q)

        data = SupportTicketSerializer(qs.order_by("-last_activity_at")[:200], many=True).data
        return Response(data, status=status.HTTP_200_OK)

    def post(self, request):
        membership, customer, tenant = _cp_context(request)

        ser = SupportTicketCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        v = ser.validated_data

        files = request.FILES.getlist("files")
        if files:
            _validate_files(files)

        with transaction.atomic():
            tkt = SupportTicket.objects.create(
                tenant=tenant,
                customer=customer,
                created_by=request.user,
                subject=v["subject"].strip(),
                category=v.get("category") or SupportTicket.Category.OTHER,
                priority=v.get("priority") or SupportTicket.Priority.NORMAL,
                status=SupportTicket.Status.OPEN,
                case_id=v.get("case_id"),
            )

            msg = SupportTicketMessage.objects.create(
                ticket=tkt,
                author=request.user,
                side=SupportTicketMessage.Side.CUSTOMER,
                body=v["body"].strip(),
            )

            for f in files:
                SupportTicketAttachment.objects.create(
                    message=msg,
                    file=f,
                    filename=getattr(f, "name", None),
                    content_type=getattr(f, "content_type", None),
                    size=int(getattr(f, "size", 0) or 0),
                )

            tkt.last_activity_at = msg.created_at
            tkt.save(update_fields=["last_activity_at", "updated_at"])

        _notify_ticket_created(tkt, msg)

        out = SupportTicketSerializer(tkt).data
        return Response(out, status=status.HTTP_201_CREATED)


class CustomerPortalSupportTicketDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get_ticket(self, request, ticket_id: int):
        membership, customer, tenant = _cp_context(request)
        tkt = SupportTicket.objects.filter(id=ticket_id, customer=customer, tenant=tenant).select_related("created_by").first()
        if not tkt:
            raise NotFound("Ticket not found.")
        return membership, customer, tenant, tkt

    def get(self, request, ticket_id: int):
        membership, customer, tenant, tkt = self.get_ticket(request, ticket_id)
        data = SupportTicketSerializer(tkt).data
        return Response(data, status=status.HTTP_200_OK)

    def patch(self, request, ticket_id: int):
        membership, customer, tenant, tkt = self.get_ticket(request, ticket_id)

        ser = SupportTicketPatchSerializer(data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        v = ser.validated_data

        # côté client: autoriser close/reopen uniquement
        if "status" in v:
            if v["status"] not in [SupportTicket.Status.CLOSED, SupportTicket.Status.OPEN]:
                raise ValidationError({"status": "Client can only set status to open/closed."})
            tkt.status = v["status"]
            tkt.last_activity_at = timezone.now()
            tkt.save(update_fields=["status", "last_activity_at", "updated_at"])

        return Response(SupportTicketSerializer(tkt).data, status=status.HTTP_200_OK)


class CustomerPortalSupportTicketMessagesView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_ticket(self, request, ticket_id: int):
        membership, customer, tenant = _cp_context(request)
        tkt = SupportTicket.objects.filter(id=ticket_id, customer=customer, tenant=tenant).first()
        if not tkt:
            raise NotFound("Ticket not found.")
        return membership, customer, tenant, tkt

    def get(self, request, ticket_id: int):
        membership, customer, tenant, tkt = self.get_ticket(request, ticket_id)
        qs = SupportTicketMessage.objects.filter(ticket=tkt).select_related("author").prefetch_related("attachments")
        data = SupportTicketMessageSerializer(qs[:300], many=True, context={"request": request}).data
        return Response(data, status=status.HTTP_200_OK)

    def post(self, request, ticket_id: int):
        membership, customer, tenant, tkt = self.get_ticket(request, ticket_id)

        body = (request.data.get("body") or "").strip()
        if not body:
            raise ValidationError({"body": "This field is required."})

        files = request.FILES.getlist("files")
        if files:
            _validate_files(files)

        with transaction.atomic():
            msg = SupportTicketMessage.objects.create(
                ticket=tkt,
                author=request.user,
                side=SupportTicketMessage.Side.CUSTOMER,
                body=body,
            )
            for f in files:
                SupportTicketAttachment.objects.create(
                    message=msg,
                    file=f,
                    filename=getattr(f, "name", None),
                    content_type=getattr(f, "content_type", None),
                    size=int(getattr(f, "size", 0) or 0),
                )

            tkt.last_activity_at = msg.created_at
            # si ticket était resolved/closed, on le ré-ouvre
            if tkt.status in [SupportTicket.Status.RESOLVED, SupportTicket.Status.CLOSED]:
                tkt.status = SupportTicket.Status.OPEN
                tkt.save(update_fields=["status", "last_activity_at", "updated_at"])
            else:
                tkt.save(update_fields=["last_activity_at", "updated_at"])

        _notify_ticket_message(tkt, msg)

        out = SupportTicketMessageSerializer(msg, context={"request": request}).data
        return Response(out, status=status.HTTP_201_CREATED)

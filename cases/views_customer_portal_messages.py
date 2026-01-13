# cases/views_customer_portal_messages.py
from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Exists, OuterRef, Q
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from customers.models import CustomerMembership
from cases.models import Case, CaseMessage, CaseMessageAttachment, CaseMessageRead


# ---------------- CP Context ----------------

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


def _user_to_dict(u):
    if not u:
        return None
    return {
        "id": u.id,
        "username": u.username,
        "first_name": getattr(u, "first_name", None),
        "last_name": getattr(u, "last_name", None),
        "email": getattr(u, "email", None),
    }


def _msg_to_dict(request, m: CaseMessage, is_read: bool | None = None):
    return {
        "id": m.id,
        "case_id": m.case_id,
        "case_reference": getattr(m.case, "reference", None),
        "case_title": getattr(m.case, "title", None),

        "author": _user_to_dict(m.author),
        "author_side": m.author_side,

        "body": m.body,
        "visibility": m.visibility,
        "action_required": m.action_required,

        "created_at": m.created_at.isoformat(),

        "is_read": bool(is_read) if is_read is not None else None,

        "attachments": [
            {
                "id": a.id,
                "filename": a.filename,
                "content_type": a.content_type,
                "size": a.size,
                "file": request.build_absolute_uri(a.file.url) if a.file else None,
                "created_at": a.created_at.isoformat(),
            }
            for a in m.attachments.all()
        ],
    }


# ---------------- Upload Security ----------------

ALLOWED_EXT = {
    ".pdf",
    ".png", ".jpg", ".jpeg", ".webp", ".gif",
    ".doc", ".docx",
    ".xls", ".xlsx",
    ".ppt", ".pptx",
    ".txt", ".csv",
}

# MIME whitelist (best effort)
ALLOWED_MIME_PREFIX = (
    "image/",
)

ALLOWED_MIME_EXACT = {
    "application/pdf",
    "text/plain",
    "text/csv",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

# hard forbidden (even if extension says ok)
FORBIDDEN_MIME_EXACT = {
    "image/svg+xml",          # svg can embed scripts
    "text/html",
    "application/javascript",
    "text/javascript",
}

def _max_file_mb():
    return int(getattr(settings, "ACX_CP_MAX_FILE_MB", 10))

def _max_total_mb():
    return int(getattr(settings, "ACX_CP_MAX_TOTAL_MB", 20))

def _validate_upload_files(files):
    max_file = _max_file_mb() * 1024 * 1024
    max_total = _max_total_mb() * 1024 * 1024

    total = 0
    for f in files:
        name = (getattr(f, "name", "") or "").lower().strip()
        content_type = (getattr(f, "content_type", "") or "").lower().strip()
        size = int(getattr(f, "size", 0) or 0)

        total += size

        # size limits
        if size <= 0:
            raise ValidationError({"files": f"Empty file is not allowed: {name or 'file'}"})
        if size > max_file:
            raise ValidationError({"files": f"File too large ({name}): max {_max_file_mb()} MB"})
        if total > max_total:
            raise ValidationError({"files": f"Total upload too large: max {_max_total_mb()} MB"})

        # extension allow list
        dot = name.rfind(".")
        ext = name[dot:] if dot >= 0 else ""
        if ext not in ALLOWED_EXT:
            raise ValidationError({"files": f"File type not allowed: {name}"})

        # forbidden mime
        if content_type in FORBIDDEN_MIME_EXACT:
            raise ValidationError({"files": f"File type not allowed (mime): {name}"})

        # allow by mime
        if content_type:
            ok = False
            if any(content_type.startswith(p) for p in ALLOWED_MIME_PREFIX):
                ok = True
            if content_type in ALLOWED_MIME_EXACT:
                ok = True
            if not ok:
                # tolerate missing/incorrect content-type for Office sometimes:
                # but keep strict: reject unknown
                raise ValidationError({"files": f"File mime not allowed: {name} ({content_type})"})


def _notify_case_message(m: CaseMessage):
    """
    Notify everyone directly associated:
    - customer memberships (active) emails
    - tenant assignee email (case.assigned_to)
    Exclude author.
    """
    try:
        case = m.case
        customer = m.customer
        author_email = (m.author.email or "").strip().lower() if m.author and getattr(m.author, "email", None) else ""

        recipients = set()

        # customer members
        cm_qs = CustomerMembership.objects.select_related("user").filter(customer=customer)
        # optional status filtering if field exists
        if hasattr(CustomerMembership, "status"):
            cm_qs = cm_qs.filter(status="active")

        for mem in cm_qs:
            u = mem.user
            if not u:
                continue
            email = (getattr(u, "email", "") or "").strip().lower()
            if email and email != author_email:
                recipients.add(email)

        # tenant assignee
        assignee = getattr(case, "assigned_to", None)
        if assignee and getattr(assignee, "email", None):
            email = (assignee.email or "").strip().lower()
            if email and email != author_email:
                recipients.add(email)

        if not recipients:
            return

        subject = f"ACX • New message • {case.reference}"
        preview = (m.body or "").strip()
        if len(preview) > 180:
            preview = preview[:177] + "..."

        # front url (optional)
        client_thread_url = getattr(settings, "FRONTEND_CLIENT_PORTAL_BASE_URL", "").rstrip("/")
        thread = f"{client_thread_url}/client/messages/{case.id}" if client_thread_url else ""

        lines = [
            f"Case: {case.reference} — {case.title}",
            f"From: @{m.author.username if m.author else '—'} ({m.author_side})",
            "",
            preview,
            "",
        ]
        if thread:
            lines.append(f"Open thread: {thread}")

        body = "\n".join(lines)

        send_mail(
            subject=subject,
            message=body,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=sorted(recipients),
            fail_silently=True,  # ✅ no crash in UI if SMTP is down
        )
    except Exception:
        # never break API for notification issues
        return


# ---------------- Views ----------------

class CustomerPortalInboxView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        membership, customer, tenant = _cp_context(request)

        q = (request.query_params.get("q") or "").strip()
        unread = (request.query_params.get("unread") or "").strip()
        action_required = (request.query_params.get("action_required") or "").strip()

        read_exists = CaseMessageRead.objects.filter(message_id=OuterRef("pk"), user=request.user)

        qs = (
            CaseMessage.objects
            .select_related("case", "author")
            .prefetch_related("attachments")
            .filter(customer=customer, case__tenant=tenant, visibility=CaseMessage.Visibility.SHARED)
            .annotate(is_read=Exists(read_exists))
        )

        if q:
            qs = qs.filter(Q(body__icontains=q) | Q(case__reference__icontains=q) | Q(case__title__icontains=q))

        if action_required in ("1", "true", "yes"):
            qs = qs.filter(action_required=True)

        if unread in ("1", "true", "yes"):
            qs = qs.filter(is_read=False)

        rows = list(qs.order_by("-id")[:200])
        data = [_msg_to_dict(request, m, is_read=getattr(m, "is_read", False)) for m in rows]
        return Response(data, status=status.HTTP_200_OK)


class CustomerPortalCaseMessagesView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def _get_case(self, request, case_id: int):
        membership, customer, tenant = _cp_context(request)
        c = Case.objects.filter(id=case_id, tenant=tenant, customer=customer).first()
        if not c:
            raise NotFound("Case not found.")
        return membership, customer, tenant, c

    def get(self, request, case_id: int):
        membership, customer, tenant, c = self._get_case(request, case_id)

        read_exists = CaseMessageRead.objects.filter(message_id=OuterRef("pk"), user=request.user)
        qs = (
            CaseMessage.objects
            .select_related("case", "author")
            .prefetch_related("attachments")
            .filter(case=c, customer=customer, visibility=CaseMessage.Visibility.SHARED)
            .annotate(is_read=Exists(read_exists))
            .order_by("-id")
        )
        rows = list(qs[:300])
        data = [_msg_to_dict(request, m, is_read=getattr(m, "is_read", False)) for m in rows]
        return Response(data, status=status.HTTP_200_OK)

    def post(self, request, case_id: int):
        membership, customer, tenant, c = self._get_case(request, case_id)

        body = (request.data.get("body") or "").strip()
        if not body:
            raise ValidationError({"body": "This field is required."})

        action_required = request.data.get("action_required")
        action_required = True if str(action_required).lower() in ("1", "true", "yes") else False

        files = request.FILES.getlist("files")
        if files:
            _validate_upload_files(files)

        m = CaseMessage.objects.create(
            case=c,
            customer=customer,
            author=request.user,
            author_side="customer",
            body=body,
            visibility=CaseMessage.Visibility.SHARED,
            action_required=action_required,
        )

        # attachments
        for f in files:
            CaseMessageAttachment.objects.create(
                message=m,
                file=f,
                filename=getattr(f, "name", None),
                content_type=getattr(f, "content_type", None),
                size=int(getattr(f, "size", 0) or 0),
            )

        # mark as read for author
        CaseMessageRead.objects.get_or_create(message=m, user=request.user)

        # notify by email (best effort)
        _notify_case_message(m)

        m = CaseMessage.objects.select_related("case", "author").prefetch_related("attachments").get(id=m.id)
        return Response(_msg_to_dict(request, m, is_read=True), status=status.HTTP_201_CREATED)


class CustomerPortalMessageReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, msg_id: int):
        membership, customer, tenant = _cp_context(request)
        m = CaseMessage.objects.select_related("case").filter(
            id=msg_id,
            customer=customer,
            case__tenant=tenant,
            visibility=CaseMessage.Visibility.SHARED
        ).first()
        if not m:
            raise NotFound("Message not found.")

        CaseMessageRead.objects.get_or_create(message=m, user=request.user)
        return Response({"detail": "ok"}, status=status.HTTP_200_OK)


class CustomerPortalCaseMessageDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def _get_msg(self, request, case_id: int, msg_id: int):
        membership, customer, tenant = _cp_context(request)
        c = Case.objects.filter(id=case_id, tenant=tenant, customer=customer).first()
        if not c:
            raise NotFound("Case not found.")
        m = CaseMessage.objects.select_related("case", "author").prefetch_related("attachments").filter(
            id=msg_id, case=c, customer=customer, visibility=CaseMessage.Visibility.SHARED
        ).first()
        if not m:
            raise NotFound("Message not found.")
        return membership, c, m

    def _can_manage(self, membership, msg: CaseMessage, user):
        if msg.author_id == user.id:
            return True
        role = getattr(membership, "role", None)
        return role in ("owner", "manager")

    def patch(self, request, case_id: int, msg_id: int):
        membership, c, m = self._get_msg(request, case_id, msg_id)
        if not self._can_manage(membership, m, request.user):
            raise PermissionDenied("Not allowed.")

        body = (request.data.get("body") or "").strip()
        if not body:
            raise ValidationError({"body": "This field is required."})

        m.body = body
        m.save(update_fields=["body"])

        CaseMessageRead.objects.get_or_create(message=m, user=request.user)

        m = CaseMessage.objects.select_related("case", "author").prefetch_related("attachments").get(id=m.id)
        return Response(_msg_to_dict(request, m, is_read=True), status=status.HTTP_200_OK)

    def delete(self, request, case_id: int, msg_id: int):
        membership, c, m = self._get_msg(request, case_id, msg_id)
        if not self._can_manage(membership, m, request.user):
            raise PermissionDenied("Not allowed.")
        m.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

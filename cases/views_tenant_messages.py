# cases/views_tenant_messages.py
"""
Messagerie côté tenant (agents / admins).
Permet aux agents de voir et répondre aux messages des clients sur un dossier.
"""
import time

from django.db.models import Exists, OuterRef, Q, Max
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response
from rest_framework import status as drf_status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from accounts.tenant_context import get_active_tenant_for_user
from cases.models import Case, CaseMessage, CaseMessageAttachment, CaseMessageRead
from cases.views_customer_portal_messages import (
    _validate_upload_files,
    _set_typing,
    _clear_typing,
    _get_typing_labels,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _tenant_context(request):
    tenant = get_active_tenant_for_user(request.user)
    if not tenant:
        raise PermissionDenied("No active tenant for this user.")
    return tenant


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


def _msg_to_dict(request, m: CaseMessage, is_read=None):
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


# ── Views ──────────────────────────────────────────────────────────────────────

class TenantMessagingInboxView(APIView):
    """
    GET /cases/messages/inbox/
    Liste tous les dossiers ayant des messages, triés par dernier message.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        tenant = _tenant_context(request)

        q = (request.query_params.get("q") or "").strip()
        unread_only = request.query_params.get("unread", "").lower() in ("1", "true")

        read_exists = CaseMessageRead.objects.filter(
            message_id=OuterRef("pk"), user=request.user
        )

        qs = (
            CaseMessage.objects
            .select_related("case", "case__customer", "author")
            .prefetch_related("attachments")
            .filter(case__tenant=tenant)
            .annotate(is_read=Exists(read_exists))
        )

        if q:
            qs = qs.filter(
                Q(body__icontains=q)
                | Q(case__reference__icontains=q)
                | Q(case__title__icontains=q)
                | Q(case__customer__name__icontains=q)
            )

        if unread_only:
            qs = qs.filter(is_read=False)

        # Regrouper par case : garder le dernier message
        rows = list(qs.order_by("-id")[:500])

        seen_cases: set[int] = set()
        threads = []
        for m in rows:
            if m.case_id in seen_cases:
                continue
            seen_cases.add(m.case_id)
            threads.append({
                "case_id": m.case_id,
                "case_reference": getattr(m.case, "reference", None),
                "case_title": getattr(m.case, "title", None),
                "customer_name": getattr(m.case.customer, "name", None) if m.case.customer_id else None,
                "last_message": _msg_to_dict(request, m, is_read=getattr(m, "is_read", False)),
                "unread": not getattr(m, "is_read", True),
            })

        return Response(threads, status=drf_status.HTTP_200_OK)


class TenantCaseMessagesView(APIView):
    """
    GET  /cases/{case_id}/messages/   → liste les messages (shared + internal)
    POST /cases/{case_id}/messages/   → envoyer un message (side=tenant)
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def _get_case(self, request, case_id: int) -> Case:
        tenant = _tenant_context(request)
        c = Case.objects.filter(id=case_id, tenant=tenant).first()
        if not c:
            raise NotFound("Case not found.")
        return c

    def get(self, request, case_id: int):
        c = self._get_case(request, case_id)

        visibility = request.query_params.get("visibility", "")  # "" = all, "shared", "internal"

        read_exists = CaseMessageRead.objects.filter(
            message_id=OuterRef("pk"), user=request.user
        )
        qs = (
            CaseMessage.objects
            .select_related("case", "author")
            .prefetch_related("attachments")
            .filter(case=c)
            .annotate(is_read=Exists(read_exists))
        )
        if visibility in ("shared", "internal"):
            qs = qs.filter(visibility=visibility)

        rows = list(qs.order_by("-id")[:300])
        data = [_msg_to_dict(request, m, is_read=getattr(m, "is_read", False)) for m in rows]
        return Response(data, status=drf_status.HTTP_200_OK)

    def post(self, request, case_id: int):
        c = self._get_case(request, case_id)

        body = (request.data.get("body") or "").strip()
        if not body:
            raise ValidationError({"body": "This field is required."})

        visibility_raw = (request.data.get("visibility") or "shared").strip().lower()
        if visibility_raw not in ("shared", "internal"):
            visibility_raw = "shared"

        action_required = str(request.data.get("action_required", "")).lower() in ("1", "true", "yes")

        files = request.FILES.getlist("files")
        if files:
            _validate_upload_files(files)

        # customer: si le case a un customer lié
        customer = getattr(c, "customer", None)
        if not customer:
            raise ValidationError({"detail": "This case has no linked customer."})

        m = CaseMessage.objects.create(
            case=c,
            customer=customer,
            author=request.user,
            author_side="tenant",
            body=body,
            visibility=visibility_raw,
            action_required=action_required,
        )

        for f in files:
            CaseMessageAttachment.objects.create(
                message=m,
                file=f,
                filename=getattr(f, "name", None),
                content_type=getattr(f, "content_type", None),
                size=int(getattr(f, "size", 0) or 0),
            )

        CaseMessageRead.objects.get_or_create(message=m, user=request.user)

        m = CaseMessage.objects.select_related("case", "author").prefetch_related("attachments").get(id=m.id)
        return Response(_msg_to_dict(request, m, is_read=True), status=drf_status.HTTP_201_CREATED)


class TenantCaseMessageDetailView(APIView):
    """
    PATCH  /cases/{case_id}/messages/{msg_id}/  → modifier
    DELETE /cases/{case_id}/messages/{msg_id}/  → supprimer
    """
    permission_classes = [IsAuthenticated]

    def _get(self, request, case_id: int, msg_id: int):
        tenant = _tenant_context(request)
        c = Case.objects.filter(id=case_id, tenant=tenant).first()
        if not c:
            raise NotFound("Case not found.")
        m = (
            CaseMessage.objects
            .select_related("case", "author")
            .prefetch_related("attachments")
            .filter(id=msg_id, case=c)
            .first()
        )
        if not m:
            raise NotFound("Message not found.")
        return c, m

    def patch(self, request, case_id: int, msg_id: int):
        c, m = self._get(request, case_id, msg_id)
        # Only author or superuser can edit
        if m.author_id != request.user.id and not request.user.is_superuser:
            raise PermissionDenied("Not allowed.")

        body = (request.data.get("body") or "").strip()
        if not body:
            raise ValidationError({"body": "Required."})

        m.body = body
        m.save(update_fields=["body"])
        CaseMessageRead.objects.get_or_create(message=m, user=request.user)
        m.refresh_from_db()
        return Response(_msg_to_dict(request, m, is_read=True), status=drf_status.HTTP_200_OK)

    def delete(self, request, case_id: int, msg_id: int):
        c, m = self._get(request, case_id, msg_id)
        if m.author_id != request.user.id and not request.user.is_superuser:
            raise PermissionDenied("Not allowed.")
        m.delete()
        return Response(status=drf_status.HTTP_204_NO_CONTENT)


class TenantCaseMessageReadView(APIView):
    """POST /cases/{case_id}/messages/{msg_id}/read/"""
    permission_classes = [IsAuthenticated]

    def post(self, request, case_id: int, msg_id: int):
        tenant = _tenant_context(request)
        c = Case.objects.filter(id=case_id, tenant=tenant).first()
        if not c:
            raise NotFound("Case not found.")
        m = CaseMessage.objects.filter(id=msg_id, case=c).first()
        if not m:
            raise NotFound("Message not found.")
        CaseMessageRead.objects.get_or_create(message=m, user=request.user)
        return Response({"ok": True}, status=drf_status.HTTP_200_OK)


class TenantTypingView(APIView):
    """
    GET/POST/DELETE /cases/{case_id}/typing/
    """
    permission_classes = [IsAuthenticated]

    def _verify(self, request, case_id: int):
        tenant = _tenant_context(request)
        c = Case.objects.filter(id=case_id, tenant=tenant).first()
        if not c:
            raise NotFound("Case not found.")
        return c

    def get(self, request, case_id: int):
        self._verify(request, case_id)
        labels = _get_typing_labels(case_id, request.user.id)
        return Response({"typing": labels})

    def post(self, request, case_id: int):
        self._verify(request, case_id)
        u = request.user
        label = f"{u.first_name} {u.last_name}".strip() or u.username or "Agent"
        _set_typing(case_id, u.id, label)
        return Response({"ok": True})

    def delete(self, request, case_id: int):
        self._verify(request, case_id)
        _clear_typing(case_id, request.user.id)
        return Response({"ok": True})

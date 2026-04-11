# cases/views_calls.py
"""
Gestion des appels audio/vidéo sur un dossier.
Signaling WebRTC natif via polling : offer SDP, answer SDP et ICE candidates
échangés entre les deux parties sans dépendance externe.
"""
import uuid

from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status as drf_status
from rest_framework.exceptions import NotFound, PermissionDenied

from accounts.tenant_context import get_active_tenant_for_user
from cases.models import Case, CaseCall


# ── Helpers ────────────────────────────────────────────────────────────────────

def _call_to_dict(call: CaseCall) -> dict:
    u = call.initiator
    if u:
        name = f"{(u.first_name or '').strip()} {(u.last_name or '').strip()}".strip() or u.username
    else:
        name = "Inconnu"
    return {
        "id": call.id,
        "case_id": call.case_id,
        "room_name": call.room_name,
        "call_type": call.call_type,
        "initiator_side": call.initiator_side,
        "initiator_name": name,
        "status": call.status,
        "created_at": call.created_at.isoformat(),
    }


def _gen_room():
    return f"acx-{uuid.uuid4().hex[:20]}"


# ── Tenant views ───────────────────────────────────────────────────────────────

class TenantCaseCallsView(APIView):
    """
    GET  /cases/{case_id}/calls/active/  → appel actif ou null
    POST /cases/{case_id}/calls/         → démarrer un appel
    """
    permission_classes = [IsAuthenticated]

    def _get_case(self, request, case_id: int) -> Case:
        tenant = get_active_tenant_for_user(request.user)
        if not tenant:
            raise PermissionDenied("No active tenant.")
        c = Case.objects.filter(id=case_id, tenant=tenant).first()
        if not c:
            raise NotFound("Case not found.")
        return c

    def get(self, request, case_id: int):
        c = self._get_case(request, case_id)
        call = CaseCall.objects.filter(case=c, status="active").first()
        return Response(_call_to_dict(call) if call else None)

    def post(self, request, case_id: int):
        c = self._get_case(request, case_id)

        # Clôturer tout appel actif en cours
        CaseCall.objects.filter(case=c, status="active").update(
            status="ended", ended_at=timezone.now()
        )

        call_type = (request.data.get("call_type") or "video").lower()
        if call_type not in ("audio", "video"):
            call_type = "video"

        call = CaseCall.objects.create(
            case=c,
            initiator=request.user,
            initiator_side="tenant",
            room_name=_gen_room(),
            call_type=call_type,
        )
        return Response(_call_to_dict(call), status=drf_status.HTTP_201_CREATED)


class TenantCaseCallEndView(APIView):
    """DELETE /cases/{case_id}/calls/{call_id}/  → terminer un appel"""
    permission_classes = [IsAuthenticated]

    def delete(self, request, case_id: int, call_id: int):
        tenant = get_active_tenant_for_user(request.user)
        if not tenant:
            raise PermissionDenied("No active tenant.")
        c = Case.objects.filter(id=case_id, tenant=tenant).first()
        if not c:
            raise NotFound("Case not found.")
        call = CaseCall.objects.filter(id=call_id, case=c).first()
        if not call:
            raise NotFound("Call not found.")
        call.status = "ended"
        call.ended_at = timezone.now()
        call.save(update_fields=["status", "ended_at"])
        return Response({"ok": True})


# ── Customer portal views ──────────────────────────────────────────────────────

class CustomerPortalCaseCallsView(APIView):
    """
    GET  /customer-portal/cases/{case_id}/calls/active/  → appel actif ou null
    POST /customer-portal/cases/{case_id}/calls/         → démarrer un appel (côté client)
    """
    permission_classes = [IsAuthenticated]

    def _get_case(self, request, case_id: int) -> Case:
        from customers.models import CustomerMembership
        membership = CustomerMembership.objects.filter(
            user=request.user, status="active"
        ).select_related("customer").first()
        if not membership:
            raise PermissionDenied("No active customer membership.")
        c = Case.objects.filter(id=case_id, customer=membership.customer).first()
        if not c:
            raise NotFound("Case not found.")
        return c

    def get(self, request, case_id: int):
        c = self._get_case(request, case_id)
        call = CaseCall.objects.filter(case=c, status="active").first()
        return Response(_call_to_dict(call) if call else None)

    def post(self, request, case_id: int):
        c = self._get_case(request, case_id)
        CaseCall.objects.filter(case=c, status="active").update(
            status="ended", ended_at=timezone.now()
        )
        call_type = (request.data.get("call_type") or "video").lower()
        if call_type not in ("audio", "video"):
            call_type = "video"
        call = CaseCall.objects.create(
            case=c,
            initiator=request.user,
            initiator_side="customer",
            room_name=_gen_room(),
            call_type=call_type,
        )
        return Response(_call_to_dict(call), status=drf_status.HTTP_201_CREATED)


class CustomerPortalCaseCallEndView(APIView):
    """DELETE /customer-portal/cases/{case_id}/calls/{call_id}/"""
    permission_classes = [IsAuthenticated]

    def delete(self, request, case_id: int, call_id: int):
        from customers.models import CustomerMembership
        membership = CustomerMembership.objects.filter(
            user=request.user, status="active"
        ).first()
        if not membership:
            raise PermissionDenied("No active customer membership.")
        c = Case.objects.filter(id=case_id, customer=membership.customer).first()
        if not c:
            raise NotFound("Case not found.")
        call = CaseCall.objects.filter(id=call_id, case=c).first()
        if not call:
            raise NotFound("Call not found.")
        call.status = "ended"
        call.ended_at = timezone.now()
        call.save(update_fields=["status", "ended_at"])
        return Response({"ok": True})


# ── WebRTC Signal views ────────────────────────────────────────────────────────

def _signal_to_dict(call: CaseCall) -> dict:
    return {
        "id": call.id,
        "status": call.status,
        "offer_sdp": call.offer_sdp,
        "answer_sdp": call.answer_sdp,
        "ice_initiator": call.ice_initiator or [],
        "ice_peer": call.ice_peer or [],
    }


class TenantCaseCallSignalView(APIView):
    """
    GET  /cases/{case_id}/calls/{call_id}/signal/  → état signaling WebRTC
    PATCH /cases/{case_id}/calls/{call_id}/signal/ → mettre à jour offer/answer/ICE
    """
    permission_classes = [IsAuthenticated]

    def _get_call(self, request, case_id: int, call_id: int) -> CaseCall:
        tenant = get_active_tenant_for_user(request.user)
        if not tenant:
            raise PermissionDenied("No active tenant.")
        c = Case.objects.filter(id=case_id, tenant=tenant).first()
        if not c:
            raise NotFound("Case not found.")
        call = CaseCall.objects.filter(id=call_id, case=c).first()
        if not call:
            raise NotFound("Call not found.")
        return call

    def get(self, request, case_id: int, call_id: int):
        call = self._get_call(request, case_id, call_id)
        return Response(_signal_to_dict(call))

    def patch(self, request, case_id: int, call_id: int):
        call = self._get_call(request, case_id, call_id)
        data = request.data
        update_fields = []

        if "offer_sdp" in data:
            call.offer_sdp = data["offer_sdp"]
            update_fields.append("offer_sdp")
        if "answer_sdp" in data:
            call.answer_sdp = data["answer_sdp"]
            update_fields.append("answer_sdp")
        if "add_ice_initiator" in data:
            candidates = data["add_ice_initiator"]
            if isinstance(candidates, list):
                call.ice_initiator = (call.ice_initiator or []) + candidates
                update_fields.append("ice_initiator")
        if "add_ice_peer" in data:
            candidates = data["add_ice_peer"]
            if isinstance(candidates, list):
                call.ice_peer = (call.ice_peer or []) + candidates
                update_fields.append("ice_peer")

        if update_fields:
            call.save(update_fields=update_fields)
        return Response(_signal_to_dict(call))


class CustomerPortalCaseCallSignalView(APIView):
    """
    GET  /customer-portal/cases/{case_id}/calls/{call_id}/signal/
    PATCH /customer-portal/cases/{case_id}/calls/{call_id}/signal/
    """
    permission_classes = [IsAuthenticated]

    def _get_call(self, request, case_id: int, call_id: int) -> CaseCall:
        from customers.models import CustomerMembership
        membership = CustomerMembership.objects.filter(
            user=request.user, status="active"
        ).select_related("customer").first()
        if not membership:
            raise PermissionDenied("No active customer membership.")
        c = Case.objects.filter(id=case_id, customer=membership.customer).first()
        if not c:
            raise NotFound("Case not found.")
        call = CaseCall.objects.filter(id=call_id, case=c).first()
        if not call:
            raise NotFound("Call not found.")
        return call

    def get(self, request, case_id: int, call_id: int):
        call = self._get_call(request, case_id, call_id)
        return Response(_signal_to_dict(call))

    def patch(self, request, case_id: int, call_id: int):
        call = self._get_call(request, case_id, call_id)
        data = request.data
        update_fields = []

        if "offer_sdp" in data:
            call.offer_sdp = data["offer_sdp"]
            update_fields.append("offer_sdp")
        if "answer_sdp" in data:
            call.answer_sdp = data["answer_sdp"]
            update_fields.append("answer_sdp")
        if "add_ice_initiator" in data:
            candidates = data["add_ice_initiator"]
            if isinstance(candidates, list):
                call.ice_initiator = (call.ice_initiator or []) + candidates
                update_fields.append("ice_initiator")
        if "add_ice_peer" in data:
            candidates = data["add_ice_peer"]
            if isinstance(candidates, list):
                call.ice_peer = (call.ice_peer or []) + candidates
                update_fields.append("ice_peer")

        if update_fields:
            call.save(update_fields=update_fields)
        return Response(_signal_to_dict(call))

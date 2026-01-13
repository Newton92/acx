# cases/views_customer_portal_cases.py
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, NotFound, ValidationError

from customers.models import CustomerMembership
from cases.models import Case


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


class CustomerPortalCaseDetailView(APIView):
    """
    GET   /customer-portal/cases/<id>/
    PATCH /customer-portal/cases/<id>/
    """
    permission_classes = [IsAuthenticated]

    # ✅ Champs autorisés à la modification côté client portal
    ALLOWED_PATCH_FIELDS = {
        "title",
        "priority",
        "due_date",
        "metadata",
        "customer_assigned_to_id",  # ✅ important
    }

    def _get_case(self, request, case_id: int):
        _, customer, tenant = _cp_context(request)
        c = Case.objects.select_related(
            "debtor",
            "assigned_to",
            "customer_assigned_to",
        ).filter(
            id=case_id,
            tenant=tenant,
            customer=customer,
        ).first()
        if not c:
            raise NotFound("Case not found.")
        return c

    def get(self, request, case_id: int):
        c = self._get_case(request, case_id)

        data = {
            "id": c.id,
            "reference": c.reference,
            "title": c.title,
            "status": c.status,
            "priority": c.priority,
            "currency": c.currency,
            "original_amount": str(c.original_amount),
            "balance_amount": str(c.balance_amount),
            "due_date": c.due_date.isoformat() if c.due_date else None,
            "opened_at": c.opened_at.isoformat() if c.opened_at else None,
            "closed_at": c.closed_at.isoformat() if c.closed_at else None,
            "debtor": {
                "id": c.debtor_id,
                "full_name": getattr(c.debtor, "full_name", None),
                "type": getattr(c.debtor, "type", None),
            } if c.debtor_id else None,

            # ✅ assignations distinctes
            "assigned_to": _user_to_dict(c.assigned_to),
            "customer_assigned_to": _user_to_dict(c.customer_assigned_to),

            "metadata": c.metadata,
        }
        return Response(data, status=status.HTTP_200_OK)

    def patch(self, request, case_id: int):
        c = self._get_case(request, case_id)

        payload = request.data or {}
        incoming_fields = set(payload.keys())

        forbidden = sorted(list(incoming_fields - self.ALLOWED_PATCH_FIELDS))
        if forbidden:
            # ✅ exactement le message que tu vois déjà
            return Response(
                {"detail": f"Forbidden fields: {', '.join(forbidden)}."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # apply allowed updates
        if "title" in payload:
            title = (payload.get("title") or "").strip()
            if not title:
                raise ValidationError({"title": "This field is required."})
            c.title = title

        if "priority" in payload:
            pr = payload.get("priority")
            valid = {x[0] for x in Case.Priority.choices}
            if pr not in valid:
                raise ValidationError({"priority": "Invalid priority."})
            c.priority = pr

        if "due_date" in payload:
            # nullable
            c.due_date = payload.get("due_date") or None

        if "metadata" in payload:
            c.metadata = payload.get("metadata")

        if "customer_assigned_to_id" in payload:
            v = payload.get("customer_assigned_to_id")
            if v in ("", None):
                c.customer_assigned_to = None
            else:
                try:
                    uid = int(v)
                except Exception:
                    raise ValidationError({"customer_assigned_to_id": "Invalid value."})
                # sécurité : l'user doit appartenir au même customer (CustomerMembership)
                _, customer, _ = _cp_context(request)
                ok = customer.memberships.filter(user_id=uid).exists()
                if not ok:
                    raise PermissionDenied("Assignee not in this customer.")
                c.customer_assigned_to_id = uid

        c.save()

        # renvoyer le détail (comme GET)
        c.refresh_from_db()
        data = {
            "id": c.id,
            "reference": c.reference,
            "title": c.title,
            "status": c.status,
            "priority": c.priority,
            "currency": c.currency,
            "original_amount": str(c.original_amount),
            "balance_amount": str(c.balance_amount),
            "due_date": c.due_date.isoformat() if c.due_date else None,
            "opened_at": c.opened_at.isoformat() if c.opened_at else None,
            "closed_at": c.closed_at.isoformat() if c.closed_at else None,
            "debtor": {
                "id": c.debtor_id,
                "full_name": getattr(c.debtor, "full_name", None),
                "type": getattr(c.debtor, "type", None),
            } if c.debtor_id else None,
            "assigned_to": _user_to_dict(c.assigned_to),
            "customer_assigned_to": _user_to_dict(c.customer_assigned_to),
            "metadata": c.metadata,
        }
        return Response(data, status=status.HTTP_200_OK)

# customers/customer_context.py
from .models import CustomerMembership


def get_active_customer_for_user(user):
    """
    Retourne un Customer si l'utilisateur a au moins un CustomerMembership ACTIVE.
    Priorité: primary_contact sinon premier.
    """
    qs = (
        CustomerMembership.objects
        .filter(user=user, status=CustomerMembership.Status.ACTIVE)
        .select_related("customer", "customer__tenant")
    )
    m = qs.filter(is_primary_contact=True).first() or qs.first()
    return m.customer if m and m.customer else None


def get_active_customer_membership(user):
    qs = (
        CustomerMembership.objects
        .filter(user=user, status=CustomerMembership.Status.ACTIVE)
        .select_related("customer", "customer__tenant")
    )
    return qs.filter(is_primary_contact=True).first() or qs.first()

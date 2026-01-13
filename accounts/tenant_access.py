from accounts.models import Membership

def get_active_membership_for_user(user):
    """
    Retourne un membership actif (priorité owner si possible),
    sinon None.
    """
    qs = Membership.objects.filter(user=user, status="active").select_related("tenant")
    m = qs.filter(is_owner=True).first() or qs.first()
    return m

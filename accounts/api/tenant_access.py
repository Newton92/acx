from accounts.models import Membership, Role

def get_active_membership(user):
    """
    Retourne un membership actif pour l'utilisateur connecté.
    Priorité : owner, sinon premier ACTIVE.
    """
    qs = Membership.objects.filter(
        user=user,
        status=Membership.Status.ACTIVE,
    ).select_related("tenant")

    return qs.filter(is_owner=True).first() or qs.first()


def is_tenant_admin(membership: Membership) -> bool:
    """
    Un tenant-admin est:
    - owner
    - ou possède un role ADMIN (4) ou APPROVER (3) selon vos choix
    """
    if not membership:
        return False
    if membership.is_owner:
        return True

    role_ids = set(membership.roles.values_list("id", flat=True))
    return Role.ADMIN in role_ids or Role.APPROVER in role_ids

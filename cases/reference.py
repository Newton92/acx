# cases/reference.py
"""
Génération de références dossier :
  <3 chars tenant>/<pays ISO2>/<YYYYMM>/<numéro séquentiel par tenant/mois>

Exemple : ACX/TD/202606/0001

Règle pays :
  1. Pays du débiteur (si fourni et non vide)
  2. Premier pays assigné à l'utilisateur dans ce tenant
  3. Pays par défaut du tenant
  4. Fallback : "XX"
"""

import re
from django.db import transaction
from django.utils import timezone


def _tenant_prefix(tenant) -> str:
    """3 caractères alphanumériques depuis le nom du tenant."""
    cleaned = re.sub(r"[^A-Z0-9]", "", tenant.name.upper())
    return (cleaned[:3] if len(cleaned) >= 3 else cleaned.ljust(3, "X"))


def get_country_for_user(user, tenant) -> str:
    """
    Pays de l'utilisateur pour ce tenant.
    Priorité : UserCountryAssignment > tenant.country > 'XX'
    """
    from accounts.models import UserCountryAssignment

    assignment = (
        UserCountryAssignment.objects
        .filter(user=user, tenant=tenant)
        .select_related("country")
        .first()
    )
    if assignment:
        return assignment.country.country_code.upper()
    return (tenant.country or "XX").upper()


def generate_case_reference(tenant, country_code: str, period: str | None = None) -> str:
    """
    Génère une référence dossier unique par tenant.
    Utilise SELECT FOR UPDATE pour garantir l'atomicité du compteur.
    """
    from cases.models import CaseSequence

    if not period:
        period = timezone.now().strftime("%Y%m")

    prefix = _tenant_prefix(tenant)
    cc = (country_code or "XX").upper()[:2]

    with transaction.atomic():
        seq, _ = CaseSequence.objects.select_for_update().get_or_create(
            tenant=tenant,
            period=period,
            defaults={"last_number": 0},
        )
        seq.last_number += 1
        seq.save(update_fields=["last_number"])
        number = seq.last_number

    return f"{prefix}/{cc}/{period}/{str(number).zfill(4)}"

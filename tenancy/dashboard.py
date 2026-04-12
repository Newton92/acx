"""
GET /api/admin-dashboard/?period=30d
Réservé aux superusers. Retourne KPIs, croissance, distribution, santé tenants, audit log.
"""
from datetime import timedelta, date

from django.db.models import Count
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Tenant
from .permissions import IsSuperUser
from accounts.models import Membership, AuditLog
from cases.models import Case


# Grille tarifaire indicative (FCFA/mois)
PLAN_MRR = {
    "enterprise": 2400,
    "business":   1200,
    "starter":     600,
}

MONTH_LABELS = ["Jan", "Fév", "Mar", "Avr", "Mai", "Jun",
                "Jul", "Aoû", "Sep", "Oct", "Nov", "Déc"]
DAY_LABELS   = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]


def _date_buckets(period: str):
    """Retourne (dates, labels) pour la période demandée."""
    today = timezone.now().date()

    if period == "7d":
        dates  = [today - timedelta(days=i) for i in range(6, -1, -1)]
        labels = [DAY_LABELS[d.weekday()] for d in dates]
        return dates, labels

    if period == "30d":
        dates  = [today - timedelta(weeks=i) for i in range(3, -1, -1)]
        labels = [f"S{i+1}" for i in range(4)]
        return dates, labels

    # 90d → 3 mois / 12m → 12 mois
    n = 3 if period == "90d" else 12
    months = []
    d = today
    for _ in range(n):
        months.insert(0, d.replace(day=1))
        d = (d.replace(day=1) - timedelta(days=1)).replace(day=1)
    labels = [MONTH_LABELS[m.month - 1] for m in months]
    return months, labels


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsSuperUser])
def admin_dashboard_stats(request):
    period = request.query_params.get("period", "30d")

    # ── KPIs ──────────────────────────────────────────────────────────────────
    total_tenants = Tenant.objects.filter(status=Tenant.Status.ACTIVE).count()
    total_users   = (
        Membership.objects
        .filter(status=Membership.Status.ACTIVE)
        .values("user")
        .distinct()
        .count()
    )
    total_cases = Case.objects.count()

    plan_qs = (
        Tenant.objects
        .filter(status=Tenant.Status.ACTIVE)
        .values("plan")
        .annotate(count=Count("id"))
    )
    total_mrr = sum(
        PLAN_MRR.get((p["plan"] or "").lower(), 0) * p["count"]
        for p in plan_qs
    )

    # Deltas : comparaison avec début du mois courant
    first_of_month   = date.today().replace(day=1)
    prev_tenants = Tenant.objects.filter(
        status=Tenant.Status.ACTIVE,
        created_at__date__lt=first_of_month,
    ).count()
    prev_users = (
        Membership.objects
        .filter(status=Membership.Status.ACTIVE, created_at__date__lt=first_of_month)
        .values("user")
        .distinct()
        .count()
    )

    # ── Courbe de croissance ──────────────────────────────────────────────────
    dates, labels = _date_buckets(period)
    growth = []
    for d, label in zip(dates, labels):
        growth.append({
            "name":    label,
            "tenants": Tenant.objects.filter(created_at__date__lte=d).count(),
            "users":   (
                Membership.objects
                .filter(created_at__date__lte=d)
                .values("user")
                .distinct()
                .count()
            ),
            "cases": Case.objects.filter(opened_at__date__lte=d).count(),
        })

    # ── Répartition par plan ──────────────────────────────────────────────────
    plan_distribution = [
        {
            "name":  (p["plan"] or "Autre").capitalize(),
            "value": p["count"],
        }
        for p in plan_qs.order_by("-count")
    ]

    # ── Santé des tenants ─────────────────────────────────────────────────────
    tenant_health = []
    for t in Tenant.objects.all().order_by("-created_at")[:20]:
        plan_key = (t.plan or "").lower()
        tenant_health.append({
            "id":     t.id,
            "name":   t.name,
            "cases":  Case.objects.filter(tenant=t).count(),
            "users":  Membership.objects.filter(
                          tenant=t, status=Membership.Status.ACTIVE
                      ).count(),
            "plan":   (t.plan or "").capitalize(),
            "status": t.status,
            "mrr":    PLAN_MRR.get(plan_key, 0),
        })

    # ── Journal d'audit ───────────────────────────────────────────────────────
    audit_log = [
        {
            "action":       log.action,
            "actor":        str(log.actor) if log.actor else "system",
            "tenant":       log.tenant.name if log.tenant else None,
            "entity_type":  log.entity_type,
            "entity_label": log.entity_label,
            "metadata":     log.metadata,
            "created_at":   log.created_at.isoformat(),
        }
        for log in AuditLog.objects.select_related("actor", "tenant").order_by("-id")[:10]
    ]

    return Response({
        "kpis": {
            "total_tenants": total_tenants,
            "prev_tenants":  prev_tenants,
            "total_users":   total_users,
            "prev_users":    prev_users,
            "total_cases":   total_cases,
            "total_mrr":     total_mrr,
        },
        "growth":            growth,
        "plan_distribution": plan_distribution,
        "tenant_health":     tenant_health,
        "audit_log":         audit_log,
    })

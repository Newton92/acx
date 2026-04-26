"""tenancy/middleware.py — vérifie que la licence du tenant est active."""

from django.http import JsonResponse

# Ces préfixes sont toujours autorisés sans vérification de licence.
_BYPASS = (
    "/api/auth/",
    "/api/tenants/",
    "/api/admin-dashboard/",
    "/admin/",
    "/media/",
)


class LicenseMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/api/") and not self._is_bypass(request.path):
            blocked = self._check(request)
            if blocked:
                return blocked
        return self.get_response(request)

    # ── helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _is_bypass(path: str) -> bool:
        return any(path.startswith(p) for p in _BYPASS)

    @staticmethod
    def _check(request):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated or user.is_superuser:
            return None

        try:
            from accounts.models import Membership
            m = (
                Membership.objects
                .filter(user=user, status="active")
                .select_related("tenant__license")
                .order_by("-is_owner")
                .first()
            )
        except Exception:
            return None

        if not m or not m.tenant:
            return None

        try:
            lic = m.tenant.license
        except Exception:
            return None  # Pas de licence => pas de blocage (période de grâce)

        if lic.is_expired:
            return JsonResponse(
                {
                    "detail": "subscription_expired",
                    "plan": lic.plan,
                    "expires_at": lic.expires_at.isoformat() if lic.expires_at else None,
                    "days_remaining": 0,
                },
                status=402,
            )

        return None

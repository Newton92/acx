from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.utils.html import format_html

from accounts.models import User, Role, Membership, AuditLog

from django.contrib import admin
from tenancy.models import Tenant


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("id", "__str__")
    ordering = ("id",)



@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "slug", "status", "plan", "country", "city", "created_at")
    list_filter = ("status", "plan", "country")
    search_fields = ("name", "slug", "legal_name", "email", "phone", "city")
    ordering = ("name",)
    readonly_fields = ("slug", "created_at", "updated_at")


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0
    autocomplete_fields = ("tenant",)
    show_change_link = True
    fields = ("tenant", "status", "is_owner", "roles_preview", "created_at")
    readonly_fields = ("roles_preview", "created_at")

    def roles_preview(self, obj: Membership):
        if not obj.pk:
            return "-"
        roles = obj.roles.all().order_by("id")
        if not roles:
            return "-"
        return ", ".join([f"{r.id}:{r.get_id_display()}" for r in roles])

    roles_preview.short_description = "Roles"


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """
    Admin User amélioré pour voir clairement tenant + membership + roles.
    """
    inlines = [MembershipInline]

    # Champs ajoutés dans votre modèle
    fieldsets = DjangoUserAdmin.fieldsets + (
        ("Infos ACX", {"fields": ("telephone", "departement")}),
        ("Tenancy (diagnostic)", {"fields": ("active_membership_preview",)}),
    )

    readonly_fields = ("active_membership_preview",)

    list_display = (
        "username",
        "email",
        "first_name",
        "last_name",
        "is_active",
        "is_staff",
        "is_superuser",
        "active_tenant_name",
        "active_membership_status",
        "active_membership_roles",
    )

    list_select_related = ()

    search_fields = ("username", "email", "first_name", "last_name")
    ordering = ("username",)

    def _get_active_membership(self, user: User):
        qs = (
            user.memberships.filter(status=Membership.Status.ACTIVE)
            .select_related("tenant")
            .prefetch_related("roles")
        )
        return qs.filter(is_owner=True).first() or qs.first()

    def active_tenant_name(self, obj: User):
        m = self._get_active_membership(obj)
        return m.tenant.name if m and m.tenant else "-"
    active_tenant_name.short_description = "Active Tenant"

    def active_membership_status(self, obj: User):
        m = self._get_active_membership(obj)
        return m.status if m else "-"
    active_membership_status.short_description = "Membership Status"

    def active_membership_roles(self, obj: User):
        m = self._get_active_membership(obj)
        if not m:
            return "-"
        roles = m.roles.all().order_by("id")
        if not roles:
            return "-"
        return ", ".join([f"{r.id}:{r.get_id_display()}" for r in roles])
    active_membership_roles.short_description = "Membership Roles"

    def active_membership_preview(self, obj: User):
        """
        Bloc lisible dans la fiche user : reproduit la logique /auth/me/.
        """
        m = self._get_active_membership(obj)
        if not m:
            return "Aucun membership ACTIVE trouvé pour cet utilisateur."

        roles = list(m.roles.all().order_by("id"))
        role_txt = ", ".join([f"{r.id}:{r.get_id_display()}" for r in roles]) or "Aucun rôle"

        return format_html(
            "<div>"
            "<b>Tenant:</b> {} (id={})<br/>"
            "<b>Status:</b> {}<br/>"
            "<b>Owner:</b> {}<br/>"
            "<b>Roles:</b> {}"
            "</div>",
            m.tenant.name,
            m.tenant.id,
            m.status,
            "✅" if m.is_owner else "❌",
            role_txt,
        )
    active_membership_preview.short_description = "Active Membership (debug)"


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "user", "status", "is_owner", "roles_preview", "created_at")
    list_filter = ("status", "is_owner", "tenant")
    search_fields = ("user__username", "user__email", "tenant__name")
    autocomplete_fields = ("tenant", "user")
    ordering = ("-id",)
    filter_horizontal = ("roles",)

    def roles_preview(self, obj: Membership):
        roles = obj.roles.all().order_by("id")
        if not roles:
            return "-"
        return ", ".join([f"{r.id}:{r.get_id_display()}" for r in roles])
    roles_preview.short_description = "Roles"


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("id", "action", "actor", "tenant", "entity_type", "entity_id", "created_at")
    list_filter = ("action", "tenant")
    search_fields = ("action", "actor__username", "entity_type", "entity_label")
    ordering = ("-id",)

#accounts/urls.py
from tkinter.font import names

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from cases.views_customer_portal_cases import CustomerPortalCaseDetailView
from customers.views import CustomerPortalMeView
from .views import UserViewSet, RoleViewSet, TenantMembershipViewSet, MembershipViewSet, AuditLogViewSet, \
    SessionViewSet, LogoutView, testmail
from .views_tenant_users import tenant_users, tenant_user_update, tenant_user_toggle_active, \
    tenant_user_membership_update, tenant_user_remove


from cases.views_customer_portal import (
    CustomerPortalDebtorsView,
    CustomerPortalDebtorDetailView,
    CustomerPortalUsersView,
    CustomerPortalUserUpdateView,
    CustomerPortalAssigneesView, CustomerPortalCaseDocumentsView, CustomerPortalCaseDocumentDetailView,
    CustomerPortalCaseNoteDetailView,
)

from customers.views_customer_portal_support import (
    CustomerPortalSupportTicketsView,
    CustomerPortalSupportTicketDetailView,
    CustomerPortalSupportTicketMessagesView,
)


from cases.views_customer_portal_messages import (
    CustomerPortalInboxView,
    CustomerPortalCaseMessagesView,
    CustomerPortalMessageReadView,
    CustomerPortalCaseMessageDetailView,
)


router = DefaultRouter()
router.register(r"users", UserViewSet, basename="users")
router.register(r"roles", RoleViewSet, basename="roles")
router.register(r"memberships", MembershipViewSet, basename="memberships")


router.register(r"audit-logs", AuditLogViewSet, basename="audit-logs")
router.register(r"sessions", SessionViewSet, basename="sessions")


urlpatterns = [


    path('test_mail', testmail, name="test_mail"),

    path("", include(router.urls)),
    path('', include('django.contrib.auth.urls')),
    path("auth/logout/", LogoutView.as_view(), name="auth-logout"),
    #path("tenants/users/", tenant_users, name="tenant-users"),
    path("tenant/users/", tenant_users, name="tenant-users"),
    path("customer-portal/me/", CustomerPortalMeView.as_view(), name="customer-portal-me"),
    path("customer-portal/cases/<int:case_id>/documents/", CustomerPortalCaseDocumentsView.as_view(), name="customer-portal-case-documents"),
    path("customer-portal/cases/<int:case_id>/", CustomerPortalCaseDetailView.as_view(), name="customer-portal-case-detail"),
    path(
      "customer-portal/cases/<int:case_id>/documents/<int:doc_id>/",
      CustomerPortalCaseDocumentDetailView.as_view(),
      name="customer-portal-case-document-detail",
    ),
    path(
      "customer-portal/cases/<int:case_id>/notes/<int:note_id>/",
      CustomerPortalCaseNoteDetailView.as_view(),
      name="customer-portal-case-note-detail",
    ),

    path("customer-portal/messages/", CustomerPortalInboxView.as_view(), name="customer-portal-inbox"),
    path("customer-portal/messages/<int:msg_id>/read/", CustomerPortalMessageReadView.as_view(),
         name="customer-portal-message-read"),

    path("customer-portal/cases/<int:case_id>/messages/", CustomerPortalCaseMessagesView.as_view(),
         name="customer-portal-case-messages"),
    path("customer-portal/cases/<int:case_id>/messages/<int:msg_id>/", CustomerPortalCaseMessageDetailView.as_view(),
         name="customer-portal-case-message-detail"),

    path("customer-portal/debtors/", CustomerPortalDebtorsView.as_view(), name="customer-portal-debtors"),
    path("customer-portal/debtors/<int:debtor_id>/", CustomerPortalDebtorDetailView.as_view(),
         name="customer-portal-debtor-detail"),

    path("customer-portal/users/", CustomerPortalUsersView.as_view(), name="customer-portal-users"),
    path("customer-portal/users/<int:user_id>/", CustomerPortalUserUpdateView.as_view(),
         name="customer-portal-user-update"),

    path("customer-portal/assignees/", CustomerPortalAssigneesView.as_view(), name="customer-portal-assignees"),

    path("customer-portal/support/tickets/", CustomerPortalSupportTicketsView.as_view(), name="cp-support-tickets"),
    path("customer-portal/support/tickets/<int:ticket_id>/", CustomerPortalSupportTicketDetailView.as_view(),
         name="cp-support-ticket-detail"),
    path("customer-portal/support/tickets/<int:ticket_id>/messages/", CustomerPortalSupportTicketMessagesView.as_view(),
         name="cp-support-ticket-messages"),

    # memberships par tenant
    path("tenants/<int:pk>/memberships/", TenantMembershipViewSet.as_view({
        "get": "list",
        "post": "create"
    }), name="tenant-memberships"),

    path("tenants/<int:pk>/memberships/<int:membership_id>/", TenantMembershipViewSet.as_view({
        "patch": "update_one"
    }), name="tenant-membership-patch"),

    path("tenants/<int:pk>/memberships/<int:membership_id>/delete/", TenantMembershipViewSet.as_view({
        "delete": "delete_one"
    }), name="tenant-membership-delete"),

    path("tenant/users/", tenant_users, name="tenant-users"),
    path("tenant/users/<int:user_id>/", tenant_user_update, name="tenant-user-update"),
    path("tenant/users/<int:user_id>/toggle-active/", tenant_user_toggle_active, name="tenant-user-toggle-active"),
    path("tenant/users/<int:user_id>/membership/", tenant_user_membership_update, name="tenant-user-membership-update"),
    path("tenant/users/<int:user_id>/remove/", tenant_user_remove, name="tenant-user-remove"),
]

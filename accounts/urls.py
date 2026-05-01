#accounts/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from cases.views_customer_portal_cases import CustomerPortalCaseDetailView
from customers.views import CustomerPortalMeView
from .views import UserViewSet, RoleViewSet, TenantMembershipViewSet, MembershipViewSet, AuditLogViewSet, \
    SessionViewSet, LogoutView, testmail, AdminDocumentsStatsView, DocumentTemplateViewSet, \
    PlatformInboxView, PlatformThreadView, PlatformUnreadView, PlatformMessageDeleteView, \
    PlatformStatsView, \
    IntegrationEmailStatusView, SmsConfigView, TenantApiKeyListView, TenantApiKeyDetailView, \
    PlatformSettingsView
from .views_tenant_users import tenant_users, tenant_user_update, tenant_user_toggle_active, \
    tenant_user_membership_update, tenant_user_remove
from .views_mail_config import (
    mail_imap_config, mail_imap_test, mail_imap_poll, mail_cron_status,
    mail_sources, mail_source_detail, mail_source_toggle,
    mail_inbox, mail_inbox_stats, mail_inbox_detail,
    mail_dispatch, mail_self_dispatch, mail_accept, mail_reassign,
    mail_reject, mail_restore, mail_mark_processed,
    mail_country_managers, mail_attachment_download, mail_sse,
)
from .views_countries import (
    tenant_countries, tenant_country_detail, tenant_country_set_manager,
    user_country_list, user_country_save, user_country_assign_all,
)


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
    CustomerPortalTypingView,
)

from cases.views_tenant_messages import (
    TenantMessagingInboxView,
    TenantCaseMessagesView,
    TenantCaseMessageDetailView,
    TenantCaseMessageReadView,
    TenantTypingView,
)

from cases.views_calls import (
    TenantCaseCallsView,
    TenantCaseCallEndView,
    CustomerPortalCaseCallsView,
    CustomerPortalCaseCallEndView,
    TenantCaseCallSignalView,
    CustomerPortalCaseCallSignalView,
)


router = DefaultRouter()
router.register(r"users", UserViewSet, basename="users")
router.register(r"roles", RoleViewSet, basename="roles")
router.register(r"memberships", MembershipViewSet, basename="memberships")


router.register(r"audit-logs", AuditLogViewSet, basename="audit-logs")
router.register(r"sessions", SessionViewSet, basename="sessions")
router.register(r"document-templates", DocumentTemplateViewSet, basename="document-templates")


urlpatterns = [


    path('test_mail', testmail, name="test_mail"),
    path("admin-documents/", AdminDocumentsStatsView.as_view(), name="admin-documents"),
    path("platform-stats/",            PlatformStatsView.as_view(),           name="platform-stats"),
    path("integration/email/",         IntegrationEmailStatusView.as_view(),  name="integration-email"),
    path("integration/sms/",           SmsConfigView.as_view(),               name="integration-sms"),
    path("integration/api-keys/",      TenantApiKeyListView.as_view(),        name="integration-api-keys"),
    path("integration/api-keys/<int:pk>/", TenantApiKeyDetailView.as_view(),  name="integration-api-key-detail"),
    path("platform-settings/",            PlatformSettingsView.as_view(),       name="platform-settings"),
    path("platform-messages/inbox/",         PlatformInboxView.as_view(),   name="platform-messages-inbox"),
    path("platform-messages/unread/",        PlatformUnreadView.as_view(),  name="platform-messages-unread"),
    path("platform-messages/<int:tenant_id>/", PlatformThreadView.as_view(), name="platform-messages-thread"),
    path("platform-messages/message/<int:msg_id>/", PlatformMessageDeleteView.as_view(), name="platform-message-delete"),

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
    path("customer-portal/cases/<int:case_id>/typing/", CustomerPortalTypingView.as_view(),
         name="customer-portal-case-typing"),

    # Tenant messaging
    path("cases/messages/inbox/", TenantMessagingInboxView.as_view(), name="tenant-messages-inbox"),
    path("cases/<int:case_id>/messages/", TenantCaseMessagesView.as_view(), name="tenant-case-messages"),
    path("cases/<int:case_id>/messages/<int:msg_id>/", TenantCaseMessageDetailView.as_view(), name="tenant-case-message-detail"),
    path("cases/<int:case_id>/messages/<int:msg_id>/read/", TenantCaseMessageReadView.as_view(), name="tenant-case-message-read"),
    path("cases/<int:case_id>/typing/", TenantTypingView.as_view(), name="tenant-case-typing"),

    # Appels audio/vidéo — tenant
    path("cases/<int:case_id>/calls/", TenantCaseCallsView.as_view(), name="tenant-case-calls"),
    path("cases/<int:case_id>/calls/active/", TenantCaseCallsView.as_view(), name="tenant-case-calls-active"),
    path("cases/<int:case_id>/calls/<int:call_id>/", TenantCaseCallEndView.as_view(), name="tenant-case-call-end"),
    path("cases/<int:case_id>/calls/<int:call_id>/signal/", TenantCaseCallSignalView.as_view(), name="tenant-case-call-signal"),

    # Appels audio/vidéo — portail client
    path("customer-portal/cases/<int:case_id>/calls/", CustomerPortalCaseCallsView.as_view(), name="cp-case-calls"),
    path("customer-portal/cases/<int:case_id>/calls/active/", CustomerPortalCaseCallsView.as_view(), name="cp-case-calls-active"),
    path("customer-portal/cases/<int:case_id>/calls/<int:call_id>/", CustomerPortalCaseCallEndView.as_view(), name="cp-case-call-end"),
    path("customer-portal/cases/<int:case_id>/calls/<int:call_id>/signal/", CustomerPortalCaseCallSignalView.as_view(), name="cp-case-call-signal"),

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

    # Mail entrant — configuration IMAP
    path("tenant/mail/imap/", mail_imap_config, name="tenant-mail-imap"),
    path("tenant/mail/imap/test/", mail_imap_test, name="tenant-mail-imap-test"),
    path("tenant/mail/imap/poll/", mail_imap_poll, name="tenant-mail-imap-poll"),
    path("tenant/mail/imap/status/", mail_cron_status, name="tenant-mail-cron-status"),

    # Mail entrant — sources
    path("tenant/mail/sources/", mail_sources, name="tenant-mail-sources"),
    path("tenant/mail/sources/<int:source_id>/", mail_source_detail, name="tenant-mail-source-detail"),
    path("tenant/mail/sources/<int:source_id>/toggle/", mail_source_toggle, name="tenant-mail-source-toggle"),

    # Mail entrant — inbox
    path("tenant/mail/inbox/", mail_inbox, name="tenant-mail-inbox"),
    path("tenant/mail/inbox/stats/", mail_inbox_stats, name="tenant-mail-inbox-stats"),
    path("tenant/mail/inbox/<int:mail_id>/", mail_inbox_detail, name="tenant-mail-inbox-detail"),
    path("tenant/mail/inbox/<int:mail_id>/dispatch/", mail_dispatch, name="tenant-mail-dispatch"),
    path("tenant/mail/inbox/<int:mail_id>/self-dispatch/", mail_self_dispatch, name="tenant-mail-self-dispatch"),
    path("tenant/mail/inbox/<int:mail_id>/accept/", mail_accept, name="tenant-mail-accept"),
    path("tenant/mail/inbox/<int:mail_id>/reassign/", mail_reassign, name="tenant-mail-reassign"),
    path("tenant/mail/inbox/<int:mail_id>/reject/", mail_reject, name="tenant-mail-reject"),
    path("tenant/mail/inbox/<int:mail_id>/restore/", mail_restore, name="tenant-mail-restore"),
    path("tenant/mail/inbox/<int:mail_id>/processed/", mail_mark_processed, name="tenant-mail-processed"),

    # Responsables pays (mail)
    path("tenant/mail/country-managers/", mail_country_managers, name="tenant-mail-country-managers"),

    # SSE — flux temps réel
    path("tenant/mail/stream/", mail_sse, name="tenant-mail-sse"),

    # Téléchargement sécurisé des pièces jointes
    path("tenant/mail/attachments/<int:attachment_id>/download/", mail_attachment_download, name="tenant-mail-attachment-download"),

    # Périmètre géographique — pays du tenant
    path("tenant/countries/", tenant_countries, name="tenant-countries"),
    path("tenant/countries/<int:country_id>/", tenant_country_detail, name="tenant-country-detail"),
    path("tenant/countries/<int:country_id>/set-manager/", tenant_country_set_manager, name="tenant-country-set-manager"),

    # Pays assignés à un utilisateur
    path("tenant/users/<int:user_id>/countries/", user_country_list, name="user-country-list"),
    path("tenant/users/<int:user_id>/countries/save/", user_country_save, name="user-country-save"),
    path("tenant/users/<int:user_id>/countries/assign-all/", user_country_assign_all, name="user-country-assign-all"),
]

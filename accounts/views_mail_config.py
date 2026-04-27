"""
Mail entrant — API views pour la configuration IMAP, les sources et l'inbox.

Routes:
  GET/PUT    /tenant/mail/imap/            → config IMAP (singleton par tenant)
  POST       /tenant/mail/imap/test/       → tester la connexion IMAP
  POST       /tenant/mail/imap/poll/       → déclencher un poll immédiat
  GET        /tenant/mail/imap/status/     → statut du service de polling (heartbeat)
  GET/POST   /tenant/mail/sources/         → lister / créer une source
  PATCH/DEL  /tenant/mail/sources/<id>/    → modifier / supprimer
  POST       /tenant/mail/sources/<id>/toggle/   → activer/désactiver
  GET        /tenant/mail/inbox/           → liste mails interceptés
  GET        /tenant/mail/inbox/<id>/      → détail + pièces jointes
  POST       /tenant/mail/inbox/<id>/dispatch/   → dispatcher au responsable pays
  POST       /tenant/mail/inbox/<id>/reject/     → rejeter
  POST       /tenant/mail/inbox/<id>/restore/    → remettre en attente
  GET        /tenant/mail/country-managers/      → liste des responsables pays du tenant
"""

import imaplib
import socket

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.models import (
    Membership, Role,
    MailInboxConfig, MailSource, IncomingMail, MailAttachment,
)

User = get_user_model()


# ─────────────────────────────────────────────────────────────
# Helpers partagés
# ─────────────────────────────────────────────────────────────

def _get_active_membership(user):
    qs = (
        Membership.objects.filter(user=user, status=Membership.Status.ACTIVE)
        .select_related("tenant")
        .prefetch_related("roles")
    )
    return qs.filter(is_owner=True).first() or qs.first()


def _is_tenant_admin(membership):
    if not membership:
        return False
    if membership.is_owner:
        return True
    role_ids = set(membership.roles.values_list("id", flat=True))
    return (Role.ADMIN in role_ids) or (Role.APPROVER in role_ids)


def _imap_config_payload(cfg):
    return {
        "id": cfg.id,
        "imap_host": cfg.imap_host,
        "imap_port": cfg.imap_port,
        "imap_user": cfg.imap_user,
        "imap_password_set": bool(cfg.imap_password),
        "use_ssl": cfg.use_ssl,
        "mailbox": cfg.mailbox,
        "is_active": cfg.is_active,
        "last_polled_at": cfg.last_polled_at,
        "last_error": cfg.last_error,
        "updated_at": cfg.updated_at,
    }


def _source_payload(src):
    return {
        "id": src.id,
        "client_name": src.client_name,
        "email_or_domain": src.email_or_domain,
        "is_domain": src.is_domain,
        "notes": src.notes,
        "is_active": src.is_active,
        "created_at": src.created_at,
        "updated_at": src.updated_at,
    }


def _mail_list_payload(mail):
    return {
        "id": mail.id,
        "from_email": mail.from_email,
        "from_name": mail.from_name,
        "subject": mail.subject,
        "received_at": mail.received_at,
        "status": mail.status,
        "mail_source": {
            "id": mail.mail_source_id,
            "client_name": mail.mail_source.client_name if mail.mail_source else "",
            "email_or_domain": mail.mail_source.email_or_domain if mail.mail_source else "",
        } if mail.mail_source_id else None,
        "assigned_to": {
            "id": mail.assigned_to_id,
            "name": str(mail.assigned_to),
        } if mail.assigned_to_id else None,
        "assigned_country": mail.assigned_country,
        "attachments_count": mail.attachments.count(),
    }


def _mail_detail_payload(mail):
    payload = _mail_list_payload(mail)
    payload.update({
        "body_text": mail.body_text,
        "body_html": mail.body_html,
        "dispatch_note": mail.dispatch_note,
        "dispatched_at": mail.dispatched_at,
        "dispatched_by": {
            "id": mail.dispatched_by_id,
            "name": str(mail.dispatched_by),
        } if mail.dispatched_by_id else None,
        "case": mail.case_id,
        "attachments": [
            {
                "id": a.id,
                "filename": a.filename,
                "content_type": a.content_type,
                "size": a.size,
                "url": a.file.url if a.file else None,
            }
            for a in mail.attachments.all()
        ],
    })
    return payload


# ─────────────────────────────────────────────────────────────
# IMAP Config
# ─────────────────────────────────────────────────────────────

@api_view(["GET", "PUT"])
@permission_classes([IsAuthenticated])
def mail_imap_config(request):
    actor_m = _get_active_membership(request.user)
    if not actor_m or not actor_m.tenant:
        return Response({"detail": "No active tenant."}, status=status.HTTP_403_FORBIDDEN)
    if not _is_tenant_admin(actor_m):
        return Response({"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)

    tenant = actor_m.tenant

    if request.method == "GET":
        try:
            cfg = MailInboxConfig.objects.get(tenant=tenant)
            return Response(_imap_config_payload(cfg))
        except MailInboxConfig.DoesNotExist:
            return Response(None)

    # PUT — créer ou mettre à jour
    data = request.data or {}
    cfg, _ = MailInboxConfig.objects.get_or_create(tenant=tenant)

    cfg.imap_host = (data.get("imap_host") or "").strip()
    cfg.imap_port = int(data.get("imap_port") or 993)
    cfg.imap_user = (data.get("imap_user") or "").strip()
    cfg.use_ssl = bool(data.get("use_ssl", True))
    cfg.mailbox = (data.get("mailbox") or "INBOX").strip() or "INBOX"
    cfg.is_active = bool(data.get("is_active", True))

    if "imap_password" in data and data["imap_password"]:
        cfg.imap_password = data["imap_password"]

    if not cfg.imap_host or not cfg.imap_user:
        return Response({"detail": "imap_host et imap_user sont requis."}, status=400)

    cfg.save()
    return Response(_imap_config_payload(cfg))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def mail_imap_test(request):
    """Teste la connexion IMAP avec les identifiants fournis."""
    actor_m = _get_active_membership(request.user)
    if not actor_m or not actor_m.tenant:
        return Response({"detail": "No active tenant."}, status=status.HTTP_403_FORBIDDEN)
    if not _is_tenant_admin(actor_m):
        return Response({"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)

    data = request.data or {}
    host = (data.get("imap_host") or "").strip()
    port = int(data.get("imap_port") or 993)
    user = (data.get("imap_user") or "").strip()
    password = data.get("imap_password") or ""
    use_ssl = bool(data.get("use_ssl", True))
    mailbox = (data.get("mailbox") or "INBOX").strip()

    if not host or not user or not password:
        return Response({"detail": "Hôte, utilisateur et mot de passe requis."}, status=400)

    # Utiliser le mot de passe enregistré si non fourni
    if not password:
        try:
            cfg = MailInboxConfig.objects.get(tenant=actor_m.tenant)
            password = cfg.imap_password
        except MailInboxConfig.DoesNotExist:
            pass

    try:
        if use_ssl:
            imap = imaplib.IMAP4_SSL(host, port)
        else:
            imap = imaplib.IMAP4(host, port)
        imap.login(user, password)
        status_code, data_resp = imap.select(mailbox, readonly=True)
        msg_count = int(data_resp[0]) if status_code == "OK" and data_resp[0] else 0
        imap.logout()
        return Response({
            "success": True,
            "message": f"Connexion réussie. {msg_count} message(s) dans {mailbox}.",
        })
    except imaplib.IMAP4.error as e:
        return Response({"success": False, "message": f"Erreur IMAP : {e}"}, status=400)
    except socket.gaierror:
        return Response({"success": False, "message": "Hôte IMAP introuvable."}, status=400)
    except Exception as e:
        return Response({"success": False, "message": str(e)}, status=400)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def mail_imap_poll(request):
    """Déclenche un poll IMAP immédiat pour le tenant courant."""
    actor_m = _get_active_membership(request.user)
    if not actor_m or not actor_m.tenant:
        return Response({"detail": "No active tenant."}, status=status.HTTP_403_FORBIDDEN)
    if not _is_tenant_admin(actor_m):
        return Response({"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)

    try:
        cfg = MailInboxConfig.objects.get(tenant=actor_m.tenant, is_active=True)
    except MailInboxConfig.DoesNotExist:
        return Response({"detail": "Aucune configuration IMAP active."}, status=404)

    from django.core.management import call_command
    try:
        call_command("poll_mail", tenant_id=cfg.tenant_id)
        cfg.refresh_from_db()
        return Response({
            "success": True,
            "last_polled_at": cfg.last_polled_at,
            "last_error": cfg.last_error,
        })
    except Exception as e:
        return Response({"success": False, "message": str(e)}, status=500)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def mail_cron_status(request):
    """
    Retourne l'état du service de polling pour ce tenant.

    health:
      "unconfigured" — aucune config IMAP
      "inactive"     — config présente mais is_active=False (arrêté par le tenant)
      "healthy"      — dernier passage < 10 min
      "delayed"      — dernier passage entre 10 et 20 min (1–2 cycles manqués)
      "stale"        — dernier passage > 20 min ou jamais (cron potentiellement arrêté)
    """
    actor_m = _get_active_membership(request.user)
    if not actor_m or not actor_m.tenant:
        return Response({"detail": "No active tenant."}, status=status.HTTP_403_FORBIDDEN)

    try:
        cfg = MailInboxConfig.objects.get(tenant=actor_m.tenant)
    except MailInboxConfig.DoesNotExist:
        return Response({
            "health": "unconfigured",
            "health_label": "Non configuré",
            "is_active": False,
            "last_run": None,
            "last_error": "",
            "minutes_since_last_run": None,
            "cron_interval_minutes": 5,
        })

    if not cfg.is_active:
        return Response({
            "health": "inactive",
            "health_label": "Arrêté",
            "is_active": False,
            "last_run": cfg.last_polled_at,
            "last_error": cfg.last_error,
            "minutes_since_last_run": _minutes_ago(cfg.last_polled_at),
            "cron_interval_minutes": 5,
        })

    minutes = _minutes_ago(cfg.last_polled_at)

    if minutes is None:
        health = "stale"
        label = "En attente du premier passage"
    elif minutes < 10:
        health = "healthy"
        label = f"Actif — dernier passage il y a {minutes} min"
    elif minutes < 20:
        health = "delayed"
        label = f"En retard — dernier passage il y a {minutes} min"
    else:
        health = "stale"
        label = f"Inactif — dernier passage il y a {minutes} min"

    return Response({
        "health": health,
        "health_label": label,
        "is_active": cfg.is_active,
        "last_run": cfg.last_polled_at,
        "last_error": cfg.last_error,
        "minutes_since_last_run": minutes,
        "cron_interval_minutes": 5,
    })


def _minutes_ago(dt) -> int | None:
    if not dt:
        return None
    delta = timezone.now() - dt
    return int(delta.total_seconds() // 60)


# ─────────────────────────────────────────────────────────────
# Sources mail
# ─────────────────────────────────────────────────────────────

@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def mail_sources(request):
    actor_m = _get_active_membership(request.user)
    if not actor_m or not actor_m.tenant:
        return Response({"detail": "No active tenant."}, status=status.HTTP_403_FORBIDDEN)

    tenant = actor_m.tenant

    if request.method == "GET":
        sources = MailSource.objects.filter(tenant=tenant)
        return Response([_source_payload(s) for s in sources])

    if not _is_tenant_admin(actor_m):
        return Response({"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)

    data = request.data or {}
    email_or_domain = (data.get("email_or_domain") or "").strip().lower()
    if not email_or_domain:
        return Response({"detail": "email_or_domain est requis."}, status=400)

    if MailSource.objects.filter(tenant=tenant, email_or_domain=email_or_domain).exists():
        return Response({"detail": "Cette source existe déjà pour ce tenant."}, status=400)

    src = MailSource.objects.create(
        tenant=tenant,
        client_name=(data.get("client_name") or "").strip(),
        email_or_domain=email_or_domain,
        notes=(data.get("notes") or "").strip(),
        is_active=bool(data.get("is_active", True)),
    )
    return Response(_source_payload(src), status=201)


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def mail_source_detail(request, source_id: int):
    actor_m = _get_active_membership(request.user)
    if not actor_m or not actor_m.tenant:
        return Response({"detail": "No active tenant."}, status=status.HTTP_403_FORBIDDEN)
    if not _is_tenant_admin(actor_m):
        return Response({"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)

    try:
        src = MailSource.objects.get(id=source_id, tenant=actor_m.tenant)
    except MailSource.DoesNotExist:
        return Response({"detail": "Source introuvable."}, status=404)

    if request.method == "DELETE":
        src.delete()
        return Response(status=204)

    data = request.data or {}
    if "client_name" in data:
        src.client_name = (data["client_name"] or "").strip()
    if "email_or_domain" in data:
        new_val = (data["email_or_domain"] or "").strip().lower()
        if new_val and new_val != src.email_or_domain:
            if MailSource.objects.filter(tenant=actor_m.tenant, email_or_domain=new_val).exists():
                return Response({"detail": "Cette source existe déjà."}, status=400)
            src.email_or_domain = new_val
    if "notes" in data:
        src.notes = (data["notes"] or "").strip()
    if "is_active" in data:
        src.is_active = bool(data["is_active"])
    src.save()
    return Response(_source_payload(src))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def mail_source_toggle(request, source_id: int):
    actor_m = _get_active_membership(request.user)
    if not actor_m or not actor_m.tenant:
        return Response({"detail": "No active tenant."}, status=status.HTTP_403_FORBIDDEN)
    if not _is_tenant_admin(actor_m):
        return Response({"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)

    try:
        src = MailSource.objects.get(id=source_id, tenant=actor_m.tenant)
    except MailSource.DoesNotExist:
        return Response({"detail": "Source introuvable."}, status=404)

    src.is_active = not src.is_active
    src.save()
    return Response(_source_payload(src))


# ─────────────────────────────────────────────────────────────
# Inbox — mails interceptés
# ─────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def mail_inbox(request):
    actor_m = _get_active_membership(request.user)
    if not actor_m or not actor_m.tenant:
        return Response({"detail": "No active tenant."}, status=status.HTTP_403_FORBIDDEN)

    qs = (
        IncomingMail.objects.filter(tenant=actor_m.tenant)
        .select_related("mail_source", "assigned_to", "dispatched_by")
        .prefetch_related("attachments")
    )

    status_filter = request.GET.get("status")
    if status_filter:
        qs = qs.filter(status=status_filter)

    search = (request.GET.get("search") or "").strip()
    if search:
        qs = qs.filter(
            subject__icontains=search
        ) | qs.filter(from_email__icontains=search) | qs.filter(from_name__icontains=search)

    country = request.GET.get("country")
    if country:
        qs = qs.filter(assigned_country=country)

    # Pagination simple
    page = max(1, int(request.GET.get("page", 1)))
    page_size = 20
    total = qs.count()
    mails = qs[(page - 1) * page_size: page * page_size]

    stats = {
        "total": IncomingMail.objects.filter(tenant=actor_m.tenant).count(),
        "pending": IncomingMail.objects.filter(tenant=actor_m.tenant, status="pending").count(),
        "dispatched": IncomingMail.objects.filter(tenant=actor_m.tenant, status="dispatched").count(),
        "processed": IncomingMail.objects.filter(tenant=actor_m.tenant, status="processed").count(),
        "rejected": IncomingMail.objects.filter(tenant=actor_m.tenant, status="rejected").count(),
    }

    return Response({
        "count": total,
        "page": page,
        "page_size": page_size,
        "results": [_mail_list_payload(m) for m in mails],
        "stats": stats,
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def mail_inbox_detail(request, mail_id: int):
    actor_m = _get_active_membership(request.user)
    if not actor_m or not actor_m.tenant:
        return Response({"detail": "No active tenant."}, status=status.HTTP_403_FORBIDDEN)

    try:
        mail = (
            IncomingMail.objects
            .select_related("mail_source", "assigned_to", "dispatched_by", "case")
            .prefetch_related("attachments")
            .get(id=mail_id, tenant=actor_m.tenant)
        )
    except IncomingMail.DoesNotExist:
        return Response({"detail": "Mail introuvable."}, status=404)

    return Response(_mail_detail_payload(mail))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def mail_dispatch(request, mail_id: int):
    """Dispatcher un mail à un responsable pays."""
    actor_m = _get_active_membership(request.user)
    if not actor_m or not actor_m.tenant:
        return Response({"detail": "No active tenant."}, status=status.HTTP_403_FORBIDDEN)
    if not _is_tenant_admin(actor_m):
        return Response({"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)

    try:
        mail = IncomingMail.objects.select_related("mail_source", "assigned_to").get(
            id=mail_id, tenant=actor_m.tenant
        )
    except IncomingMail.DoesNotExist:
        return Response({"detail": "Mail introuvable."}, status=404)

    data = request.data or {}
    assigned_to_id = data.get("assigned_to_id")
    assigned_country = (data.get("assigned_country") or "").strip().upper()[:2]
    dispatch_note = (data.get("dispatch_note") or "").strip()

    if not assigned_to_id:
        return Response({"detail": "assigned_to_id est requis."}, status=400)

    # Vérifier que l'assigné est bien un responsable pays du tenant
    try:
        assignee_m = Membership.objects.select_related("user").prefetch_related("roles").get(
            tenant=actor_m.tenant, user_id=assigned_to_id, status=Membership.Status.ACTIVE
        )
    except Membership.DoesNotExist:
        return Response({"detail": "Responsable introuvable dans ce tenant."}, status=404)

    mail.assigned_to = assignee_m.user
    mail.assigned_country = assigned_country
    mail.dispatch_note = dispatch_note
    mail.dispatched_by = request.user
    mail.dispatched_at = timezone.now()
    mail.status = IncomingMail.Status.DISPATCHED
    mail.save()

    # Notifier le responsable pays
    _notify_dispatch(mail, assignee_m.user)

    return Response(_mail_detail_payload(mail))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def mail_reject(request, mail_id: int):
    actor_m = _get_active_membership(request.user)
    if not actor_m or not actor_m.tenant:
        return Response({"detail": "No active tenant."}, status=status.HTTP_403_FORBIDDEN)
    if not _is_tenant_admin(actor_m):
        return Response({"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)

    try:
        mail = IncomingMail.objects.get(id=mail_id, tenant=actor_m.tenant)
    except IncomingMail.DoesNotExist:
        return Response({"detail": "Mail introuvable."}, status=404)

    mail.status = IncomingMail.Status.REJECTED
    mail.save(update_fields=["status", "updated_at"])
    return Response(_mail_list_payload(mail))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def mail_restore(request, mail_id: int):
    actor_m = _get_active_membership(request.user)
    if not actor_m or not actor_m.tenant:
        return Response({"detail": "No active tenant."}, status=status.HTTP_403_FORBIDDEN)
    if not _is_tenant_admin(actor_m):
        return Response({"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)

    try:
        mail = IncomingMail.objects.get(id=mail_id, tenant=actor_m.tenant)
    except IncomingMail.DoesNotExist:
        return Response({"detail": "Mail introuvable."}, status=404)

    mail.status = IncomingMail.Status.PENDING
    mail.assigned_to = None
    mail.assigned_country = ""
    mail.dispatched_at = None
    mail.dispatched_by = None
    mail.dispatch_note = ""
    mail.save()
    return Response(_mail_list_payload(mail))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def mail_mark_processed(request, mail_id: int):
    actor_m = _get_active_membership(request.user)
    if not actor_m or not actor_m.tenant:
        return Response({"detail": "No active tenant."}, status=status.HTTP_403_FORBIDDEN)

    try:
        mail = IncomingMail.objects.get(id=mail_id, tenant=actor_m.tenant)
    except IncomingMail.DoesNotExist:
        return Response({"detail": "Mail introuvable."}, status=404)

    # Seul l'assigné ou un admin peut marquer comme traité
    is_admin = _is_tenant_admin(actor_m)
    is_assignee = mail.assigned_to_id == request.user.id
    if not is_admin and not is_assignee:
        return Response({"detail": "Not allowed."}, status=403)

    mail.status = IncomingMail.Status.PROCESSED
    mail.save(update_fields=["status", "updated_at"])
    return Response(_mail_list_payload(mail))


# ─────────────────────────────────────────────────────────────
# Responsables Pays du tenant
# ─────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def mail_country_managers(request):
    actor_m = _get_active_membership(request.user)
    if not actor_m or not actor_m.tenant:
        return Response({"detail": "No active tenant."}, status=status.HTTP_403_FORBIDDEN)

    memberships = (
        Membership.objects.filter(
            tenant=actor_m.tenant,
            status=Membership.Status.ACTIVE,
            roles__id=Role.COUNTRY_MANAGER,
        )
        .select_related("user")
        .distinct()
    )

    result = [
        {
            "id": m.user.id,
            "username": m.user.username,
            "full_name": str(m.user),
            "email": m.user.email,
        }
        for m in memberships
    ]
    return Response(result)


# ─────────────────────────────────────────────────────────────
# Notification interne
# ─────────────────────────────────────────────────────────────

def _notify_dispatch(mail: IncomingMail, assignee):
    from django.core.mail import send_mail
    from django.conf import settings as dj_settings

    if not assignee.email:
        return
    try:
        send_mail(
            subject=f"[ACX] Demande client assignée — {mail.subject[:80]}",
            message=(
                f"Bonjour {assignee.first_name or assignee.username},\n\n"
                f"Un mail client vous a été assigné.\n\n"
                f"De : {mail.from_email}\n"
                f"Objet : {mail.subject}\n"
                f"Pays : {mail.assigned_country or '—'}\n\n"
                f"Connectez-vous à la plateforme ACX pour le traiter."
            ),
            from_email=dj_settings.DEFAULT_FROM_EMAIL,
            recipient_list=[assignee.email],
            fail_silently=True,
        )
    except Exception:
        pass

"""
Commande de polling IMAP pour les mails entrants des tenants.

Usage:
  python manage.py poll_mail                    → tous les tenants actifs
  python manage.py poll_mail --tenant-id 5      → un seul tenant
"""

import email
import email.header
import email.utils
import hashlib
import imaplib
import socket
from datetime import datetime, timezone as dt_tz, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import (
    MailInboxConfig, MailSource, IncomingMail, MailAttachment, Membership,
)

User = get_user_model()


class Command(BaseCommand):
    help = "Poll les boîtes IMAP configurées et intercepte les mails clients."

    def add_arguments(self, parser):
        parser.add_argument(
            "--tenant-id",
            type=int,
            default=None,
            help="Limiter le poll à un seul tenant (par ID).",
        )

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int, default=None)
        parser.add_argument("--verbose", action="store_true", help="Affiche le détail de chaque email traité")

    def handle(self, *args, **options):
        tenant_id = options.get("tenant_id")
        self.verbose = options.get("verbose", False)
        qs = MailInboxConfig.objects.filter(is_active=True).select_related("tenant")
        if tenant_id:
            qs = qs.filter(tenant_id=tenant_id)

        if not qs.exists():
            self.stdout.write("Aucune configuration IMAP active.")
            return

        for cfg in qs:
            self.stdout.write(f"→ Polling [{cfg.tenant.name}] {cfg.imap_user}…")
            try:
                new_count = self._poll_tenant(cfg)
                self.stdout.write(
                    self.style.SUCCESS(f"  ✓ {new_count} nouveau(x) mail(s) intercepté(s).")
                )
            except Exception as exc:
                cfg.last_error = str(exc)
                cfg.save(update_fields=["last_error"])
                self.stderr.write(self.style.ERROR(f"  ✗ Erreur : {exc}"))

    # ─────────────────────────────────────────────────────────
    # Cœur du polling
    # ─────────────────────────────────────────────────────────

    def _poll_tenant(self, cfg: MailInboxConfig) -> int:
        if cfg.use_ssl:
            imap = imaplib.IMAP4_SSL(cfg.imap_host, cfg.imap_port)
        else:
            imap = imaplib.IMAP4(cfg.imap_host, cfg.imap_port)

        imap.login(cfg.imap_user, cfg.imap_password)
        imap.select(cfg.mailbox)

        # Recherche par date : depuis le dernier poll (- 1 jour de marge) ou 30 jours max.
        # On ne dépend plus du flag UNSEEN — la déduplication par message_id évite les doublons.
        if cfg.last_polled_at:
            since_dt = cfg.last_polled_at - timedelta(days=1)
        else:
            since_dt = timezone.now() - timedelta(days=30)
        since_str = since_dt.strftime("%d-%b-%Y")
        _, data = imap.search(None, f'SINCE "{since_str}"')
        uid_list = [u for u in data[0].split() if u]

        self.stdout.write(f"  {len(uid_list)} message(s) trouvé(s) depuis le {since_str}.")

        sources = list(
            MailSource.objects.filter(tenant=cfg.tenant, is_active=True)
        )
        if self.verbose:
            self.stdout.write(f"  Sources actives ({len(sources)}) : " +
                              ", ".join(s.email_or_domain for s in sources) or "(aucune)")

        new_count = 0
        for uid in uid_list:
            try:
                created, reason = self._process_uid(imap, uid, cfg.tenant, sources)
                if created:
                    new_count += 1
                elif self.verbose:
                    self.stdout.write(f"    UID {uid.decode()} ignoré — {reason}")
            except Exception as exc:
                self.stderr.write(f"    UID {uid} — erreur : {exc}")

        imap.close()
        imap.logout()

        cfg.last_polled_at = timezone.now()
        cfg.last_error = ""
        cfg.save(update_fields=["last_polled_at", "last_error"])

        return new_count

    def _process_uid(self, imap, uid, tenant, sources):
        _, msg_data = imap.fetch(uid, "(RFC822)")
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)

        # Déduplication par Message-ID
        message_id = (msg.get("Message-ID") or "").strip()
        if not message_id:
            message_id = "no-id-" + hashlib.md5(raw[:512]).hexdigest()

        if IncomingMail.objects.filter(message_id=message_id).exists():
            return False, "doublon (message_id déjà enregistré)"

        # Expéditeur
        from_header = msg.get("From", "")
        from_name_raw, from_email_raw = email.utils.parseaddr(from_header)
        from_name = self._decode_header(from_name_raw)
        from_email = from_email_raw.lower().strip()
        if not from_email:
            return False, "aucun expéditeur détectable"

        # Filtrer par source configurée
        matched_source = self._match_source(from_email, sources)
        if not matched_source:
            return False, f"expéditeur '{from_email}' ne correspond à aucune source active"

        # Objet
        subject = self._decode_header(msg.get("Subject", ""))

        # Date de réception
        date_str = msg.get("Date", "")
        try:
            received_at = email.utils.parsedate_to_datetime(date_str)
            if received_at.tzinfo is None:
                received_at = received_at.replace(tzinfo=dt_tz.utc)
        except Exception:
            received_at = timezone.now()

        # Corps
        body_text, body_html = self._extract_body(msg)

        # Créer le mail intercepté
        incoming = IncomingMail.objects.create(
            tenant=tenant,
            mail_source=matched_source,
            message_id=message_id,
            from_email=from_email,
            from_name=from_name,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            received_at=received_at,
        )

        # Pièces jointes
        self._save_attachments(msg, incoming)

        if self.verbose:
            self.stdout.write(self.style.SUCCESS(
                f"    ✓ Intercepté : {from_email} — « {subject[:60]} »"
            ))

        # Notifications
        self._notify_tenant_owner(tenant, incoming)
        self._notify_superadmin(incoming)

        return True, "ok"

    # ─────────────────────────────────────────────────────────
    # Matching source
    # ─────────────────────────────────────────────────────────

    def _match_source(self, from_email: str, sources):
        domain = from_email.split("@")[-1] if "@" in from_email else ""
        for source in sources:
            pattern = source.email_or_domain.lower()
            if "@" in pattern:
                if from_email == pattern:
                    return source
            else:
                if domain == pattern:
                    return source
        return None

    # ─────────────────────────────────────────────────────────
    # Parsing email
    # ─────────────────────────────────────────────────────────

    def _decode_header(self, value: str) -> str:
        if not value:
            return ""
        parts = email.header.decode_header(value)
        decoded = []
        for part, charset in parts:
            if isinstance(part, bytes):
                decoded.append(part.decode(charset or "utf-8", errors="replace"))
            else:
                decoded.append(part)
        return " ".join(decoded).strip()

    def _extract_body(self, msg):
        body_text = ""
        body_html = ""

        if msg.is_multipart():
            for part in msg.walk():
                ct = part.get_content_type()
                cd = str(part.get("Content-Disposition", ""))
                if "attachment" in cd:
                    continue
                payload = part.get_payload(decode=True)
                if not payload:
                    continue
                charset = part.get_content_charset() or "utf-8"
                if ct == "text/plain" and not body_text:
                    body_text = payload.decode(charset, errors="replace")
                elif ct == "text/html" and not body_html:
                    body_html = payload.decode(charset, errors="replace")
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                ct = msg.get_content_type()
                if ct == "text/html":
                    body_html = payload.decode(charset, errors="replace")
                else:
                    body_text = payload.decode(charset, errors="replace")

        return body_text, body_html

    def _save_attachments(self, msg, incoming: IncomingMail):
        if not msg.is_multipart():
            return

        for part in msg.walk():
            cd = str(part.get("Content-Disposition", ""))
            if "attachment" not in cd and "inline" not in cd:
                continue

            filename = part.get_filename()
            if not filename:
                continue
            filename = self._decode_header(filename)

            data = part.get_payload(decode=True)
            if not data:
                continue

            ct = part.get_content_type() or "application/octet-stream"

            attachment = MailAttachment(
                mail=incoming,
                filename=filename,
                content_type=ct,
                size=len(data),
            )
            safe_filename = filename.replace("/", "_").replace("\\", "_")
            path = f"mail_attachments/{incoming.tenant_id}/{incoming.id}/{safe_filename}"
            attachment.file.save(path, ContentFile(data), save=True)

    # ─────────────────────────────────────────────────────────
    # Notifications
    # ─────────────────────────────────────────────────────────

    def _notify_tenant_owner(self, tenant, incoming: IncomingMail):
        owner_m = (
            Membership.objects.filter(tenant=tenant, is_owner=True)
            .select_related("user")
            .first()
        )
        if not owner_m or not owner_m.user.email:
            return
        try:
            send_mail(
                subject=f"[ACX] Nouvelle demande client — {incoming.subject[:80]}",
                message=(
                    f"Bonjour {owner_m.user.first_name or owner_m.user.username},\n\n"
                    f"Un nouveau mail client a été reçu et intercepté.\n\n"
                    f"De : {incoming.from_name or incoming.from_email} <{incoming.from_email}>\n"
                    f"Objet : {incoming.subject}\n"
                    f"Client : {incoming.mail_source.client_name if incoming.mail_source else '—'}\n\n"
                    f"Connectez-vous à la plateforme ACX pour le consulter et le dispatcher."
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[owner_m.user.email],
                fail_silently=True,
            )
        except Exception:
            pass

    def _notify_superadmin(self, incoming: IncomingMail):
        superadmin = (
            User.objects.filter(is_superuser=True, is_active=True)
            .order_by("id")
            .first()
        )
        if not superadmin or not superadmin.email:
            return
        try:
            send_mail(
                subject=f"[ACX Platform] Mail intercepté — {incoming.tenant.name}",
                message=(
                    f"Un mail a été intercepté pour le tenant « {incoming.tenant.name} ».\n\n"
                    f"Expéditeur : {incoming.from_email}\n"
                    f"Objet : {incoming.subject}\n"
                    f"Date : {incoming.received_at}\n"
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[superadmin.email],
                fail_silently=True,
            )
        except Exception:
            pass

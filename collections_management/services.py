# collections_management/services.py
from __future__ import annotations

from decimal import Decimal
from typing import Union

from django.apps import apps
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.core.files.base import ContentFile
from django.conf import settings
from django.core.mail import EmailMultiAlternatives

from email import policy
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime, make_msgid

from .models import CollectionCase, CollectionAction, Payment, CollectionCaseStatus, CollectionEmail, CollectionEmailAttachment, CollectionEmailStatus


def _clamp_non_negative(value: Decimal) -> Decimal:
    return value if value > Decimal("0.00") else Decimal("0.00")


def _sync_core_case_balance_from_collection_case(collection_case: CollectionCase) -> None:
    """
    Optionnel (mais recommandé): synchronise le champ balance_amount du modèle `cases.Case`
    avec le solde calculé côté recouvrement (CollectionCase).

    Pourquoi ?
    - Dans l'UI "dossier", l'encours peut venir du module `cases` (Case.balance_amount).
    - Or les paiements sont enregistrés dans `collections_management.Payment`.
    - Donc si on ne synchronise pas, tu vois bien les paiements en base mais l'encours ne bouge pas.
    """
    try:
        Case = apps.get_model("cases", "Case")
    except Exception:
        return

    balance = _clamp_non_negative(collection_case.balance)

    # On identifie le Case par (tenant, reference) — dans ton front, tu crées CollectionCase.reference = Case.reference
    Case.objects.filter(
        tenant_id=collection_case.tenant_id,
        reference=collection_case.reference,
    ).update(balance_amount=balance)


@transaction.atomic
def recompute_case_balances(collection_case: Union[CollectionCase, int], *, sync_core_case: bool = True) -> CollectionCase:
    """
    Recalcule les agrégats "dossier recouvrement" à partir des paiements persistés.
    On met à jour au minimum `total_paid_amount` (dénormalisé) pour alimenter l'UI
    (Total payé / Solde / etc.).

    ✅ Important : l'ancien code écrivait dans paid_amount/balance_amount/last_activity_at
    qui n'existent PAS sur CollectionCase (ton modèle utilise `total_paid_amount`).
    """
    case_id = collection_case.pk if hasattr(collection_case, "pk") else int(collection_case)

    # Lock row pour éviter les races si plusieurs paiements arrivent en même temps
    case = CollectionCase.objects.select_for_update().get(pk=case_id)

    totals = case.payments.aggregate(paid=Sum("amount"))
    paid = totals["paid"] or Decimal("0.00")

    case.total_paid_amount = paid

    # Auto-settle si le solde est à 0 ou moins
    if case.balance <= Decimal("0.00") and case.status not in (
        CollectionCaseStatus.CLOSED,
        CollectionCaseStatus.WRITE_OFF,
    ):
        case.status = CollectionCaseStatus.SETTLED
        case.next_action_date = None
        case.next_action_type = None

    case.save(
        update_fields=[
            "total_paid_amount",
            "status",
            "next_action_date",
            "next_action_type",
            "updated_at",
        ]
    )

    if sync_core_case:
        _sync_core_case_balance_from_collection_case(case)

    return case


@transaction.atomic
def apply_payment_to_case(payment: Payment) -> None:
    """
    Wrapper "métier" : après création/modif/suppression d'un paiement,
    on recalcule les agrégats du dossier.
    """
    recompute_case_balances(payment.case, sync_core_case=True)

@transaction.atomic
def sync_treasury_for_payment(payment: Payment, *, tenant=None, require_account: bool = False) -> None:
    """Synchronise la trésorerie minimaliste avec un paiement.

    Règles:
    - received_by=acx             => crée/maj un TreasuryMovement(IN)
    - received_by=customer_direct => annule (CANCELLED) le mouvement s'il existait

    `require_account=True` permet de forcer l'existence d'un TreasuryAccount pour les paiements ACX
    (sinon le mouvement n'est pas créé et on laisse le paiement exister).
    """
    if tenant is None:
        tenant = getattr(payment, "tenant", None)

    try:
        from treasury_management.models import TreasuryMovement
        from treasury_management.services import record_payment_inflow, get_default_account
    except Exception:
        # module treasury_management non installé
        return

    received_by = getattr(payment, "received_by", None) or "acx"

    if received_by == "customer_direct":
        TreasuryMovement.objects.filter(tenant=tenant, source_key=f"payment:{payment.id}").update(
            status=TreasuryMovement.Status.CANCELLED
        )
        return

    # received_by == acx
    ta = getattr(payment, "treasury_account", None)
    if ta is None:
        # tente d'utiliser un compte par défaut
        ta = get_default_account(tenant=tenant, currency="XAF")
        if ta is not None:
            payment.treasury_account = ta
            payment.save(update_fields=["treasury_account", "updated_at"])

    if ta is None:
        if require_account:
            raise ValueError("No TreasuryAccount configured for this tenant.")
        return

    mv = record_payment_inflow(tenant=tenant, payment=payment, treasury_account=ta, confirmed=True)
    # Réactive si annulé
    if mv and mv.status == TreasuryMovement.Status.CANCELLED:
        mv.status = TreasuryMovement.Status.CONFIRMED
        mv.save(update_fields=["status"])





@transaction.atomic
def apply_action_to_case(action: CollectionAction) -> None:
    """
    Applique sur le dossier les infos "next action" proposées par l'agent + statut en cas de litige.
    """
    case: CollectionCase = action.case

    if action.next_action_date:
        case.next_action_date = action.next_action_date
        case.next_action_type = action.next_action_type

    if action.outcome == "dispute":
        case.status = CollectionCaseStatus.DISPUTED

    case.save(update_fields=["next_action_date", "next_action_type", "status", "updated_at"])

def _emails_from_header(value: str | None) -> list[str]:
    if not value:
        return []
    return [addr.strip() for _, addr in getaddresses([value]) if addr and addr.strip()]


def parse_eml_bytes(eml_bytes: bytes) -> dict:
    '''
    Parse un fichier .eml (RFC822) et retourne un dict normalisé :
    - from_address, to, cc, bcc, subject, message_id, sent_at
    - body_text, body_html
    - attachments: list[{filename, content_type, data, size}]
    '''
    msg = BytesParser(policy=policy.default).parsebytes(eml_bytes)

    from_address = (msg.get("from") or "").strip()
    subject = (msg.get("subject") or "").strip()
    message_id = (msg.get("message-id") or "").strip()

    to_list = _emails_from_header(msg.get("to"))
    cc_list = _emails_from_header(msg.get("cc"))
    bcc_list = _emails_from_header(msg.get("bcc"))

    sent_at = None
    date_hdr = msg.get("date")
    if date_hdr:
        try:
            dt = parsedate_to_datetime(date_hdr)
            if dt is not None:
                if dt.tzinfo is None:
                    dt = timezone.make_aware(dt, timezone.get_current_timezone())
                sent_at = dt
        except Exception:
            sent_at = None

    body_text = ""
    body_html = ""
    attachments: list[dict] = []

    def _is_attachment(part) -> bool:
        cd = part.get_content_disposition()
        filename = part.get_filename()
        return cd == "attachment" or bool(filename)

    if msg.is_multipart():
        for part in msg.walk():
            if part.is_multipart():
                continue

            ctype = (part.get_content_type() or "").lower()
            if _is_attachment(part):
                filename = part.get_filename() or "attachment.bin"
                data = part.get_payload(decode=True) or b""
                attachments.append(
                    {
                        "filename": filename,
                        "content_type": ctype or "application/octet-stream",
                        "data": data,
                        "size": len(data),
                    }
                )
                continue

            payload = part.get_payload(decode=True)
            if payload is None:
                continue

            charset = part.get_content_charset() or "utf-8"
            try:
                decoded = payload.decode(charset, errors="replace")
            except Exception:
                decoded = payload.decode("utf-8", errors="replace")

            if ctype == "text/plain" and not body_text.strip():
                body_text = decoded
            elif ctype == "text/html" and not body_html.strip():
                body_html = decoded
    else:
        ctype = (msg.get_content_type() or "").lower()
        payload = msg.get_payload(decode=True) or b""
        charset = msg.get_content_charset() or "utf-8"
        decoded = payload.decode(charset, errors="replace")
        if ctype == "text/html":
            body_html = decoded
        else:
            body_text = decoded

    return {
        "from_address": from_address,
        "to": to_list,
        "cc": cc_list,
        "bcc": bcc_list,
        "subject": subject,
        "message_id": message_id,
        "sent_at": sent_at,
        "body_text": body_text,
        "body_html": body_html,
        "attachments": attachments,
    }


@transaction.atomic
def attach_outlook_eml(
    *,
    tenant,
    case: CollectionCase,
    eml_file,
    created_by,
    action: CollectionAction | None = None,
    direction: str = "outbound",
    source: str = "outlook",
    notes: str = "",
    create_action_if_missing: bool = True,
) -> tuple[CollectionEmail, CollectionAction]:
    '''
    Attache un email Outlook (fichier .eml) au dossier recouvrement.
    - Crée (ou réutilise) une CollectionAction(action_type=email) pour la timeline.
    - Crée un CollectionEmail + ses attachments.
    - Met à jour la timeline (action_date, summary, details).
    '''
    if not eml_file:
        raise ValueError("eml_file is required")

    raw_bytes = eml_file.read()
    parsed = parse_eml_bytes(raw_bytes)

    if action is None:
        if not create_action_if_missing:
            raise ValueError("action is required when create_action_if_missing=False")

        action = CollectionAction.objects.create(
            tenant=tenant,
            case=case,
            action_type="email",
            outcome=None,
            summary=parsed["subject"] or "Email (Outlook)",
            details="Email envoyé via Outlook. Preuve attachée.",
            action_date=parsed["sent_at"] or timezone.now(),
            created_by=created_by,
        )
    else:
        if action.tenant_id != tenant.id or action.case_id != case.id:
            raise ValueError("Action does not belong to current tenant/case")

        if not (action.summary or "").strip():
            action.summary = parsed["subject"] or "Email (Outlook)"

        if parsed["sent_at"]:
            action.action_date = parsed["sent_at"]

        extra_line = f"Preuve Outlook attachée: {getattr(eml_file, 'name', 'email.eml')}"
        if extra_line not in (action.details or ""):
            action.details = ((action.details or "").rstrip() + "\n" + extra_line).strip()

        action.save(update_fields=["summary", "details", "action_date", "updated_at"])

    raw_name = getattr(eml_file, "name", None) or "email.eml"
    raw_content = ContentFile(raw_bytes, name=raw_name)

    email_obj = CollectionEmail.objects.create(
        tenant=tenant,
        case=case,
        action=action,
        direction=direction,
        source=source,
        status=CollectionEmailStatus.RECEIVED,
        provider="outlook" if source == "outlook" else source,
        from_address=parsed["from_address"] or "",
        to=parsed["to"] or [],
        cc=parsed["cc"] or [],
        bcc=parsed["bcc"] or [],
        subject=parsed["subject"] or "",
        sent_at=parsed["sent_at"],
        message_id=parsed["message_id"] or "",
        body_text=parsed["body_text"] or "",
        body_html=parsed["body_html"] or "",
        raw_eml=raw_content,
        notes=(notes or "").strip(),
        created_by=created_by,
    )

    for att in parsed["attachments"]:
        filename = att.get("filename") or "attachment.bin"
        data = att.get("data") or b""
        ctype = att.get("content_type") or "application/octet-stream"

        a = CollectionEmailAttachment(
            email=email_obj,
            filename=filename,
            content_type=ctype,
            size=len(data),
        )
        a.file.save(filename, ContentFile(data), save=False)
        a.save()

    return email_obj, action


@transaction.atomic
def send_acx_email(
    *,
    tenant,
    case: CollectionCase,
    to: list[str],
    subject: str,
    body_text: str = "",
    body_html: str = "",
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    from_address: str | None = None,
    notes: str = "",
    created_by=None,
    action: CollectionAction | None = None,
    attachments: list | None = None,
) -> tuple[CollectionEmail, CollectionAction]:
    """
    Envoie un email depuis ACX (SMTP Django) et stocke une preuve (.eml) + PJ.

    Métier:
    - Crée (ou réutilise) une CollectionAction(action_type=email) pour la timeline.
    - Crée un CollectionEmail + ses attachments.
    - Statut: queued -> sent/failed
    """
    cc = cc or []
    bcc = bcc or []
    attachments = attachments or []

    # Action timeline
    if action is None:
        action = CollectionAction.objects.create(
            tenant=tenant,
            case=case,
            action_type="email",
            outcome="reached",
            summary=(subject or "Email envoyé"),
            details=(notes or "").strip(),
            action_date=timezone.now(),
            next_action_type=None,
            next_action_date=None,
            created_by=created_by,
        )

    # Message-ID RFC
    msgid = make_msgid()

    # Email record (preuve métier)
    email_obj = CollectionEmail.objects.create(
        tenant=tenant,
        case=case,
        action=action,
        direction="outbound",
        source="acx",
        status=CollectionEmailStatus.QUEUED,
        provider="smtp",
        from_address=(from_address or getattr(settings, "DEFAULT_FROM_EMAIL", "") or ""),
        to=to,
        cc=cc,
        bcc=bcc,
        subject=subject or "",
        body_text=body_text or "",
        body_html=body_html or "",
        notes=notes or "",
        message_id=msgid,
        sent_at=None,
        error_message="",
        created_by=created_by,
    )

    # Sauvegarder les PJ en base (preuve)
    for f in attachments:
        if not f:
            continue
        try:
            f.seek(0)
        except Exception:
            pass

        a = CollectionEmailAttachment(
            email=email_obj,
            filename=getattr(f, "name", "") or "",
            content_type=getattr(f, "content_type", "") or "",
            size=getattr(f, "size", 0) or 0,
        )
        a.file.save(a.filename or "attachment.bin", f, save=False)
        a.save()

    # Construire le message (Django)
    msg = EmailMultiAlternatives(
        subject=subject or "",
        body=body_text or "",
        from_email=(from_address or getattr(settings, "DEFAULT_FROM_EMAIL", None)),
        to=to,
        cc=cc,
        bcc=bcc,
        headers={"Message-ID": msgid},
    )
    if body_html:
        msg.attach_alternative(body_html, "text/html")

    # Attachments SMTP
    for f in attachments:
        if not f:
            continue
        try:
            f.seek(0)
        except Exception:
            pass
        data = f.read()
        ctype = getattr(f, "content_type", None) or "application/octet-stream"
        filename = getattr(f, "name", None) or "attachment"
        msg.attach(filename, data, ctype)

    # Preuve .eml (générée par ACX)
    try:
        raw_bytes = msg.message().as_bytes()
        eml_name = f"acx_{case.reference}_{timezone.now().strftime('%Y%m%d%H%M%S')}.eml"
        email_obj.raw_eml.save(eml_name, ContentFile(raw_bytes), save=False)
    except Exception:
        # on n'empêche pas l'envoi si la preuve échoue
        pass

    # Envoi + statut
    try:
        msg.send(fail_silently=False)
        email_obj.status = CollectionEmailStatus.SENT
        email_obj.sent_at = timezone.now()
        email_obj.error_message = ""
    except Exception as e:
        email_obj.status = CollectionEmailStatus.FAILED
        email_obj.sent_at = timezone.now()
        email_obj.error_message = str(e)

    email_obj.save(update_fields=["status", "sent_at", "error_message", "updated_at", "raw_eml"])

    return email_obj, action

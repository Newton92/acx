# cases/email_notifications.py
"""
Envoi des notifications email lors des modifications de dossiers.
Appelé depuis le signal post_save de Case.
"""
import logging
import threading
from django.conf import settings
from django.core.mail import EmailMultiAlternatives

logger = logging.getLogger(__name__)

TRACKED_FIELDS = {
    "status":        "Statut",
    "priority":      "Priorité",
    "title":         "Titre",
    "balance_amount": "Solde",
    "due_date":      "Échéance",
    "assigned_to_id": "Agent responsable",
    "creditor_id":   "Créancier",
    "portfolio_id":  "Portefeuille",
}

STATUS_LABELS = {
    "open":        "Ouvert",
    "in_progress": "En cours",
    "on_hold":     "En attente",
    "closed":      "Clôturé",
}

PRIORITY_LABELS = {
    "low":    "Faible",
    "medium": "Moyenne",
    "high":   "Élevée",
    "urgent": "Urgente",
}


def _human(field: str, value) -> str:
    if value is None:
        return "—"
    if field == "status":
        return STATUS_LABELS.get(str(value), str(value))
    if field == "priority":
        return PRIORITY_LABELS.get(str(value), str(value))
    return str(value)


def _build_html(case, changes: dict, actor_name: str) -> str:
    rows = ""
    for field, vals in changes.items():
        label = TRACKED_FIELDS.get(field, field)
        old = _human(field, vals["old"])
        new = _human(field, vals["new"])
        rows += f"""
        <tr>
          <td style="padding:8px 12px;border-bottom:1px solid #f1f5f9;color:#64748b;font-size:13px;">{label}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #f1f5f9;font-size:13px;text-decoration:line-through;color:#94a3b8;">{old}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #f1f5f9;font-size:13px;font-weight:600;color:#1a3578;">{new}</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f8fafc;font-family:system-ui,-apple-system,sans-serif;">
  <div style="max-width:580px;margin:32px auto;background:#fff;border-radius:16px;
              border:1px solid rgba(15,23,42,.07);overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,.06);">

    <!-- Header -->
    <div style="background:linear-gradient(135deg,#1a3578 0%,#2655b0 100%);padding:24px 28px;">
      <div style="color:#fff;font-size:18px;font-weight:700;margin-bottom:4px;">
        Dossier mis à jour
      </div>
      <div style="color:rgba(255,255,255,.75);font-size:13px;">
        Référence : {case.reference}
      </div>
    </div>

    <!-- Body -->
    <div style="padding:24px 28px;">
      <p style="margin:0 0 16px;font-size:14px;color:#475569;">
        Le dossier <strong style="color:#1a3578;">{case.title}</strong> a été modifié
        par <strong>{actor_name}</strong>.
      </p>

      <table style="width:100%;border-collapse:collapse;border-radius:10px;overflow:hidden;
                    border:1px solid #f1f5f9;margin-bottom:20px;">
        <thead>
          <tr style="background:#f8fafc;">
            <th style="padding:8px 12px;text-align:left;font-size:11px;font-weight:700;
                       text-transform:uppercase;letter-spacing:.06em;color:#94a3b8;">Champ</th>
            <th style="padding:8px 12px;text-align:left;font-size:11px;font-weight:700;
                       text-transform:uppercase;letter-spacing:.06em;color:#94a3b8;">Avant</th>
            <th style="padding:8px 12px;text-align:left;font-size:11px;font-weight:700;
                       text-transform:uppercase;letter-spacing:.06em;color:#94a3b8;">Après</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>

      <p style="margin:0;font-size:12px;color:#94a3b8;">
        Ceci est un message automatique — merci de ne pas y répondre directement.
      </p>
    </div>

    <!-- Footer -->
    <div style="background:#f8fafc;padding:14px 28px;border-top:1px solid #f1f5f9;">
      <p style="margin:0;font-size:11px;color:#cbd5e1;">ACX · Gestion de recouvrement</p>
    </div>
  </div>
</body>
</html>"""


def _send_notification(case_id: int, changes: dict, actor_name: str):
    """Envoi réel — exécuté dans un thread daemon."""
    try:
        from cases.models import Case
        case = (
            Case.objects
            .select_related("customer", "creditor", "debtor")
            .get(pk=case_id)
        )
    except Exception:
        return

    recipients: list[str] = []

    if case.notify_customer and case.customer and case.customer.email:
        recipients.append(case.customer.email)

    if case.notify_creditor:
        cred_email = None
        if case.creditor_id and case.creditor and case.creditor.email:
            cred_email = case.creditor.email
        elif not case.creditor_id and case.customer and case.customer.email:
            # créancier = client, email déjà ajouté si notify_customer
            cred_email = None
        if cred_email and cred_email not in recipients:
            recipients.append(cred_email)

    if case.notify_debtor and case.debtor and case.debtor.email:
        email = case.debtor.email
        if email not in recipients:
            recipients.append(email)

    if not recipients:
        return

    subject = f"[ACX] Mise à jour dossier {case.reference}"
    html = _build_html(case, changes, actor_name)
    text = (
        f"Dossier {case.reference} — {case.title}\n"
        f"Modifié par : {actor_name}\n\n"
        + "\n".join(
            f"- {TRACKED_FIELDS.get(f, f)} : {_human(f, v['old'])} → {_human(f, v['new'])}"
            for f, v in changes.items()
        )
    )

    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@acx.app")

    try:
        msg = EmailMultiAlternatives(subject, text, from_email, recipients)
        msg.attach_alternative(html, "text/html")
        msg.send(fail_silently=True)
        logger.info("Notification case %s envoyée à %s", case.reference, recipients)
    except Exception as exc:
        logger.warning("Notification case %s échouée: %s", case.reference, exc)


def send_case_change_notifications(case_id: int, changes: dict, actor_name: str):
    """Lance l'envoi en arrière-plan pour ne pas bloquer la réponse API."""
    if not changes:
        return
    t = threading.Thread(
        target=_send_notification,
        args=(case_id, changes, actor_name),
        daemon=True,
    )
    t.start()

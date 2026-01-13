# customers/models_support.py
from django.conf import settings
from django.db import models
from django.utils import timezone

from customers.models import Customer
from tenancy.models import Tenant


class SupportTicket(models.Model):
    class Category(models.TextChoices):
        ACCESS = "access", "Access / Account"
        CASES = "cases", "Cases"
        DOCUMENTS = "documents", "Documents"
        PAYMENTS = "payments", "Payments"
        OTHER = "other", "Other"

    class Priority(models.TextChoices):
        NORMAL = "normal", "Normal"
        URGENT = "urgent", "Urgent"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        IN_PROGRESS = "in_progress", "In progress"
        WAITING_CUSTOMER = "waiting_customer", "Waiting customer"
        RESOLVED = "resolved", "Resolved"
        CLOSED = "closed", "Closed"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="support_tickets")
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="support_tickets")

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_support_tickets")

    subject = models.CharField(max_length=200)
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.OTHER)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.NORMAL)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)

    # optionnel : relier au dossier
    case_id = models.IntegerField(null=True, blank=True, db_index=True)

    last_activity_at = models.DateTimeField(default=timezone.now)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-last_activity_at", "-id"]

    def __str__(self):
        return f"Ticket #{self.id} - {self.subject}"


class SupportTicketMessage(models.Model):
    class Side(models.TextChoices):
        CUSTOMER = "customer", "Customer"
        TENANT = "tenant", "Tenant"
        PLATFORM = "platform", "Platform"

    ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name="messages")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    side = models.CharField(max_length=12, choices=Side.choices, default=Side.CUSTOMER)

    body = models.TextField()

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return f"TicketMessage #{self.id} ({self.ticket_id})"


class SupportTicketAttachment(models.Model):
    message = models.ForeignKey(SupportTicketMessage, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to="support/tickets/")
    filename = models.CharField(max_length=255, blank=True, null=True)
    content_type = models.CharField(max_length=120, blank=True, null=True)
    size = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return self.filename or f"Attachment #{self.id}"

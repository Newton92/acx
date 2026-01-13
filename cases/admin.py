from django.contrib import admin
from cases.models import Portfolio, Debtor, Case, CaseNote, CaseDocument

@admin.register(Portfolio)
class PortfolioAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "name", "is_active", "created_at")
    search_fields = ("name",)
    list_filter = ("is_active", "tenant")

@admin.register(Debtor)
class DebtorAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "type", "full_name", "phone", "email", "created_at")
    search_fields = ("full_name", "phone", "email", "national_id", "tax_id")
    list_filter = ("type", "tenant")

@admin.register(Case)
class CaseAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "reference", "title", "status", "priority", "assigned_to", "opened_at")
    search_fields = ("reference", "title", "debtor__full_name")
    list_filter = ("status", "priority", "tenant")
    raw_id_fields = ("debtor", "assigned_to", "created_by")

@admin.register(CaseNote)
class CaseNoteAdmin(admin.ModelAdmin):
    list_display = ("id", "case", "author", "created_at")

@admin.register(CaseDocument)
class CaseDocumentAdmin(admin.ModelAdmin):
    list_display = ("id", "case", "title", "doc_type", "uploaded_by", "created_at")

from django.contrib import admin

from .models import Attachment, Settlement, SettlementEvent


class SettlementEventInline(admin.TabularInline):
    model = SettlementEvent
    extra = 0
    readonly_fields = ("from_state", "to_state", "actor", "reason", "created_at")


@admin.register(Settlement)
class SettlementAdmin(admin.ModelAdmin):
    list_display = ("id", "transaction", "category", "status", "submitted_by", "created_at")
    list_filter = ("status", "category")
    inlines = [SettlementEventInline]


class AttachmentInline(admin.TabularInline):
    """추가 증빙 — 추출 결과는 Agent가 채우므로 읽기 전용으로 확인만 한다."""
    model = Attachment
    extra = 0
    fields = ("kind", "original_name", "extraction_status", "extracted", "extracted_at")
    readonly_fields = ("extraction_status", "extracted", "extracted_at")


SettlementAdmin.inlines = [SettlementEventInline, AttachmentInline]

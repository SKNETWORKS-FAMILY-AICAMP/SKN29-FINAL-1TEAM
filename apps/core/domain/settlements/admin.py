from django.contrib import admin

from .models import Settlement, SettlementEvent


class SettlementEventInline(admin.TabularInline):
    model = SettlementEvent
    extra = 0
    readonly_fields = ("from_state", "to_state", "actor", "reason", "created_at")


@admin.register(Settlement)
class SettlementAdmin(admin.ModelAdmin):
    list_display = ("id", "transaction", "category", "status", "submitted_by", "created_at")
    list_filter = ("status", "category")
    inlines = [SettlementEventInline]

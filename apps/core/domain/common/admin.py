from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("id", "action", "target", "actor", "created_at")
    list_filter = ("action",)
    readonly_fields = ("actor", "action", "target", "before", "after", "created_at")

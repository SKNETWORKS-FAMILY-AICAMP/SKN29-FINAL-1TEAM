from django.contrib import admin

from .models import ErpVoucher


@admin.register(ErpVoucher)
class ErpVoucherAdmin(admin.ModelAdmin):
    list_display = ("id", "settlement", "status", "created_at")
    list_filter = ("status",)

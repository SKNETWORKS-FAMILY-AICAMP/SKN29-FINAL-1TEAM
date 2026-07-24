from django.contrib import admin

from .models import MerchantCategory, Receipt, Transaction


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ("id", "merchant", "amount", "ts", "card")
    search_fields = ("merchant",)


@admin.register(MerchantCategory)
class MerchantCategoryAdmin(admin.ModelAdmin):
    list_display = ("normalized_name", "industry_label", "source", "confidence", "resolved_at")
    list_filter = ("source",)
    search_fields = ("normalized_name",)


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = ("id", "status", "matched_tx")

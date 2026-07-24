from django.contrib import admin

from .models import Card


@admin.register(Card)
class CardAdmin(admin.ModelAdmin):
    list_display = ("id", "card_type", "name", "owner", "team")
    list_filter = ("card_type",)

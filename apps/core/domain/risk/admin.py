from django.contrib import admin

from .models import DecisionLabel, RiskReview


@admin.register(RiskReview)
class RiskReviewAdmin(admin.ModelAdmin):
    list_display = ("id", "settlement", "anomaly_score", "ai_recommendation", "ai_confidence")


@admin.register(DecisionLabel)
class DecisionLabelAdmin(admin.ModelAdmin):
    list_display = ("id", "settlement", "label", "actor", "created_at")

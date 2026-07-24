"""Risk 결과 / 학습 라벨 (기술명세서 §3.1).

MVP: 비지도 이상탐지(1차) + RAG 내규검증(2차) 결과. review_prob는 post-MVP(nullable).
decision_labels는 MVP에선 '적재만' — 향후 지도학습용.
"""
from django.conf import settings
from django.db import models


class RiskReview(models.Model):
    settlement = models.ForeignKey(
        "settlements.Settlement", on_delete=models.CASCADE, related_name="risk_reviews"
    )
    anomaly_score = models.FloatField(default=0.0)          # 1차 비지도 이상탐지
    reasons = models.JSONField(default=list, blank=True)    # 피처 기여/이상 사유
    rag_refs = models.JSONField(default=list, blank=True)   # 2차 RAG 근거(출처 포함)
    ai_recommendation = models.CharField(max_length=10, blank=True)  # APPROVE/RETURN/REJECT
    ai_confidence = models.FloatField(default=0.0)
    review_prob = models.FloatField(null=True, blank=True)  # post-MVP 지도학습
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-anomaly_score"]


class DecisionLabel(models.Model):
    class Label(models.TextChoices):
        APPROVE = "APPROVE", "승인"
        RETURN = "RETURN", "보완요청"
        REJECT = "REJECT", "반려"
        CORRECT = "CORRECT", "수정"

    settlement = models.ForeignKey(
        "settlements.Settlement", on_delete=models.CASCADE, related_name="decision_labels"
    )
    label = models.CharField(max_length=10, choices=Label.choices)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

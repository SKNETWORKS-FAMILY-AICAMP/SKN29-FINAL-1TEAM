"""정산/상태이력 — SoR의 핵심 (기술명세서 §3.1, §3.3 / 요구사항 §4.4).

상태머신(FR-ST-01):
  DRAFT→SUBMITTED→RPA_JUDGED→(PENDING_CONFIRM/RETURNED/IN_REVIEW/REJECT)→CONFIRMED→ERP_VOUCHER_DRAFTED
  REJECT=최종반려(재제출 불가), RETURNED=보완요청(재제출 가능)
전이는 서비스 레이어(services.py)에서만 수행하고 SettlementEvent + audit_logs에 기록한다.
"""
from django.conf import settings
from django.db import models


class Category(models.TextChoices):
    OPERATION = "업무활성", "업무활성"
    MEETING = "회의", "회의"
    MEAL = "식대", "식대"
    TRIP = "출장", "출장"
    ENTERTAIN = "접대", "접대"
    SUPPLIES = "비품", "비품"


class SettlementStatus(models.TextChoices):
    DRAFT = "DRAFT", "초안"
    SUBMITTED = "SUBMITTED", "제출됨"
    RPA_JUDGED = "RPA_JUDGED", "1차판정"
    PENDING_CONFIRM = "PENDING_CONFIRM", "승인대기"
    RETURNED = "RETURNED", "보완요청"
    IN_REVIEW = "IN_REVIEW", "검토중"
    REJECT = "REJECT", "반려(최종)"
    CONFIRMED = "CONFIRMED", "확정"
    ERP_VOUCHER_DRAFTED = "ERP_VOUCHER_DRAFTED", "전표생성"


class Settlement(models.Model):
    transaction = models.ForeignKey(
        "transactions.Transaction", on_delete=models.CASCADE, related_name="settlements"
    )
    category = models.CharField(max_length=20, choices=Category.choices, blank=True)
    ai_category = models.CharField(max_length=20, choices=Category.choices, blank=True)  # AI 제안
    ai_suggested = models.BooleanField(default=False)  # 저신뢰라 사용자 확인 필요
    merchant_industry = models.CharField(max_length=100, blank=True)  # 업종(보조, §6.5)
    status = models.CharField(
        max_length=24, choices=SettlementStatus.choices, default=SettlementStatus.DRAFT
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="settlements",
    )
    team = models.ForeignKey(
        "accounts.Team", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="settlements",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Settlement#{self.pk} ({self.status})"


class SettlementEvent(models.Model):
    settlement = models.ForeignKey(Settlement, on_delete=models.CASCADE, related_name="events")
    from_state = models.CharField(max_length=24, blank=True)
    to_state = models.CharField(max_length=24)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

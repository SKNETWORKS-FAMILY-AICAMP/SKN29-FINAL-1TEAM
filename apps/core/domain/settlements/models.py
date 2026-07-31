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
    DRAFT = "DRAFT", "개인 보유중"
    # ② 팀 취합 단계
    TEAM_COLLECTING = "TEAM_COLLECTING", "팀 취합중"
    TEAM_RETURNED = "TEAM_RETURNED", "팀 보완요청"
    TEAM_REJECTED = "TEAM_REJECTED", "팀 반려"
    SUBMITTED = "SUBMITTED", "회계 제출"
    RPA_JUDGED = "RPA_JUDGED", "1차판정"
    PENDING_CONFIRM = "PENDING_CONFIRM", "승인대기"
    RETURNED = "RETURNED", "보완요청"
    IN_REVIEW = "IN_REVIEW", "검토중"
    REJECT = "REJECT", "반려(최종)"
    CONFIRMED = "CONFIRMED", "확정"
    ERP_VOUCHER_DRAFTED = "ERP_VOUCHER_DRAFTED", "전표생성"


class Settlement(models.Model):
    # PROTECT: 거래를 물리 삭제해도 정산·이력·감사(events/risk/labels/hits/voucher)가 연쇄 삭제되지 않도록 차단.
    #  (append-only·감사추적 원칙 — 다른 FK도 이력 보존 위해 SET_NULL). 삭제가 필요하면 소프트 삭제(상태값)로.
    transaction = models.ForeignKey(
        "transactions.Transaction", on_delete=models.PROTECT, related_name="settlements"
    )
    category = models.CharField(max_length=20, choices=Category.choices, blank=True)
    ai_category = models.CharField(max_length=20, choices=Category.choices, blank=True)  # AI 제안
    ai_suggested = models.BooleanField(default=False)  # 저신뢰라 사용자 확인 필요
    merchant_industry = models.CharField(max_length=100, blank=True)  # 업종(보조, §6.5)
    purpose = models.CharField("지출 목적/사유", max_length=300, blank=True)
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


class TeamBudget(models.Model):
    """팀·월·계정과목별 예산 한도 (SoR의 DB 데이터).

    예산은 통제(차단)가 아니라 지표·추천 근거로만 쓴다(CLAUDE §2). 한도(limit)만 DB로 정의하고,
    사용액(used)은 저장하지 않고 해당 팀·월·과목의 Settlement 집계로 산출한다(실 내역 개체 기반).
    category='' 행은 팀 총예산(월 총한도)을 의미한다.
    """
    team = models.ForeignKey(
        "accounts.Team", on_delete=models.CASCADE, related_name="budgets"
    )
    year_month = models.CharField("YYYY-MM", max_length=7)  # 예: '2026-07'
    category = models.CharField(max_length=20, choices=Category.choices, blank=True)  # ''=팀 총예산
    limit_amount = models.PositiveBigIntegerField("한도(원)", default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("team", "year_month", "category")
        ordering = ["team", "year_month", "category"]

    def __str__(self):
        return f"{self.team} {self.year_month} {self.category or '총액'} {self.limit_amount:,}"


class SettlementEvent(models.Model):
    settlement = models.ForeignKey(Settlement, on_delete=models.CASCADE, related_name="events")
    from_state = models.CharField(max_length=24, blank=True)
    to_state = models.CharField(max_length=24)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

"""정산/상태이력 — SoR의 핵심 (기술명세서 §3.1, §3.3 / 요구사항 §4.4).

상태머신(FR-ST-01):
  DRAFT→SUBMITTED→RPA_JUDGED→(PENDING_CONFIRM/RETURNED/IN_REVIEW/REJECT)→CONFIRMED→ERP_VOUCHER_DRAFTED
  REJECT=최종반려(재제출 불가), RETURNED=보완요청(재제출 가능)
전이는 서비스 레이어(services.py)에서만 수행하고 SettlementEvent + audit_logs에 기록한다.
"""
from django.conf import settings
from django.db import models


class Category(models.TextChoices):
    GATHERING = "회식", "회식"
    MEETING = "회의", "회의"
    MEAL = "식대", "식대"
    TRIP = "출장", "출장"
    ENTERTAIN = "접대", "접대"
    SUPPLIES = "비품", "비품"


class ItemType(models.TextChoices):
    """지출 세부유형 — 청탁금지 한도 룩업 키(`kickback_limit_table`)를 겸한다.

    구 `policy.gift_type`이 여기로 이관됐다(정책값이 아니라 룩업 키였다 —
    `_context/policy-domain.md` §4.1).
    """
    MEAL = "식사", "식사·다과"
    GIFT = "선물", "선물"
    CONDOLENCE = "경조사", "경조사비"
    VOUCHER = "상품권", "상품권·유가증권"
    EVENT = "행사성", "행사성"
    LODGING = "숙박", "숙박"
    TRANSPORT = "교통", "교통"
    SUPPLY = "소모품", "소모품·비품"
    OTHER = "기타", "기타"


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
    # ── 판정 입력 필드 (EvalContext 원자 사실) ─────────────────────
    #  룰 엔진이 비교할 '사실'을 저장한다. 조립기(`policies/context_builder`)가 그대로 읽는다.
    #
    #  **전부 null 허용이다. `None`은 "거짓"이 아니라 "모름"을 뜻한다**
    #  (`_context/eval-context-sourcing.md` §0 계약). 사용자가 확인해 "아니오"를 고르면 False를
    #  저장하고, 아예 묻지 않았거나 비워두면 None으로 남긴다. None이면 그 필드를 참조하는 룰은
    #  미해소 가드가 REVIEW로 강등한다 — 모르는 채로 통과시키지 않기 위해서다.
    #
    #  값의 출처는 두 갈래다: 화면 입력, 그리고 첨부 문서 추출(`Attachment.extracted`).
    headcount = models.PositiveIntegerField(
        "참석 인원", null=True, blank=True,
        help_text="0 = 참석자 기록 없음(=명단 누락). 비우면 '모름'.",
    )
    external_headcount = models.PositiveIntegerField("외부 참석 인원", null=True, blank=True)
    pre_approved = models.BooleanField("사전승인 받음", null=True, blank=True)
    actual_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, verbose_name="카드 실사용자",
        on_delete=models.SET_NULL, related_name="used_settlements",
    )
    actual_user_recorded = models.BooleanField(
        "실사용자 기록 여부", null=True, blank=True,
        help_text="공용·팀 카드에서만 의미 있다. 개인카드는 조립기가 True로 채운다.",
    )
    item_type = models.CharField(
        "지출 세부유형", max_length=20, choices=ItemType.choices, blank=True,
        help_text="청탁금지 한도(kickback_limit_table) 룩업 키로도 쓰인다.",
    )
    kickback_target = models.BooleanField("청탁금지법 대상자 참석", null=True, blank=True)
    is_secondary_venue = models.BooleanField("2차 성격 지출", null=True, blank=True)
    includes_alcohol = models.BooleanField("주류 포함", null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Settlement#{self.pk} ({self.status})"

    @property
    def per_person_amount(self):
        """1인당 환산 금액. 인원을 모르거나 0명이면 계산하지 않는다(None = 모름)."""
        if not self.headcount:
            return None
        amount = getattr(self.transaction, "amount", None)
        return int(amount) // self.headcount if amount is not None else None


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


# 추가 증빙 첨부 + 추출 결과는 별도 모듈에 둔다(모델 등록을 위해 여기서 재노출).
from .attachments import Attachment, AttachmentKind, ExtractionStatus  # noqa: E402,F401

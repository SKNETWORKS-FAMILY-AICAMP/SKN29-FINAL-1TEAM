"""거래 / 가맹점 업종 캐시 / 증빙 (기술명세서 §3.1, §7-1)."""
from django.db import models


class Transaction(models.Model):
    card = models.ForeignKey(
        "cards.Card", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="transactions",
    )
    merchant = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=12, decimal_places=0)  # KRW 정수
    ts = models.DateTimeField("거래일시")
    raw_payload = models.JSONField(default=dict, blank=True)
    # 카드사/ERP 결제기록의 원천 식별자(승인번호 등). **재수집 멱등성의 근거**다 —
    # "내역 불러오기"를 두 번 눌러도 같은 결제가 두 건이 되면 안 된다.
    # 손으로 만든 거래(F-1 신규 등록)는 빈 문자열이라 아래 제약에 걸리지 않는다.
    external_id = models.CharField("원천 식별자", max_length=64, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-ts"]
        constraints = [
            models.UniqueConstraint(
                fields=["external_id"],
                condition=~models.Q(external_id=""),
                name="uq_transaction_external_id",
            ),
        ]

    def __str__(self):
        return f"{self.merchant} {self.amount}"


class MerchantSource(models.TextChoices):
    CACHE = "CACHE", "캐시"
    KAKAO = "KAKAO", "카카오 지도"


class MerchantCategory(models.Model):
    """가맹점 업종 캐시 (§7-1). 비용분류 보조 힌트 — 세무 기준 아님(MCC는 post-MVP)."""
    normalized_name = models.CharField(max_length=200, unique=True, db_index=True)
    place_id = models.CharField(max_length=64, blank=True)
    industry_code = models.CharField(max_length=32, blank=True)
    industry_label = models.CharField(max_length=100, blank=True)
    source = models.CharField(max_length=10, choices=MerchantSource.choices, default=MerchantSource.CACHE)
    confidence = models.FloatField(default=0.0)
    resolved_at = models.DateTimeField(auto_now=True)
    raw = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name_plural = "merchant categories"

    def __str__(self):
        return f"{self.normalized_name} → {self.industry_label}"


class Receipt(models.Model):
    class Status(models.TextChoices):
        UPLOADED = "UPLOADED", "업로드됨"
        MATCHED = "MATCHED", "매칭됨"
        MISSING = "MISSING", "누락"

    file_ref = models.CharField(max_length=300, blank=True)
    ocr_text = models.TextField(blank=True)
    matched_tx = models.ForeignKey(
        Transaction, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="receipts",
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.UPLOADED)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Receipt#{self.pk} ({self.status})"

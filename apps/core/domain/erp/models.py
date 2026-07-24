"""ERP 전표(안) (기술명세서 §3.1).

MVP는 전표(안) 생성까지만. 실제 ERP 적재·연동은 범위 밖.
"""
from django.db import models


class ErpVoucher(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "전표(안)"
        CONFIRMED = "CONFIRMED", "확정"

    settlement = models.OneToOneField(
        "settlements.Settlement", on_delete=models.CASCADE, related_name="voucher"
    )
    voucher_payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Voucher(settlement={self.settlement_id}, {self.status})"

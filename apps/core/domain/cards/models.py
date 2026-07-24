"""카드 (기술명세서 §3.1). 카드 구분에 따라 사용자 귀속·증빙 요구가 달라진다."""
from django.conf import settings
from django.db import models


class CardType(models.TextChoices):
    PERSONAL = "PERSONAL", "개인 배정"
    TEAM = "TEAM", "팀 카드"
    SHARED = "SHARED", "공용"
    POST_PAID = "POST_PAID", "후정산"
    PREPAID = "PREPAID", "선결제·충전형"


class Card(models.Model):
    card_type = models.CharField(max_length=20, choices=CardType.choices)
    name = models.CharField(max_length=100, blank=True)
    number_masked = models.CharField(max_length=25, blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="cards",
    )
    team = models.ForeignKey(
        "accounts.Team", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="cards",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.get_card_type_display()} {self.number_masked or self.name}"

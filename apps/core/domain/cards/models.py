"""카드 (기술명세서 §3.1). 카드 구분에 따라 사용자 귀속·증빙 요구가 달라진다."""
from django.conf import settings
from django.db import models


class CardType(models.TextChoices):
    PERSONAL = "PERSONAL", "개인 배정"
    TEAM = "TEAM", "팀 카드"
    SHARED = "SHARED", "공용"
    POST_PAID = "POST_PAID", "후정산"
    PREPAID = "PREPAID", "선결제·충전형"


class CardStatus(models.TextChoices):
    """**사람이 내린 결정만** 저장한다.

    "회수/중지가 필요하다"는 상태는 여기 없다 — 그건 저장값이 아니라 **파생**이기 때문이다
    (퇴사 여부·최근 사용 패턴에서 계산된다). 컬럼으로 굳히면 퇴사 처리 뒤에도 카드가
    `NORMAL`로 남아 조용히 어긋난다. 규정 문서 화면의 조항 상태와 같은 규율이다.
    """
    ACTIVE = "ACTIVE", "정상"
    STOPPED = "STOPPED", "정지·회수"


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
    #  월 사용 한도. **사용액은 저장하지 않는다** — 해당 카드·월 Transaction 집계로 낸다
    #  (TeamBudget과 같은 규율: 한도만 DB, 사용액은 실 내역에서).
    limit_amount = models.PositiveBigIntegerField("월 한도(원)", default=0)

    status = models.CharField(max_length=12, choices=CardStatus.choices, default=CardStatus.ACTIVE)
    stopped_reason = models.TextField("정지 사유", blank=True)
    stopped_at = models.DateTimeField(null=True, blank=True)
    stopped_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.get_card_type_display()} {self.number_masked or self.name}"

    @property
    def assignee_label(self) -> str:
        """배정 대상 표기 — 개인카드는 사람, 팀·공용은 팀."""
        if self.owner_id:
            team = getattr(self.owner, "team", None)
            who = self.owner.first_name or self.owner.get_full_name() or self.owner.username
            return f"{who}" + (f" ({team.name})" if team else "")
        if self.team_id:
            return self.team.name
        return "미배정"

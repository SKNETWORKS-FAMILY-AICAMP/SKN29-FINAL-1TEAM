"""ERP/카드사 결제기록 수집 — "내역 불러오기".

실제 연동(카드사 API·ERP 배치) 대신 **미리 준비한 표본 3회분**을 순서대로 넣는다. 수집
자체의 규칙(귀속·멱등성·상태)은 실제 연동과 같게 짜 뒀으므로, 나중에 `SAMPLE_BATCHES`를
실제 커넥터 응답으로 바꾸면 아래 로직은 그대로 쓴다.

## 단위는 **카드 결제기록 1건**

ERP가 주는 건 "정산"이 아니라 결제다. 그래서 결제기록 하나가 `Transaction` 하나가 되고,
그 위에 `Settlement`(DRAFT)이 하나 붙는다. 사람은 그 초안을 고쳐서 올린다.

## 귀속 규칙 — 카드 구분이 정한다

  · **개인 배정 카드**: 카드에 배정된 사람이 곧 사용자다 → `submitted_by=owner`로 바로 귀속.
  · **팀·공용 카드**: 결제기록만 봐서는 **누가 썼는지 알 수 없다.** 그래서 주인을 비워 두고
    (`submitted_by=None`) 팀원 전원에게 보인다. 실사용자가 "내가 사용했어요"를 누르면
    그때 귀속된다(`claim()`).

빈 주인을 임의로 팀장이나 수집 실행자에게 붙이지 않는 이유: 그건 **틀린 사실을 만드는 것**이고,
`card.actual_user_recorded`(공용카드 실사용자 기록 여부)가 판정에 쓰이는 값이라 그대로
오판으로 이어진다. 모르는 건 모르는 채로 두고 사람이 해소하게 한다.

## 멱등성

같은 결제(`Transaction.external_id`)는 두 번 들어오지 않는다. 버튼을 여러 번 눌러도
다음 회차만 들어오고, 이미 받은 회차는 건너뛴다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction as db_tx
from django.utils import timezone

from domain.cards.models import Card, CardType
from domain.transactions.models import Transaction

from .models import Settlement, SettlementStatus

logger = logging.getLogger(__name__)

# 팀·공용 카드는 결제기록만으로 사용자를 알 수 없다 → 등록 대기 대상.
UNASSIGNED_CARD_TYPES = {CardType.TEAM, CardType.SHARED}


@dataclass
class ImportResult:
    batch: int
    total_batches: int
    created: int
    skipped: int          # 이미 받은 결제(멱등)
    claim_pending: int    # 팀·공용 카드라 주인이 비어 있는 건
    exhausted: bool       # 준비된 표본을 다 받았는가

    def to_dict(self) -> dict:
        return {
            "batch": self.batch, "totalBatches": self.total_batches,
            "created": self.created, "skipped": self.skipped,
            "claimPending": self.claim_pending, "exhausted": self.exhausted,
        }


# ── 표본 결제기록 3회분 ────────────────────────────────────────
#  card: "PERSONAL"=요청자 배정 카드 / "TEAM"=요청자 팀 카드
#  days: 오늘로부터 며칠 전. 화면 기본 필터가 "이번 달"이라 이번 달 안에 들어오게 잡는다.
SAMPLE_BATCHES: list[list[dict]] = [
    [
        {"card": "PERSONAL", "merchant": "스타벅스 역삼점", "amount": 18400, "days": 1, "hour": 9,
         "category": "식대", "industry": "카페"},
        {"card": "PERSONAL", "merchant": "김밥천국 강남", "amount": 9500, "days": 2, "hour": 12,
         "category": "식대", "industry": "분식"},
        {"card": "TEAM", "merchant": "미소야 삼성점", "amount": 168000, "days": 2, "hour": 19,
         "category": "회식", "industry": "일식"},
    ],
    [
        {"card": "PERSONAL", "merchant": "교보문고 광화문", "amount": 46500, "days": 4, "hour": 14,
         "category": "비품", "industry": "서점"},
        {"card": "TEAM", "merchant": "투썸플레이스 선릉", "amount": 32000, "days": 5, "hour": 15,
         "category": "회의", "industry": "카페"},
        {"card": "TEAM", "merchant": "한우담 본점", "amount": 452000, "days": 6, "hour": 20,
         "category": "접대", "industry": "한식"},
    ],
    [
        {"card": "PERSONAL", "merchant": "쿠팡", "amount": 89000, "days": 8, "hour": 11,
         "category": "비품", "industry": "종합소매"},
        {"card": "PERSONAL", "merchant": "SRT 수서-부산", "amount": 118600, "days": 9, "hour": 7,
         "category": "출장", "industry": "여객운송"},
        {"card": "TEAM", "merchant": "호프 갈매기", "amount": 214000, "days": 10, "hour": 22,
         "category": "회식", "industry": "주점"},
    ],
]
TOTAL_BATCHES = len(SAMPLE_BATCHES)


def _external_id(user, batch_index: int, row_index: int) -> str:
    """표본이라 결정론적으로 만든다 — 같은 사용자가 다시 눌러도 같은 키가 나와야 멱등하다."""
    return f"erp-sample:{user.pk}:{batch_index}:{row_index}"


def _cards_for(user) -> dict[str, Card]:
    """요청자 기준 개인·팀 카드. 없으면 만든다.

    시드에 따라 카드 구성이 달라서(`seed_clean`은 소유자 없는 카드만 만든다) 없으면
    수집이 통째로 실패한다. 여기서 채워 두면 어느 시드에서도 시연이 막히지 않는다.
    """
    personal, _ = Card.objects.get_or_create(
        card_type=CardType.PERSONAL, owner=user,
        defaults={"name": f"{user.first_name or user.username} 개인배정",
                  "number_masked": "1234-****-****-5678", "team": user.team},
    )
    team, _ = Card.objects.get_or_create(
        card_type=CardType.TEAM, team=user.team,
        defaults={"name": f"{user.team.name if user.team else '팀'} 공용",
                  "number_masked": "9876-****-****-4321"},
    )
    return {"PERSONAL": personal, "TEAM": team}


def next_batch_index(user) -> int:
    """이 사용자가 다음에 받을 회차(0-based). 이미 받은 회차는 건너뛴다."""
    for index in range(TOTAL_BATCHES):
        keys = [_external_id(user, index, row) for row in range(len(SAMPLE_BATCHES[index]))]
        if not Transaction.objects.filter(external_id__in=keys).exists():
            return index
    return TOTAL_BATCHES


@db_tx.atomic
def import_next_batch(user) -> ImportResult:
    """다음 회차 결제기록을 수집해 `Transaction` + `Settlement(DRAFT)`을 만든다."""
    index = next_batch_index(user)
    if index >= TOTAL_BATCHES:
        return ImportResult(batch=TOTAL_BATCHES, total_batches=TOTAL_BATCHES,
                            created=0, skipped=0, claim_pending=0, exhausted=True)

    cards = _cards_for(user)
    now = timezone.localtime()
    created = skipped = pending = 0

    for row_index, row in enumerate(SAMPLE_BATCHES[index]):
        key = _external_id(user, index, row_index)
        if Transaction.objects.filter(external_id=key).exists():
            skipped += 1
            continue

        card = cards[row["card"]]
        ts = (now - timedelta(days=row["days"])).replace(
            hour=row["hour"], minute=0, second=0, microsecond=0,
        )
        tx = Transaction.objects.create(
            card=card, merchant=row["merchant"], amount=row["amount"], ts=ts,
            external_id=key,
            raw_payload={"source": "ERP_SAMPLE", "batch": index + 1, "approvalNo": key[-8:]},
        )

        # 팀·공용 카드는 사용자를 모른다 — 주인을 비워 두고 팀원 전원에게 보인다.
        unassigned = card.card_type in UNASSIGNED_CARD_TYPES
        Settlement.objects.create(
            transaction=tx,
            category="", ai_category=row["category"], ai_suggested=True,
            merchant_industry=row["industry"],
            status=SettlementStatus.DRAFT,
            submitted_by=None if unassigned else card.owner,
            team=card.team or user.team,
            # 개인카드는 소유자가 곧 사용자라 기록이 성립한다. 팀·공용은 아직 모른다(None).
            actual_user=None if unassigned else card.owner,
            actual_user_recorded=None if unassigned else True,
        )
        created += 1
        pending += unassigned

    logger.info("ERP 수집 user=%s batch=%d created=%d pending=%d",
                user.username, index + 1, created, pending)
    return ImportResult(batch=index + 1, total_batches=TOTAL_BATCHES, created=created,
                        skipped=skipped, claim_pending=pending,
                        exhausted=index + 1 >= TOTAL_BATCHES)


class ClaimError(ValueError):
    """본인 등록 불가 — 사유를 화면에 그대로 보여준다."""


@db_tx.atomic
def claim(settlement: Settlement, user) -> Settlement:
    """팀·공용 카드 결제의 **실사용자 본인 등록**.

    귀속과 동시에 `actual_user_recorded=True`가 된다 — 이 값은 판정이 쓰는 사실이라
    (공용카드 실사용자 기록 여부) 등록이 곧 그 사실의 해소다.
    """
    if settlement.submitted_by_id is not None:
        raise ClaimError("이미 사용자가 등록된 건입니다.")
    if settlement.status != SettlementStatus.DRAFT:
        raise ClaimError("아직 개인 보유(작성 중) 상태인 건만 등록할 수 있습니다.")
    if settlement.team_id and getattr(user, "team_id", None) != settlement.team_id:
        # 다른 팀 카드 결제를 가져가면 그 팀의 정산이 사라진 것처럼 보인다.
        raise ClaimError("같은 팀의 카드 결제만 본인 등록할 수 있습니다.")

    settlement.submitted_by = user
    settlement.actual_user = user
    settlement.actual_user_recorded = True
    settlement.save(update_fields=["submitted_by", "actual_user", "actual_user_recorded"])
    logger.info("실사용자 등록 settlement=%s user=%s", settlement.pk, user.username)
    return settlement

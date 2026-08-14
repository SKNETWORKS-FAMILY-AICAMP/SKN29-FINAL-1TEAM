"""이상탐지 모델 입력용 원본 15개 피처 조립 (apps/ai `app/ml/features.py`의 `FEATURE_COLUMNS`와 1:1 대응).

관계형 데이터 접근(카드별 과거 거래 집계 등)은 전부 여기서 끝낸다 — FastAPI(ai)는 이 함수가
반환한 사실(fact) 딕셔너리만 받아 `app.ml.features.build_feature_matrix`로 순수 변환한다
(CLAUDE.md §1 "Postgres 직접 SQL 금지" 원칙과 동일하게, 원-핫 인코딩 등 "판단 없는 변환"은
AI 쪽에 두고 "조회"만 여기서 담당).

출처: ml/ml_final_report.md §4, ml/mvp_isolation_forest/법인카드_이상거래_전처리_v2/v3 노트북의
피처 정의를 Django 서빙 경로로 그대로 이식했다(정의를 바꾸면 학습된 모델과 어긋난다).
"""
from __future__ import annotations

import statistics
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from .models import Transaction

# 노트북 정의(전처리_v2 §2): 0~5시 심야, 6~11시 오전, 12~17시 오후, 18~23시 저녁.
_TIME_BANDS = [
    (0, 6, "심야(00-05)"),
    (6, 12, "오전(06-11)"),
    (12, 18, "오후(12-17)"),
    (18, 24, "저녁(18-23)"),
]
_WEEKDAY_KO = ["월", "화", "수", "목", "금", "토", "일"]

# 실거래 데이터에 없는 카드사 원천 필드(§Tier1) — 확보 전까지는 학습 데이터의 "결측/공란" 센티널인
# '_'로 채운다(임의의 다수파 값 A로 채우면 결측을 평범한 값으로 위장하는 것과 같다, EDA 10-4절 교훈).
DEFAULT_INSTALLMENT_CODE = "_"


def _time_band(hour: int) -> str:
    for start, end, label in _TIME_BANDS:
        if start <= hour < end:
            return label
    raise AssertionError(hour)  # 0~23 범위를 벗어난 시각은 나올 수 없다


def build_tx_features(tx: Transaction) -> dict:
    """거래 1건 → 15개 원본 피처(원-핫 인코딩 이전) 딕셔너리. `get_tx_features` 내부 read API 전용."""
    local_ts = timezone.localtime(tx.ts)
    hour = local_ts.hour
    amount = float(tx.amount)

    # 정렬 기준은 (ts, id) — 노트북의 (거래일자, 승인SEQ) 타이브레이커를 id(pk, 생성 순서)로 대체한다.
    # 원본 데이터엔 있는 승인SEQ가 이 스키마엔 없어 완전한 동치는 아니지만, 같은 카드 안에서 시간순
    # 정렬을 결정론적으로 만든다는 목적은 동일하게 달성한다.
    same_card = Transaction.objects.filter(card=tx.card)
    strictly_before = same_card.filter(Q(ts__lt=tx.ts) | (Q(ts=tx.ts) & Q(id__lt=tx.id)))
    upto_and_including = strictly_before | same_card.filter(id=tx.id)

    recent_7d_count = same_card.filter(
        ts__gt=tx.ts - timedelta(days=7), ts__lte=tx.ts,
    ).count()

    card_cumulative_amount = sum(
        (float(a) for a in upto_and_including.values_list("amount", flat=True)), 0.0
    )

    prior_amounts = [float(a) for a in strictly_before.values_list("amount", flat=True)]
    if prior_amounts:
        avg_expanding = statistics.fmean(prior_amounts)
        std_expanding = statistics.stdev(prior_amounts) if len(prior_amounts) >= 2 else None
    else:
        avg_expanding = None
        std_expanding = None

    if avg_expanding is not None and std_expanding not in (None, 0):
        zscore_expanding = (amount - avg_expanding) / std_expanding
    else:
        zscore_expanding = None

    return {
        "승인시간대": hour,
        "통합승인금액": amount,
        "거래일자": local_ts.date().isoformat(),
        "거래연월": local_ts.strftime("%Y-%m"),
        "거래요일_한글": _WEEKDAY_KO[local_ts.weekday()],
        "시간대구간": _time_band(hour),
        "월말여부": local_ts.day >= 25,
        "취소성거래_추정": int(amount == 0),
        "최근7일사용횟수": recent_7d_count,
        "카드누적사용액": card_cumulative_amount,
        "사용자평균사용액_확장": avg_expanding,
        "사용자표준편차_확장": std_expanding,
        "거래금액_Zscore_확장": zscore_expanding,
        "카드첫거래여부": int(avg_expanding is None),
        "일시불할부구분코드": (tx.raw_payload or {}).get("일시불할부구분코드", DEFAULT_INSTALLMENT_CODE),
    }

"""
피처 세트 B(§2) 로딩 공용 로직 — supervised_topk_ranking.py가 사용.

주의: 이 로더는 Tier0(12, 피처 A와 동일) + 일시불할부구분코드(1) 외에
거래일자/거래연월을 정렬 순서를 보존하는 정수(ordinal)로 변환해 함께 넣는다.
이건 실제 팀원의 Isolation Forest 원본 작업(`ml/ML_0728/`)에는 없는 컬럼이라 팀원
원본과는 피처 구성이 다르다(팀원 원본은 날짜 컬럼을 모델 입력에 아예 안 씀).
supervised_topk_ranking.py의
기존 결과(§3-3)는 이 로더 기준으로 이미 산출된 값이라 그대로 두되, 재현/재현 시
이 차이를 감안할 것.
"""
import numpy as np
import pandas as pd
from pathlib import Path

from sklearn.metrics import precision_score, recall_score

BASE = Path(__file__).resolve().parent.parent.parent / ".data" / "data" / "processed"

# Tier0(14) — feature_tiers.json의 tier0_transaction_safe에서 가맹점 관련 2개 제외
NUMERIC_COLS = [
    "승인시간대", "통합승인금액", "최근7일사용횟수", "카드누적사용액",
    "사용자평균사용액_확장", "사용자표준편차_확장", "거래금액_Zscore_확장",
]
FLAG_COLS = ["월말여부", "취소성거래_추정", "카드첫거래여부"]
DATE_COLS = ["거래일자", "거래연월"]
CATEGORICAL_COLS = ["거래요일_한글", "시간대구간"]
# Tier1에서 유일하게 도움이 된 피처 (팀원 ablation 결과, ml/ML_0728 참고)
EXTRA_CATEGORICAL = ["일시불할부구분코드"]

TARGET = "이상거래여부"
CARD_COL = "카드KEY"

ALL_LOAD_COLS = (NUMERIC_COLS + FLAG_COLS + DATE_COLS + CATEGORICAL_COLS
                  + EXTRA_CATEGORICAL + [TARGET, CARD_COL])


def load_and_prepare(path, cat_columns=None):
    df = pd.read_csv(path, encoding="utf-8", usecols=ALL_LOAD_COLS)

    df["거래일자"] = pd.to_datetime(df["거래일자"])
    df = df.sort_values("거래일자").reset_index(drop=True)

    # 날짜 컬럼은 순서를 보존하는 정수(ordinal)로 변환해 모델 입력에 사용
    df["거래일자_ordinal"] = df["거래일자"].map(pd.Timestamp.toordinal)
    df["거래연월_ordinal"] = pd.PeriodIndex(df["거래연월"], freq="M").astype(int)

    for c in ["사용자평균사용액_확장", "사용자표준편차_확장", "거래금액_Zscore_확장"]:
        df[c] = df[c].fillna(0)
    df["월말여부"] = df["월말여부"].astype(int)
    df["일시불할부구분코드"] = df["일시불할부구분코드"].fillna("UNK")

    y = df[TARGET].astype(int)
    cards = df[CARD_COL]
    dates = df["거래일자"]

    X_num = df[NUMERIC_COLS + FLAG_COLS + ["거래일자_ordinal", "거래연월_ordinal"]]
    X_cat = pd.get_dummies(df[CATEGORICAL_COLS + EXTRA_CATEGORICAL],
                            prefix=CATEGORICAL_COLS + EXTRA_CATEGORICAL)

    if cat_columns is None:
        cat_columns = X_cat.columns.tolist()
    else:
        X_cat = X_cat.reindex(columns=cat_columns, fill_value=0)

    X = pd.concat([X_num.reset_index(drop=True), X_cat.reset_index(drop=True)], axis=1)
    return X, y, cat_columns, cards, dates


def eval_topk(anomaly_score, y_true, k):
    n = len(y_true)
    cut = max(1, int(n * k))
    order = np.argsort(-anomaly_score)  # 점수 높은 순
    top_idx = order[:cut]
    pred = np.zeros(n, dtype=int)
    pred[top_idx] = 1
    return {
        f"recall@top{int(k*100)}%": recall_score(y_true, pred, zero_division=0),
        f"precision@top{int(k*100)}%": precision_score(y_true, pred, zero_division=0),
    }
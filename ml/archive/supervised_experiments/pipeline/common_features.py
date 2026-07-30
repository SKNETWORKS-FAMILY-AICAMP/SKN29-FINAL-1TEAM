"""
법인카드 이상거래 탐지 모델들이 공용으로 쓰는 데이터 로딩/피처 구성 로직.
model_training.py, model_tuning.py에서 공유한다.
"""
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent.parent.parent.parent.parent / ".data" / "data" / "processed"

NUMERIC_COLS = [
    "승인시간대", "통합승인금액", "최근7일사용횟수", "카드누적사용액",
    "사용자평균사용액_확장", "사용자표준편차_확장", "거래금액_Zscore_확장",
]
FLAG_COLS = ["월말여부", "취소성거래_추정", "카드첫거래여부"]
CATEGORICAL_COLS = ["거래요일_한글", "시간대구간"]
TARGET = "이상거래여부"
SORT_COL = "거래일자"

ALL_LOAD_COLS = NUMERIC_COLS + FLAG_COLS + CATEGORICAL_COLS + [TARGET, SORT_COL]


def load_and_prepare(path, train_cat_columns=None):
    """CSV를 읽어 날짜순 정렬 + 결측치 처리 + 원-핫 인코딩까지 마친 (X, y, cat_columns, dates)를 반환."""
    df = pd.read_csv(path, encoding="utf-8", usecols=ALL_LOAD_COLS)

    df[SORT_COL] = pd.to_datetime(df[SORT_COL])
    df = df.sort_values(SORT_COL).reset_index(drop=True)

    for c in ["사용자평균사용액_확장", "사용자표준편차_확장", "거래금액_Zscore_확장"]:
        df[c] = df[c].fillna(0)

    df["월말여부"] = df["월말여부"].astype(int)

    y = df[TARGET].astype(int)
    X_num = df[NUMERIC_COLS + FLAG_COLS]
    X_cat = pd.get_dummies(df[CATEGORICAL_COLS], prefix=CATEGORICAL_COLS)

    if train_cat_columns is None:
        train_cat_columns = X_cat.columns.tolist()
    else:
        X_cat = X_cat.reindex(columns=train_cat_columns, fill_value=0)

    X = pd.concat([X_num.reset_index(drop=True), X_cat.reset_index(drop=True)], axis=1)
    return X, y, train_cat_columns, df[SORT_COL]
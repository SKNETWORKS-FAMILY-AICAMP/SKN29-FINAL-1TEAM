"""이상탐지 모델 입력 피처 변환 — ml_final_report.md §4 확정 피처셋(15개)과 동일 로직.

출처: ml/mvp_isolation_forest/법인카드_이상거래_모델링_v2_최종test평가.ipynb,
ml/비지도학습 정리/법인카드_이상거래_ECOD_COPOD_비교실험.ipynb 셀2~3의 `build_model_matrix`를
그대로 이식(전처리·인코딩 방식을 절대 바꾸지 않는다 — 바꾸면 학습된 모델과 실시간 입력의 피처
정의가 어긋난다).
"""
from __future__ import annotations

import pandas as pd

# Tier0(14개) + 일시불할부구분코드(1개) = 15개 — ml_final_report.md §4 확정 피처셋
FEATURE_COLUMNS = [
    "승인시간대", "통합승인금액", "거래일자", "거래연월", "거래요일_한글", "시간대구간",
    "월말여부", "취소성거래_추정", "최근7일사용횟수", "카드누적사용액",
    "사용자평균사용액_확장", "사용자표준편차_확장", "거래금액_Zscore_확장", "카드첫거래여부",
    "일시불할부구분코드",
]

# 콜드스타트(카드 이력 없음)로 인한 NaN — train 기준 median으로만 대체(test 누수 방지)
_NAN_FILL_COLUMNS = ["사용자평균사용액_확장", "사용자표준편차_확장", "거래금액_Zscore_확장"]

# 저카디널리티 범주형만 원-핫 인코딩(그 외는 이미 수치/불리언)
_ONEHOT_COLUMNS = ["거래요일_한글", "시간대구간", "일시불할부구분코드"]

# 파생 피처(최근7일사용횟수 등)로 이미 대체된 날짜 원본 — 모델 입력에서는 제외
_DROP_FROM_MODEL = ["거래일자", "거래연월"]

# 원-핫 대상 3컬럼의 고정 카테고리 목록(ml/.data/processed/train_processed.csv 전수 관측치 기준,
# get_dummies가 object dtype에 대해 만드는 정렬 순서와 동일하게 나열했다 — 순서를 바꾸면 이미 학습된
# model.feature_columns와 컬럼 순서가 어긋난다). 카테고리를 고정하는 이유: get_tx_features처럼 행 1건만
# 넘어오는 서빙 경로에서는 그 행의 값 하나만으로 get_dummies를 돌리면 컬럼이 1개만 생겨(나머지 카테고리가
# 아예 안 보임) 학습 스키마와 어긋난다. Categorical dtype으로 카테고리를 미리 고정해두면 행 개수와 무관하게
# 항상 전체 컬럼이 생성된다(관측 안 된 값은 전부 0).
CATEGORY_VALUES: dict[str, list[str]] = {
    "거래요일_한글": ["금", "목", "수", "월", "일", "토", "화"],
    "시간대구간": ["심야(00-05)", "오전(06-11)", "오후(12-17)", "저녁(18-23)"],
    "일시불할부구분코드": ["A", "B", "_"],
}


def compute_fill_values(train_df: pd.DataFrame) -> pd.Series:
    """콜드스타트 확장 통계 컬럼의 NaN 대체값. 반드시 train에서만 계산한다."""
    return train_df[_NAN_FILL_COLUMNS].median()


def build_feature_matrix(df: pd.DataFrame, fill_values: pd.Series) -> pd.DataFrame:
    """원본 거래 컬럼(FEATURE_COLUMNS 기준)을 IsolationForest 입력용 수치 행렬로 변환.

    df는 전처리 노트북(법인카드_이상거래_전처리_v3_세그먼트플래그.ipynb)이 만든
    파생 피처(최근7일사용횟수, 사용자평균사용액_확장 등)를 이미 포함하고 있어야 한다 —
    이 함수는 "선택 + 결측 대체 + 원-핫 인코딩"만 담당하고, Expanding Window 등
    시점 안전 통계 계산은 하지 않는다.
    """
    cols = [c for c in FEATURE_COLUMNS if c not in _DROP_FROM_MODEL]
    X = df[cols].copy()

    X[_NAN_FILL_COLUMNS] = X[_NAN_FILL_COLUMNS].fillna(fill_values)
    X["월말여부"] = X["월말여부"].astype(int)
    for col, categories in CATEGORY_VALUES.items():
        X[col] = pd.Categorical(X[col], categories=categories)
    X = pd.get_dummies(X, columns=_ONEHOT_COLUMNS, drop_first=False)

    remaining_na = X.isna().sum()
    remaining_na = remaining_na[remaining_na > 0]
    if len(remaining_na) > 0:
        X = X.fillna(0)
    return X


def align_columns(X_train: pd.DataFrame, X_other: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """원-핫 인코딩 후 두 데이터셋의 컬럼이 다를 수 있어(특정 카테고리가 한쪽에만 존재) 맞춰준다."""
    return X_train.align(X_other, join="outer", axis=1, fill_value=0)


def align_to_model(X: pd.DataFrame, feature_columns: list[str]) -> pd.DataFrame:
    """서빙 시점 단건 feature 행렬을 학습된 model.feature_columns 순서·구성에 맞춘다.

    CATEGORY_VALUES로 카테고리를 고정해뒀으므로 정상 경로에서는 컬럼이 이미 동일해야 하지만,
    모델을 재학습해 카테고리 집합이 달라진 경우를 대비해 reindex로 안전하게 맞춘다(없는 컬럼은 0).
    """
    return X.reindex(columns=feature_columns, fill_value=0)

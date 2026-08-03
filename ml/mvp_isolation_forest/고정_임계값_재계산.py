# 상위 10% 컷오프에 대응하는 train 고정 임계값(score) 재계산
# 전처리/모델 스펙은 법인카드_이상거래_모델링_v2_최종test평가.ipynb 셀2/4/6/8/14와 동일 로직
# (unsupervised_baseline_비교.py의 build_model_matrix를 그대로 재사용)
# 결과 해석: isolation_forest_modeling_결과.md §5 참고.
import json
import os

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

DATA_DIR = "../../.data/data/processed"
TRAIN_PATH = os.path.join(DATA_DIR, "train_processed.csv")
TEST_PATH = os.path.join(DATA_DIR, "test_processed.csv")
TIERS_PATH = os.path.join(DATA_DIR, "feature_tiers.json")

RANDOM_STATE = 42

train_df = pd.read_csv(TRAIN_PATH, low_memory=False, encoding="utf-8")
test_df = pd.read_csv(TEST_PATH, low_memory=False, encoding="utf-8")
with open(TIERS_PATH, encoding="utf-8") as f:
    FEATURE_TIERS = json.load(f)

for df in (train_df, test_df):
    df["거래요일_한글"] = df["거래요일_한글"].astype("category")
    df["시간대구간"] = df["시간대구간"].astype("category")
    df["거래일자"] = pd.to_datetime(df["거래일자"])
    df["월말여부"] = df["월말여부"].astype(bool)
    df["일시불할부구분코드"] = df["일시불할부구분코드"].astype("category")

NAN_FILL_COLS = ["사용자평균사용액_확장", "사용자표준편차_확장", "거래금액_Zscore_확장"]
ONEHOT_COLS = ["거래요일_한글", "시간대구간", "일시불할부구분코드"]
DROP_FROM_MODEL = ["거래일자", "거래연월"]
FINAL_FEATURE_COLS = FEATURE_TIERS["tier0_transaction_safe"] + ["일시불할부구분코드"]
_fill_values = train_df[NAN_FILL_COLS].median()


def build_model_matrix(df, fill_values=_fill_values):
    cols = [c for c in FINAL_FEATURE_COLS if c not in DROP_FROM_MODEL]
    X = df[cols].copy()
    X[NAN_FILL_COLS] = X[NAN_FILL_COLS].fillna(fill_values)
    X["월말여부"] = X["월말여부"].astype(int)
    X = pd.get_dummies(X, columns=ONEHOT_COLS, drop_first=False)
    if X.isna().sum().sum() > 0:
        X = X.fillna(0)
    return X


X_train = build_model_matrix(train_df)
X_test = build_model_matrix(test_df)
X_train, X_test = X_train.align(X_test, join="outer", axis=1, fill_value=0)
assert X_train.isna().sum().sum() == 0 and X_test.isna().sum().sum() == 0

y_test = test_df["이상거래여부"].values

final_model = IsolationForest(
    n_estimators=200,
    max_samples="auto",
    contamination="auto",
    random_state=RANDOM_STATE,
    n_jobs=-1,
)
final_model.fit(X_train)

train_anomaly_score = -final_model.decision_function(X_train)
test_anomaly_score = -final_model.decision_function(X_test)

results = {}
for pct, label in [(97, "top3%(기존)"), (90, "top10%(신규)")]:
    fixed_threshold = float(np.percentile(train_anomaly_score, pct))
    flagged = test_anomaly_score >= fixed_threshold
    actual_pct = float(flagged.mean() * 100)
    recall = float(y_test[flagged].sum() / y_test.sum())
    precision = float(y_test[flagged].sum() / flagged.sum()) if flagged.sum() > 0 else float("nan")
    results[label] = {
        "threshold_percentile": pct,
        "fixed_threshold_score": fixed_threshold,
        "flagged_pct": actual_pct,
        "flagged_count": int(flagged.sum()),
        "recall": recall,
        "precision": precision,
    }

with open("고정_임계값_재계산_result.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

for label, row in results.items():
    print(label, row)

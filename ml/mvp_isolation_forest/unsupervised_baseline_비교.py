# 비지도 baseline 비교 — One-Class SVM(RBF) / LOF(novelty) / SGDOneClassSVM vs Isolation Forest
# 전처리는 법인카드_이상거래_모델링_v2_최종test평가.ipynb 셀2/4/6과 동일한 로직을 재사용한다.
# 결과 해석은 비지도_baseline_비교_결과.md 참고.
import json
import os
import time

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.linear_model import SGDOneClassSVM
from sklearn.metrics import average_precision_score
from sklearn.neighbors import LocalOutlierFactor
from sklearn.preprocessing import StandardScaler
from sklearn.svm import OneClassSVM

DATA_DIR = "../.data/processed"
TRAIN_PATH = os.path.join(DATA_DIR, "train_processed.csv")
TEST_PATH = os.path.join(DATA_DIR, "test_processed.csv")
TIERS_PATH = os.path.join(DATA_DIR, "feature_tiers.json")

RANDOM_STATE = 42
SUB_N = 50_000  # One-Class SVM(RBF)/LOF는 148만 행 전량이 비현실적(§2 효율성 벤치마크 근거) → 무작위 서브샘플

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
# 주의: 카드_train노출여부(세그먼트 플래그)는 이번 비교의 FINAL_FEATURE_COLS에 없어 불필요 —
# 전처리 v2/v3 버전 차이와 무관하게 핵심 피처셋에는 영향 없음.

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
    remaining_na = X.isna().sum()
    if remaining_na.sum() > 0:
        X = X.fillna(0)
    return X


X_train = build_model_matrix(train_df)
X_test = build_model_matrix(test_df)
X_train, X_test = X_train.align(X_test, join="outer", axis=1, fill_value=0)
assert X_train.isna().sum().sum() == 0 and X_test.isna().sum().sum() == 0

y_test = test_df["이상거래여부"].values
TOP_K_FRACTIONS = [0.01, 0.03, 0.05, 0.10]


def compute_metrics(y_true, scores):
    row = {"pr_auc": average_precision_score(y_true, scores)}
    order = np.argsort(-scores)
    n_pos = y_true.sum()
    for frac in TOP_K_FRACTIONS:
        k = max(1, int(len(y_true) * frac))
        idx = order[:k]
        row[f"recall@top{int(frac*100)}%"] = float(y_true[idx].sum() / n_pos)
        row[f"precision@top{int(frac*100)}%"] = float(y_true[idx].sum() / k)
    return row


results = {}
rng = np.random.default_rng(RANDOM_STATE)

# One-Class SVM/LOF는 거리 기반이라 표준화 필요, IsolationForest/SGDOneClassSVM은 없어도 무해
scaler = StandardScaler().fit(X_train)
X_train_s = scaler.transform(X_train)
X_test_s = scaler.transform(X_test)

# 1) Isolation Forest — 기존 확정 모델 재현(전체 규모)
t0 = time.perf_counter()
ifm = IsolationForest(n_estimators=200, max_samples="auto", contamination="auto", random_state=RANDOM_STATE, n_jobs=-1)
ifm.fit(X_train)
fit_sec = time.perf_counter() - t0
t0 = time.perf_counter()
score_if = -ifm.decision_function(X_test)
pred_sec = time.perf_counter() - t0
results["IsolationForest"] = {"n_train": len(X_train), "fit_sec": fit_sec, "pred_sec": pred_sec, **compute_metrics(y_test, score_if)}

# 2) SGDOneClassSVM — 선형 근사, 전체 규모 그대로(One-Class SVM의 대용량 대응 변형)
t0 = time.perf_counter()
sgd = SGDOneClassSVM(random_state=RANDOM_STATE)
sgd.fit(X_train_s)
fit_sec = time.perf_counter() - t0
t0 = time.perf_counter()
score_sgd = -sgd.score_samples(X_test_s)
pred_sec = time.perf_counter() - t0
results["SGDOneClassSVM"] = {"n_train": len(X_train), "fit_sec": fit_sec, "pred_sec": pred_sec, **compute_metrics(y_test, score_sgd)}

# 3) One-Class SVM(RBF) — 서브샘플(SUB_N)
sub_idx = rng.choice(len(X_train_s), size=SUB_N, replace=False)
X_sub = X_train_s[sub_idx]

t0 = time.perf_counter()
ocsvm = OneClassSVM(kernel="rbf", gamma="scale")
ocsvm.fit(X_sub)
fit_sec = time.perf_counter() - t0
t0 = time.perf_counter()
score_ocsvm = -ocsvm.score_samples(X_test_s)
pred_sec = time.perf_counter() - t0
results[f"OneClassSVM_rbf_sub{SUB_N}"] = {"n_train": SUB_N, "fit_sec": fit_sec, "pred_sec": pred_sec, **compute_metrics(y_test, score_ocsvm)}

# 4) LOF(novelty=True) — 서브샘플(SUB_N). sklearn 규약: score_samples는 클수록 정상 → 부호 반전
t0 = time.perf_counter()
lof = LocalOutlierFactor(novelty=True, n_neighbors=20, n_jobs=-1)
lof.fit(X_sub)
fit_sec = time.perf_counter() - t0
t0 = time.perf_counter()
score_lof = -lof.score_samples(X_test_s)
pred_sec = time.perf_counter() - t0
results[f"LOF_sub{SUB_N}"] = {"n_train": SUB_N, "fit_sec": fit_sec, "pred_sec": pred_sec, **compute_metrics(y_test, score_lof)}

with open("unsupervised_baseline_비교_result.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

for name, row in results.items():
    print(name, row)

# fold 4가 다른 fold보다 지속적으로 낮게 나온 원인 조사
# 최종 확정 피처셋(Tier0 14개 + 일시불할부구분코드)으로 5-fold CV(카드 단위 분할)를 재현하고,
# fold별 PR-AUC와 함께 라벨 비율·카드 그룹 누수·결측치 비율·이상거래 금액 분포를 비교한다.
# 결과 해석: isolation_forest_modeling_결과.md "fold 4 원인 조사" 절 참고.
import json
import os

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import average_precision_score

DATA_DIR = "../../.data/data/processed"
TRAIN_PATH = os.path.join(DATA_DIR, "train_processed.csv")
TIERS_PATH = os.path.join(DATA_DIR, "feature_tiers.json")

RANDOM_STATE = 42

train_df = pd.read_csv(TRAIN_PATH, low_memory=False, encoding="utf-8")
with open(TIERS_PATH, encoding="utf-8") as f:
    FEATURE_TIERS = json.load(f)

train_df["거래요일_한글"] = train_df["거래요일_한글"].astype("category")
train_df["시간대구간"] = train_df["시간대구간"].astype("category")
train_df["거래일자"] = pd.to_datetime(train_df["거래일자"])
train_df["월말여부"] = train_df["월말여부"].astype(bool)
train_df["일시불할부구분코드"] = train_df["일시불할부구분코드"].astype("category")

NAN_FILL_COLS = ["사용자평균사용액_확장", "사용자표준편차_확장", "거래금액_Zscore_확장"]
ONEHOT_COLS = ["거래요일_한글", "시간대구간", "일시불할부구분코드"]
DROP_FROM_MODEL = ["거래일자", "거래연월"]
FINAL_FEATURE_COLS = FEATURE_TIERS["tier0_transaction_safe"] + ["일시불할부구분코드"]


def build_model_matrix(df, fill_values):
    cols = [c for c in FINAL_FEATURE_COLS if c not in DROP_FROM_MODEL]
    X = df[cols].copy()
    X[NAN_FILL_COLS] = X[NAN_FILL_COLS].fillna(fill_values)
    X["월말여부"] = X["월말여부"].astype(int)
    X = pd.get_dummies(X, columns=ONEHOT_COLS, drop_first=False)
    if X.isna().sum().sum() > 0:
        X = X.fillna(0)
    return X


print("=== 1) 5-fold CV 재현 -- fold별 PR-AUC ===")
fold_rows = []
for f in range(5):
    tr_idx = train_df.index[train_df["fold"] != f]
    va_idx = train_df.index[train_df["fold"] == f]

    fill_values = train_df.loc[tr_idx, NAN_FILL_COLS].median()
    X_full = build_model_matrix(train_df, fill_values)
    X_tr, X_va = X_full.loc[tr_idx], X_full.loc[va_idx]
    y_va = train_df.loc[va_idx, "이상거래여부"].values

    iso = IsolationForest(n_estimators=200, max_samples="auto", contamination="auto", random_state=RANDOM_STATE, n_jobs=-1)
    iso.fit(X_tr)
    score = -iso.decision_function(X_va)
    pr_auc = average_precision_score(y_va, score)
    fold_rows.append({"fold": f, "pr_auc": pr_auc, "n": len(y_va), "n_pos": int(y_va.sum()), "base_rate": y_va.mean()})
    print(f"  fold {f}: PR-AUC={pr_auc:.4f}  n={len(y_va)}  n_pos={int(y_va.sum())}  base_rate={y_va.mean():.4f}")

fold_df = pd.DataFrame(fold_rows)
mean_, std_ = fold_df["pr_auc"].mean(), fold_df["pr_auc"].std()
print(f"\n평균 PR-AUC: {mean_:.4f} +- {std_:.4f}")
fold_df["z_score"] = (fold_df["pr_auc"] - mean_) / std_
print(fold_df)

print("\n=== 2) fold별 카드 그룹 누수 점검 (검증셋 카드가 학습셋에도 등장하는 비율) ===")
for f in range(5):
    tr_idx = train_df.index[train_df["fold"] != f]
    va_idx = train_df.index[train_df["fold"] == f]
    tr_cards = set(train_df.loc[tr_idx, "카드KEY"])
    va_cards = train_df.loc[va_idx, "카드KEY"]
    seen_rate = va_cards.isin(tr_cards).mean()
    print(f"  fold {f}: {seen_rate:.4f} (카드 단위 그룹 분할이면 0.0000이어야 정상)")

print("\n=== 3) fold별 결측치 비율(확장 통계 피처) ===")
for f in range(5):
    va_idx = train_df.index[train_df["fold"] == f]
    na_rate = train_df.loc[va_idx, NAN_FILL_COLS].isna().mean()
    print(f"  fold {f}: {dict(na_rate.round(4))}")

print("\n=== 4) fold별 이상거래(양성) 금액 분포 ===")
for f in range(5):
    va_idx = train_df.index[train_df["fold"] == f]
    pos = train_df.loc[va_idx][train_df.loc[va_idx, "이상거래여부"] == 1]
    print(f"  fold {f}: 중앙값={pos['통합승인금액'].median():.0f}  평균={pos['통합승인금액'].mean():.0f}  건수={len(pos)}")

fold_df.to_json("fold4_원인조사_result.json", orient="records", force_ascii=False, indent=2)
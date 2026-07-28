"""
법인카드 이상거래 탐지 - 지도학습 모델 비교 및 pickle 저장

조건:
1. 2021~2023년 데이터로 학습(train_processed.csv), 2024년 데이터로 평가(test_processed.csv)
2. 거래일자 오름차순 정렬 후 진행 (시계열 순서 보존)
3. 학습된 모델을 pickle(joblib)로 저장

피처 범위: feature_tiers.json의 tier0_transaction_safe 중 가맹점 관련 2개
(가맹점평균금액_확장, 가맹점첫거래여부) 제외 — 사용자 확정 사항.
거래일자/거래연월은 정렬용으로만 쓰고 모델 입력 피처에서는 제외한다
(원본 날짜 문자열은 그 자체로 예측 신호가 아니라 식별/정렬용이기 때문).
"""
import json
import time
import joblib
import numpy as np
import pandas as pd
from pathlib import Path

from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    roc_auc_score, average_precision_score,
    precision_score, recall_score, f1_score, confusion_matrix,
)
from xgboost import XGBClassifier
from lightgbm import LGBMClassifier

from common_features import (
    load_and_prepare, BASE, NUMERIC_COLS, FLAG_COLS, CATEGORICAL_COLS, TARGET,
)

MODEL_DIR = Path(__file__).resolve().parent.parent / "models" / "round1_baseline"
MODEL_DIR.mkdir(parents=True, exist_ok=True)
SHARED_DIR = Path(__file__).resolve().parent.parent / "models" / "shared"
SHARED_DIR.mkdir(parents=True, exist_ok=True)


def evaluate(name, model, X_test, y_test):
    proba = model.predict_proba(X_test)[:, 1]
    pred = (proba >= 0.5).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_test, pred).ravel()
    return {
        "model": name,
        "roc_auc": roc_auc_score(y_test, proba),
        "pr_auc": average_precision_score(y_test, proba),
        "precision@0.5": precision_score(y_test, pred, zero_division=0),
        "recall@0.5": recall_score(y_test, pred, zero_division=0),
        "f1@0.5": f1_score(y_test, pred, zero_division=0),
        "tn": tn, "fp": fp, "fn": fn, "tp": tp,
    }


def main():
    t0 = time.time()
    print("[1/4] 데이터 로드 및 날짜순 정렬...")
    X_train, y_train, cat_cols, train_dates = load_and_prepare(BASE / "train_processed.csv")
    X_test, y_test, _, test_dates = load_and_prepare(BASE / "test_processed.csv", train_cat_columns=cat_cols)

    print(f"  train: {X_train.shape}, 기간 {train_dates.min().date()} ~ {train_dates.max().date()}")
    print(f"  test : {X_test.shape}, 기간 {test_dates.min().date()} ~ {test_dates.max().date()}")
    print(f"  feature columns ({len(X_train.columns)}): {list(X_train.columns)}")
    pos_rate = y_train.mean()
    scale_pos_weight = (1 - pos_rate) / pos_rate
    print(f"  train 양성비율: {pos_rate:.4f}, scale_pos_weight={scale_pos_weight:.2f}")

    models = {
        "logistic_regression": LogisticRegression(
            max_iter=1000, class_weight="balanced", n_jobs=-1,
        ),
        "random_forest": RandomForestClassifier(
            n_estimators=200, max_depth=12, min_samples_leaf=20,
            class_weight="balanced", n_jobs=-1, random_state=42,
        ),
        "xgboost": XGBClassifier(
            n_estimators=300, max_depth=6, learning_rate=0.1,
            scale_pos_weight=scale_pos_weight, tree_method="hist",
            eval_metric="aucpr", random_state=42, n_jobs=-1,
        ),
        "lightgbm": LGBMClassifier(
            n_estimators=300, num_leaves=31, learning_rate=0.1,
            class_weight="balanced", random_state=42, n_jobs=-1, verbose=-1,
        ),
    }

    results = []
    for i, (name, model) in enumerate(models.items(), start=2):
        print(f"[{i}/{len(models)+1}] {name} 학습 중...")
        t1 = time.time()
        model.fit(X_train, y_train)
        print(f"  학습 완료 ({time.time()-t1:.1f}s)")

        metrics = evaluate(name, model, X_test, y_test)
        results.append(metrics)
        print(f"  ROC-AUC={metrics['roc_auc']:.4f} PR-AUC={metrics['pr_auc']:.4f} "
              f"F1={metrics['f1@0.5']:.4f} Recall={metrics['recall@0.5']:.4f} Precision={metrics['precision@0.5']:.4f}")

        pkl_path = MODEL_DIR / f"{name}.pkl"
        joblib.dump(model, pkl_path)
        print(f"  저장: {pkl_path}")

    # 재현에 필요한 메타데이터(피처 컬럼 순서 등) 저장
    meta = {
        "numeric_cols": NUMERIC_COLS,
        "flag_cols": FLAG_COLS,
        "categorical_cols": CATEGORICAL_COLS,
        "onehot_columns": cat_cols,
        "feature_columns": X_train.columns.tolist(),
        "target": TARGET,
        "train_period": [str(train_dates.min().date()), str(train_dates.max().date())],
        "test_period": [str(test_dates.min().date()), str(test_dates.max().date())],
    }
    joblib.dump(meta, SHARED_DIR / "feature_meta.pkl")
    with open(SHARED_DIR / "feature_meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    result_df = pd.DataFrame(results).sort_values("pr_auc", ascending=False)
    result_df.to_csv(MODEL_DIR / "model_comparison.csv", index=False, encoding="utf-8-sig")
    print("\n=== 모델 비교 결과 (PR-AUC 기준 정렬) ===")
    print(result_df.to_string(index=False))
    print(f"\n총 소요시간: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
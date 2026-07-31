"""
8개 지도학습 모델 — Isolation Forest MVP(팀원 원본: `ml/mvp_isolation_forest/`)와 동일한 top-K% 랭킹 평가
조건으로 재실행. 피처 로더는 `feature_set_b.py`(이 실험 전용 재구성 — 팀원 원본과 피처 구성이
일부 다름, 해당 모듈 docstring 참고).

바뀐 것:
- 피처: 12개(Tier0 중 가맹점 제외) -> 15개(Tier0 14 + 일시불할부구분코드), Isolation Forest(MVP)와 동일
- 평가: 0.5/F1 임계값 -> top1/3/5/10% 랭킹 recall·precision
- 임계값: F1 최적화 -> train 분포 97번째 백분위수 고정값 (test 실제 분류비율 검증)
- 세그먼트 진단: 재사용카드 vs 신규카드 추가

바뀌지 않은 것:
- 8개 모델 자체, 이전 라운드(model_tuning.py)에서 찾은 최적 하이퍼파라미터를 그대로 재사용
  (재튜닝은 하지 않음 — 이번 요청 목적이 피처/평가방식 변경이라서)
"""
import json
import time

import joblib
import numpy as np
import pandas as pd
from pathlib import Path

from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier, ExtraTreesClassifier
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import average_precision_score
from xgboost import XGBClassifier
from lightgbm import LGBMClassifier
from catboost import CatBoostClassifier
from imblearn.ensemble import BalancedRandomForestClassifier

from feature_set_b import load_and_prepare, BASE, eval_topk  # 15피처 로더/평가 재사용

MODEL_DIR = Path(__file__).resolve().parent.parent / "models" / "round3_topk_ranking"
MODEL_DIR.mkdir(parents=True, exist_ok=True)
TOPK_LIST = [0.01, 0.03, 0.05, 0.10]
VAL_PERCENTILE = 97
RANDOM_STATE = 42


def log(msg):
    print(msg, flush=True)


BEST_PARAMS = {
    "logistic_regression": {"clf__C": 0.1},
    "random_forest": {"n_estimators": 200, "min_samples_leaf": 20, "max_depth": None},
    "extra_trees": {"n_estimators": 200, "min_samples_leaf": 20, "max_depth": None},
    "balanced_random_forest": {"n_estimators": 100, "min_samples_leaf": 20, "max_depth": None},
    "xgboost": {"subsample": 0.85, "n_estimators": 300, "max_depth": 6,
                "learning_rate": 0.05, "colsample_bytree": 1.0},
    "lightgbm": {"num_leaves": 31, "n_estimators": 400, "learning_rate": 0.1, "feature_fraction": 1.0},
    "catboost": {"learning_rate": 0.1, "l2_leaf_reg": 7, "iterations": 200, "depth": 8},
    "mlp": {"clf__learning_rate_init": 0.005, "clf__hidden_layer_sizes": (128,), "clf__alpha": 0.01},
}


def build_model(name, scale_pos_weight):
    if name == "logistic_regression":
        m = Pipeline([("scaler", StandardScaler()),
                      ("clf", LogisticRegression(max_iter=2000, class_weight="balanced"))])
    elif name == "random_forest":
        m = RandomForestClassifier(class_weight="balanced", n_jobs=-1, random_state=RANDOM_STATE)
    elif name == "extra_trees":
        m = ExtraTreesClassifier(class_weight="balanced", n_jobs=-1, random_state=RANDOM_STATE)
    elif name == "balanced_random_forest":
        m = BalancedRandomForestClassifier(n_jobs=-1, random_state=RANDOM_STATE)
    elif name == "xgboost":
        m = XGBClassifier(tree_method="hist", eval_metric="aucpr", random_state=RANDOM_STATE,
                           n_jobs=-1, scale_pos_weight=scale_pos_weight)
    elif name == "lightgbm":
        m = LGBMClassifier(class_weight="balanced", random_state=RANDOM_STATE, n_jobs=-1, verbose=-1)
    elif name == "catboost":
        m = CatBoostClassifier(auto_class_weights="Balanced", random_state=RANDOM_STATE,
                                thread_count=-1, verbose=False, allow_writing_files=False)
    elif name == "mlp":
        m = Pipeline([("scaler", StandardScaler()),
                      ("clf", MLPClassifier(early_stopping=True, n_iter_no_change=10,
                                             max_iter=150, random_state=RANDOM_STATE))])
    else:
        raise ValueError(name)
    m.set_params(**BEST_PARAMS[name])
    return m


def main():
    t_all = time.time()
    log("[데이터 로드] 15개 피처(Tier0+일시불할부구분코드) 구성...")
    X_train, y_train, cat_cols, cards_train, dates_train = load_and_prepare(BASE / "train_processed.csv")
    X_test, y_test, _, cards_test, dates_test = load_and_prepare(BASE / "test_processed.csv", cat_columns=cat_cols)
    log(f"  train {X_train.shape} / test {X_test.shape}")

    train_cards = set(cards_train.unique())
    is_reused = cards_test.isin(train_cards).values

    pos_rate = y_train.mean()
    scale_pos_weight = (1 - pos_rate) / pos_rate

    results = []
    for name in BEST_PARAMS:
        log(f"\n===== [{name}] =====")
        t0 = time.time()
        model = build_model(name, scale_pos_weight)
        model.fit(X_train, y_train)
        proba_train = model.predict_proba(X_train)[:, 1]
        proba_test = model.predict_proba(X_test)[:, 1]
        log(f"  학습 완료 ({time.time()-t0:.1f}s)")

        pr_auc = average_precision_score(y_test, proba_test)
        topk = {}
        for k in TOPK_LIST:
            topk.update(eval_topk(proba_test, y_test.values, k))

        threshold = np.percentile(proba_train, VAL_PERCENTILE)
        flagged_rate = (proba_test >= threshold).mean()

        seg = {}
        for seg_name, mask in [("reused", is_reused), ("new", ~is_reused)]:
            if mask.sum() == 0:
                continue
            seg_metrics = {}
            for k in [0.03, 0.10]:
                seg_metrics.update(eval_topk(proba_test[mask], y_test.values[mask], k))
            seg[seg_name] = seg_metrics

        log(f"  PR-AUC={pr_auc:.4f} | top3% recall={topk['recall@top3%']:.4f} precision={topk['precision@top3%']:.4f}")
        log(f"  threshold(97pct)={threshold:.4f} test 분류비율={flagged_rate:.4f}")
        log(f"  segment: {seg}")

        joblib.dump(model, MODEL_DIR / f"{name}_topk_ranking.pkl")
        results.append({
            "model": name, "pr_auc": pr_auc, "threshold_97pct": threshold,
            "test_flagged_rate": flagged_rate, **topk,
            "seg_reused": seg.get("reused"), "seg_new": seg.get("new"),
        })

        with open(MODEL_DIR / "topk_ranking_results.json", "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2, default=str)
        pd.DataFrame(results).to_csv(MODEL_DIR / "topk_ranking_results.csv", index=False, encoding="utf-8-sig")

    result_df = pd.DataFrame(results).sort_values("pr_auc", ascending=False)
    log("\n=== 최종 비교 (PR-AUC 기준) ===")
    log(result_df[["model", "pr_auc", "recall@top3%", "precision@top3%",
                    "recall@top10%", "precision@top10%"]].to_string(index=False))
    log(f"\n총 소요시간: {time.time()-t_all:.1f}s")


if __name__ == "__main__":
    main()
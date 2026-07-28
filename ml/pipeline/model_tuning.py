"""
법인카드 이상거래 탐지 - 하이퍼파라미터 튜닝 + 임계값 튜닝 + 모델 다양화

절차 (모델별로 반복):
1. train_processed(2021~2023)를 시간순으로 다시 나눠 2023-10~12월을 검증용(val)으로 떼어둔다.
   (2021-01~2023-09 = train_fit)
2. train_fit에서 계층적 서브샘플(~25만 건)을 뽑아 RandomizedSearchCV로 하이퍼파라미터 탐색
   (전체 데이터로 탐색하면 너무 오래 걸리므로 서브샘플 사용, 서치 단계는 저병렬 설정으로 실행).
3. 찾은 최적 파라미터로 train_fit 전체를 학습 -> val(2023-10~12)에서 F1이 최대가 되는 임계값 선택.
4. 같은 최적 파라미터로 train 전체(2021~2023)를 다시 학습한 것을 "운영용" 모델로 확정,
   pickle로 저장하고 test(2024)에서 최종 평가(3번에서 고른 임계값 적용).

기존 4개 모델(logistic_regression/random_forest/xgboost/lightgbm)에 더해
CatBoost, Extra Trees, MLP(신경망), Balanced Random Forest(imblearn)까지 총 8개 모델을 다룬다.
"""
import json
import time
import traceback

import joblib
import numpy as np
import pandas as pd
from pathlib import Path

from sklearn.base import clone
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier, ExtraTreesClassifier
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import RandomizedSearchCV, StratifiedKFold, train_test_split
from sklearn.metrics import (
    roc_auc_score, average_precision_score,
    precision_score, recall_score, f1_score, confusion_matrix,
)
from xgboost import XGBClassifier
from lightgbm import LGBMClassifier
from catboost import CatBoostClassifier
from imblearn.ensemble import BalancedRandomForestClassifier

from common_features import load_and_prepare, BASE

MODEL_DIR = Path(__file__).resolve().parent.parent / "models" / "round2_tuned"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

VAL_START = "2023-10-01"  # 이 날짜부터는 검증(임계값 선택)용으로 떼어둔다
SEARCH_SUBSAMPLE_SIZE = 250_000
RANDOM_STATE = 42


def log(msg):
    print(msg, flush=True)


# ---------------------------------------------------------------------------
# 모델별: (탐색용 인스턴스 생성 함수, 파라미터 분포, RandomizedSearchCV 설정)
# 탐색 단계는 내부 병렬화를 끄고(n_jobs=1) RandomizedSearchCV가 후보 조합 단위로
# 병렬화하도록 하고, 최종(전체 데이터) 학습 때만 모델 자체 병렬화를 켠다.
# ---------------------------------------------------------------------------

def make_lr(n_jobs=1):
    return Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(max_iter=2000, class_weight="balanced", n_jobs=n_jobs)),
    ])


def make_rf(n_jobs=1):
    return RandomForestClassifier(class_weight="balanced", n_jobs=n_jobs, random_state=RANDOM_STATE)


def make_extra_trees(n_jobs=1):
    return ExtraTreesClassifier(class_weight="balanced", n_jobs=n_jobs, random_state=RANDOM_STATE)


def make_balanced_rf(n_jobs=1):
    return BalancedRandomForestClassifier(n_jobs=n_jobs, random_state=RANDOM_STATE)


def make_xgb(n_jobs=1, scale_pos_weight=1.0):
    return XGBClassifier(
        tree_method="hist", eval_metric="aucpr", random_state=RANDOM_STATE,
        n_jobs=n_jobs, scale_pos_weight=scale_pos_weight,
    )


def make_lgbm(n_jobs=1):
    return LGBMClassifier(class_weight="balanced", random_state=RANDOM_STATE, n_jobs=n_jobs, verbose=-1)


def make_catboost(thread_count=1):
    return CatBoostClassifier(
        auto_class_weights="Balanced", random_state=RANDOM_STATE,
        thread_count=thread_count, verbose=False,
        allow_writing_files=False,  # 병렬 탐색 시 여러 프로세스가 catboost_info 디렉터리를 동시에 만들며 충돌하는 것을 방지
    )


def make_mlp(n_jobs=None):
    return Pipeline([
        ("scaler", StandardScaler()),
        ("clf", MLPClassifier(
            early_stopping=True, n_iter_no_change=10, max_iter=150,
            random_state=RANDOM_STATE,
        )),
    ])


PARAM_DISTS = {
    "logistic_regression": {"clf__C": [0.001, 0.01, 0.1, 1, 10, 100]},
    "random_forest": {
        "n_estimators": [100, 200, 300],
        "max_depth": [8, 12, 16, None],
        "min_samples_leaf": [5, 20, 50],
    },
    "extra_trees": {
        "n_estimators": [100, 200, 300],
        "max_depth": [8, 12, 16, None],
        "min_samples_leaf": [5, 20, 50],
    },
    "balanced_random_forest": {
        "n_estimators": [100, 200, 300],
        "max_depth": [8, 12, 16, None],
        "min_samples_leaf": [5, 20, 50],
    },
    "xgboost": {
        "n_estimators": [200, 300, 400],
        "max_depth": [4, 6, 8],
        "learning_rate": [0.05, 0.1, 0.2],
        "subsample": [0.7, 0.85, 1.0],
        "colsample_bytree": [0.7, 0.85, 1.0],
    },
    "lightgbm": {
        "n_estimators": [200, 300, 400],
        "num_leaves": [15, 31, 63],
        "learning_rate": [0.05, 0.1, 0.2],
        "feature_fraction": [0.7, 0.85, 1.0],
    },
    "catboost": {
        "iterations": [200, 400, 600],
        "depth": [4, 6, 8, 10],
        "learning_rate": [0.03, 0.1, 0.2],
        "l2_leaf_reg": [1, 3, 5, 7],
    },
    "mlp": {
        "clf__hidden_layer_sizes": [(64,), (128,), (128, 64), (64, 32)],
        "clf__alpha": [1e-5, 1e-4, 1e-3, 1e-2],
        "clf__learning_rate_init": [1e-3, 5e-3, 1e-2],
    },
}

# (탐색 n_iter, cv 폴드 수) - 느린 모델은 더 적게
SEARCH_CFG = {
    "logistic_regression": (10, 3),
    "random_forest": (6, 2),
    "extra_trees": (6, 2),
    "balanced_random_forest": (6, 2),
    "xgboost": (10, 3),
    "lightgbm": (10, 3),
    "catboost": (10, 3),
    "mlp": (6, 2),
}


def evaluate(proba, y_true, threshold):
    pred = (proba >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, pred).ravel()
    return {
        "roc_auc": roc_auc_score(y_true, proba),
        "pr_auc": average_precision_score(y_true, proba),
        "threshold": threshold,
        "precision": precision_score(y_true, pred, zero_division=0),
        "recall": recall_score(y_true, pred, zero_division=0),
        "f1": f1_score(y_true, pred, zero_division=0),
        "tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp),
    }


def best_threshold(proba, y_true):
    thresholds = np.arange(0.01, 1.0, 0.01)
    best_t, best_f1 = 0.5, -1.0
    for t in thresholds:
        f1 = f1_score(y_true, (proba >= t).astype(int), zero_division=0)
        if f1 > best_f1:
            best_f1, best_t = f1, t
    return best_t, best_f1


def run_model(name, search_factory, final_factory, X_search, y_search,
              X_train_fit, y_train_fit, X_val, y_val, X_train_full, y_train_full,
              X_test, y_test):
    log(f"\n===== [{name}] 시작 =====")
    t_start = time.time()

    # 1) 서브샘플로 하이퍼파라미터 탐색
    n_iter, cv_folds = SEARCH_CFG[name]
    cv = StratifiedKFold(n_splits=cv_folds, shuffle=True, random_state=RANDOM_STATE)
    search = RandomizedSearchCV(
        estimator=search_factory(),
        param_distributions=PARAM_DISTS[name],
        n_iter=n_iter, cv=cv, scoring="average_precision",
        random_state=RANDOM_STATE, n_jobs=-1, refit=False,
    )
    t0 = time.time()
    search.fit(X_search, y_search)
    log(f"  [1/3] 하이퍼파라미터 탐색 완료 ({time.time()-t0:.1f}s) best_params={search.best_params_} "
        f"best_cv_pr_auc={search.best_score_:.4f}")

    # 2) train_fit(~2023-09까지) 전체로 학습 -> val(2023-10~12)에서 임계값 선택
    t0 = time.time()
    model_for_threshold = clone(final_factory())
    model_for_threshold.set_params(**search.best_params_)
    model_for_threshold.fit(X_train_fit, y_train_fit)
    val_proba = model_for_threshold.predict_proba(X_val)[:, 1]
    thr, val_f1 = best_threshold(val_proba, y_val)
    log(f"  [2/3] train_fit 학습 + 임계값 탐색 완료 ({time.time()-t0:.1f}s) "
        f"선택된 threshold={thr:.2f} (val F1={val_f1:.4f})")

    # 3) train 전체(2021~2023)로 운영용 모델 재학습 -> test(2024) 최종 평가
    t0 = time.time()
    final_model = clone(final_factory())
    final_model.set_params(**search.best_params_)
    final_model.fit(X_train_full, y_train_full)
    test_proba = final_model.predict_proba(X_test)[:, 1]
    metrics_tuned_thr = evaluate(test_proba, y_test, thr)
    metrics_default_thr = evaluate(test_proba, y_test, 0.5)
    log(f"  [3/3] 전체 train 재학습 + test 평가 완료 ({time.time()-t0:.1f}s)")
    log(f"  TEST 결과 @thr={thr:.2f}: ROC-AUC={metrics_tuned_thr['roc_auc']:.4f} "
        f"PR-AUC={metrics_tuned_thr['pr_auc']:.4f} F1={metrics_tuned_thr['f1']:.4f} "
        f"Recall={metrics_tuned_thr['recall']:.4f} Precision={metrics_tuned_thr['precision']:.4f}")

    pkl_path = MODEL_DIR / f"{name}_tuned.pkl"
    joblib.dump(final_model, pkl_path)
    log(f"  저장: {pkl_path} (총 소요 {time.time()-t_start:.1f}s)")

    return {
        "model": name,
        "best_params": search.best_params_,
        "best_cv_pr_auc": search.best_score_,
        "chosen_threshold": thr,
        "val_f1_at_chosen_threshold": val_f1,
        **{f"test_{k}_tunedthr": v for k, v in metrics_tuned_thr.items()},
        **{f"test_{k}_thr0.5": v for k, v in metrics_default_thr.items()},
    }


def main():
    t_all = time.time()
    log("[데이터 로드] train/test 로드 및 날짜순 정렬...")
    X_train_full, y_train_full, cat_cols, train_dates = load_and_prepare(BASE / "train_processed.csv")
    X_test, y_test, _, test_dates = load_and_prepare(BASE / "test_processed.csv", train_cat_columns=cat_cols)
    log(f"  train 전체: {X_train_full.shape} ({train_dates.min().date()} ~ {train_dates.max().date()})")
    log(f"  test      : {X_test.shape} ({test_dates.min().date()} ~ {test_dates.max().date()})")

    val_mask = train_dates >= pd.Timestamp(VAL_START)
    X_train_fit, y_train_fit = X_train_full[~val_mask], y_train_full[~val_mask]
    X_val, y_val = X_train_full[val_mask], y_train_full[val_mask]
    log(f"  train_fit(탐색/학습용): {X_train_fit.shape} (~{VAL_START} 이전)")
    log(f"  val(임계값 선택용)    : {X_val.shape} ({VAL_START} 이후)")

    X_search, _, y_search, _ = train_test_split(
        X_train_fit, y_train_fit,
        train_size=min(SEARCH_SUBSAMPLE_SIZE, len(X_train_fit)),
        stratify=y_train_fit, random_state=RANDOM_STATE,
    )
    log(f"  탐색용 서브샘플: {X_search.shape} (양성비율 {y_search.mean():.4f})")

    pos_rate = y_train_fit.mean()
    scale_pos_weight = (1 - pos_rate) / pos_rate

    jobs = [
        ("logistic_regression", lambda: make_lr(n_jobs=1), lambda: make_lr(n_jobs=-1)),
        ("random_forest", lambda: make_rf(n_jobs=1), lambda: make_rf(n_jobs=-1)),
        ("extra_trees", lambda: make_extra_trees(n_jobs=1), lambda: make_extra_trees(n_jobs=-1)),
        ("balanced_random_forest", lambda: make_balanced_rf(n_jobs=1), lambda: make_balanced_rf(n_jobs=-1)),
        ("xgboost", lambda: make_xgb(n_jobs=1, scale_pos_weight=scale_pos_weight),
                    lambda: make_xgb(n_jobs=-1, scale_pos_weight=scale_pos_weight)),
        ("lightgbm", lambda: make_lgbm(n_jobs=1), lambda: make_lgbm(n_jobs=-1)),
        ("catboost", lambda: make_catboost(thread_count=1), lambda: make_catboost(thread_count=-1)),
        ("mlp", lambda: make_mlp(), lambda: make_mlp()),
    ]

    results = []
    for name, search_factory, final_factory in jobs:
        try:
            r = run_model(
                name, search_factory, final_factory,
                X_search, y_search, X_train_fit, y_train_fit, X_val, y_val,
                X_train_full, y_train_full, X_test, y_test,
            )
            results.append(r)
        except Exception:
            log(f"  !! {name} 실패, 건너뜀 !!")
            log(traceback.format_exc())

        # 중간 결과를 매 모델마다 저장(진행 중 확인 가능하도록)
        with open(MODEL_DIR / "tuning_results.json", "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2, default=str)
        pd.DataFrame(results).to_csv(MODEL_DIR / "tuning_results.csv", index=False, encoding="utf-8-sig")

    if results:
        result_df = pd.DataFrame(results).sort_values("test_pr_auc_tunedthr", ascending=False)
        log("\n=== 튜닝 결과 비교 (PR-AUC 기준 정렬) ===")
        show_cols = ["model", "chosen_threshold", "test_roc_auc_tunedthr", "test_pr_auc_tunedthr",
                     "test_precision_tunedthr", "test_recall_tunedthr", "test_f1_tunedthr"]
        log(result_df[show_cols].to_string(index=False))

    log(f"\n전체 소요시간: {time.time()-t_all:.1f}s")


if __name__ == "__main__":
    main()
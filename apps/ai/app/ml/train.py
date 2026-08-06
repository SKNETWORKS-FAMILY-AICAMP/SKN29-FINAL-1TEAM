"""오프라인 배치 학습 — 법인카드 이상거래 탐지 Isolation Forest (관리자 수동 실행).

  python -m app.ml.train --train-csv <경로> --test-csv <경로> [--out-dir <경로>]

ml/mvp_isolation_forest/법인카드_이상거래_모델링_v2_최종test평가.ipynb ·
ml/mvp_isolation_forest/고정_임계값_재계산.py의 확정 로직(피처셋·하이퍼파라미터·임계값 산정
방식)을 서비스 코드로 이식한 버전이다. "동기 REST(MVP), 무거운 작업은 관리자 온디맨드 배치"
원칙(CLAUDE.md)에 따라 HTTP 엔드포인트가 아니라 CLI 스크립트로만 트리거한다.

입력 CSV는 전처리 노트북(법인카드_이상거래_전처리_v3_세그먼트플래그.ipynb)이 만든
train_processed.csv / test_processed.csv와 동일 스키마여야 한다(이 스크립트는 피처
선택·인코딩만 담당하고 Expanding Window 등 시점 안전 통계는 다시 계산하지 않는다).

결과 아티팩트(--out-dir, 기본값 settings.model_dir):
  - anomaly.pkl         : app.ml.registry.get_active_model()이 그대로 로드하는 표준 경로
  - isolation_forest_v1.pkl : 위와 동일 모델(감사·롤백용 버전 스냅샷)
  - threshold_v1.json   : 하이퍼파라미터·피처 목록·고정 임계값·decile 보정표(감사/디버깅용)

주의: 여기서 산출되는 PR-AUC는 "참고용"이다. 이 리포에서 이미 여러 차례 확인했듯
(ml/ml_final_report.md §3 참고) IsolationForest의 절대 성능 수치는 scikit-learn 버전 등
실행 환경에 따라 달라진다 — ml_final_report.md에 확정된 0.5865는 팀원 환경(final_prj)의
결과이며, 이 스크립트를 재실행해서 나온 값과 다를 수 있다. 이 스크립트의 목적은 "확정된
피처셋·하이퍼파라미터로 학습해 운영 임계값·보정표를 최신 데이터 기준으로 재계산하는 것"이지
0.5865 재현이 아니다.
"""
from __future__ import annotations

import argparse
import json
import pickle
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from app.config import settings
from app.ml import features
from app.ml.anomaly import AnomalyModel
from app.ml.calibration import decile_calibration_table, fixed_threshold
from app.ml.registry import register_model

LABEL_COLUMN = "이상거래여부"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--train-csv", required=True, help="전처리 노트북이 만든 train_processed.csv 경로")
    parser.add_argument("--test-csv", required=True, help="전처리 노트북이 만든 test_processed.csv 경로")
    parser.add_argument("--out-dir", default=settings.model_dir, help="아티팩트 저장 경로 (기본: settings.model_dir)")
    parser.add_argument("--threshold-percentile", type=float, default=90.0, help="고정 임계값 = train 점수 분포의 이 백분위수 (기본 90 = 상위 10% 컷오프)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    print(f"[1/5] 데이터 로드: {args.train_csv} / {args.test_csv}")
    train_df = pd.read_csv(args.train_csv, low_memory=False)
    test_df = pd.read_csv(args.test_csv, low_memory=False)
    if LABEL_COLUMN not in test_df.columns:
        raise SystemExit(f"test CSV에 라벨 컬럼 '{LABEL_COLUMN}'이 없습니다 — decile 보정표를 만들 수 없습니다.")

    fill_values = features.compute_fill_values(train_df)
    X_train = features.build_feature_matrix(train_df, fill_values)
    X_test = features.build_feature_matrix(test_df, fill_values)
    X_train, X_test = features.align_columns(X_train, X_test)
    y_test = test_df[LABEL_COLUMN].to_numpy()
    print(f"       train={len(X_train):,}건 · test={len(X_test):,}건 · 피처={X_train.shape[1]}컬럼(원-핫 후)")

    print(f"[2/5] Isolation Forest 학습 (n_estimators=200, max_samples='auto', contamination='auto', random_state=42)")
    model = AnomalyModel()
    model.fit(X_train.to_numpy(dtype=float))
    model.feature_columns = list(X_train.columns)

    print("[3/5] train 점수 분포 → 고정 임계값 계산")
    train_scores = -model.model.decision_function(X_train.to_numpy(dtype=float))
    threshold = fixed_threshold(train_scores, args.threshold_percentile)
    model.threshold = threshold

    print("[4/5] test 채점 → decile 보정표 + 참고 성능지표")
    test_scores = -model.model.decision_function(X_test.to_numpy(dtype=float))
    calibration_table = decile_calibration_table(y_test, test_scores)
    model.calibration_table = calibration_table

    from sklearn.metrics import average_precision_score
    pr_auc_reference = float(average_precision_score(y_test, test_scores))
    flagged_rate = float((test_scores >= threshold).mean())
    recall_at_threshold = float(y_test[test_scores >= threshold].sum() / y_test.sum()) if y_test.sum() > 0 else None

    print("[5/5] 아티팩트 저장")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # register_model()은 settings.model_dir 기준 표준 경로(anomaly.pkl)에 저장하므로,
    # --out-dir로 지정한 위치와 반드시 일치시킨다(불일치 시 settings 기본값으로 조용히 새는 것을 방지).
    settings.model_dir = str(out_dir)
    register_model(model)  # anomaly.pkl(표준 경로) 저장 + 레지스트리 캐시 갱신
    with open(out_dir / "isolation_forest_v1.pkl", "wb") as f:
        pickle.dump(model, f)

    meta = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "hyperparameters": model.model.get_params(),
        "feature_columns": model.feature_columns,
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "threshold_percentile": args.threshold_percentile,
        "fixed_threshold": threshold,
        "test_flagged_rate": round(flagged_rate, 4),
        "test_recall_at_threshold": round(recall_at_threshold, 4) if recall_at_threshold is not None else None,
        "test_pr_auc_reference": round(pr_auc_reference, 4),
        "pr_auc_reference_note": (
            "참고용 수치 — 확정치는 ml/ml_final_report.md의 0.5865(팀원 환경 final_prj). "
            "실행 환경(scikit-learn 버전 등)에 따라 달라질 수 있음(ml_final_report.md §3 참고)."
        ),
        "calibration_table": calibration_table,
    }
    with open(out_dir / "threshold_v1.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(
        f"완료: threshold={threshold:.4f}, test 분류비율={flagged_rate:.2%}, "
        f"recall={recall_at_threshold:.2%} (PR-AUC 참고치={pr_auc_reference:.4f})"
    )
    print(f"저장: {out_dir / 'anomaly.pkl'}, {out_dir / 'isolation_forest_v1.pkl'}, {out_dir / 'threshold_v1.json'}")


if __name__ == "__main__":
    main()

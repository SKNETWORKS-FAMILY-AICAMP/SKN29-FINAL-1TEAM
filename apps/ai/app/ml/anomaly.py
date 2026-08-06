"""MVP 1차: 단순 이상거래 탐지 (비지도, 라벨 불필요) — 기술명세서 §7.

Isolation Forest. anomaly_score(높을수록 이상) + 이상치 여부 반환.
하이퍼파라미터 기본값은 ml/ml_final_report.md 확정치(§7). threshold·calibration_table·
feature_columns는 오프라인 배치 학습(app/ml/train.py)이 채워 넣는 운영 메타데이터이며,
없으면(레거시 학습·테스트 등) sklearn 기본 판정으로 대체 동작한다.
"""
from __future__ import annotations

import numpy as np
from sklearn.ensemble import IsolationForest

from app.ml.calibration import lookup_calibration


class AnomalyModel:
    def __init__(
        self,
        n_estimators: int = 200,
        max_samples="auto",
        contamination="auto",
        random_state: int = 42,
    ):
        self.model = IsolationForest(
            n_estimators=n_estimators,
            max_samples=max_samples,
            contamination=contamination,
            random_state=random_state,
        )
        self.fitted = False
        # app/ml/train.py(오프라인 배치 학습)가 채워 넣는 운영 메타데이터 — 기본값 None
        self.threshold: float | None = None
        self.calibration_table: list[dict] | None = None
        self.feature_columns: list[str] | None = None

    def fit(self, X) -> "AnomalyModel":
        self.model.fit(np.asarray(X, dtype=float))
        self.fitted = True
        return self

    def score(self, x: list[float]) -> dict:
        arr = np.asarray([x], dtype=float)
        # decision_function: 값이 클수록 정상 → 부호 반전해 anomaly_score(클수록 이상)로.
        # ml_final_report.md·모델링 노트북과 동일 정의 — score_samples가 아님에 주의
        # (decision_function = score_samples - offset_ 이라 스케일이 다르며, 고정 임계값
        # -0.0123은 decision_function 기준으로만 의미가 있다).
        raw = float(self.model.decision_function(arr)[0])
        anomaly_score = -raw

        if self.threshold is not None:
            is_outlier = anomaly_score >= self.threshold
        else:
            # threshold 미설정(레거시 학습 등) — sklearn contamination 기반 기본 판정으로 대체
            is_outlier = bool(self.model.predict(arr)[0] == -1)

        result: dict = {"anomaly_score": anomaly_score, "is_outlier": is_outlier}

        band = lookup_calibration(anomaly_score, self.calibration_table)
        if band is not None:
            result["percentile_band"] = band["band"]
            result["calibrated_rate"] = band["observed_rate"]

        return result

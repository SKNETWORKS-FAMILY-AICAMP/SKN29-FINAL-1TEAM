"""MVP 1차: 단순 이상거래 탐지 (비지도, 라벨 불필요) — 기술명세서 §7.

예) Isolation Forest. anomaly_score(높을수록 이상) + 이상치 여부 반환.
"""
from __future__ import annotations

import numpy as np
from sklearn.ensemble import IsolationForest


class AnomalyModel:
    def __init__(self, contamination: float = 0.05, random_state: int = 42):
        self.model = IsolationForest(contamination=contamination, random_state=random_state)
        self.fitted = False

    def fit(self, X) -> "AnomalyModel":
        self.model.fit(np.asarray(X, dtype=float))
        self.fitted = True
        return self

    def score(self, x: list[float]) -> dict:
        arr = np.asarray([x], dtype=float)
        # score_samples: 값이 클수록 정상 → 부호 반전해 anomaly_score(클수록 이상)로.
        raw = float(self.model.score_samples(arr)[0])
        is_outlier = bool(self.model.predict(arr)[0] == -1)
        return {"anomaly_score": -raw, "is_outlier": is_outlier}

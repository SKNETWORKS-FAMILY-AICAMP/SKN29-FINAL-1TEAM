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
        # train 기준 콜드스타트 NaN 대체값(features.compute_fill_values 결과). get_tx_features가
        # 단건 서빙 시 학습 때와 동일한 median으로 결측을 채우려면 이 값이 모델과 함께 저장돼야 한다
        # (없으면 서빙마다 임의로 다른 값을 쓰게 되어 학습-서빙 불일치가 생긴다).
        self.fill_values: dict[str, float] | None = None
        # train 기준 컬럼별 평균/표준편차. Risk Review 2차 검증 입력으로 쓰는 "어느 피처가
        # 튀었는지"(feature_contribs)를 계산하려면 IsolationForest 자체엔 없는 이 통계가 필요하다.
        self.feature_stats: dict[str, dict[str, float]] | None = None

    def __setstate__(self, state: dict) -> None:
        """pickle.load는 __init__을 건너뛰고 __dict__를 그대로 복원한다 — 그 시점 이후 새로 추가된
        속성(fill_values·feature_stats 등)은 옛 pkl에 아예 없어 평범한 getattr 기본값도 못 받고
        AttributeError가 난다. 새 속성을 추가할 때마다 여기 기본값을 함께 채워, 학습 시점이 다른
        pkl을 로드해도 서빙 경로가 죽지 않고 "그 정보 없이" 동작하도록 한다.
        """
        self.__dict__.update(state)
        self.__dict__.setdefault("fill_values", None)
        self.__dict__.setdefault("feature_stats", None)

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

    def feature_contribs(self, x: list[float], top_n: int = 3) -> list[dict]:
        """train 분포 대비 |z-score| 상위 top_n 피처 — "어느 피처가 튀었는지"(Risk Review 2차 입력).

        IsolationForest는 사이킷런 기본 API로 샘플별 피처 기여도를 주지 않는다(SHAP 등 별도
        라이브러리 없이 v0 범위). z-score는 근사치이지 진짜 기여도가 아니라는 점을 호출부(LLM
        프롬프트)에 그대로 노출해야 한다 — 과장된 설명력을 주장하지 않는다.
        """
        if not self.feature_columns or not self.feature_stats:
            return []
        devs = []
        for name, val in zip(self.feature_columns, x):
            stats = self.feature_stats.get(name)
            if not stats or not stats.get("std"):
                continue
            z = abs((val - stats["mean"]) / stats["std"])
            devs.append((name, z))
        devs.sort(key=lambda pair: -pair[1])
        top = devs[:top_n]
        total = sum(z for _, z in top) or 1.0
        return [{"feature": name, "weight": round(z / total, 3)} for name, z in top]

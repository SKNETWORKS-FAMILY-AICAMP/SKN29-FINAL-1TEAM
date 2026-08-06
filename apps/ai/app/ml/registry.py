"""단순 모델 레지스트리 (기술명세서 §7). MVP: 파일 pickle 저장/로드."""
from __future__ import annotations

import os
import pickle

from app.config import settings
from app.ml.anomaly import AnomalyModel

_cache: AnomalyModel | None = None


def _model_path() -> str:
    # settings.model_dir을 호출 시점마다 다시 읽는다 — 모듈 import 시점에 상수로
    # 고정해두면(과거 버전의 버그) 이후 settings.model_dir을 바꿔도 반영되지 않는다.
    return os.path.join(settings.model_dir, "anomaly.pkl")


def get_active_model() -> AnomalyModel | None:
    """학습된 활성 모델 반환. 없으면 None(추론 측에서 stub 처리)."""
    global _cache
    if _cache is not None:
        return _cache
    path = _model_path()
    if os.path.exists(path):
        with open(path, "rb") as f:
            _cache = pickle.load(f)
    return _cache


def register_model(model: AnomalyModel) -> AnomalyModel:
    """이미 학습된 모델을 레지스트리에 저장(오프라인 배치 학습 스크립트 app/ml/train.py 등에서 사용)."""
    global _cache
    os.makedirs(settings.model_dir, exist_ok=True)
    with open(_model_path(), "wb") as f:
        pickle.dump(model, f)
    _cache = model
    return model


def train_and_register(X) -> AnomalyModel:
    """비지도 이상탐지 학습 후 레지스트리에 저장(threshold·calibration 없는 레거시 경로)."""
    return register_model(AnomalyModel().fit(X))

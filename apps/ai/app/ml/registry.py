"""단순 모델 레지스트리 (기술명세서 §7). MVP: 파일 pickle 저장/로드."""
from __future__ import annotations

import os
import pickle

from app.config import settings
from app.ml.anomaly import AnomalyModel

_MODEL_PATH = os.path.join(settings.model_dir, "anomaly.pkl")
_cache: AnomalyModel | None = None


def get_active_model() -> AnomalyModel | None:
    """학습된 활성 모델 반환. 없으면 None(추론 측에서 stub 처리)."""
    global _cache
    if _cache is not None:
        return _cache
    if os.path.exists(_MODEL_PATH):
        with open(_MODEL_PATH, "rb") as f:
            _cache = pickle.load(f)
    return _cache


def train_and_register(X) -> AnomalyModel:
    """비지도 이상탐지 학습 후 레지스트리에 저장."""
    global _cache
    model = AnomalyModel().fit(X)
    os.makedirs(settings.model_dir, exist_ok=True)
    with open(_MODEL_PATH, "wb") as f:
        pickle.dump(model, f)
    _cache = model
    return model

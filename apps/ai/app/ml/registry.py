"""단순 모델 레지스트리 (기술명세서 §7). MVP: 파일 pickle 저장/로드.

## 모델이 없으면 **반드시 로그를 남긴다**

`get_active_model()`이 `None`을 돌려주면 추론 측(`ml_infer`·Risk Review `_stage1`)은
조용히 stub(`anomaly_score=0.0`)으로 떨어진다. 그 자체는 의도된 동작이지만, **로그가
한 줄도 안 남아서** "모델을 넣었는데 왜 안 도나"를 추적할 방법이 없었다(2026-08-23 실측:
pkl을 `var/`에 뒀는데 레지스트리는 `var/models/`를 봐서 못 찾고 있었고, 그 사실이 어디에도
안 찍혔다). 찾는 경로를 함께 찍어 **어디를 보고 있는지**가 바로 드러나게 한다.
"""
from __future__ import annotations

import logging
import os
import pickle

from app.config import settings
from app.ml.anomaly import AnomalyModel

logger = logging.getLogger(__name__)

_cache: AnomalyModel | None = None
#: 같은 경고를 요청마다 찍지 않는다 — 없다는 사실은 한 번만 알면 된다.
_missing_warned = False


def _model_path() -> str:
    # settings.model_dir을 호출 시점마다 다시 읽는다 — 모듈 import 시점에 상수로
    # 고정해두면(과거 버전의 버그) 이후 settings.model_dir을 바꿔도 반영되지 않는다.
    return os.path.join(settings.model_dir, "anomaly.pkl")


def get_active_model() -> AnomalyModel | None:
    """학습된 활성 모델 반환. 없으면 None(추론 측에서 stub 처리).

    **로드 성공·실패를 모두 로그로 남긴다** — 모듈 docstring 참조.
    """
    global _cache, _missing_warned
    if _cache is not None:
        return _cache

    path = _model_path()
    if not os.path.exists(path):
        if not _missing_warned:
            logger.warning(
                "이상탐지 모델이 없다 — 경로 %s (MODEL_DIR=%s). "
                "Risk Review 1차는 stub(anomaly_score=0.0)으로 돈다. "
                "학습된 pkl을 이 경로에 두거나 MODEL_DIR을 맞춰라.",
                path, settings.model_dir,
            )
            _missing_warned = True
        return None

    try:
        with open(path, "rb") as f:
            _cache = pickle.load(f)
    except Exception:  # noqa: BLE001  # 손상·버전 불일치 등 — 예외로 서비스를 죽이지 않는다
        logger.exception("이상탐지 모델 로드 실패 (%s) — stub으로 진행한다", path)
        return None

    #  **무엇이 실린지 찍는다.** `feature_stats`가 없는 pkl은 로드는 되지만
    #  `feature_contribs`가 상시 빈 배열이라 "모델이 안 돈다"로 오인된다.
    logger.info(
        "이상탐지 모델 로드: %s (columns=%d, threshold=%.6f, feature_stats=%s, fill_values=%s)",
        path,
        len(_cache.feature_columns or []) if _cache.feature_columns else 0,
        _cache.threshold or 0.0,
        bool(getattr(_cache, "feature_stats", None)),
        bool(getattr(_cache, "fill_values", None)),
    )
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

from fastapi import APIRouter
from pydantic import BaseModel

from app.ml.registry import get_active_model

router = APIRouter()


class Features(BaseModel):
    feature_vector: list[float]


@router.post("/infer")
def infer(req: Features):
    """이상탐지 추론 (MVP: 비지도만). review_prob는 post-MVP."""
    model = get_active_model()
    if not model or not model.fitted:
        return {"anomaly_score": 0.0, "contribs": {}, "note": "no trained model (stub)"}
    return {**model.score(req.feature_vector), "contribs": {}}


@router.post("/train")
def train():
    """온디맨드 배치 학습(관리자 트리거). TODO: core 거래 로드 → feature → IsolationForest fit."""
    return {"status": "stub", "detail": "비지도 이상탐지 배치 학습 자리표시자"}

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
    """학습은 이 API가 아니라 오프라인 배치 스크립트로 수행한다(관리자 CLI 실행).

    docker compose exec ai python -m app.ml.train --train-csv <경로> --test-csv <경로>
    """
    return {
        "status": "not_available_via_api",
        "detail": "학습은 `python -m app.ml.train` 스크립트로 수행합니다(app/ml/train.py 참고).",
    }

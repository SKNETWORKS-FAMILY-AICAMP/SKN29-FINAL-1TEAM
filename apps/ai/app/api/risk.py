from fastapi import APIRouter
from pydantic import BaseModel

from app.agents import risk_review_agent

router = APIRouter()


class RiskRequest(BaseModel):
    settlement_id: int


@router.post("/risk-review")
def risk_review(req: RiskRequest):
    """Risk Review 실행 (MVP 2단계: 이상탐지 1차 → RAG 내규 검증 2차).

    feature_vector는 호출부가 넘기지 않는다 — get_tx_features(Django 경유)가 내부에서 조립한다.
    """
    return risk_review_agent.run(req.settlement_id)

from fastapi import APIRouter
from pydantic import BaseModel

from app.agents import risk_review_agent

router = APIRouter()


class RiskRequest(BaseModel):
    settlement_id: int
    feature_vector: list[float] | None = None


@router.post("/risk-review")
def risk_review(req: RiskRequest):
    """Risk Review 실행 (MVP 2단계: 이상탐지 1차 → RAG 내규 검증 2차)."""
    return risk_review_agent.run(req.settlement_id, req.feature_vector)

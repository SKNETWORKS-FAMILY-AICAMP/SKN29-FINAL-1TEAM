from fastapi import APIRouter
from pydantic import BaseModel

from app.agents import draft_agent

router = APIRouter()


class DraftRequest(BaseModel):
    settlement_id: int


@router.post("/draft")
def run_draft(req: DraftRequest):
    """Draft Agent 실행 (동기). 영수증 판독·분류·규정힌트 초안."""
    return draft_agent.run(req.settlement_id)

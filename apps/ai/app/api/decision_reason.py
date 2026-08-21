from fastapi import APIRouter
from pydantic import BaseModel

from app.agents import decision_reason_agent

router = APIRouter()


class RuleFlagInfo(BaseModel):
    label: str
    severity: str = ""


class DraftDecisionReasonRequest(BaseModel):
    decision: str  # RETURN | REJECT
    reasonCategory: str = ""
    merchant: str = ""
    amount: int = 0
    category: str = ""
    purpose: str | None = None
    ruleFlags: list[RuleFlagInfo] = []
    violationVerdict: str = ""
    reviewReasons: list[str] = []
    anomalyReasons: list[str] = []


@router.post("/draft-decision-reason")
def draft_decision_reason(req: DraftDecisionReasonRequest):
    """보완요청/반려 사유 초안 — 이미 있는 판정 근거를 문장으로 정리(신규 판단 없음).

    담당자가 그대로 제출하지 않고 편집할 초안이다. 실패를 감추지 않는다 — Django가
    5xx를 그대로 보고 "직접 입력하세요"로 안내해야 "AI가 판단했다"는 오해가 안 생긴다.
    """
    detail = decision_reason_agent.draft(req.model_dump())
    return {"detail": detail}

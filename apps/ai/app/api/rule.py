from fastapi import APIRouter
from pydantic import BaseModel

from app.agents import rule_agent

router = APIRouter()


class GenerateRequest(BaseModel):
    doc_query: str | None = None


class ApplyRequest(BaseModel):
    settlement_id: int


@router.post("/rule/generate")
def generate(req: GenerateRequest):
    """Rule 생성 (LLM). status=DRAFT."""
    return rule_agent.generate(req.doc_query)


@router.post("/rule/validate")
def validate():
    """Rule 검증 — 과거 거래 시뮬레이션(매칭/오탐율/검토감소량)."""
    return rule_agent.validate()


@router.post("/rule/apply")
def apply(req: ApplyRequest):
    """Rule 적용 — 결정론적 엔진 1차 판정."""
    return rule_agent.apply(req.settlement_id)

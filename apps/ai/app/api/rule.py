from fastapi import APIRouter
from pydantic import BaseModel

from app.agents import rule_agent
from app.mcp import tools

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
    """Rule 적용 — 결정론적 엔진 1차 판정 (Django 위임).

    LLM은 개입하지 않는다(FR-RA-06 재현성). 판정·`rule_hits` 기록·상태 전이가 한
    트랜잭션이어야 해서 실체는 Django에 있고, 여기서는 tool 경로를 유지할 뿐이다.
    """
    return tools.run_rule_engine(req.settlement_id)

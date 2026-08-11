"""Draft Agent API (기술명세서 §4.1 / _context/draft-agent-plan.md).

POST /agent/draft — 생성 모드(신규 초안) / 수정 모드(자연어 지시로 기존 초안 수정) 공용 엔드포인트.
요청 바디에 `instruction`이 있으면 수정 모드, 없으면 생성 모드로 처리한다(Django `draft-suggest`
액션과 동일한 분기 방식 — B-5에서 Django가 이 엔드포인트로 그대로 위임한다).
"""
from typing import Literal, Optional

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, ValidationError

from app.agents import draft_agent
from app.schemas import Category, CardType, Evidence

router = APIRouter()


class DraftRequest(BaseModel):
    """생성 모드 요청. 실제 프론트 호출은 이 필드들을 flat하게 보낸다."""
    merchant: str
    amount: int
    date: Optional[str] = None
    ts: Optional[str] = None            # date/ts 중 하나만 와도 되게 둘 다 optional
    cardType: CardType
    evidence: Optional[Evidence] = "OK"
    headcount: Optional[int] = 0        # 실제 프론트는 생성 모드에서 이 필드를 보내지 않음 → 기본값 필수
    receipt_image: Optional[str] = None  # 범위 밖. 받아도 무시

    def resolved_ts(self) -> str:
        return self.date or self.ts or ""


class ReviseCurrent(BaseModel):
    """수정 모드의 `current` — 화면에 지금 떠 있는 초안 값 그대로."""
    merchant: str
    amount: int
    category: Category
    aiCategory: Optional[Category] = None
    purpose: str = ""
    evidence: Optional[Evidence] = "OK"
    headcount: Optional[int] = 0


class ReviseRequest(BaseModel):
    """수정 모드 요청. 실제 프론트는 `{ instruction, current: {...} }` 중첩 구조로 보낸다."""
    instruction: str
    current: ReviseCurrent


class DraftComment(BaseModel):
    icon: Literal["ocr", "ai", "doc"]
    text: str


class PolicyHint(BaseModel):
    level: Literal["warn", "info"]
    clause: str
    text: str
    status: str


class Draft(BaseModel):
    merchant: str
    amount: int
    category: Category
    aiCategory: Category
    aiSuggested: bool
    merchantIndustry: str = ""
    purpose: str
    evidence: Evidence
    headcount: int = 0


class DraftResponse(BaseModel):
    mode: Literal["create", "revise"] = "create"
    draft: Draft
    confidence: float
    changes: list[str] = []  # 수정 모드에서만 채워짐(생성 모드는 빈 배열)
    comments: list[DraftComment]
    policyHints: list[PolicyHint]


@router.post("/draft", response_model=DraftResponse)
def run_draft(payload: dict = Body(...)):
    """`instruction`이 있으면 수정 모드, 없으면 생성 모드로 위임(Django draft-suggest와 동일 분기)."""
    if str(payload.get("instruction", "")).strip():
        try:
            req = ReviseRequest(**payload)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()) from exc
        return draft_agent.revise(req)

    try:
        req = DraftRequest(**payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    return draft_agent.run(req)

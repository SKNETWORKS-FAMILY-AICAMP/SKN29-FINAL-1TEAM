"""Draft Agent API (기술명세서 §4.1 / _context/draft-agent-plan.md).

POST /agent/draft — 생성 모드(신규 초안) / 수정 모드(자연어 지시로 기존 초안 수정) 공용 엔드포인트.
요청 바디에 `instruction`이 있으면 수정 모드, 없으면 생성 모드로 처리한다(Django `draft-suggest`
액션과 동일한 분기 방식 — B-5에서 Django가 이 엔드포인트로 그대로 위임한다).
"""
from typing import Literal, Optional

import httpx
from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, ValidationError

from app.agents import draft_agent, submit_polish
from app.schemas import CardType, Evidence

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
    # 업종 조회(카카오)의 장소 힌트 — 같은 상호가 여러 곳일 때 검색 정확도를 올린다.
    #  현재 화면은 보내지 않는다(거래에 주소 필드가 없다). 영수증 판독이 주소를 뽑으면 그때 채운다.
    placeHint: Optional[str] = None
    receipt_image: Optional[str] = None  # 범위 밖. 받아도 무시

    def resolved_ts(self) -> str:
        return self.date or self.ts or ""


class ReviseCurrent(BaseModel):
    """수정 모드의 `current` — 화면에 지금 떠 있는 초안 값 그대로."""
    merchant: str
    amount: int
    category: str = ""                  # ""=미분류(사람이 아직 안 골랐다)
    aiCategory: Optional[str] = None
    # 생성 모드에서 서버가 조회해 넣어 준 업종. 수정 모드는 이걸 그대로 물려받는다
    # (재조회는 비어 있을 때만 — §7-1 캐스케이드를 매 수정마다 다시 태울 이유가 없다).
    merchantIndustry: str = ""
    merchantIndustryCode: str = ""
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
    #  `Category` Literal로 묶지 않는다 — 어휘 정본은 core이고 ai는 런타임에 그 목록을
    #  받아 구조화 출력 enum으로 강제한다(`draft_agent._with_categories`). 여기서 정적
    #  미러로 한 번 더 조이면 core가 분류를 늘렸을 때 **응답 검증에서** 422가 나서,
    #  모델은 새 값을 제대로 골랐는데 화면에는 서버 오류로 보인다.
    #  빈 문자열은 「아직 못 정했다」 — 화면이 「선택 필요」로 띄운다.
    category: str
    aiCategory: str
    aiSuggested: bool
    merchantIndustry: str = ""
    merchantIndustryCode: str = ""
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


class SettlementDraftRequest(BaseModel):
    """정산 기반 초안 — 사실은 서버가 조회한다(화면이 보내는 건 id와 지시뿐)."""
    settlementId: int
    instruction: str = ""


@router.post("/draft/settlement")
def run_settlement_draft(req: SettlementDraftRequest):
    """저장된 정산 한 건으로 초안 작성.

    응답 모델을 고정하지 않는다 — `notices`·`judgement`는 core가 조립한 사실을 그대로
    실어 보내는 자리라, 여기서 다시 pydantic으로 좁히면 core가 필드를 늘릴 때마다
    **응답 검증에서** 막힌다(분류 어휘를 `str`로 푼 것과 같은 이유).
    """
    try:
        return draft_agent.run_for_settlement(req.settlementId, req.instruction)
    except httpx.HTTPStatusError as exc:
        #  사실 조회 실패를 200으로 덮지 않는다 — 사실 없이 쓴 초안은 실패보다 나쁘다.
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=f"정산 사실 조회 실패({exc.request.url.path}): {exc.response.text[:300]}",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"core 연결 실패: {exc}") from exc


class PolishRequest(BaseModel):
    purpose: str
    contextHint: str = ""


@router.post("/draft/polish")
def polish_purpose(req: PolishRequest):
    """제출 직전 「지출 목적」 문체 다듬기.

    사실이 늘었는지는 **서버가 기계적으로 대조**한다(`submit_polish` 모듈 docstring).
    """
    return submit_polish.polish(req.purpose, req.contextHint)


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

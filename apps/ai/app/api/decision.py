"""결정 사유 초안 REST — Django가 「보완요청·반려」 모달을 열 때 부른다.

Draft Agent 계열이지만 초안 대상이 **정산 내역이 아니라 통보 문구**라 라우터를 나눴다
(`/agent/draft`는 지출 내역 초안, 여기는 처리 사유 초안).

실패를 200으로 덮지 않는다 — core가 판정 플래그 기반 폴백을 갖고 있어서, 여기서 빈
문자열을 성공으로 돌려주면 오히려 **더 나쁜 초안**(빈 사유)이 화면에 뜬다.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Body, HTTPException

from app.agents import decision_reason_agent

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/decision-reason")
def decision_reason(payload: dict = Body(...)) -> dict:
    if str(payload.get("decision") or "").upper() not in {"APPROVE", "RETURN", "REJECT"}:
        raise HTTPException(status_code=400, detail="decision은 APPROVE/RETURN/REJECT 중 하나여야 합니다.")
    if not payload.get("options"):
        raise HTTPException(status_code=400, detail="사유 선택지(options)가 필요합니다.")
    try:
        return decision_reason_agent.draft(payload)
    except Exception as exc:  # noqa: BLE001
        logger.exception("decision-reason 실패")
        raise HTTPException(status_code=502, detail=f"사유 초안 생성 실패: {exc}") from exc

"""① 초안 작성 Agent (기술명세서 §4.1 / _context/draft-agent-plan.md).

거래 정보 → 분류·지출목적·규정힌트 초안 자동 완성. 생성 모드(run)·수정 모드(revise) 지원.
- 응답 형식은 OpenAI Structured Output(strict)으로 API 단에서 강제한다 — 6개 분류·필드 타입이
  어긋난 값 자체가 나올 수 없으므로, 별도의 사후 clamp 로직이 필요 없다(B-2).
- get_policy는 Django `Policy` 테이블을 FastMCP 경유로 실조회한다(B-3). 조회 실패 시에만 폴백값 사용.
- 영수증 비전 판독은 이 파일 범위 밖.
- `trace` 인자는 AI-LAB(관리자 실험 화면)이 "왜 이렇게 나왔는지"를 보기 위한 선택적 수집 통로다
  (모델·프롬프트·원본 응답·토큰·지연·정책 출처). None이면 아무것도 하지 않으므로 운영 경로는
  그대로다 — 응답 본문에 추적 정보를 섞지 않기 위해 반환값이 아니라 인자로 받는다.
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Literal

from openai import OpenAI
from pydantic import BaseModel

from app.config import settings
from app.mcp import tools
from app.schemas import Category, Evidence

if TYPE_CHECKING:
    from app.api.draft import DraftRequest, ReviseRequest

logger = logging.getLogger(__name__)

MODEL = "gpt-4o-mini"  # 키 권한에 따라 조정. model_not_found면 사용 가능 모델로 교체

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    # 지연 생성: 모듈 import 시점(=앱 기동 시점)에 키가 없어도 서비스 전체가 죽지 않게 한다.
    # OpenAI()는 api_key가 빈 문자열이면 생성자 단계에서 바로 예외를 던지므로, 그 예외를
    # run()/revise()의 try/except가 흡수할 수 있도록 호출 시점까지 생성을 미룬다.
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.openai_api_key)
    return _client


VALID_CATEGORIES = {"업무활성", "회의", "식대", "출장", "접대", "비품"}

# get_policy(Django 실연동, B-3)가 실패했을 때만 쓰는 최후 폴백값 — 정상 경로에서는 쓰이지 않는다.
FALLBACK_POLICY = {"limit": 30000, "required_evidence": ["영수증"]}


# ── LLM 구조화 출력 스키마(Structured Output) ─────────────────────────────
# API가 이 스키마를 강제하므로, category가 6개 밖 값으로 나오거나 필드가 빠지는 일 자체가 없다.

class LLMComment(BaseModel):
    icon: Literal["ai", "doc"]
    text: str


class LLMDraftOutput(BaseModel):
    category: Category
    merchantIndustry: str
    purpose: str
    confidence: float
    aiSuggested: bool
    comments: list[LLMComment]


class LLMReviseOutput(BaseModel):
    category: Category
    merchantIndustry: str
    purpose: str
    amount: int
    headcount: int
    evidence: Evidence
    confidence: float
    aiSuggested: bool
    changes: list[str]
    comments: list[LLMComment]


# ── 프롬프트 ────────────────────────────────────────────────────────────

SYSTEM_PROMPT_CREATE = """당신은 법인카드 정산 초안 작성 보조입니다.

반드시 지켜야 할 규칙:
1. 비용 분류(category)는 다음 6개 중 하나만 선택하세요: 업무활성, 회의, 식대, 출장, 접대, 비품.
2. 가맹점 업종(merchantIndustry)은 참고용 힌트일 뿐이며, 세무·회계 판단의 근거로 사용하지 마세요.
3. 판단 확신이 낮으면 aiSuggested를 true로 하고 confidence를 낮게(0.5 이하) 주세요.
   확신이 높으면 aiSuggested는 true로 유지하되(사람 확인 대상) confidence만 높게 주세요.
4. purpose(지출 목적)는 가맹점·금액·참석 인원 정보를 근거로 1~2문장으로 자연스럽게 작성하세요.
   참석 인원 정보가 없으면(0명) 인원수를 언급하지 말고 목적만 작성하세요.
5. 정책 한도·규정 문구는 절대 스스로 계산하거나 만들어내지 마세요. policyHints는 서버가 별도로 채웁니다."""

USER_PROMPT_TEMPLATE_CREATE = """가맹점: {merchant}
금액: {amount}원
일시: {ts}
카드구분: {card_type}
증빙 여부: {evidence}
참석 인원: {headcount}명 (0이면 정보 없음)"""

SYSTEM_PROMPT_REVISE = """당신은 법인카드 정산 초안 수정 보조입니다.
현재 초안 값과 사용자의 자연어 수정 지시가 함께 주어집니다.

반드시 지켜야 할 규칙:
1. 지시에 해당하는 항목만 수정하고, 언급되지 않은 항목은 현재 값을 그대로 유지하세요.
2. 비용 분류(category)를 바꾸는 경우 다음 6개 중 하나만 선택하세요: 업무활성, 회의, 식대, 출장, 접대, 비품.
3. 지시를 해석하지 못했다면 모든 값을 원래대로 유지하고, comments에 어떤 지시를 이해하지 못했는지 안내하세요.
4. changes에는 실제로 값이 바뀐 항목만 "필드명 → 새 값" 형태의 문장으로 나열하세요. 아무것도 안 바뀌었으면 빈 배열로 두세요.
5. 정책 한도·규정 문구는 절대 스스로 계산하거나 만들어내지 마세요."""

USER_PROMPT_TEMPLATE_REVISE = """현재 초안:
가맹점: {merchant}
금액: {amount}원
분류: {category}
지출 목적: {purpose}
증빙 여부: {evidence}
참석 인원: {headcount}명

사용자 지시: {instruction}"""


# ── 정책 힌트(get_policy 실연동, B-3) ──────────────────────────────────

def _resolve_policy(category: str, trace: dict | None = None) -> dict:
    """Django `Policy` 테이블 실조회(FastMCP get_policy 경유). 실패해도 절대 예외를 올리지 않는다."""
    try:
        policy = tools.get_policy(category)
        if policy.get("limit") is not None:
            if trace is not None:
                trace["policy"] = {"source": "core", "value": policy}
            return policy
        if trace is not None:
            trace["policy"] = {"source": "fallback", "reason": "limit이 비어 있음", "lookup": policy}
    except Exception as exc:  # noqa: BLE001  # Django 미기동·네트워크 오류 등
        logger.warning("get_policy(%s) 실패, 폴백 사용: %s", category, exc)
        if trace is not None:
            trace["policy"] = {"source": "fallback", "reason": f"{type(exc).__name__}: {exc}"}
    fallback = {"category": category, **FALLBACK_POLICY}
    if trace is not None:
        trace["policy"]["value"] = fallback
    return fallback


def _build_policy_hints(amount: int, evidence: str, category: str, trace: dict | None = None) -> list[dict]:
    """LLM이 지어내지 않고, 정책 숫자를 근거로 서버가 결정론적으로 생성(감사 가능성)."""
    policy = _resolve_policy(category, trace)
    limit = policy["limit"]
    hints = []
    if limit is not None and amount > limit:
        hints.append({
            "level": "warn" if evidence != "OK" else "info",
            "clause": f"POLICY-{category}",
            "text": f"{int(limit):,}원을 초과하면 증빙이 필요합니다.",
            "status": "증빙 첨부됨" if evidence == "OK" else "증빙 미첨부 → 첨부를 권장합니다.",
        })
    return hints


# ── OpenAI 호출 (Structured Output strict) ─────────────────────────────

def _record_call(trace: dict | None, system_prompt: str, user_prompt: str) -> None:
    if trace is not None:
        trace.update(model=MODEL, temperature=0.3, systemPrompt=system_prompt, userPrompt=user_prompt)


def _record_response(trace: dict | None, resp, started: float) -> None:
    """원본 응답·토큰·지연을 추적에 남긴다. 추적 수집이 본 호출을 깨뜨리지 않도록 전부 getattr."""
    if trace is None:
        return
    trace["latencyMs"] = round((time.perf_counter() - started) * 1000, 1)
    usage = getattr(resp, "usage", None)
    if usage is not None:
        trace["usage"] = {
            "promptTokens": getattr(usage, "prompt_tokens", None),
            "completionTokens": getattr(usage, "completion_tokens", None),
            "totalTokens": getattr(usage, "total_tokens", None),
        }
    message = resp.choices[0].message
    trace["rawOutput"] = getattr(message, "content", None)   # 구조화 출력 원본 JSON 문자열
    trace["refusal"] = getattr(message, "refusal", None)
    trace["finishReason"] = getattr(resp.choices[0], "finish_reason", None)


def _call_llm_create(req: "DraftRequest", trace: dict | None = None) -> LLMDraftOutput:
    user_prompt = USER_PROMPT_TEMPLATE_CREATE.format(
        merchant=req.merchant,
        amount=req.amount,
        ts=req.resolved_ts(),
        card_type=req.cardType,
        evidence=req.evidence or "OK",
        headcount=req.headcount or 0,
    )
    _record_call(trace, SYSTEM_PROMPT_CREATE, user_prompt)
    started = time.perf_counter()
    resp = _get_client().beta.chat.completions.parse(
        model=MODEL,
        temperature=0.3,
        timeout=15,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT_CREATE},
            {"role": "user", "content": user_prompt},
        ],
        response_format=LLMDraftOutput,
    )
    _record_response(trace, resp, started)
    parsed = resp.choices[0].message.parsed
    if parsed is None:
        raise ValueError("LLM이 구조화된 응답을 반환하지 않았습니다(모델 거부 등)")
    return parsed


def _call_llm_revise(req: "ReviseRequest", trace: dict | None = None) -> LLMReviseOutput:
    current = req.current
    user_prompt = USER_PROMPT_TEMPLATE_REVISE.format(
        merchant=current.merchant,
        amount=current.amount,
        category=current.category,
        purpose=current.purpose,
        evidence=current.evidence or "OK",
        headcount=current.headcount or 0,
        instruction=req.instruction,
    )
    _record_call(trace, SYSTEM_PROMPT_REVISE, user_prompt)
    started = time.perf_counter()
    resp = _get_client().beta.chat.completions.parse(
        model=MODEL,
        temperature=0.3,
        timeout=15,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT_REVISE},
            {"role": "user", "content": user_prompt},
        ],
        response_format=LLMReviseOutput,
    )
    _record_response(trace, resp, started)
    parsed = resp.choices[0].message.parsed
    if parsed is None:
        raise ValueError("LLM이 구조화된 응답을 반환하지 않았습니다(모델 거부 등)")
    return parsed


# ── 생성 모드 ───────────────────────────────────────────────────────────

def run(req: "DraftRequest", trace: dict | None = None) -> dict:
    """생성 모드 초안 작성. LLM 호출·응답 처리가 어떤 이유로 실패해도 항상 200 형태로 방어."""
    try:
        llm_out = _call_llm_create(req, trace)
        draft = {
            "merchant": req.merchant,
            "amount": req.amount,
            "category": llm_out.category,
            "aiCategory": llm_out.category,
            "aiSuggested": llm_out.aiSuggested,
            "merchantIndustry": llm_out.merchantIndustry,
            "purpose": llm_out.purpose,
            "evidence": req.evidence or "OK",
            "headcount": req.headcount or 0,
        }
        confidence = llm_out.confidence
        comments = [c.model_dump() for c in llm_out.comments]

    except Exception as exc:  # noqa: BLE001  # OpenAI 호출 실패·응답 처리 오류 등 전부 여기서 흡수
        if trace is not None:
            trace["error"] = f"{type(exc).__name__}: {exc}"
            trace["fallbackUsed"] = True
        comments = [{"icon": "ai", "text": f"LLM 호출/응답 처리에 실패해 기본값으로 채웠습니다: {exc}"}]
        draft = {
            "merchant": req.merchant,
            "amount": req.amount,
            "category": "업무활성",
            "aiCategory": "업무활성",
            "aiSuggested": True,
            "merchantIndustry": "",
            "purpose": f"{req.merchant} 관련 지출 (초안 자동 생성 실패)",
            "evidence": req.evidence or "OK",
            "headcount": req.headcount or 0,
        }
        confidence = 0.3

    return {
        "mode": "create",
        "draft": draft,
        "confidence": confidence,
        "comments": comments,
        "policyHints": _build_policy_hints(req.amount, req.evidence or "OK", draft["category"], trace),
    }


# ── 수정 모드 ───────────────────────────────────────────────────────────

def revise(req: "ReviseRequest", trace: dict | None = None) -> dict:
    """자연어 지시로 기존 초안을 수정. 실패 시 기존 값을 그대로 유지해 반환한다(추측으로 덮어쓰지 않음)."""
    current = req.current
    try:
        llm_out = _call_llm_revise(req, trace)
        draft = {
            "merchant": current.merchant,
            "amount": llm_out.amount,
            "category": llm_out.category,
            "aiCategory": llm_out.category,
            "aiSuggested": llm_out.aiSuggested,
            "merchantIndustry": llm_out.merchantIndustry,
            "purpose": llm_out.purpose,
            "evidence": llm_out.evidence,
            "headcount": llm_out.headcount,
        }
        confidence = llm_out.confidence
        changes = llm_out.changes
        comments = [c.model_dump() for c in llm_out.comments]

    except Exception as exc:  # noqa: BLE001
        if trace is not None:
            trace["error"] = f"{type(exc).__name__}: {exc}"
            trace["fallbackUsed"] = True
        comments = [{"icon": "ai", "text": f"지시를 반영하지 못해 기존 값을 그대로 유지했습니다: {exc}"}]
        draft = {
            "merchant": current.merchant,
            "amount": current.amount,
            "category": current.category,
            "aiCategory": current.aiCategory or current.category,
            "aiSuggested": True,
            "merchantIndustry": "",
            "purpose": current.purpose,
            "evidence": current.evidence or "OK",
            "headcount": current.headcount or 0,
        }
        confidence = 0.3
        changes = []

    return {
        "mode": "revise",
        "draft": draft,
        "confidence": confidence,
        "changes": changes,
        "comments": comments,
        "policyHints": _build_policy_hints(draft["amount"], draft["evidence"], draft["category"], trace),
    }

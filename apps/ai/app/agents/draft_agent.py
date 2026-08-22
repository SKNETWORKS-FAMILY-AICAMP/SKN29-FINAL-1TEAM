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
from typing import TYPE_CHECKING, Any, Literal

from functools import lru_cache

from openai import OpenAI
from pydantic import BaseModel, create_model

from app.agents import draft_facts
from app.clients import core_client
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


#  비용분류 어휘는 **core가 정본**이다(`settlements.Category`). 여기에 상수로 적어 두면
#  core가 분류를 늘려도 LLM이 새 값을 고를 수 없어 조용히 옛 목록만 돈다.
#  `UNSET`은 「아직 못 정했다」 — `기타`("나열된 어디에도 안 맞는다"는 확정)와 다르다.
#  화면은 이 값을 「선택 필요」로 띄우고, 판정은 `CATEGORY_MISSING`으로 검토에 넘긴다.
UNSET_CATEGORY = ""

# get_policy(Django 실연동, B-3)가 실패했을 때만 쓰는 최후 폴백값 — 정상 경로에서는 쓰이지 않는다.
FALLBACK_POLICY = {"limit": 30000, "required_evidence": ["영수증"]}


# ── LLM 구조화 출력 스키마(Structured Output) ─────────────────────────────
# API가 이 스키마를 강제하므로, category가 6개 밖 값으로 나오거나 필드가 빠지는 일 자체가 없다.

class LLMComment(BaseModel):
    icon: Literal["ai", "doc"]
    text: str


class LLMDraftOutput(BaseModel):
    category: Category
    purpose: str
    confidence: float
    aiSuggested: bool
    comments: list[LLMComment]


class LLMReviseOutput(BaseModel):
    category: Category
    purpose: str
    amount: int
    headcount: int
    evidence: Evidence
    confidence: float
    aiSuggested: bool
    changes: list[str]
    comments: list[LLMComment]


class FlagExplanation(BaseModel):
    """판정 플래그 하나에 대한 **사용자용 한 문장**.

    `code`는 서버가 준 목록에서만 고르게 하고, 목록 밖 코드는 서버가 버린다 —
    모델이 없는 사유를 만들어 안내하면 사용자는 있지도 않은 문제를 고치려 한다.
    """
    code: str
    text: str


class LLMSettlementDraftOutput(BaseModel):
    """정산 기반 초안 — **분류·목적·설명만** 낸다.

    가맹점·금액·일시·업종은 스키마에 아예 없다. 그것들은 ERP 수집·영수증 비전·카드 원장이
    이미 확정한 사실이라, 모델이 낼 수 있는 자리를 두면 언젠가 덮어쓴다(업종을 스키마에서
    뺀 것과 같은 이유 — `_resolve_industry` docstring).
    """
    category: Category
    purpose: str
    reasoning: str                       # 왜 이 분류·목적인지 사용자에게 하는 설명
    flagExplanations: list[FlagExplanation]


SYSTEM_PROMPT_SETTLEMENT = """당신은 법인카드 정산 초안 작성 보조입니다.
사용자가 지출 건을 올리면, 확정된 사실을 읽고 **비용 분류와 지출 목적**을 채우고
**왜 그렇게 했는지, 지금 제출하면 어떻게 되는지**를 사용자에게 설명합니다.

반드시 지켜야 할 규칙:
1. 비용 분류(category)는 다음 중 하나만 선택하세요: {categories}.
   - 지출 성격은 파악됐지만 나열된 분류 어디에도 맞지 않으면 "기타".
   - 주어진 사실로 판단할 수 없으면 **빈 문자열("")** 로 두세요. 추측하지 마세요.
2. **기본 내역(가맹점·금액·일시·업종·카드)은 확정된 사실입니다.** 다시 추측하거나
   바꾸려 하지 말고, 목적·설명을 쓸 때 근거로만 쓰세요.
3. **판정 결과를 스스로 계산하지 마세요.** 룰 엔진이 이미 판정했고 그 결과가 주어집니다.
   당신은 그 결과를 사용자가 알아들을 말로 옮기기만 합니다.
   - 판정이 REVIEW면 **정상입니다.** "회계 담당자가 직접 확인하는 건"이라고만 안내하고,
     문제가 있는 것처럼 쓰지 마세요.
   - 판정이 RETURN/REJECT면 지금 제출하면 되돌아온다는 뜻입니다. 무엇을 하면 해소되는지
     구체적으로 안내하세요(첨부 추가·인원 기재·목적 보완 등).
4. flagExplanations에는 **주어진 플래그 코드에 대해서만** 한 문장씩 쓰세요. 코드를
   지어내지 말고, 설명할 것이 없는 코드는 빼세요.
5. purpose(지출 목적)는 주어진 사실에 있는 내용만으로 1~2문장으로 쓰세요.
   참석자 수·거래처명처럼 **사실에 없는 정보를 채워 넣지 마세요.** 모르면 쓰지 않습니다.
6. reasoning은 사용자에게 하는 설명입니다. 내부 필드명(evidence.* 같은 dot-path)이나
   플래그 코드를 그대로 노출하지 말고 일상어로 쓰세요."""


# ── 분류 어휘 주입 — 구조화 출력 enum을 **런타임에 core 목록으로 다시 만든다** ─────────
#  위 두 모델의 `Category`(정적 미러)는 core 미기동 시 폴백이다. 정상 경로에서는
#  `_with_categories()`가 같은 모델을 core 어휘 + 빈 값으로 다시 찍어 `response_format`에
#  넘긴다 — 그래야 "분류가 늘었는데 모델이 그 값을 낼 방법이 없다"가 생기지 않는다.
#  (API가 enum을 강제하므로 목록 밖 값이 나오는 일 자체가 없다는 기존 성질은 그대로다.)


def category_values() -> list[str]:
    """core 정본 어휘. 조회 실패 시 정적 미러로 떨어진다(`core_client.get_categories`)."""
    return core_client.get_categories()


@lru_cache(maxsize=8)
def _with_categories(base: type[BaseModel], values: tuple[str, ...]) -> type[BaseModel]:
    #  빈 문자열을 enum에 포함시킨다 — 모델이 판단할 수 없을 때 **아무거나 고르는 대신**
    #  비워 둘 자리가 필요하다. 없으면 정보가 부족한 건도 반드시 하나를 찍게 되고,
    #  그 추측이 `ai_category`로 저장돼 사람에게는 "AI가 정했다"로 보인다.
    return create_model(
        f"{base.__name__}Runtime",
        __base__=base,
        category=(Literal[(UNSET_CATEGORY, *values)], ...),
    )


def _draft_output_model() -> type[BaseModel]:
    return _with_categories(LLMDraftOutput, tuple(category_values()))


def _revise_output_model() -> type[BaseModel]:
    return _with_categories(LLMReviseOutput, tuple(category_values()))


def _settlement_output_model() -> type[BaseModel]:
    return _with_categories(LLMSettlementDraftOutput, tuple(category_values()))


# ── 프롬프트 ────────────────────────────────────────────────────────────

#  분류 목록은 프롬프트에도 **런타임에 끼워 넣는다** — 스키마(enum)만 바꾸고 지시문에
#  옛 목록이 남아 있으면 모델이 "고를 수 있지만 고르면 안 되는 값"으로 취급한다.
SYSTEM_PROMPT_CREATE = """당신은 법인카드 정산 초안 작성 보조입니다.

반드시 지켜야 할 규칙:
1. 비용 분류(category)는 다음 중 하나만 선택하세요: {categories}.
   - 지출 성격은 파악됐지만 나열된 분류 어디에도 맞지 않으면 "기타"를 고르세요.
   - 주어진 정보로 지출 성격 자체를 판단할 수 없으면 **빈 문자열("")로 두세요.**
     추측해서 아무 분류나 고르지 마세요 — 비워 두면 사람이 직접 고릅니다.
2. 가맹점 업종은 **서버가 조회해 사용자 메시지로 함께 준다**. 주어진 값을 분류 판단의 근거로
   참고하되, 값이 "미확인"이면 업종을 추측하지 말고 다른 정보(가맹점명·금액·시간)만 쓰세요.
   업종은 보조 힌트일 뿐이라 세무·회계 판단의 근거로 삼지 마세요.
3. 판단 확신이 낮으면 aiSuggested를 true로 하고 confidence를 낮게(0.5 이하) 주세요.
   확신이 높으면 aiSuggested는 true로 유지하되(사람 확인 대상) confidence만 높게 주세요.
4. purpose(지출 목적)는 가맹점·금액·참석 인원 정보를 근거로 1~2문장으로 자연스럽게 작성하세요.
   참석 인원 정보가 없으면(0명) 인원수를 언급하지 말고 목적만 작성하세요.
5. 정책 한도·규정 문구는 절대 스스로 계산하거나 만들어내지 마세요. policyHints는 서버가 별도로 채웁니다."""

USER_PROMPT_TEMPLATE_CREATE = """가맹점: {merchant}
가맹점 업종(서버 조회): {industry}
금액: {amount}원
일시: {ts}
카드구분: {card_type}
증빙 여부: {evidence}
참석 인원: {headcount}명 (0이면 정보 없음)"""

SYSTEM_PROMPT_REVISE = """당신은 법인카드 정산 초안 수정 보조입니다.
현재 초안 값과 사용자의 자연어 수정 지시가 함께 주어집니다.

반드시 지켜야 할 규칙:
1. 지시에 해당하는 항목만 수정하고, 언급되지 않은 항목은 현재 값을 그대로 유지하세요.
2. 비용 분류(category)를 바꾸는 경우 다음 중 하나만 선택하세요: {categories}.
   나열된 어디에도 맞지 않으면 "기타", 판단할 수 없으면 빈 문자열("")로 두세요.
3. 지시를 해석하지 못했다면 모든 값을 원래대로 유지하고, comments에 어떤 지시를 이해하지 못했는지 안내하세요.
4. changes에는 실제로 값이 바뀐 항목만 "필드명 → 새 값" 형태의 문장으로 나열하세요. 아무것도 안 바뀌었으면 빈 배열로 두세요.
5. 정책 한도·규정 문구는 절대 스스로 계산하거나 만들어내지 마세요."""

USER_PROMPT_TEMPLATE_REVISE = """현재 초안:
가맹점: {merchant}
가맹점 업종(서버 조회): {industry}
금액: {amount}원
분류: {category}
지출 목적: {purpose}
증빙 여부: {evidence}
참석 인원: {headcount}명

사용자 지시: {instruction}"""


# ── 가맹점 업종(classify_merchant 실연동) ──────────────────────────────

def _resolve_industry(merchant: str, place_hint: str | None, trace: dict | None = None) -> dict:
    """가맹점 업종을 **서버가 조회해** 초안에 넣는다(§7-1).

    예전엔 이 값을 LLM 출력 스키마(`merchantIndustry`)로 받았다 — 모델이 가맹점명만 보고
    지어낸 문자열이 그대로 화면에 뜨고 `Settlement.merchant_industry`에 저장돼
    `merchant.merchant_type` 판정 사실이 됐다. 조회 결과가 있는데도 추측을 쓸 이유가 없고,
    무엇보다 자유 문자열이라 룰의 `in [...]` 비교에 걸릴 수가 없었다(정본 어휘가 아니다).

    실패·미확정이면 빈 값이다 — 업종은 보조 힌트라 없어도 초안 작성은 계속된다.
    """
    try:
        result = tools.classify_merchant(merchant, place_hint)
    except Exception as exc:  # noqa: BLE001  # core 미기동·카카오 장애 등
        logger.warning("classify_merchant(%r) 실패, 업종 미확정: %s", merchant, exc)
        if trace is not None:
            trace["industry"] = {"source": "unresolved", "reason": f"{type(exc).__name__}: {exc}"}
        return {"industry_code": "", "industry_label": "", "confidence": 0.0, "source": ""}
    if trace is not None:
        trace["industry"] = {"source": result.get("source") or "unresolved", "value": result}
    return result


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
    if not category:
        #  분류가 아직 없으면 안내할 임계값 자체가 정해지지 않는다 — 조회 URL도 성립하지
        #  않고(`/api/internal/policies//`), "POLICY-" 같은 빈 근거를 화면에 띄우게 된다.
        return []
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


def _system_prompt(template: str) -> str:
    """지시문에 현재 분류 어휘를 끼워 넣는다(스키마와 같은 목록을 본다)."""
    return template.format(categories=", ".join(category_values()))


def _call_llm_create(req: "DraftRequest", industry: str, trace: dict | None = None) -> LLMDraftOutput:
    system_prompt = _system_prompt(SYSTEM_PROMPT_CREATE)
    user_prompt = USER_PROMPT_TEMPLATE_CREATE.format(
        merchant=req.merchant,
        industry=industry or "미확인",
        amount=req.amount,
        ts=req.resolved_ts(),
        card_type=req.cardType,
        evidence=req.evidence or "OK",
        headcount=req.headcount or 0,
    )
    _record_call(trace, system_prompt, user_prompt)
    started = time.perf_counter()
    resp = _get_client().beta.chat.completions.parse(
        model=MODEL,
        temperature=0.3,
        timeout=15,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format=_draft_output_model(),
    )
    _record_response(trace, resp, started)
    parsed = resp.choices[0].message.parsed
    if parsed is None:
        raise ValueError("LLM이 구조화된 응답을 반환하지 않았습니다(모델 거부 등)")
    return parsed


def _call_llm_revise(req: "ReviseRequest", industry: str, trace: dict | None = None) -> LLMReviseOutput:
    current = req.current
    system_prompt = _system_prompt(SYSTEM_PROMPT_REVISE)
    user_prompt = USER_PROMPT_TEMPLATE_REVISE.format(
        merchant=current.merchant,
        industry=industry or "미확인",
        amount=current.amount,
        category=current.category,
        purpose=current.purpose,
        evidence=current.evidence or "OK",
        headcount=current.headcount or 0,
        instruction=req.instruction,
    )
    _record_call(trace, system_prompt, user_prompt)
    started = time.perf_counter()
    resp = _get_client().beta.chat.completions.parse(
        model=MODEL,
        temperature=0.3,
        timeout=15,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format=_revise_output_model(),
    )
    _record_response(trace, resp, started)
    parsed = resp.choices[0].message.parsed
    if parsed is None:
        raise ValueError("LLM이 구조화된 응답을 반환하지 않았습니다(모델 거부 등)")
    return parsed


# ── 생성 모드 ───────────────────────────────────────────────────────────

def run(req: "DraftRequest", trace: dict | None = None) -> dict:
    """생성 모드 초안 작성. LLM 호출·응답 처리가 어떤 이유로 실패해도 항상 200 형태로 방어.

    업종은 LLM보다 **먼저** 조회한다 — 분류 판단의 입력이기 때문이다(뒤에 붙이면 그냥 표시용).
    """
    industry = _resolve_industry(req.merchant, req.placeHint, trace)
    try:
        llm_out = _call_llm_create(req, industry["industry_label"], trace)
        draft = {
            "merchant": req.merchant,
            "amount": req.amount,
            "category": llm_out.category,
            "aiCategory": llm_out.category,
            "aiSuggested": llm_out.aiSuggested,
            "merchantIndustry": industry["industry_label"],
            "merchantIndustryCode": industry["industry_code"],
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
        #  **실패했을 때 분류를 지어내지 않는다.** 예전엔 "비품"으로 채웠는데, 사용자에게는
        #  AI가 판단한 값과 구분되지 않아 그대로 확정되곤 했다(비품은 자기 예산·룰을 가진
        #  실제 과목이다). 비워 두면 화면이 「선택 필요」로 띄우고 판정이 검토로 보낸다.
        comments = [{"icon": "ai", "text": f"LLM 호출/응답 처리에 실패해 비용분류를 비워 두었습니다 — 직접 골라주세요: {exc}"}]
        draft = {
            "merchant": req.merchant,
            "amount": req.amount,
            "category": UNSET_CATEGORY,
            "aiCategory": UNSET_CATEGORY,
            "aiSuggested": True,
            # 업종 조회는 LLM과 별개 경로라 살아 있다 — 초안이 실패해도 이건 버리지 않는다.
            "merchantIndustry": industry["industry_label"],
            "merchantIndustryCode": industry["industry_code"],
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
    # 수정 모드에선 화면에 이미 떠 있는 업종을 그대로 쓴다 — 사용자가 금액·인원을 고치는
    # 동안 업종이 바뀔 이유가 없고, 매 수정마다 카카오·LLM을 다시 부르면 비용만 는다.
    # 화면 값이 비어 있을 때만(첫 조회 실패 등) 다시 조회한다.
    industry = {"industry_label": current.merchantIndustry, "industry_code": current.merchantIndustryCode}
    if not industry["industry_label"]:
        industry = _resolve_industry(current.merchant, None, trace)
    try:
        llm_out = _call_llm_revise(req, industry["industry_label"], trace)
        draft = {
            "merchant": current.merchant,
            "amount": llm_out.amount,
            "category": llm_out.category,
            "aiCategory": llm_out.category,
            "aiSuggested": llm_out.aiSuggested,
            "merchantIndustry": industry["industry_label"],
            "merchantIndustryCode": industry["industry_code"],
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
            "merchantIndustry": industry["industry_label"],
            "merchantIndustryCode": industry["industry_code"],
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


# ── 정산 기반 초안 (settlement 모드) ────────────────────────────────────
#
# 기존 폼 기반 모드(`run`/`revise`)와의 차이는 "무엇을 사실로 받는가"다. 폼 모드는
# 사용자가 타이핑한 가맹점·금액만 봤고, 그래서 모델이 지어낼 수 있는 자리가 넓었다.
# 이 모드는 core `draft_context`가 조립한 사실 묶음(기본 내역·첨부 추출·EvalContext·
# **엔진 판정 미리보기**·보완요청 맥락)을 받는다.
#
# 판정을 LLM이 예측하지 않는다는 것이 이 모드의 핵심이다 — 자세한 근거는
# core `domain/settlements/draft_context.py` 모듈 docstring 참조.

def _notice_level(decision: str, flag: dict) -> str:
    """안내 등급. **판정이 정하고 플래그가 이유를 댄다.**

    REVIEW를 경고로 올리지 않는 이유: 룰이 자동 판단하지 않고 회계가 보는 것뿐이라
    지출자가 고칠 것이 없다. 여기서 경고를 띄우면 정상 건마다 사용자가 멈춰 선다.
    """
    if decision in draft_facts.BLOCKING_DECISIONS:
        return "blocker"
    if decision == "REVIEW":
        return "info"
    return "info"


def _build_notices(ctx: dict, explanations: list) -> list[dict]:
    """LLM 문장 + 엔진 사실을 합쳐 안내 목록을 만든다.

    **코드는 서버가 정하고 문장만 LLM에서 받는다.** 모델이 코드를 지어내면 사용자는
    있지도 않은 문제를 고치려 한다 — 목록 밖 코드는 버린다.
    설명이 안 온 플래그는 등록된 `description`으로 채운다(빈손으로 두지 않는다).
    """
    judgement = ctx.get("judgement") or {}
    decision = judgement.get("decision") or ""
    by_code = {e.code: e.text for e in explanations if getattr(e, "code", "")}

    notices = []
    for flag in judgement.get("flags") or []:
        code = flag.get("code")
        if not code:
            continue
        notices.append({
            "level": _notice_level(decision, flag),
            "code": code,
            "label": flag.get("label") or code,
            "severity": flag.get("severityLabel") or flag.get("severity") or "",
            "owner": flag.get("ownerLabel") or flag.get("owner") or "",
            "text": by_code.get(code) or flag.get("description") or flag.get("label") or code,
        })

    dropped = sorted(set(by_code) - {n["code"] for n in notices})
    if dropped:
        logger.info("모델이 목록 밖 플래그 코드를 설명했다(버림): %s", dropped)
    return notices


def _judgement_summary(ctx: dict) -> dict:
    """화면이 그대로 쓸 판정 요약 — LLM을 거치지 않은 엔진 원본."""
    j = ctx.get("judgement") or {}
    return {
        "available": bool(j.get("available")),
        "decision": j.get("decision") or "",
        "blocking": bool(j.get("blocking")),
        "scope": j.get("scope") or "",
        "graphs": j.get("graphs") or [],
        "error": j.get("error") or "",
    }


def _call_llm_settlement(ctx: dict, instruction: str, trace: dict | None) -> Any:
    system_prompt = _system_prompt(SYSTEM_PROMPT_SETTLEMENT)
    user_prompt = draft_facts.render(ctx)
    if instruction:
        user_prompt += (
            f"\n\n[사용자 지시]\n{instruction}\n"
            "→ 지시에 해당하는 항목만 고치고, 나머지는 현재 값을 유지하라. "
            "지시가 사실과 어긋나면(없는 참석자 수를 넣으라는 등) 따르지 말고 그 이유를 reasoning에 적어라."
        )
    _record_call(trace, system_prompt, user_prompt)
    started = time.perf_counter()
    resp = _get_client().beta.chat.completions.parse(
        model=MODEL,
        temperature=0.3,
        timeout=25,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format=_settlement_output_model(),
    )
    _record_response(trace, resp, started)
    parsed = resp.choices[0].message.parsed
    if parsed is None:
        raise ValueError("LLM이 구조화된 응답을 반환하지 않았습니다(모델 거부 등)")
    return parsed


def run_for_settlement(settlement_id: int, instruction: str = "", trace: dict | None = None) -> dict:
    """저장된 정산 한 건으로 초안을 만든다.

    **사실 조회 실패는 감추지 않는다.** 사실 없이 초안을 쓰면 모델이 폼 값만 보고 그럴듯한
    문장을 만들던 상태로 되돌아가는데, 그건 실패보다 나쁘다(사용자는 성공으로 읽는다).
    LLM 호출 실패는 흡수하되 분류를 지어내지 않고 비워 둔다.
    """
    ctx = core_client.get_draft_context(settlement_id)
    if trace is not None:
        trace["draftContext"] = ctx

    current = ctx.get("current") or {}
    judgement = _judgement_summary(ctx)

    try:
        out = _call_llm_settlement(ctx, instruction.strip(), trace)
        return {
            "mode": "settlement",
            "settlementId": settlement_id,
            "draft": {
                "category": out.category,
                "purpose": out.purpose,
                #  기본 내역은 **되돌려 보내기만** 한다 — 화면이 다시 그리는 값이고
                #  모델은 이 자리에 아무것도 쓸 수 없다(스키마에 없다).
                **(ctx.get("basics") or {}),
            },
            "reasoning": out.reasoning,
            "notices": _build_notices(ctx, out.flagExplanations),
            "judgement": judgement,
            "returnContext": ctx.get("returnContext"),
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("정산 초안 생성 실패(settlement=%s)", settlement_id)
        if trace is not None:
            trace["error"] = f"{type(exc).__name__}: {exc}"
            trace["fallbackUsed"] = True
        return {
            "mode": "settlement",
            "settlementId": settlement_id,
            "draft": {
                "category": current.get("category") or "",
                "purpose": current.get("purpose") or "",
                **(ctx.get("basics") or {}),
            },
            "reasoning": f"초안을 생성하지 못했습니다 — 분류와 목적을 직접 입력해 주세요. ({type(exc).__name__})",
            #  LLM이 없어도 **판정 사유는 그대로 안내한다** — 등록된 설명이 있으므로
            #  빈손으로 두지 않는다(사유 코드를 펴는 것이지 지어내는 게 아니다).
            "notices": _build_notices(ctx, []),
            "judgement": judgement,
            "returnContext": ctx.get("returnContext"),
        }

"""③ Risk Review Agent — MVP 2단계 (요구사항 §5.5 / 기술명세서 §4.3).

  [1차] 단순 이상거래 탐지(비지도) → anomaly_score + feature_contribs
  [2차] RAG 내규 기반 검증(컷오프 없이 IN_REVIEW 전건 대상, v0) → 내규 위반 여부 + 권장의견(출처 포함)

※ 지도학습(review_probability)·자동 재학습 피드백 루프는 post-MVP 확장.
  회계 결정(decision_labels)은 MVP에선 '적재만'.
  FastAPI는 확정 데이터를 소유하지 않는다 — 이 모듈은 응답만 만들고, 저장은 Django(judge 액션)가 한다.
"""
from __future__ import annotations

import logging
import time
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel

from app.clients import core_client
from app.config import settings
from app.mcp import tools
from app.ml.registry import get_active_model

logger = logging.getLogger(__name__)

MODEL = "gpt-4o-mini"

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.openai_api_key)
    return _client


# ── LLM 구조화 출력 스키마(Structured Output) ─────────────────────────────

class Citation(BaseModel):
    doc: str
    article: str
    quote_summary: str


class SimilarCase(BaseModel):
    case_id: str
    outcome: str
    relevance: str


class RiskVerdict(BaseModel):
    violation_verdict: Literal["VIOLATION", "NO_VIOLATION", "INSUFFICIENT_INFO"]
    review_reasons: list[str]
    recommendation: Literal["APPROVE", "SUPPLEMENT", "REJECT"]
    citations: list[Citation]
    similar_cases: list[SimilarCase]


# ── 프롬프트 ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """당신은 법인카드 정산 Risk Review의 2차(내규 검증) 담당입니다.
1차 비지도 이상탐지가 이상 후보로 올린 건에 대해, 아래에 주어지는 근거(규정 조항 발췌·유사 과거
사례)만 사용해 내규 위반 여부를 판단하세요.

반드시 지켜야 할 규칙:
1. 출처 표기는 반드시 「문서명」제N조(조항 제목) 전체 형식으로만 인용하세요. "제11조" 처럼
   조 번호만 쓰거나 문서명을 생략하는 축약 인용은 금지합니다. 근거로 주어진 청크의 citation
   문자열을 그대로 doc/article에 나눠 담고, quote_summary는 해당 조항 내용을 1문장으로 요약하세요.
2. 아래 "근거"에 없는 규정·조항·수치를 스스로 만들어내지 마세요. 근거가 없으면 citations를
   빈 배열로 두세요.
3. 검색된 근거로 위반/비위반을 판단할 수 없으면 violation_verdict를 절대 VIOLATION이나
   NO_VIOLATION으로 억지로 결론짓지 말고 INSUFFICIENT_INFO를 반환하세요.
   - "정보가 없어서 검토 필요"(근거 자체가 검색되지 않음)와 "판단이 애매해서 검토 필요"
     (근거는 있으나 이 사안에 명확히 적용되지 않음)는 서로 다른 상황입니다. review_reasons에
     이 둘을 구분해서 서술하세요(예: "정보 없음: policy_docs에서 해당 지출 유형 관련 조항이
     검색되지 않았습니다" vs "판단 보류: 제12조가 있으나 이 건의 구체 상황(공용카드 실사용자
     미기재)까지는 다루지 않습니다").
4. 세법(tax_refs) 판단은 요구하지 않습니다 — 이 검증은 policy_docs(사내 규정)와 case_history
   (과거 유사 사례)만 근거로 사용하고, 세무상 손금 처리 여부 등은 판단하지 마세요.
5. recommendation은 violation_verdict가 VIOLATION이면 REJECT 또는 SUPPLEMENT(보완요청) 중
   사안의 심각도에 맞게, NO_VIOLATION이면 APPROVE, INSUFFICIENT_INFO면 사람 판단이 필요하므로
   원칙적으로 SUPPLEMENT를 선택하세요."""

USER_PROMPT_TEMPLATE = """[1차 이상탐지 결과]
anomaly_score: {anomaly_score:.3f}
튀는 피처(근사 기여도): {contribs}

[검토 대상 거래]
가맹점: {merchant}
금액: {amount}원
분류: {category}
지출 목적: {purpose}

[근거 — policy_docs 검색 결과]
{policy_chunks}

[근거 — case_history 검색 결과(유사 과거 사례)]
{cases}"""


def _format_chunks(chunks: list[dict]) -> str:
    if not chunks:
        return "(검색 결과 없음)"
    return "\n".join(f"- {c['citation']}: {c['text'][:400]}" for c in chunks)


def _format_cases(cases: list[dict]) -> str:
    if not cases:
        return "(검색 결과 없음)"
    return "\n".join(f"- [{c['outcome']}] {c['citation']}: {c['text'][:300]}" for c in cases)


def _build_query(category: str, merchant: str, contribs: list[dict]) -> str:
    feature_hint = " ".join(c["feature"] for c in contribs)
    return f"{category} {merchant} {feature_hint}".strip()


def _stage1(tx_id: int) -> dict:
    """1차 이상탐지: get_tx_features → ml_infer. 모델 미학습이면 stub 그대로 통과."""
    features = tools.get_tx_features(tx_id)
    model = get_active_model()
    if not model or not model.fitted:
        return {"anomaly_score": 0.0, "is_outlier": False, "contribs": [], "note": "no trained model (stub)"}
    return tools.ml_infer(features["feature_vector"])


def _stage2(summary: dict, stage1: dict) -> dict:
    """2차 RAG 내규 검증. search_policy/search_cases 근거 + LLM structured output."""
    contribs = stage1.get("contribs", [])
    query = _build_query(summary["category"], summary["merchant"], contribs)

    policy_hits = tools.search_policy(query)["chunks"]
    case_hits = tools.search_cases(query)["similar_cases"]

    user_prompt = USER_PROMPT_TEMPLATE.format(
        anomaly_score=stage1.get("anomaly_score", 0.0),
        contribs=", ".join(f"{c['feature']}({c['weight']})" for c in contribs) or "(없음)",
        merchant=summary["merchant"],
        amount=summary["amount"],
        category=summary["category"],
        purpose=summary.get("purpose") or "(미기재)",
        policy_chunks=_format_chunks(policy_hits),
        cases=_format_cases(case_hits),
    )

    resp = _get_client().beta.chat.completions.parse(
        model=MODEL,
        temperature=0.2,
        timeout=30,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        response_format=RiskVerdict,
    )
    parsed = resp.choices[0].message.parsed
    if parsed is None:
        return {
            "violation_verdict": "INSUFFICIENT_INFO",
            "review_reasons": ["LLM이 구조화된 응답을 반환하지 않았습니다(모델 거부 등) — 사람 검토 필요"],
            "recommendation": "SUPPLEMENT",
            "citations": [],
            "similar_cases": [],
        }
    return parsed.model_dump()


def run(settlement_id: int) -> dict:
    try:
        summary = core_client.get_settlement_summary(settlement_id)
    except Exception as exc:  # noqa: BLE001  # Django 미기동 등 — 1차만이라도 stub으로 응답
        logger.warning("get_settlement_summary(%s) 실패: %s", settlement_id, exc)
        return {
            "settlement_id": settlement_id,
            "stage1_anomaly": {"anomaly_score": 0.0, "is_outlier": False, "contribs": [], "note": "stub"},
            "stage2_rag_review": {
                "violation_verdict": "INSUFFICIENT_INFO",
                "review_reasons": [f"정산 조회 실패: {type(exc).__name__}"],
                "recommendation": "SUPPLEMENT", "citations": [], "similar_cases": [],
            },
            "status": "error",
        }

    stage1 = _stage1(summary["tx_id"])
    stage2 = _stage2(summary, stage1)

    return {
        "settlement_id": settlement_id,
        "stage1_anomaly": stage1,
        "stage2_rag_review": stage2,
        "status": "ok",
    }

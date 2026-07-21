"""② Rule Agent — 생성/검증/적용 (기술명세서 §4.2).

- 생성: RAG로 조항 추출 → LLM이 Rule 초안(condition+action), status=DRAFT
- 검증: 과거 거래 시뮬레이션 → 매칭/오탐율/검토감소량
- 적용: 결정론적 엔진 1차 판정(θ_pass/θ_reject). LLM은 생성 단계에서만.
스캐폴드: stub 반환.
"""


def generate(doc_query: str | None = None) -> dict:
    return {"doc_query": doc_query, "rule_draft": None, "status": "DRAFT (stub)"}


def validate() -> dict:
    return {"matched": 0, "false_positive_rate": None, "review_reduction": None, "status": "stub"}


def apply(settlement_id: int) -> dict:
    # decision ∈ {PASS, REJECT, NEEDS_REVIEW}. NEEDS_REVIEW는 Risk Review로 이관.
    return {"settlement_id": settlement_id, "decision": None, "confidence": 0.0, "status": "stub"}

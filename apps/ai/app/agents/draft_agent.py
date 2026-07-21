"""① 초안 작성 Agent (기술명세서 §4.1).

거래·영수증 → 분류·증빙매칭·규정힌트 초안 자동 완성.
- OpenAI 비전으로 영수증 필드 직접 추출(별도 OCR 없음)
- get_policy / get_card_context (FastMCP) 로 규정·카드컨텍스트 조회
스캐폴드: stub 반환.
"""


def run(settlement_id: int) -> dict:
    # TODO: 비전 판독 + 분류 추론 + get_policy/get_card_context
    return {
        "settlement_id": settlement_id,
        "category": None,
        "matched_receipt": None,
        "missing_evidence": [],
        "policy_hints": [],
        "status": "stub",
    }

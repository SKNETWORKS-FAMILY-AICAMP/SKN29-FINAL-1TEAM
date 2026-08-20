"""Risk Review stage2 프롬프트 조립 회귀 — `agents/risk_review_agent.py`.

두 가지를 검증한다(둘 다 네트워크 호출 없이, 순수 함수만):

1. `_format_chunks`: 검색(`search_policy`)은 항상 `parent_text`(같은 조 전문)를 함께
   돌려주는데, 이 함수가 그걸 버리고 잎 청크만 LLM에 넘기고 있었다 — 긴 조는 항 단위로
   쪼개져 검색되므로, 잎 하나만 보이면 같은 조의 다른 항이 통째로 안 보인다.
   `rule_agent_v0/agent.py::_format_chunks`는 이미 부모를 붙이고 있어 그 계약과 맞춘다.
2. `_build_user_prompt`: `build_query()`(검색어 조립)는 `facts_nl()`로 Settlement 판정필드
   (headcount·preApproved 등)를 검색어에 녹이는데, 정작 최종 판정 프롬프트(`USER_PROMPT_TEMPLATE`)엔
   그 사실이 전달되지 않고 있었다 — 검색은 "참석 인원 2명"을 알고 찾아오는데 판정 LLM은 그
   사실 자체를 모르는 불일치. 실측(2026-08-19, 실 Chroma+OpenAI)으로 확인 후 `facts` 필드를
   템플릿에 추가했다.
"""
from __future__ import annotations

from app.agents.risk_review_agent import _build_user_prompt, _format_chunks


def test_format_chunks_includes_parent_text_when_present():
    chunks = [{
        "citation": "업무추진비_사용규정 제6조 제6~7항",
        "text": "6. 청탁금지법 적용대상자 접대 시 사전 확인 절차를 거친다. 7. 위반 시 정산이 거부된다.",
        "parent_text": (
            "1. 기업업무추진비는 사업 관련성이 있는 거래처·고객 접대에 한해 사용한다. "
            "... 6. 청탁금지법 적용대상자 접대 시 사전 확인 절차를 거친다. "
            "7. 위반 시 정산이 거부된다."
        ),
    }]
    out = _format_chunks(chunks)
    assert "같은 조 전문" in out
    assert "사업 관련성이 있는 거래처" in out  # 잎에는 없고 부모에만 있는 내용


def test_format_chunks_cites_the_leaf_not_the_parent():
    """부모를 인용하면 「제N조」통째로가 근거로 찍혀 근거가 뭉툭해진다 — 인용은 잎의 citation."""
    chunks = [{
        "citation": "업무추진비_사용규정 제6조 제6~7항",
        "text": "7. 위반 시 정산이 거부된다.",
        "parent_text": "1. 기업업무추진비는... 7. 위반 시 정산이 거부된다.",
    }]
    out = _format_chunks(chunks)
    assert "제6조 제6~7항" in out
    assert "인용은 위 citation을 쓸 것" in out


def test_format_chunks_omits_parent_block_when_leaf_is_the_whole_article():
    """parent_text == text(짧은 조라 안 쪼개진 경우)면 중복으로 안 붙인다."""
    chunks = [{
        "citation": "법인카드_사용규정 제1조",
        "text": "이 규정은 법인카드 사용에 관한 사항을 정한다.",
        "parent_text": "이 규정은 법인카드 사용에 관한 사항을 정한다.",
    }]
    out = _format_chunks(chunks)
    assert "같은 조 전문" not in out


def test_format_chunks_omits_parent_block_when_parent_text_missing():
    """검색 결과에 parent_text가 없는(빈 문자열) 경우도 안전하게 처리한다."""
    chunks = [{"citation": "출장비_사용규정 제3조", "text": "출장 신청은 사전에 한다.", "parent_text": ""}]
    out = _format_chunks(chunks)
    assert "같은 조 전문" not in out
    assert "출장 신청은 사전에 한다." in out


def test_format_chunks_caps_length_to_avoid_runaway_prompt():
    """조 전문이 아무리 길어도 프롬프트가 폭주하지 않게 잘린다(잎 400 + 부모 800 상한)."""
    chunks = [{"citation": "테스트", "text": "짧은 잎", "parent_text": "가" * 5000}]
    result = _format_chunks(chunks)
    assert len(result) < 1300


def test_format_chunks_empty_list_unchanged():
    assert _format_chunks([]) == "(검색 결과 없음)"


def test_build_user_prompt_includes_settlement_facts():
    """headcount 등 판정필드가 검색 쿼리뿐 아니라 최종 판정 프롬프트에도 실려야 한다."""
    summary = {"category": "회식", "merchant": "강남모던바", "amount": 90000,
               "purpose": None, "headcount": 2, "preApproved": False}
    stage1 = {"anomaly_score": 0.12, "contribs": []}
    prompt = _build_user_prompt(summary, stage1, policy_hits=[], case_hits=[])

    assert "참석 인원 2명" in prompt
    assert "사전승인 받지 않음" in prompt


def test_build_user_prompt_omits_unknown_facts_instead_of_inventing_them():
    """None은 '모름'이지 '아니오'가 아니다 — facts_nl 계약을 그대로 이어받는다."""
    summary = {"category": "출장", "merchant": "OO호텔", "amount": 300000, "purpose": "출장 숙박"}
    stage1 = {"anomaly_score": 0.0, "contribs": []}
    prompt = _build_user_prompt(summary, stage1, policy_hits=[], case_hits=[])

    assert "거래 사실: (없음)" in prompt


def test_build_user_prompt_still_includes_anomaly_and_chunks():
    summary = {"category": "업무추진비", "merchant": "한정식당", "amount": 500000, "purpose": None}
    stage1 = {"anomaly_score": 0.87, "contribs": [{"feature": "카드첫거래여부", "weight": 1.0}]}
    policy_hits = [{"citation": "업무추진비_사용규정 제9조", "text": "청탁금지법 한도 초과 금지"}]
    prompt = _build_user_prompt(summary, stage1, policy_hits, case_hits=[])

    assert "anomaly_score: 0.870" in prompt
    assert "카드첫거래여부(1.0)" in prompt
    assert "업무추진비_사용규정 제9조" in prompt

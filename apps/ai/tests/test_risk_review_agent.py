"""Risk Review ①분류 프롬프트 조립 회귀 — `agents/risk_review_agent.py`.

두 가지를 검증한다(둘 다 네트워크 호출 없이, 순수 함수만):

1. `_format_policy_chunks`: 검색(`search_policy`)은 항상 `parent_text`(같은 조 전문)를 함께
   돌려주는데, 이 함수가 그걸 버리고 잎 청크만 LLM에 넘기면 긴 조는 항 단위로 쪼개져
   검색되므로 같은 조의 다른 항이 통째로 안 보이게 된다. `rule_agent_v0/agent.py::_format_chunks`
   와 동일 계약(부모 첨부, 인용은 잎의 citation).
2. `_build_classify_prompt`: `build_query()`(검색어 조립)는 `facts_nl()`로 Settlement 판정필드
   (headcount·preApproved 등)를 검색어에 녹이는데, 최종 분류 프롬프트에도 그 사실이 실려야
   한다 — 검색은 "참석 인원 2명"을 알고 찾아오는데 분류 LLM은 그 사실 자체를 모르는 불일치를
   막기 위해 `_CLASSIFY_USER_PROMPT_TEMPLATE`에 `facts` 필드가 있다(main 병합분 c605e99/21ffe4f,
   v1 MCP 툴콜링 재작성 위에도 동일하게 적용).

v0 시절 이 파일이 테스트하던 `_format_chunks`/`_build_user_prompt`는 v1에서 각각
`_format_policy_chunks`/`_build_classify_prompt`로 이름·시그니처가 바뀌었다(분류/액션
단계 분리, MCP 툴콜링 루프 재작성 — `risk-review-agent-v1-implementation.md` 참조).
"""
from __future__ import annotations

from unittest.mock import patch

from app.agents import risk_review_agent as agent
from app.agents.risk_review_agent import (
    _build_classify_prompt,
    _decide_action,
    _format_case_hits,
    _format_policy_chunks,
    _risk_tier,
    _safe_search,
    _stage1,
)


def test_format_policy_chunks_includes_parent_text_when_present():
    chunks = [{
        "citation": "업무추진비_사용규정 제6조 제6~7항",
        "text": "6. 청탁금지법 적용대상자 접대 시 사전 확인 절차를 거친다. 7. 위반 시 정산이 거부된다.",
        "parent_text": (
            "1. 기업업무추진비는 사업 관련성이 있는 거래처·고객 접대에 한해 사용한다. "
            "... 6. 청탁금지법 적용대상자 접대 시 사전 확인 절차를 거친다. "
            "7. 위반 시 정산이 거부된다."
        ),
    }]
    out = _format_policy_chunks(chunks)
    assert "같은 조 전문" in out
    assert "사업 관련성이 있는 거래처" in out  # 잎에는 없고 부모에만 있는 내용


def test_format_policy_chunks_cites_the_leaf_not_the_parent():
    """부모를 인용하면 「제N조」통째로가 근거로 찍혀 근거가 뭉툭해진다 — 인용은 잎의 citation."""
    chunks = [{
        "citation": "업무추진비_사용규정 제6조 제6~7항",
        "text": "7. 위반 시 정산이 거부된다.",
        "parent_text": "1. 기업업무추진비는... 7. 위반 시 정산이 거부된다.",
    }]
    out = _format_policy_chunks(chunks)
    assert "제6조 제6~7항" in out
    assert "인용은 위 citation을 쓸 것" in out


def test_format_policy_chunks_omits_parent_block_when_leaf_is_the_whole_article():
    """parent_text == text(짧은 조라 안 쪼개진 경우)면 중복으로 안 붙인다."""
    chunks = [{
        "citation": "법인카드_사용규정 제1조",
        "text": "이 규정은 법인카드 사용에 관한 사항을 정한다.",
        "parent_text": "이 규정은 법인카드 사용에 관한 사항을 정한다.",
    }]
    out = _format_policy_chunks(chunks)
    assert "같은 조 전문" not in out


def test_format_policy_chunks_omits_parent_block_when_parent_text_missing():
    """검색 결과에 parent_text가 없는(빈 문자열) 경우도 안전하게 처리한다."""
    chunks = [{"citation": "출장비_사용규정 제3조", "text": "출장 신청은 사전에 한다.", "parent_text": ""}]
    out = _format_policy_chunks(chunks)
    assert "같은 조 전문" not in out
    assert "출장 신청은 사전에 한다." in out


def test_format_policy_chunks_caps_length_to_avoid_runaway_prompt():
    """조 전문이 아무리 길어도 프롬프트가 폭주하지 않게 잘린다(잎 400 + 부모 800 상한)."""
    chunks = [{"citation": "테스트", "text": "짧은 잎", "parent_text": "가" * 5000}]
    result = _format_policy_chunks(chunks)
    assert len(result) < 1300


def test_format_policy_chunks_empty_list_unchanged():
    assert _format_policy_chunks([]) == "(검색 결과 없음)"


def test_build_classify_prompt_includes_settlement_facts():
    """headcount 등 판정필드가 검색 쿼리뿐 아니라 분류 프롬프트에도 실려야 한다."""
    summary = {"category": "회식", "merchant": "강남모던바", "amount": 90000,
               "purpose": None, "headcount": 2, "preApproved": False}
    stage1 = {"anomaly_score": 0.12, "contribs": [], "risk_tier": "MEDIUM"}
    prompt = _build_classify_prompt(summary, stage1, initial_query="q", policy_hits=[], case_hits=[])

    assert "참석 인원 2명" in prompt
    assert "사전승인 받지 않음" in prompt


def test_build_classify_prompt_omits_unknown_facts_instead_of_inventing_them():
    """None은 '모름'이지 '아니오'가 아니다 — facts_nl 계약을 그대로 이어받는다."""
    summary = {"category": "출장", "merchant": "OO호텔", "amount": 300000, "purpose": "출장 숙박"}
    stage1 = {"anomaly_score": 0.0, "contribs": [], "risk_tier": "LOW"}
    prompt = _build_classify_prompt(summary, stage1, initial_query="q", policy_hits=[], case_hits=[])

    assert "거래 사실: (없음)" in prompt


def test_build_classify_prompt_still_includes_anomaly_tier_and_chunks():
    summary = {"category": "업무추진비", "merchant": "한정식당", "amount": 500000, "purpose": None}
    stage1 = {"anomaly_score": 0.87, "contribs": [{"feature": "카드첫거래여부", "weight": 1.0}], "risk_tier": "HIGH"}
    policy_hits = [{"citation": "업무추진비_사용규정 제9조", "text": "청탁금지법 한도 초과 금지"}]
    prompt = _build_classify_prompt(summary, stage1, initial_query="q", policy_hits=policy_hits, case_hits=[])

    assert "anomaly_score: 0.870 (risk_tier: HIGH)" in prompt
    assert "카드첫거래여부(1.0)" in prompt
    assert "업무추진비_사용규정 제9조" in prompt


# ── 2026-08-19 전수 검토에서 잡은 결함 4건의 회귀 ────────────────────────────

def test_case_hits_expose_case_id_so_the_model_need_not_invent_one():
    """스키마가 case_id를 요구하는데 안 보여주면 모델이 citation 조각을 지어낸다(실측).

    실측 재현: case_id를 뺐더니 `case-golden-005`인 사례를 모델이 `#0511`로 채웠고, 그 값이
    Django `rag_refs`에 실려 검토 화면에 떴다 — 우리 store엔 없는 id라 역추적 불가였다.
    """
    cases = [{
        "case_id": "case-golden-005",
        "citation": "과거 보완요청사례 #0511",
        "outcome": "RETURN",
        "text": "회식 2차(주점) 19.8만원, 1인당 한도 초과.",
    }]
    out = _format_case_hits(cases)
    assert "case_id=case-golden-005" in out
    assert "과거 보완요청사례 #0511" in out  # 사람이 읽는 라벨도 함께 유지


def test_stage1_failure_degrades_to_stub_instead_of_killing_stage2():
    """1차 실패가 예외로 올라가면 Django가 RiskReview 행을 아예 안 만든다 — 2차까지 유실."""
    with patch.object(agent.tools, "get_tx_features", side_effect=RuntimeError("tx-features 500")):
        out = _stage1(tx_id=1)

    assert out["risk_tier"] == "LOW"
    assert out["anomaly_score"] == 0.0
    assert "stage1 실패" in out["note"]  # 조용히 0점으로 위장하지 않고 사유를 남긴다


def test_safe_search_returns_empty_on_backend_failure():
    """Chroma 장애가 2차 검증 전체를 죽이지 않는다(근거 없음으로 격하 + 로그)."""
    with patch.object(agent.mcp_client, "call_tool", side_effect=RuntimeError("chroma down")):
        assert _safe_search("search_policy", "chunks", query="q") == []


def test_action_falls_back_deterministically_when_llm_fails():
    """액션 LLM 장애로 이미 성공한 ①분류(검색·인용 포함)까지 버리지 않는다."""
    with patch.object(agent, "_get_client", side_effect=RuntimeError("openai 500")):
        out = _decide_action({"violation_verdict": "NO_VIOLATION", "review_reasons": [],
                              "citations": [], "similar_cases": []})
    assert out["recommendation"] == "APPROVE"


def test_action_fallback_never_auto_rejects():
    """최종반려는 되돌릴 수 없는 단말 — 장애 경로에서 자동으로 내리지 않는다(사람 확정 원칙)."""
    with patch.object(agent, "_get_client", side_effect=RuntimeError("openai 500")):
        out = _decide_action({"violation_verdict": "VIOLATION", "review_reasons": ["한도 초과"],
                              "citations": [], "similar_cases": []})
    assert out["recommendation"] == "SUPPLEMENT"


def test_risk_tier_boundaries_are_inclusive_at_the_threshold():
    """경계값 자체는 그 등급에 포함된다(`>=`) — 상수를 튜닝해도 이 계약은 유지돼야 한다."""
    assert _risk_tier(agent.RISK_TIER_HIGH_THRESHOLD) == "HIGH"
    assert _risk_tier(agent.RISK_TIER_HIGH_THRESHOLD - 1e-9) == "MEDIUM"
    assert _risk_tier(agent.RISK_TIER_MEDIUM_THRESHOLD) == "MEDIUM"
    assert _risk_tier(agent.RISK_TIER_MEDIUM_THRESHOLD - 1e-9) == "LOW"
    assert _risk_tier(-0.05) == "LOW"

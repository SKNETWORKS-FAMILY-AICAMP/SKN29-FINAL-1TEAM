"""Risk Review ①분류 프롬프트 조립 회귀 — `agents/agent.py`.

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
    _report_problems,
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

    #  **등급을 채우지 않는다.** 예전엔 `LOW`를 돌려줬는데, 화면이 그걸 「이상 신호 낮음」
    #  으로 읽어 못 잰 건이 「검사해보니 안전한 건」으로 둔갑했다.
    assert out["risk_tier"] == ""
    assert out["status"] == agent.STAGE1_ERROR
    assert out["anomaly_score"] == 0.0
    assert out["note"]  # 조용히 0점으로 위장하지 않고 사유를 남긴다


def test_safe_search_returns_empty_on_backend_failure():
    """Chroma 장애가 2차 검증 전체를 죽이지 않는다(근거 없음으로 격하 + 로그)."""
    with patch.object(agent.mcp_client, "call_tool", side_effect=RuntimeError("chroma down")):
        assert _safe_search("search_policy", "chunks", query="q") == []


def test_report_fallback_maps_verdict_deterministically():
    """보고서 LLM 장애로 이미 성공한 ①분류(검색·인용 포함)까지 버리지 않는다.

    이전엔 이 계약을 `_decide_action`으로 검증했는데, **그 함수는 실행 경로에서
    호출되지 않고 있었다** — 테스트가 죽은 함수를 살아 있는 것처럼 통과시켰다
    (검증 100건 실측, `docs/report/risk-review-agent-report.md` §5-②). 이제 실제로
    쓰이는 폴백을 검증한다.
    """
    out = agent._fallback_report(
        {"violation_verdict": "NO_VIOLATION", "review_reasons": [], "citations": []}, "timeout")
    assert out["recommendation"] == "APPROVE"


def test_report_fallback_never_auto_rejects():
    """최종반려는 되돌릴 수 없는 단말 — 장애 경로에서 자동으로 내리지 않는다(사람 확정 원칙)."""
    out = agent._fallback_report(
        {"violation_verdict": "VIOLATION", "review_reasons": ["한도 초과"], "citations": []},
        "timeout")
    assert out["recommendation"] == "SUPPLEMENT"


def test_recommendation_outside_verdict_is_corrected_by_server():
    """**권고는 분류를 뒤집을 수 없다.** 스키마·프롬프트를 다 뚫어도 서버가 되돌린다."""
    report = agent.RiskReport(summary="문제 없음", recommendation="SUPPLEMENT",
                              highlights=[], findings=[], advisories=[])
    out = agent._validate_report(report, {"violation_verdict": "NO_VIOLATION"}, {})
    assert out["recommendation"] == "APPROVE"


def test_report_problems_flags_contradicting_recommendation():
    """재작성 루프가 되돌려 보낼 이유 — 분류와 어긋난 권고는 고쳐 쓸 값어치가 있다."""
    report = agent.RiskReport(summary="ok", recommendation="REJECT",
                              highlights=[], findings=[], advisories=[])
    problems = _report_problems(report, {"violation_verdict": "NO_VIOLATION"}, {})
    assert any("NO_VIOLATION" in p for p in problems)
    assert not _report_problems(
        agent.RiskReport(summary="ok", recommendation="APPROVE",
                         highlights=[], findings=[], advisories=[]),
        {"violation_verdict": "NO_VIOLATION"}, {})


def test_report_schema_is_narrowed_by_verdict():
    """낼 수 없어야 하는 값은 지시가 아니라 **스키마에서** 뺀다."""
    assert agent._REPORT_MODEL["NO_VIOLATION"].model_fields["recommendation"].annotation.__args__         == ("APPROVE",)


def test_tier_override_is_loud_and_read_at_call_time(monkeypatch):
    """등급 강제는 **조용히** 동작하면 안 된다 — 호출 시점에 읽고, 켜지면 티가 난다."""
    monkeypatch.delenv("RISK_TIER_OVERRIDE", raising=False)
    assert agent._tier_override() == ""
    monkeypatch.setenv("RISK_TIER_OVERRIDE", "medium")
    assert agent._tier_override() == "MEDIUM"
    assert _risk_tier(-99.0) == "MEDIUM"      # 점수를 무시한다
    monkeypatch.setenv("RISK_TIER_OVERRIDE", "nonsense")
    assert agent._tier_override() == ""       # 오타는 조용히 무시하지 않고 꺼진 것으로 본다


def test_risk_tier_boundaries_are_inclusive_at_the_threshold():
    """경계값 자체는 그 등급에 포함된다(`>=`) — 상수를 튜닝해도 이 계약은 유지돼야 한다."""
    assert _risk_tier(agent.RISK_TIER_HIGH_THRESHOLD) == "HIGH"
    assert _risk_tier(agent.RISK_TIER_HIGH_THRESHOLD - 1e-9) == "MEDIUM"
    assert _risk_tier(agent.RISK_TIER_MEDIUM_THRESHOLD) == "MEDIUM"
    assert _risk_tier(agent.RISK_TIER_MEDIUM_THRESHOLD - 1e-9) == "LOW"
    assert _risk_tier(-0.05) == "LOW"

# ── 모델이 없을 때: **stub이 아니라 「못 쟀다」로 내려간다** ────────────────────
#
#  예전엔 `risk_tier="LOW"`를 돌려줬다. 화면은 그걸 「이상 신호 낮음」으로 읽으므로,
#  모델이 없어서 못 잰 건이 **검사해보니 안전한 건**으로 둔갑했다.

def test_모델이_없으면_등급을_비운다(monkeypatch):
    monkeypatch.setattr(agent, "get_active_model", lambda: None)
    monkeypatch.setattr(agent.tools, "get_tx_features",
                        lambda tx_id: {"feature_vector": [0.0]})
    out = agent._stage1(1)
    assert out["status"] == agent.STAGE1_NO_MODEL
    assert out["risk_tier"] == "", "LOW로 채우면 「안전한 건」으로 읽힌다"
    assert out["anomaly_score"] == 0.0
    assert "모델" in out["note"]


def test_피처_조립이_실패해도_등급을_비운다(monkeypatch):
    def _boom(tx_id):
        raise RuntimeError("core down")

    monkeypatch.setattr(agent.tools, "get_tx_features", _boom)
    out = agent._stage1(1)
    assert out["status"] == agent.STAGE1_ERROR
    assert out["risk_tier"] == ""


def test_정상_채점이면_status가_ok(monkeypatch):
    class _Model:
        fitted = True

    monkeypatch.setattr(agent, "get_active_model", lambda: _Model())
    monkeypatch.setattr(agent.tools, "get_tx_features",
                        lambda tx_id: {"feature_vector": [0.0]})
    #  **점수를 하드코딩하지 않는다.** 컷오프는 데이터 분포에서 다시 잡히는 값이라
    #  (2026-08-26에 .0134 → .072로 바뀌었다) 숫자를 박으면 그때마다 이 테스트가 깨진다.
    #  여기서 고정하려는 계약은 「채점이 정상이면 status가 ok이고 등급이 붙는다」이지
    #  「0.02가 HIGH다」가 아니다.
    monkeypatch.setattr(agent.tools, "ml_infer",
                        lambda vec: {"anomaly_score": agent.RISK_TIER_HIGH_THRESHOLD + 0.01,
                                     "is_outlier": True, "contribs": []})
    out = agent._stage1(1)
    assert out["status"] == agent.STAGE1_OK
    assert out["risk_tier"] == "HIGH"


# ══════════════════════════════════════════════════════════════════
#  등급 분기 + 보고서 (상/중/하)
# ══════════════════════════════════════════════════════════════════

_CLASSIFICATION = {
    "violation_verdict": "VIOLATION",
    "review_reasons": ["1인당 한도 초과"],
    "citations": [{"doc": "회식 운영규정", "article": "제14조①",
                   "chunk_id": "c-1", "quote_summary": "1인당 5만원을 초과할 수 없다"}],
    "similar_cases": [{"case_id": "K-9", "outcome": "REJECT", "relevance": "동일 한도 초과 건"}],
}
_SUMMARY = {"tx_id": 1, "merchant": "이자카야 정", "amount": 198000,
            "category": "회식", "purpose": "팀 회식 2차"}


def test_LOW는_LLM을_부르지_않는다(monkeypatch):
    """【하】 등급 — 비용·지연 0. 고정 문구라 지어낼 여지도 없다."""
    def _boom(*a, **kw):
        raise AssertionError("LOW 등급에서 LLM을 부르면 안 된다")

    monkeypatch.setattr(agent.llm, "chat", _boom)
    out = agent._stage2(_SUMMARY, {"risk_tier": "LOW", "status": agent.STAGE1_OK,
                                   "anomaly_score": 0.001})
    assert out["tier_path"] == "low"
    assert out["recommendation"] == "APPROVE"
    #  **「검사해보니 문제없음」이 아니라 「검사하지 않음」**이라고 말해야 한다.
    assert "수행하지 않았습니다" in out["report"]["summary"]
    assert any("직접 확인" in a for a in out["report"]["advisories"])


def test_등급이_모델을_고른다(monkeypatch):
    """MEDIUM=fast / HIGH=heavy — 위험이 높을수록 비싼 모델."""
    seen = []
    monkeypatch.setattr(agent, "_classify",
                        lambda s, st, profile: seen.append(profile) or _CLASSIFICATION)
    monkeypatch.setattr(agent, "_build_report",
                        lambda s, st, c, profile: {"summary": "", "recommendation": "SUPPLEMENT",
                                                   "highlights": [], "findings": [], "advisories": []})
    for tier, expected in (("MEDIUM", "fast"), ("HIGH", "heavy")):
        agent._stage2(_SUMMARY, {"risk_tier": tier, "status": agent.STAGE1_OK, "anomaly_score": 0.02})
    assert seen == ["fast", "heavy"]


def test_등급을_못_쟀으면_heavy로_보낸다(monkeypatch):
    """못 잰 것을 LOW로 접으면 「검사해보니 일반 거래」가 된다 — 실제로는 검사를 못 한 것."""
    seen = []
    monkeypatch.setattr(agent, "_classify",
                        lambda s, st, profile: seen.append(profile) or _CLASSIFICATION)
    monkeypatch.setattr(agent, "_build_report",
                        lambda s, st, c, profile: {"summary": "", "recommendation": "SUPPLEMENT",
                                                   "highlights": [], "findings": [], "advisories": []})
    agent._stage2(_SUMMARY, {"risk_tier": "", "status": agent.STAGE1_NO_MODEL, "anomaly_score": 0.0})
    assert seen == ["heavy"]


# ── 보고서 서버 검증 ──

def _report(**over):
    base = dict(summary="요약", recommendation="SUPPLEMENT", highlights=["23:40 결제"],
                findings=[], advisories=[])
    base.update(over)
    return agent.RiskReport(**base)


def _finding(ref, claim="1인당 한도를 넘었습니다"):
    return agent.ReportFinding(
        claim=claim, reasoning="참석 4명에 19.8만원",
        evidence=[agent.ReportEvidence(kind="policy", ref=ref, label="위조된 라벨", quote="위조된 인용")],
    )


def test_지어낸_근거_id는_버린다():
    _, index = agent._evidence_pool(_CLASSIFICATION)
    out = agent._validate_report(_report(findings=[_finding("없는-id")]), _CLASSIFICATION, index)
    #  근거가 전멸한 finding은 판단이 아니라 참고 사항으로 강등된다.
    assert out["findings"][0]["evidence"] == []
    assert any("근거 조항을 확인하지 못해" in a for a in out["advisories"])


def test_라벨과_인용은_서버_원본으로_덮는다():
    """모델이 옮겨 적다 바꿔도 화면에는 실제 검색 결과가 떠야 한다."""
    _, index = agent._evidence_pool(_CLASSIFICATION)
    out = agent._validate_report(_report(findings=[_finding("c-1")]), _CLASSIFICATION, index)
    ev = out["findings"][0]["evidence"][0]
    assert ev["label"] == "「회식 운영규정」제14조①"
    assert ev["quote"] == "1인당 5만원을 초과할 수 없다"


def test_판단보류인데_승인이면_보완요청으로_정정한다():
    """배너는 「판단 보류」인데 본문이 승인을 권하면 서로 다른 말을 한다."""
    cls = {**_CLASSIFICATION, "violation_verdict": "INSUFFICIENT_INFO"}
    _, index = agent._evidence_pool(cls)
    out = agent._validate_report(_report(recommendation="APPROVE"), cls, index)
    assert out["recommendation"] == "SUPPLEMENT"


def test_finding이_비면_최소_한_줄을_만든다():
    """빈 목록은 화면에서 「검증 안 함」과 구분되지 않는다."""
    _, index = agent._evidence_pool(_CLASSIFICATION)
    out = agent._validate_report(_report(findings=[]), _CLASSIFICATION, index)
    assert len(out["findings"]) == 1


def test_보고서_LLM이_죽어도_분류_결과를_버리지_않는다(monkeypatch):
    """①분류는 근거 검색까지 마쳐 비용을 이미 지불했다."""
    def _boom(*a, **kw):
        raise RuntimeError("openai 500")

    monkeypatch.setattr(agent.llm, "parse", _boom)
    out = agent._build_report(_SUMMARY, {"anomaly_score": 0.02}, _CLASSIFICATION, "heavy")
    assert out["recommendation"] == "SUPPLEMENT"      # 결정론적 폴백
    assert "1인당 한도 초과" in out["findings"][0]["claim"]

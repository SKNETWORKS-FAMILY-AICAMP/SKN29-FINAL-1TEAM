"""Draft Agent ↔ 가맹점 업종 연동 (§7-1).

이 연결이 없던 동안 `merchantIndustry`는 **LLM이 가맹점명만 보고 지어낸 자유 문자열**이었고,
그 값이 그대로 `Settlement.merchant_industry` → `merchant.merchant_type` 판정 사실이 됐다.
자유 문자열은 룰의 `in [...]`에 걸릴 수가 없으므로 금지업종·주의업종 판정이 조용히 죽어 있었다.

여기서 고정하는 계약 3가지:
  ① 업종은 **LLM 호출 전에** 조회된다(분류 판단의 입력이라 뒤에 붙이면 표시용밖에 안 된다)
  ② 초안 결과의 업종은 **조회값 그대로**다(LLM이 덮어쓰지 않는다)
  ③ 조회가 실패해도 초안 작성은 계속된다(업종은 보조 힌트)
"""
from __future__ import annotations

import pytest

from app.agents import draft_agent
from app.api.draft import DraftRequest, ReviseCurrent, ReviseRequest

CAFE = {"industry_code": "CAFE", "industry_label": "카페", "confidence": 0.9, "source": "KAKAO"}
UNRESOLVED = {"industry_code": "", "industry_label": "", "confidence": 0.0, "source": ""}


class _FakeLLMOut:
    """`_call_llm_*`의 반환 자리를 대신한다 — 업종 필드는 더 이상 스키마에 없다."""

    def __init__(self, **kw):
        self.category = kw.get("category", "식대")
        self.purpose = kw.get("purpose", "팀 커피")
        self.confidence = kw.get("confidence", 0.8)
        self.aiSuggested = True
        self.comments = []
        self.amount = kw.get("amount", 18400)
        self.headcount = kw.get("headcount", 0)
        self.evidence = kw.get("evidence", "OK")
        self.changes = []


@pytest.fixture
def no_policy_hints(monkeypatch):
    """정책 힌트는 별개 경로(별표 조회)라 이 테스트에서 끈다."""
    monkeypatch.setattr(draft_agent, "_build_policy_hints", lambda *a, **kw: [])


@pytest.fixture
def request_create() -> DraftRequest:
    return DraftRequest(merchant="스타벅스 강남점", amount=18400, date="2026-08-19", cardType="PERSONAL")


def test_industry_is_resolved_before_llm_and_passed_into_prompt(monkeypatch, no_policy_hints, request_create):
    order: list[str] = []
    seen_industry: list[str] = []

    monkeypatch.setattr(draft_agent.tools, "classify_merchant",
                        lambda merchant, place_hint=None: (order.append("classify"), CAFE)[1])

    def _fake_llm(req, industry, trace=None):
        order.append("llm")
        seen_industry.append(industry)
        return _FakeLLMOut()

    monkeypatch.setattr(draft_agent, "_call_llm_create", _fake_llm)

    result = draft_agent.run(request_create)

    assert order == ["classify", "llm"]      # ① 조회가 먼저다
    assert seen_industry == ["카페"]          # 프롬프트에 사실로 들어간다
    assert result["draft"]["merchantIndustry"] == "카페"        # ② 조회값 그대로
    assert result["draft"]["merchantIndustryCode"] == "CAFE"


def test_llm_cannot_override_industry(monkeypatch, no_policy_hints, request_create):
    """LLM이 뭘 뱉든 업종은 조회값이다 — 예전엔 이 값이 LLM 출력 스키마에 있었다."""
    monkeypatch.setattr(draft_agent.tools, "classify_merchant", lambda merchant, place_hint=None: CAFE)
    monkeypatch.setattr(
        draft_agent, "_call_llm_create",
        lambda req, industry, trace=None: _FakeLLMOut(category="접대"),
    )

    draft = draft_agent.run(request_create)["draft"]
    assert draft["merchantIndustry"] == "카페"
    # 애초에 LLM이 업종을 말할 자리가 없어야 한다 — 스키마에서 뺐다.
    assert "merchantIndustry" not in draft_agent.LLMDraftOutput.model_fields
    assert "merchantIndustry" not in draft_agent.LLMReviseOutput.model_fields


def test_classify_failure_does_not_break_draft(monkeypatch, no_policy_hints, request_create):
    """업종 조회가 터져도 초안은 나온다 — 업종은 보조 힌트다."""
    def _boom(*_a, **_kw):
        raise RuntimeError("core 미기동")

    monkeypatch.setattr(draft_agent.tools, "classify_merchant", _boom)
    monkeypatch.setattr(draft_agent, "_call_llm_create",
                        lambda req, industry, trace=None: _FakeLLMOut())

    result = draft_agent.run(request_create)
    assert result["draft"]["merchantIndustry"] == ""
    assert result["draft"]["category"] == "식대"       # 초안 자체는 정상


def test_unresolved_industry_is_marked_unknown_in_prompt(monkeypatch, no_policy_hints, request_create):
    """미확정이면 프롬프트에 "미확인"이라고 적는다 — 빈 칸을 주면 모델이 추측해 채운다."""
    captured: dict = {}

    class _Resp:
        class _Choice:
            finish_reason = "stop"

            class message:
                parsed = _FakeLLMOut()
                content = "{}"
                refusal = None

        choices = [_Choice()]
        usage = None

    class _FakeClient:
        class beta:
            class chat:
                class completions:
                    @staticmethod
                    def parse(**kw):
                        captured.update(kw)
                        return _Resp()

    monkeypatch.setattr(draft_agent.tools, "classify_merchant", lambda merchant, place_hint=None: UNRESOLVED)
    monkeypatch.setattr(draft_agent, "_get_client", lambda: _FakeClient)

    trace: dict = {}
    result = draft_agent.run(request_create, trace)

    assert "가맹점 업종(서버 조회): 미확인" in captured["messages"][1]["content"]
    assert result["draft"]["merchantIndustry"] == ""
    assert trace["industry"]["source"] == "unresolved"      # AI-LAB이 "왜 비었는지"를 본다


def test_llm_failure_keeps_resolved_industry(monkeypatch, no_policy_hints, request_create):
    """초안 LLM이 실패해도 이미 조회한 업종은 버리지 않는다(별개 경로다)."""
    monkeypatch.setattr(draft_agent.tools, "classify_merchant", lambda merchant, place_hint=None: CAFE)

    def _boom(*_a, **_kw):
        raise RuntimeError("모델 거부")

    monkeypatch.setattr(draft_agent, "_call_llm_create", _boom)

    draft = draft_agent.run(request_create)["draft"]
    assert draft["merchantIndustry"] == "카페"
    assert draft["merchantIndustryCode"] == "CAFE"


def test_revise_reuses_current_industry_without_reclassifying(monkeypatch, no_policy_hints):
    """수정 모드는 화면 값을 물려받는다 — 매 수정마다 카카오·LLM을 다시 부르지 않는다."""
    def _fail_if_called(*_a, **_kw):
        raise AssertionError("수정 모드에서 업종을 재조회했다")

    monkeypatch.setattr(draft_agent.tools, "classify_merchant", _fail_if_called)
    monkeypatch.setattr(draft_agent, "_call_llm_revise",
                        lambda req, industry, trace=None: _FakeLLMOut(category="회의"))

    req = ReviseRequest(
        instruction="분류를 회의로 바꿔줘",
        current=ReviseCurrent(
            merchant="스타벅스 강남점", amount=18400, category="식대",
            merchantIndustry="카페", merchantIndustryCode="CAFE",
        ),
    )
    draft = draft_agent.revise(req)["draft"]
    assert draft["merchantIndustry"] == "카페"
    assert draft["category"] == "회의"


def test_revise_resolves_when_current_industry_is_empty(monkeypatch, no_policy_hints):
    """첫 조회가 실패해 비어 있으면 그때는 다시 조회한다."""
    monkeypatch.setattr(draft_agent.tools, "classify_merchant", lambda merchant, place_hint=None: CAFE)
    monkeypatch.setattr(draft_agent, "_call_llm_revise",
                        lambda req, industry, trace=None: _FakeLLMOut())

    req = ReviseRequest(
        instruction="금액을 2만원으로",
        current=ReviseCurrent(merchant="스타벅스 강남점", amount=18400, category="식대"),
    )
    assert draft_agent.revise(req)["draft"]["merchantIndustry"] == "카페"

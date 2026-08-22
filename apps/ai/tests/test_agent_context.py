"""`app/context` 회귀 — core 왕복 없이 카탈로그 조립·렌더·캐시·실패 계약을 고정한다.

지키는 계약 셋:
  ① **프롬프트와 검증기가 같은 객체를 본다** — `Bundle.paths`/`.operators`가 프롬프트에
     실린 목록과 같은 데이터에서 나온다(따로 계산하지 않는다).
  ② **실패는 침묵하지 않는다** — 조회가 깨지면 프롬프트가 "카탈로그 조회 실패"라고 말한다.
     빈 블록을 내보내면 모델은 "제약이 없다"로 읽는다.
  ③ **실패를 캐시하지 않는다** — core가 잠깐 안 떠 있었다고 TTL 동안 stale에 갇히면
     그 사이 생성된 룰이 전부 무제약 프롬프트로 만들어진다.
"""
from __future__ import annotations

import pytest

from app.context import client as ctx_client
from app.context.client import Bundle, get_context, invalidate
from app.context.render import render


def _payload() -> dict:
    """core `/api/internal/agent-context/` 응답 모양(축소판)."""
    return {
        "profile": "rule_generate",
        "etag": "abc123",
        "sections": [
            {
                "id": "dsl.grammar",
                "title": "조건식 DSL 문법",
                "data": {
                    "logic_operators": ["and", "not", "or"],
                    "compare_operators": ["!=", "<", "<=", "==", ">", ">=", "in"],
                    "value_operator": "var",
                    "max_depth": 32,
                },
                "notes": ["산술 연산자가 없다."],
            },
            {
                "id": "eval_context.paths",
                "title": "판정에 쓸 수 있는 사실 목록",
                "data": {
                    "schema_version": 5,
                    "builder_version": "5.0",
                    "sections": [
                        {
                            "section": "tx",
                            "title": "거래 사실",
                            "fields": [
                                {"path": "tx.amount", "type": "number", "desc": "총액", "enum": None},
                            ],
                        },
                        {
                            "section": "merchant",
                            "title": "가맹점",
                            "fields": [
                                {"path": "merchant.merchant_type", "type": "string",
                                 "desc": "업종", "enum": "vocab.industry"},
                            ],
                        },
                        {"section": "tables", "title": "감사용", "fields": []},
                    ],
                },
                "notes": ["null은 모름이다."],
            },
            {
                "id": "policy.vars",
                "title": "규정 임계값",
                "data": {
                    "vars": [
                        {"path": "policy.kickback_limit", "table_key": "kickback_limit_table",
                         "title": "별표3", "key_axes": ["category.item_type"], "loaded": True,
                         "strict_keys": False, "effective_date": "2026-01-01", "source_clause": ""},
                        {"path": "policy.lodging_limit", "table_key": "lodging_limit_table",
                         "title": None, "key_axes": None, "loaded": False,
                         "strict_keys": None, "effective_date": None, "source_clause": None},
                    ],
                    "derived": [],
                },
                "notes": [],
            },
            {
                "id": "action.schema",
                "title": "판정·심각도",
                "data": {
                    "decisions": ["PASS", "REJECT", "RETURN", "REVIEW", "PASS_THROUGH"],
                    "severities": ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"],
                    "pass_through": "PASS_THROUGH",
                    "decision_effect": {"REJECT": {"status": "RETURNED", "label": "보완요청"}},
                },
                "notes": ["엔진은 최종반려를 만들지 않는다."],
            },
            {
                "id": "flags.registry",
                "title": "사유 플래그",
                "data": {
                    "source": "db",
                    "rule_flags": [
                        {"code": "EVIDENCE_MISSING", "label": "적격증빙 없음", "category": "EVIDENCE",
                         "severity": "HIGH", "owner": "SPENDER", "description": "증빙 없음"},
                    ],
                    "system_flags": [{"code": "UNRESOLVED_FACT", "label": "판정 정보 부족"}],
                    "categories": {"EVIDENCE": "증빙·기재"},
                    "severities": {}, "owners": {},
                },
                "notes": [],
            },
        ],
    }


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def _clear_cache():
    invalidate()
    yield
    invalidate()


@pytest.fixture
def bundle(monkeypatch) -> Bundle:
    monkeypatch.setattr(ctx_client.httpx, "get", lambda *a, **kw: _FakeResponse(_payload()))
    return get_context("rule_generate")


# ── ① 프롬프트와 검증기가 같은 출처 ────────────────────────────────────────

def test_경로와_연산자가_카탈로그에서_나온다(bundle):
    assert bundle.paths == ["tx.amount", "merchant.merchant_type"]
    assert bundle.operators == {
        "and", "or", "not", "==", "!=", ">", ">=", "<", "<=", "in", "var",
    }
    assert bundle.decisions[0] == "PASS"
    assert bundle.flag_codes == ["EVIDENCE_MISSING"]
    assert bundle.etag == "abc123"


def test_프롬프트에_경로_타입_설명_어휘가_모두_들어간다(bundle):
    out = bundle.prompt()
    assert "tx.amount (number) — 총액" in out
    assert "←어휘:vocab.industry" in out          # in [...] 우변을 지어내지 못하게 하는 표시
    assert "고정 필드 없음(룰 참조 불가)" in out    # tables 섹션
    assert "- null은 모름이다." in out             # core가 소유한 불변식이 그대로 실린다


def test_미적재_임계값은_경고와_함께_보인다(bundle):
    """`loaded=false`를 숨기면 모델이 못 쓰는 변수로 자신 있게 룰을 만든다."""
    out = bundle.prompt("policy.vars")
    assert "policy.kickback_limit ← kickback_limit_table" in out
    assert "축: category.item_type" in out
    assert "미적재" in out and "policy.lodging_limit" in out


def test_섹션을_골라_뽑을_수_있다(bundle):
    out = bundle.prompt("action.schema")
    assert "판정·심각도" in out
    assert "tx.amount" not in out


# ── ② 실패 계약 ───────────────────────────────────────────────────────────

def test_조회_실패는_프롬프트에_그대로_적힌다(monkeypatch):
    def _boom(*a, **kw):
        raise RuntimeError("core down")

    monkeypatch.setattr(ctx_client.httpx, "get", _boom)
    b = get_context("rule_generate")
    assert b.stale is True
    assert b.paths == [] and b.operators == set()
    out = b.prompt()
    assert "카탈로그 조회 실패" in out
    assert "core down" in out


def test_조회_실패해도_판정_선택지는_남는다(monkeypatch):
    """structured output의 enum은 빈 배열일 수 없다 — 여기만 로컬 기본값을 허용한다."""
    monkeypatch.setattr(ctx_client.httpx, "get", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("x")))
    b = get_context("rule_generate")
    assert b.decisions and b.severities


def test_빈_섹션도_실패로_취급한다():
    assert "카탈로그 조회 실패" in render([])


# ── ③ 캐시 ────────────────────────────────────────────────────────────────

def test_성공은_캐시하고_실패는_캐시하지_않는다(monkeypatch):
    calls = {"n": 0}

    def _count(*a, **kw):
        calls["n"] += 1
        return _FakeResponse(_payload())

    monkeypatch.setattr(ctx_client.httpx, "get", _count)
    get_context("rule_generate")
    get_context("rule_generate")
    assert calls["n"] == 1

    invalidate()
    monkeypatch.setattr(ctx_client.httpx, "get", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("x")))
    get_context("rule_generate")
    monkeypatch.setattr(ctx_client.httpx, "get", _count)
    get_context("rule_generate")
    assert calls["n"] == 2      # 실패가 TTL 동안 붙들려 있었다면 여전히 1이다


def test_프로파일이_다르면_캐시가_섞이지_않는다(monkeypatch):
    seen: list[str] = []

    def _spy(*a, **kw):
        seen.append(kw["params"]["profile"])
        return _FakeResponse(_payload())

    monkeypatch.setattr(ctx_client.httpx, "get", _spy)
    get_context("rule_generate")
    get_context("rule_chat")
    assert seen == ["rule_generate", "rule_chat"]


# ── 모르는 섹션(core가 먼저 늘어난 경우) ───────────────────────────────────

def test_모르는_섹션도_버리지_않는다():
    out = render([{"id": "vocab.future", "title": "새 어휘", "data": {"a": 1}, "notes": []}])
    assert "새 어휘" in out and '"a": 1' in out

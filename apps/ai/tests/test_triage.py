"""`app/rag/triage` 회귀 — LLM 왕복 없이 계약만 고정한다.

지키는 것 넷:
  ① **범위** — 회사 규정 컬렉션에만 돈다. 건너뛰면 그 사실이 결과에 남는다(조용한 누락 금지).
  ② **모델 출력을 믿지 않는다** — 지어낸 조 라벨·모르는 분류값·없는 축은 버린다.
     특히 축은 틀려도 에러가 안 나고 **항상 기본값으로 떨어지는** 가장 조용한 결함이다.
  ③ **부분 실패는 부분만 잃는다** — 배치 하나가 깨졌다고 나머지 조항 분류가 사라지면 안 된다.
  ④ **적재를 실패시키지 않는다** — 분류가 통째로 터져도 결과를 돌려준다.
  ⑤ **선별은 문서 단위로 한다** — 성격 판별(배치) → 우선순위 선별(후보 전체 1회). 후보가
     있는데 AUTO가 0이면 자동 생성이 통째로 멈추므로, 선별이 실패하거나 하나도 안 고르면
     코드가 대신 채운다(모델 장애가 "만들 규칙이 없다"로 둔갑하면 안 된다).
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from app.rag import triage


@dataclass
class FakeChunk:
    chunk_id: str
    text: str
    chunk_type: str = "annex"
    chunk_role: str = "atomic"
    has_table: bool = True
    article_label: str = "별표1"
    citation: str = "규정 별표1"
    page_start: int = 3
    page_end: int = 3


AXES = [
    {"path": "user.job_title", "type": "string", "desc": "직책"},
    {"path": "tx.amount", "type": "number", "desc": "결제 총액"},
]

CLAUSES = [
    {"articleLabel": "제1조", "articleTitle": "(목적)", "body": "이 규정은 …을 목적으로 한다."},
    {"articleLabel": "제9조", "articleTitle": "(사용 한도)", "body": "1인당 5만원을 초과할 수 없다."},
]


def _reply(payload: dict):
    """OpenAI structured-output 응답 흉내."""
    class _Msg:
        content = json.dumps(payload, ensure_ascii=False)

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

    return _Resp()


@pytest.fixture
def chat(monkeypatch):
    """`_chat` 호출을 가로채 순서대로 응답을 돌려준다."""
    calls: list[dict] = []

    def _install(replies):
        queue = list(replies)

        def fake(system, user, schema, name):
            calls.append({"name": name, "user": user})
            if not queue:
                raise AssertionError("예상보다 많은 LLM 호출")
            nxt = queue.pop(0)
            if isinstance(nxt, Exception):
                raise nxt
            return nxt

        monkeypatch.setattr(triage, "_chat", fake)
        return calls

    return _install


# ── ① 범위 ────────────────────────────────────────────────────────────────

def test_회사_규정이_아닌_컬렉션은_건너뛰고_사유를_남긴다():
    result = triage.run(chunks=[], clauses=CLAUSES, collection="tax_refs")
    assert result.ran is False
    assert "건너뜁니다" in result.skipped_reason
    assert result.clauses == {} and result.tables == []


# ── ② 모델 출력 검증 ──────────────────────────────────────────────────────

def _kind(label, kind="RULE", threshold=True, certainty=0.9, summary="한도", reason="명확"):
    return {"label": label, "kind": kind, "has_threshold": threshold,
            "certainty": certainty, "summary": summary, "reason": reason}


def test_지어낸_조항과_모르는_분류값은_버린다(chat):
    chat([
        {"clauses": [
            _kind("제9조"),
            _kind("제99조"),                       # 없는 조
            _kind("제1조", kind="NONSENSE"),        # 모르는 kind
        ]},
        {"ranked": [{"label": "제9조", "priority": "AUTO", "reason": "임계값이 조항에 있다"}]},
    ])
    out = triage.classify_clauses(CLAUSES)
    assert set(out) == {"제9조"}
    assert out["제9조"]["triagePriority"] == "AUTO"


def test_안내_조항은_선별에_올리지_않고_SKIP으로_못박는다(chat):
    """안내 조항이 1순위로 큐에 오르면 목록이 곧 신뢰를 잃는다. 후보가 없으니 선별도 안 돈다."""
    calls = chat([{"clauses": [_kind("제1조", kind="INFO", summary="", reason="목적 조항")]}])
    out = triage.classify_clauses(CLAUSES[:1])
    assert out["제1조"]["triagePriority"] == "SKIP"
    assert [c["name"] for c in calls] == ["clause_triage"]     # 선별 호출 없음


def test_선별은_후보_전체를_한_번에_본다(chat):
    """조항 하나만 놓고 물으면 모델이 전부 「확인 필요」로 미룬다 — 그래서 문서 단위로 묻는다."""
    calls = chat([
        {"clauses": [_kind("제9조"), _kind("제10조", certainty=0.7)]},
        {"ranked": [
            {"label": "제9조", "priority": "AUTO", "reason": "가장 자주 걸린다"},
            {"label": "제10조", "priority": "P2", "reason": "제9조와 겹친다"},
        ]},
    ])
    out = triage.classify_clauses(CLAUSES + [
        {"articleLabel": "제10조", "articleTitle": "(증빙)", "body": "영수증을 첨부한다."},
    ])
    rank_user = next(c["user"] for c in calls if c["name"] == "clause_ranking")
    assert "제9조" in rank_user and "제10조" in rank_user
    assert out["제9조"]["triagePriority"] == "AUTO"
    assert out["제10조"]["triagePriority"] == "P2"
    assert "선별:" in out["제10조"]["triageReason"]


def test_AUTO_상한을_코드가_강제한다(chat, monkeypatch):
    """모델이 열 개를 고르면 자동 생성 질의가 문서 전체가 되어 검색이 아무것도 좁히지 못한다."""
    monkeypatch.setattr(triage, "AUTO_MAX", 2)
    labels = [f"제{i}조" for i in range(1, 5)]
    chat([
        {"clauses": [_kind(l) for l in labels]},
        {"ranked": [{"label": l, "priority": "AUTO", "reason": "명확"} for l in labels]},
    ])
    out = triage.classify_clauses(
        [{"articleLabel": l, "articleTitle": "(한도)", "body": "5만원"} for l in labels]
    )
    assert sum(1 for v in out.values() if v["triagePriority"] == "AUTO") == 2
    assert sum(1 for v in out.values() if v["triagePriority"] == "P1") == 2


def test_후보가_있는데_AUTO가_없으면_가장_명확한_하나는_올린다(chat):
    """AUTO가 0이면 자동 생성이 통째로 멈춘다(SKIPPED_NO_AUTO_CLAUSE) — 초안은 사람이 승인한다."""
    chat([
        {"clauses": [_kind("제9조", threshold=True, certainty=0.9),
                     _kind("제10조", threshold=False, certainty=0.5)]},
        {"ranked": [{"label": "제9조", "priority": "P1", "reason": "확인 필요"},
                    {"label": "제10조", "priority": "P2", "reason": "확인 필요"}]},
    ])
    out = triage.classify_clauses(CLAUSES + [
        {"articleLabel": "제10조", "articleTitle": "(증빙)", "body": "영수증"},
    ])
    assert out["제9조"]["triagePriority"] == "AUTO"      # 임계값이 있고 확신이 높은 쪽
    assert out["제10조"]["triagePriority"] == "P2"


def test_선별_호출이_실패하면_규칙_기반으로_대신_매긴다(chat):
    """모델 장애가 「이 문서엔 만들 규칙이 없다」로 둔갑하는 것이 가장 나쁜 실패 방향이다."""
    chat([
        {"clauses": [_kind("제9조")]},
        RuntimeError("timeout"),
    ])
    out = triage.classify_clauses(CLAUSES)
    assert out["제9조"]["triagePriority"] == "AUTO"
    assert "임시 순위" in out["제9조"]["triageReason"]


def test_선별이_빠뜨린_후보는_중간_순위로_남긴다(chat):
    chat([
        {"clauses": [_kind("제9조"), _kind("제10조")]},
        {"ranked": [{"label": "제9조", "priority": "AUTO", "reason": "명확"}]},
    ])
    out = triage.classify_clauses(CLAUSES + [
        {"articleLabel": "제10조", "articleTitle": "(증빙)", "body": "영수증"},
    ])
    assert out["제10조"]["triagePriority"] == "P2"

def test_없는_축은_제외하고_그_사실을_메모에_남긴다(chat):
    chat([{
        "is_threshold_table": True, "key": "welfare_limit_table", "title": "별표1",
        "key_axes": ["user.job_title", "user.position"],       # 뒤엣것은 스키마에 없다
        "payload_json": json.dumps({"부서장": 200000, "*": 100000}),
        "strict_keys": False, "confidence": 0.8, "notes": "",
    }])
    rows = triage.extract_tables([FakeChunk("c1", "| 직책 | 한도 |")], AXES)
    assert rows[0]["keyAxes"] == ["user.job_title"]
    assert "user.position" in rows[0]["notes"]


def test_임계값_표가_아니면_제안하지_않는다(chat):
    chat([{
        "is_threshold_table": False, "key": "", "title": "", "key_axes": [],
        "payload_json": "{}", "strict_keys": False, "confidence": 0.1, "notes": "결재 서식",
    }])
    assert triage.extract_tables([FakeChunk("c1", "| 결재 | 서명 |")], AXES) == []


def test_payload가_깨지면_그_표만_버린다(chat):
    chat([{
        "is_threshold_table": True, "key": "k_table", "title": "t", "key_axes": [],
        "payload_json": "{이건 JSON이 아니다", "strict_keys": False, "confidence": 0.5, "notes": "",
    }])
    assert triage.extract_tables([FakeChunk("c1", "| a | b |")], AXES) == []


def test_축_목록을_프롬프트에_싣는다(chat):
    """모델이 고를 수 있는 것을 안 보여주면 축을 지어내고, 그러면 승인 화면에서 되돌아온다."""
    calls = chat([{
        "is_threshold_table": True, "key": "k_table", "title": "t", "key_axes": [],
        "payload_json": json.dumps({"value": 1}), "strict_keys": False, "confidence": 1, "notes": "",
    }])
    triage.extract_tables([FakeChunk("c1", "| a | b |")], AXES)
    assert "user.job_title" in calls[0]["user"]


# ── ③ 부분 실패 ───────────────────────────────────────────────────────────

def test_배치_하나가_깨져도_나머지_분류는_남는다(chat, monkeypatch):
    monkeypatch.setattr(triage, "CLAUSE_BATCH", 1)
    chat([
        RuntimeError("timeout"),                                   # 제1조 배치 실패
        {"clauses": [_kind("제9조")]},
        {"ranked": [{"label": "제9조", "priority": "AUTO", "reason": "명확"}]},
    ])
    out = triage.classify_clauses(CLAUSES)
    assert set(out) == {"제9조"}


# ── ④ 적재를 실패시키지 않는다 ────────────────────────────────────────────

def test_분류가_통째로_터져도_결과를_돌려준다(monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("모델 장애")

    monkeypatch.setattr(triage, "classify_clauses", boom)
    monkeypatch.setattr(triage, "extract_tables", boom)
    result = triage.run(chunks=[], clauses=CLAUSES, collection="policy_docs", axis_options=AXES)
    assert result.ran is True
    assert "모델 장애" in result.error
    assert result.clauses == {} and result.tables == []


def test_AUTO_건수를_센다(chat):
    chat([
        {"clauses": [_kind("제1조", kind="INFO", summary="", reason="목적"), _kind("제9조")]},
        {"ranked": [{"label": "제9조", "priority": "AUTO", "reason": "명확"}]},
    ])
    result = triage.run(chunks=[], clauses=CLAUSES, collection="policy_docs", axis_options=AXES)
    assert result.auto_count == 1
    assert result.candidate_count == 1          # INFO는 후보가 아니다
    assert result.to_dict()["clauseCount"] == 2

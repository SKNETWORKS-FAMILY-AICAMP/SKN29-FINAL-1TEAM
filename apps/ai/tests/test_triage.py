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
    """실제 `Chunk`의 대역 — **필드가 실물과 어긋나면 안 된다.**

    `parent_chunk_id`·`prev/next`가 없던 동안 이 대역은 통과했지만 실물은 그 필드로
    표 조각을 묶는다. 대역이 실물보다 좁으면 테스트는 지나가고 운영이 깨진다.
    """
    chunk_id: str
    text: str
    chunk_type: str = "annex"
    chunk_role: str = "atomic"
    has_table: bool = True
    article_label: str = "별표1"
    article_title: str | None = None
    chapter_title: str | None = None
    citation: str = "규정 별표1"
    header: str = ""
    doc_name: str = "규정"
    page_start: int = 3
    page_end: int = 3
    parent_chunk_id: str | None = None
    prev_chunk_id: str | None = None
    next_chunk_id: str | None = None


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
    #  없는 축은 **재시도 대상**이다(목록에서 다시 고르게 한다). 모델이 같은 답을
    #  되풀이하면 그 사실을 메모로 남기고 사람에게 넘긴다.
    chat([{
        "is_threshold_table": True, "key": "welfare_limit_table", "title": "별표1",
        "key_axes": ["user.job_title", "user.position"],       # 뒤엣것은 스키마에 없다
        "payload_json": json.dumps({"부서장": 200000, "*": 100000}),
        "strict_keys": False, "confidence": 0.8, "notes": "", "comment": "",
    }] * 2)
    #  표 원문에 값이 있어야 한다 — 없으면 「원문에 없는 숫자」 검사에 걸려 재시도한다.
    rows = triage.extract_tables(
        [FakeChunk("c1", "| 직책 | 한도 |\n| 부서장 | 200,000 |\n| 그 외 | 100,000 |")], AXES)
    assert rows[0]["keyAxes"] == ["user.job_title"]
    assert "user.position" in rows[0]["notes"]


def test_임계값_표가_아니면_승인_대기에_넣지_않되_사유는_남긴다(chat):
    """**조용히 버리지 않는다** — 화면에 아무것도 안 남으면 담당자는
    「표가 있는데 왜 후보가 없지」를 스스로 알아내야 한다."""
    chat([{
        "is_threshold_table": False, "skip_reason": "결재 서식이라 임계값이 없습니다.",
        "key": "", "title": "", "key_axes": [], "payload_json": "{}",
        "strict_keys": False, "confidence": 0.1, "notes": "", "comment": "",
    }])
    rows = triage.extract_tables([FakeChunk("c1", "| 결재 | 서명 |")], AXES)
    assert len(rows) == 1
    assert rows[0]["skipped"] is True
    assert "결재 서식" in rows[0]["skipReason"]
    assert rows[0]["key"] == ""


def test_페이지에_걸친_표는_한_덩어리로_읽는다(chat):
    """실측: `출장비_사용규정` 별표2가 A·B등급(5쪽)과 C등급(6쪽) 두 청크였다.
    따로 읽으면 **반쪽 표 두 개**가 승인 대기에 올라오고, 머리글 없는 뒷조각은
    축조차 고를 수 없다."""
    calls = chat([{
        "is_threshold_table": True, "skip_reason": "", "key": "lodging_limit_table",
        "title": "별표2", "key_axes": ["user.job_title"],
        "payload_json": json.dumps({"부장": 250000, "*": 150000}),
        "strict_keys": False, "confidence": 0.9, "notes": "", "comment": "숙박비 상한입니다.",
    }])
    rows = triage.extract_tables([
        FakeChunk("x2#01", "| 직책 | 상한 |\n| 부장 | 250,000 |", parent_chunk_id="x2#P",
                  page_start=5, page_end=5),
        FakeChunk("x2#02", "| 그 외 | 150,000 |", parent_chunk_id="x2#P",
                  page_start=6, page_end=6),
    ], AXES)
    assert len(rows) == 1, "조각마다 제안이 생기면 반쪽 표가 승인 대기에 올라온다"
    assert len(calls) == 1, "그룹당 한 번만 호출해야 한다"
    #  두 조각이 한 프롬프트에 다 들어갔는가
    assert "250,000" in calls[0]["user"] and "150,000" in calls[0]["user"]
    assert rows[0]["pageStart"] == 5 and rows[0]["pageEnd"] == 6
    assert any("합쳐 읽었습니다" in c["message"] for c in rows[0]["checks"])


def test_맥락을_함께_넘긴다(chat):
    """머리글이 "구분"뿐이면 그게 무엇의 구분인지는 **표 밖**에 있다."""
    calls = chat([{
        "is_threshold_table": True, "skip_reason": "", "key": "daily_limit_table",
        "title": "별표1", "key_axes": [], "payload_json": json.dumps({"value": 30000}),
        "strict_keys": False, "confidence": 0.9, "notes": "", "comment": "",
    }])
    table = FakeChunk("t1", "| 구분 | 30,000 |", chapter_title="제3장 국외출장",
                      article_title="(여비)", prev_chunk_id="p0", next_chunk_id="n0",
                      doc_name="출장비_사용규정")
    prev = FakeChunk("p0", "국외출장 여비는 다음 표에 따른다.", chunk_type="clause")
    nxt = FakeChunk("n0", "다만 항공권은 실비로 정산한다.", chunk_type="clause")
    triage.extract_tables([table], AXES, [table, prev, nxt])
    user = calls[0]["user"]
    assert "출장비_사용규정" in user and "제3장 국외출장" in user
    assert "다음 표에 따른다" in user, "앞 문맥이 빠지면 무엇의 구분인지 알 수 없다"
    assert "실비로 정산한다" in user, "뒤 문맥에 단위·예외가 붙는다"


def test_지어낸_숫자는_재시도로_되돌린다(chat):
    """원문에 없는 값이 payload에 있으면 셀을 잘못 읽었거나 만든 것이다."""
    calls = chat([
        {"is_threshold_table": True, "skip_reason": "", "key": "daily_limit_table",
         "title": "별표1", "key_axes": [], "payload_json": json.dumps({"value": 999999}),
         "strict_keys": False, "confidence": 0.9, "notes": "", "comment": ""},
        {"is_threshold_table": True, "skip_reason": "", "key": "daily_limit_table",
         "title": "별표1", "key_axes": [], "payload_json": json.dumps({"value": 30000}),
         "strict_keys": False, "confidence": 0.9, "notes": "", "comment": ""},
    ])
    rows = triage.extract_tables([FakeChunk("c1", "| 한도 | 30,000원 |")], AXES)
    assert len(calls) == 2, "검사에 걸리면 문제를 적어 다시 부른다"
    assert "999999" in calls[1]["user"], "무엇이 틀렸는지 알려주지 않으면 같은 답이 온다"
    assert rows[0]["payload"] == {"value": 30000}
    assert all(c["level"] != "warn" for c in rows[0]["checks"])


def test_만원_표기는_지어낸_숫자가_아니다(chat):
    """실측 2026-08-25: 회식 별표4 원문이 "5만원"이라 payload의 50000이 「원문에 없는
    숫자」로 걸렸다 — **검사가 맞는 값을 틀렸다고 하면 사람이 검사를 안 믿게 된다.**"""
    chat([{
        "is_threshold_table": True, "skip_reason": "", "key": "dining_limit_table",
        "title": "별표4", "key_axes": [], "payload_json": json.dumps({"value": 50000}),
        "strict_keys": False, "confidence": 0.9, "notes": "", "comment": "",
    }])
    row = triage.extract_tables([FakeChunk("c1", "| 팀 회식 | 5만원 |")], AXES)[0]
    assert all(c["level"] != "warn" for c in row["checks"]), row["checks"]


def test_고쳐지지_않은_문제는_숨기지_않는다(chat):
    """재시도로도 안 풀리면 **승인 화면이 그대로 띄운다** — 조용히 통과시키지 않는다."""
    bad = {"is_threshold_table": True, "skip_reason": "", "key": "daily_limit_table",
           "title": "별표1", "key_axes": [], "payload_json": json.dumps({"value": 999999}),
           "strict_keys": False, "confidence": 0.9, "notes": "", "comment": ""}
    chat([bad, bad])
    rows = triage.extract_tables([FakeChunk("c1", "| 한도 | 30,000원 |")], AXES)
    warns = [c for c in rows[0]["checks"] if c["level"] == "warn"]
    assert warns and "999999" in warns[0]["message"]


def test_축의_값_어휘가_아니면_재시도한다(chat):
    """**축이 실재하기만 해서는 부족하다.** 실측 2026-08-25: 업무추진비 별표1이
    `category.value` 축으로 「검사 통과」였는데 키는 음식물·선물·경조사비였다 —
    그 축의 값으로는 절대 안 나오므로 룩업이 매번 `*`로 떨어진다(에러도 로그도 없다)."""
    axes = [
        {"path": "category.value", "type": "string", "desc": "비용분류",
         "values": ["회식", "회의", "식대", "출장", "접대", "기타"]},
        {"path": "category.item_type", "type": "string", "desc": "지출 세부유형",
         "values": ["식사", "선물", "경조사", "상품권", "행사성", "숙박", "교통"]},
    ]
    wrong = {"is_threshold_table": True, "skip_reason": "", "key": "kickback_limit_table",
             "title": "별표1", "key_axes": ["category.value"],
             "payload_json": json.dumps({"식사": 50000, "선물": 50000}),
             "strict_keys": False, "confidence": 0.9, "notes": "", "comment": ""}
    right = {**wrong, "key_axes": ["category.item_type"]}
    calls = chat([wrong, right])
    row = triage.extract_tables(
        [FakeChunk("c1", "| 구분 | 1인당 한도 |\n| 식사 | 50,000 |\n| 선물 | 50,000 |")], axes)[0]
    assert len(calls) == 2, "어휘가 안 맞으면 다시 만들게 한다"
    assert "category.value" in calls[1]["user"] and "식사" in calls[1]["user"]
    assert row["keyAxes"] == ["category.item_type"]
    assert all(c["level"] != "warn" for c in row["checks"])


def test_어휘_전체를_채우면_잡는다(chat):
    """실측 2026-08-25: 「키를 값 목록의 표기로 쓰라」는 지시를 모델이 **어휘 전체를 채우라**로
    읽어 `{"회식":50000,"회의":50000,...}`를 냈고 다른 검사를 전부 통과했다 — 조용히 틀렸는데
    ✅로 보이는, 이 검사들이 막으려던 바로 그 상태다."""
    axes = [{"path": "category.value", "type": "string", "desc": "비용분류",
             "values": ["회식", "회의", "식대", "출장", "접대", "기타"]}]
    flat = {"is_threshold_table": True, "skip_reason": "", "key": "kickback_limit_table",
            "title": "별표1", "key_axes": ["category.value"],
            "payload_json": json.dumps({v: 50000 for v in
                                        ["회식", "회의", "식대", "출장", "접대", "기타"]}),
            "strict_keys": False, "confidence": 0.9, "notes": "", "comment": ""}
    chat([flat, flat])
    raw = "| 구분 | 1인당 한도 |" + '\\n' + "| 음식물 | 50,000 |" + '\\n' + "| 선물 | 50,000 |"
    row = triage.extract_tables([FakeChunk("c1", raw)], axes)[0]
    warns = [c["message"] for c in row["checks"] if c["level"] == "warn"]
    assert any("찾을 수 없는 항목" in m for m in warns), warns


def test_축_어휘를_프롬프트에_보여준다(chat):
    """고를 수 있는 값을 안 보여주고 「목록에서 고르라」고만 하면 모델은 표 머리글을
    그대로 쓰고, 그 표기는 판정에서 영영 안 맞는다."""
    axes = [{"path": "category.item_type", "type": "string", "desc": "세부유형",
             "values": ["식사", "선물", "경조사"]}]
    calls = chat([{
        "is_threshold_table": True, "skip_reason": "", "key": "kickback_limit_table",
        "title": "별표1", "key_axes": ["category.item_type"],
        "payload_json": json.dumps({"식사": 50000}),
        "strict_keys": False, "confidence": 0.9, "notes": "", "comment": "",
    }])
    triage.extract_tables([FakeChunk("c1", "| 식사 | 50,000 |")], axes)
    assert "값: 식사 | 선물 | 경조사" in calls[0]["user"]


def test_활용_안내를_사람_말로_붙인다(chat):
    """승인하는 사람이 판단할 것은 「이 숫자가 맞나」만이 아니라 「어디에 쓰이나」다."""
    chat([{
        "is_threshold_table": True, "skip_reason": "", "key": "daily_limit_table",
        "title": "별표1", "key_axes": ["user.job_title"],
        "payload_json": json.dumps({"부장": 200000, "*": 100000}),
        "strict_keys": False, "confidence": 0.8, "notes": "", "comment": "직책별 한도입니다.",
    }])
    row = triage.extract_tables([FakeChunk("c1", "| 부장 | 200,000 | 100,000 |")], AXES)[0]
    assert "policy.daily_limit" in row["usageNote"]
    assert "user.job_title" in row["usageNote"]
    assert row["comment"] == "직책별 한도입니다."


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

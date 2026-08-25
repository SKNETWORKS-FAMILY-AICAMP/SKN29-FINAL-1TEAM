"""청킹 회귀 테스트 — `chunking-strategy.md` §10.

파싱 테스트와 같은 방식으로, docling을 재실행하지 않고 덤프(13종 4,561요소)에 교정 →
청킹을 걸어 계약을 고정한다.

여기서 고정하는 것은 **청크 개수 같은 숫자가 아니라 규칙**이다 — 유실 0, 표 원자성,
인용 정확성, 조 보존. 숫자는 예산 파라미터를 바꾸면 당연히 변한다.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.rag.chunking import chunk_document
from app.rag.chunking.model import Budget
from app.rag.parsing import dump
from app.rag.parsing.corrections import pipeline

from tests.dump_path import find_dump

DUMP_DIR = find_dump() or Path("docling_eval/output")   # None이면 아래 skipif가 잡는다
LAYOUT_CSV = DUMP_DIR / "layout" / "layout_result.csv"
TABLES_DIR = DUMP_DIR / "tables"

pytestmark = pytest.mark.skipif(
    not LAYOUT_CSV.exists(), reason="docling_eval 덤프가 없는 환경"
)

DOCS = [
    "법인카드_사용규정", "업무추진비_사용규정", "출장비_사용규정", "회식_운영규정",
    "법인세법", "부가가치세법", "여신전문금융업법",
    "부서소개", "조직도", "직급체계", "조직설계_상세기획서",
]
REGULATIONS = DOCS[:4]
LAWS = DOCS[4:7]


@pytest.fixture(scope="module")
def chunked() -> dict:
    """{문서명: (ParsedDoc, chunks, report)}"""
    out = {}
    for name, doc in dump.load_all(LAYOUT_CSV, TABLES_DIR).items():
        pipeline.run(doc)
        chunks, report = chunk_document(doc)
        out[name] = (doc, chunks, report)
    return out


# ── 유실·중복 ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", DOCS)
def test_no_content_loss(chunked, name):
    """본문 요소는 하나도 빠지지 않는다. 헤더로만 실린 요소는 참조로 계정한다."""
    doc, chunks, report = chunked[name]
    covered = {eid for c in chunks for eid in c.element_ids}
    covered |= {eid for c in chunks for eid in c.context_element_ids}
    missing = [e.element_id for e in doc.body()
               if e.text.strip() and not e.attrs.get("dropped") and e.element_id not in covered]
    assert not missing, f"{name}: 청크에 담기지 않은 요소 {len(missing)}건 {missing[:3]}"
    assert not report.uncovered_elements


@pytest.mark.parametrize("name", DOCS)
def test_each_element_owned_once(chunked, name):
    """소유(`element_ids`)는 정확히 한 청크. 중복 계상은 검색 결과 중복으로 이어진다."""
    _, chunks, _ = chunked[name]
    owned = [eid for c in chunks for eid in c.element_ids]
    assert len(owned) == len(set(owned)), f"{name}: 요소 소유 중복"


@pytest.mark.parametrize("name", DOCS)
def test_chunk_ids_unique(chunked, name):
    _, chunks, _ = chunked[name]
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids))


# ── 크기 예산 ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", DOCS)
def test_sizes_within_hard_limit(chunked, name):
    """hard(2,000자)를 넘는 청크는 없어야 한다 — 넘었다면 분할 사다리가 끊긴 것이다."""
    _, chunks, _ = chunked[name]
    over = [(c.chunk_id, c.size) for c in chunks
            if c.chunk_role != "parent" and c.size > Budget().hard]
    assert not over, f"{name}: hard 초과 {over[:3]}"


@pytest.mark.parametrize("name", DOCS)
def test_articles_split_only_when_they_must(chunked, name):
    """분할은 **예산 초과이거나 표가 끼었을 때만** 일어난다.

    이게 깨지면 "제9조 위반" 인용이 이유 없이 조각난 청크로 흩어진다. 실측상 규정 4종의
    조 블록은 대부분 예산 안에 들어오므로 조=청크가 유지된다.
    """
    _, chunks, _ = chunked[name]
    budget = Budget()
    for parent in (c for c in chunks if c.chunk_role == "parent"):
        children = [c for c in chunks if c.parent_chunk_id == parent.chunk_id]
        reason = parent.size > budget.max or any(c.has_table for c in children)
        assert reason, f"{name}: 이유 없이 쪼개진 블록 {parent.chunk_id} ({parent.size}자)"


def test_smaller_budget_produces_more_chunks(chunked):
    """예산은 실제로 작동하는 손잡이여야 한다."""
    doc = chunked["법인세법"][0]
    default, _ = chunk_document(doc)
    tight, _ = chunk_document(doc, Budget(target=300, max=500))
    assert len(tight) > len(default)


@pytest.mark.parametrize("kwargs", [
    dict(max=600),                          # target(기본 800)이 max를 넘는다
    dict(target=1500),                      # 같은 사고를 반대편에서
    dict(max=2400),                         # max > hard — 분할 사다리 마지막 칸이 죽는다
    dict(min_merge=900),                    # 꼬리 병합이 target을 삼킨다
])
def test_incoherent_budget_raises(kwargs):
    """예산 손잡이는 틀리면 **멈춰야** 한다 — 조용히 다르게 동작하면 안 된다(§10.2).

    실제 사고: `--max 600`만 주면 target이 기본값 800으로 남아 채우기 목표가 영영 안 걸린다.
    """
    with pytest.raises(ValueError):
        Budget(**kwargs)


# ── 인용·계층 ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", DOCS)
def test_every_chunk_carries_citation_and_header(chunked, name):
    """청크 하나만 검색돼도 출처를 말할 수 있어야 한다(FR-RV)."""
    _, chunks, _ = chunked[name]
    for chunk in chunks:
        assert chunk.citation.startswith(name), f"{name}: 인용 누락 {chunk.chunk_id}"
        assert name in chunk.header
        assert chunk.context_text().startswith(chunk.header)


@pytest.mark.parametrize("name", REGULATIONS + LAWS)
def test_article_citation_matches_article_label(chunked, name):
    """`제55조의2`가 `제55조`로 접히면 다른 조가 된다 — 원문 표기를 지킨다."""
    _, chunks, _ = chunked[name]
    for chunk in (c for c in chunks if c.article_label):
        assert chunk.article_label in chunk.citation
        assert chunk.article_label in chunk.header


@pytest.mark.parametrize("name", DOCS)
def test_clause_range_is_ordered(chunked, name):
    """'제3~2항' 같은 역순 인용을 금지한다."""
    _, chunks, _ = chunked[name]
    for chunk in chunks:
        if chunk.clause_start is not None and chunk.clause_end is not None:
            assert chunk.clause_start <= chunk.clause_end, chunk.chunk_id


@pytest.mark.parametrize("name", REGULATIONS)
def test_clause_kind_follows_the_articles_own_wording(chunked, name):
    """항/호 호칭은 **조 단위**로 정한다 — 도입부에 `각 호`가 있는 조만 `호`다(§11 ④).

    프로파일 하나로 `호`를 박아 두면 규정 4종의 조 27개 중 26개에서 틀린 호칭이 인용
    문자열로 나간다(📏 검수 노트북이 자기인용 표기 역산으로 확인). 여기서 고정하는 것은
    개수가 아니라 **판정 근거가 원문이라는 것**이다.
    """
    doc, chunks, _ = chunked[name]
    intros: dict[int, str] = {}
    for el in doc.body():
        article = el.attrs.get("article_no")
        if article is not None and el.attrs.get("clause_no") is None:
            intros[article] = intros.get(article, "") + " " + el.text
    for chunk in (c for c in chunks if c.clause_kind and c.article_no is not None):
        expected = "호" if re.search(r"각\s?호", intros.get(chunk.article_no, "")) else "항"
        assert chunk.clause_kind == expected, (
            f"{name}: {chunk.article_label} 호칭 {chunk.clause_kind} (원문 근거 {expected})")
        assert f"{chunk.clause_start}" in chunk.citation


def test_regulation_clause_kind_is_article_scoped(chunked):
    """같은 문서 안에서도 조마다 호칭이 갈린다 — 회식 규정이 그 증거다(`각 호` 1개 조)."""
    kinds = set()
    for name in REGULATIONS:
        _, chunks, _ = chunked[name]
        kinds |= {c.clause_kind for c in chunks if c.clause_kind}
    assert kinds == {"항", "호"}, f"규정 전체가 한 호칭으로 뭉뚱그려졌다: {kinds}"


@pytest.mark.parametrize("name", LAWS)
def test_law_clauses_are_always_hang(chunked, name):
    """법령의 `clause_no`는 원문자 `①②③`(파싱 C3)이 원천이라 예외 없이 `항`이다."""
    _, chunks, _ = chunked[name]
    kinds = {c.clause_kind for c in chunks if c.clause_kind}
    assert kinds <= {"항"}, f"{name}: 법령에 항 아닌 호칭 {kinds}"


@pytest.mark.parametrize("name", LAWS)
def test_article_starting_in_body_opens_its_own_block(chunked, name):
    """법령은 조의 상당수가 heading이 아니라 paragraph로 나온다(`제17조(…) ① …`).

    헤딩만 경계로 삼으면 그 조가 앞 조의 청크에 흡수돼 **남의 조문으로 인용**된다
    (실측 회귀: 조 경계 위반 64건). 본문형 조 시작도 블록을 열어야 한다.
    """
    _, chunks, report = chunked[name]
    assert report.splits.get("article_start_in_body", 0) > 0
    labels = [c.article_label for c in chunks if c.chunk_role == "parent" or c.chunk_role == "atomic"]
    assert len(set(labels)) > 1


@pytest.mark.parametrize("name", DOCS)
def test_no_citation_misattribution(chunked, name):
    """청크가 소유한 요소는 그 청크가 인용한 조에 속해야 한다.

    파싱이 붙인 `article_no`와 대조한다. 어긋나면 "제N조 위반"이라는 근거 제시가 거짓이 된다.
    **예외 1건**: `제6조(사용 승인)·제7조(기록 사항)를 적용한다`처럼 조문 참조로 시작하는
    **연속 문장**에 C2가 그 조 번호를 붙여 둔 것(파싱 쪽 태깅 잔재이지 청킹의 오귀속이 아니다).
    """
    doc, chunks, _ = chunked[name]
    articles = {e.element_id: e.attrs.get("article_no") for e in doc.elements}
    bad = []
    for c in chunks:
        if c.chunk_role == "parent" or c.article_no is None:
            continue
        others = {articles.get(e) for e in c.element_ids} - {None, c.article_no}
        if others:
            bad.append((c.chunk_id, c.article_label, sorted(others)))
    assert len(bad) <= 1, f"{name}: 인용 오귀속 {bad[:3]}"


def test_law_front_matter_gets_no_article_citation(chunked):
    """법령 표지의 조 제목 나열이 조문 인용으로 둔갑하면 안 된다(실측 회귀: 제55조의2)."""
    _, chunks, report = chunked["법인세법"]
    front = [c for c in chunks if c.chunk_type == "preamble"]
    assert front, "표지 블록이 조로 흡수됐다"
    assert all(c.article_label is None for c in front)
    assert report.splits.get("suspect_article_heading", 0) >= 1


@pytest.mark.parametrize("name", ["부서소개", "조직도", "직급체계", "조직설계_상세기획서"])
def test_diagram_docs_claim_no_article_hierarchy(chunked, name):
    """도해형에는 조 체계가 없다. 없는 계층을 지어내면 인용이 거짓이 된다."""
    _, chunks, _ = chunked[name]
    assert all(c.article_no is None for c in chunks)


# ── 표·별표 ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", DOCS)
def test_tables_are_atomic(chunked, name):
    """표 청크는 표 요소 하나만 소유한다 — 본문과 섞이면 값 조회가 오염된다.

    도입 문장은 `context_element_ids`로 복제해 붙일 뿐 소유하지 않는다.
    """
    doc, chunks, _ = chunked[name]
    types = {e.element_id: e.type for e in doc.elements}
    for chunk in (c for c in chunks if c.has_table and c.chunk_role != "parent"):
        owned = [types.get(eid) for eid in chunk.element_ids]
        assert owned.count("table") == 1, f"{name}: 표 청크 소유 이상 {chunk.chunk_id} {owned}"
        assert all(t in ("table", "heading", "title", "caption") for t in owned), owned


def test_limit_table_survives_as_one_chunk(chunked):
    """직책별 한도표는 룰 임계값의 원천이다. 한 청크 안에 전 행이 있어야 한다."""
    _, chunks, _ = chunked["법인카드_사용규정"]
    hits = [c for c in chunks if "대표이사" in c.text and "300만원" in c.text]
    assert hits, "한도표 청크를 찾지 못했다"
    table = hits[0]
    for role in ("대표이사", "본부장", "부서장", "팀장", "비직책자"):
        assert role in table.text, f"한도표에서 {role} 행이 사라졌다"
    assert "별표" in table.header


def test_split_table_repeats_header():
    """행 분할이 일어나면 모든 조각에 헤더행이 반복돼야 한다."""
    from app.rag.parsing.model import Element, ParseReport, ParsedDoc

    grid = [["구분", "한도"]] + [[f"항목{i}", f"{i}만원"] for i in range(1, 12)]
    table = Element("t:p1:e1", "table", "", 1, 1,
                    attrs={"grid": grid, "rows": len(grid), "cols": 2, "header_rows": 1})
    doc = ParsedDoc("t", "테스트", "GENERIC", [table], report=ParseReport())
    chunks, _ = chunk_document(doc, Budget(table_max_rows=5))
    parts = [c for c in chunks if "table_row_split" in c.flags]
    assert len(parts) == 3
    assert all(part.text.count("구분") == 1 for part in parts)
    assert all("한도" in part.text for part in parts)


# ── Parent-Child ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", DOCS)
def test_parent_child_wiring(chunked, name):
    """자식은 반드시 부모를 가리키고, 부모 본문은 자식 본문을 모두 포함한다."""
    _, chunks, _ = chunked[name]
    by_id = {c.chunk_id: c for c in chunks}
    for child in (c for c in chunks if c.chunk_role == "child"):
        assert child.parent_chunk_id in by_id, f"{name}: 부모 없는 자식 {child.chunk_id}"
        parent = by_id[child.parent_chunk_id]
        assert parent.chunk_role == "parent"
        assert child.text in parent.text
    for parent in (c for c in chunks if c.chunk_role == "parent"):
        assert not parent.element_ids, "부모가 요소를 소유하면 커버리지가 이중 계상된다"
        assert len([c for c in chunks if c.parent_chunk_id == parent.chunk_id]) >= 2


@pytest.mark.parametrize("name", DOCS)
def test_neighbor_chain_excludes_parents(chunked, name):
    """오버랩 대신 이웃 확장을 쓰므로 prev/next 체인이 끊기면 안 된다(§8)."""
    _, chunks, _ = chunked[name]
    chain = [c for c in chunks if c.chunk_role != "parent"]
    for prev, nxt in zip(chain, chain[1:]):
        assert prev.next_chunk_id == nxt.chunk_id
        assert nxt.prev_chunk_id == prev.chunk_id


def test_parent_embedding_text_is_truncated(chunked):
    """부모 전문을 그대로 임베딩하면 긴 조문에서 벡터가 평균화된다(§7.3)."""
    _, chunks, _ = chunked["법인세법"]
    parents = [c for c in chunks if c.chunk_role == "parent" and c.size > 2000]
    assert parents
    assert len(parents[0].embedding_text()) < len(parents[0].context_text())


# ── Chroma 계약 ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", DOCS)
def test_chroma_metadata_is_scalar_only(chunked, name):
    """Chroma 메타데이터는 스칼라만 받는다. 리스트가 새면 upsert가 런타임에 죽는다."""
    _, chunks, _ = chunked[name]
    for chunk in chunks:
        cid, document, meta = chunk.to_chroma()
        assert cid and document
        for key, value in meta.items():
            assert isinstance(value, (str, int, float, bool)), f"{key}={value!r}"


def test_noise_chunks_are_flagged_not_dropped(chunked):
    """목차 잔재는 표시만 하고 지우지 않는다 — 삭제 판단은 인덱싱 정책의 몫이다."""
    _, chunks, _ = chunked["법인세법"]
    assert any("toc_like" in c.flags for c in chunks)


@pytest.mark.parametrize("name", DOCS)
def test_annex_citation_names_the_annex(chunked, name):
    """별표 인용이 문서명뿐이면 어느 별표인지 알 수 없다 — 한도표가 룰 임계값의 원천이다.

    `article_label`이 `제N조`만 알던 시절 별표 청크의 인용은 `법인카드_사용규정`으로만
    나왔고, 한 문서에 별표가 둘 이상이면(업무추진비 별표1·별표2) 근거를 특정하지 못했다.
    """
    _, chunks, _ = chunked[name]
    for chunk in chunks:
        if chunk.chunk_type != "annex":
            continue
        assert chunk.article_label, f"{chunk.chunk_id}: 별표 라벨 없음"
        assert chunk.article_label in chunk.citation, (
            f"{chunk.chunk_id}: 인용에 별표가 빠졌다 — {chunk.citation!r}"
        )

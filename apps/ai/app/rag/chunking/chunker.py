"""구조 기반 청킹 — `llm_wiki/_context/chunking-strategy.md` §6.

한 줄 요약: **자르는 단위는 조(條)다. 문자 수는 조가 너무 클 때만 개입한다.**

파싱이 이미 장·조·항 계층을 복원해 뒀으므로(`attrs["chapter_no"]`·`["article_no"]`·
`["clause_no"]`) 청킹이 다시 텍스트를 해석할 이유가 없다. 실측이 이 선택을 지지한다 —
문단 요소 중앙값이 76자(61%가 100자 미만)라 요소 단위로는 검색이 안 되고, 조 블록
중앙값은 449자로 임베딩 한 덩어리에 맞는다. 조의 79%는 1,200자 안에 통째로 들어간다.

분할이 필요할 때의 경계도 지어내지 않는다. 항(項) 서브블록 p90이 420자이므로 **항 경계가
곧 안전한 2차 분할선**이고, 그마저 넘치는 것은 실측 1.3%뿐이다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.rag.chunking import serialize
from app.rag.chunking.model import Budget, Chunk, ChunkReport, ChunkType, DEFAULT_BUDGET
from app.rag.parsing.model import Element, ParsedDoc

_SENTENCE = re.compile(r"(?<=[.!?])\s+|(?<=다\.)\s*")
_ARTICLE_MENTION = re.compile(r"제\s*\d+\s*조")
_EACH_ITEM = re.compile(r"각\s?호")


@dataclass
class _Block:
    """조 하나(또는 별표·서문) 분량의 요소 묶음. 청크의 상위 단위다."""

    kind: ChunkType
    heading: Element | None
    elements: list[Element] = field(default_factory=list)
    chapter_no: int | None = None
    chapter_title: str | None = None
    key: str = ""
    chapter_el: Element | None = None       # 헤더 문자열로만 소비되는 장 헤딩

    def all_elements(self) -> list[Element]:
        return ([self.heading] if self.heading else []) + self.elements


@dataclass
class _Unit:
    """청크 하나가 될 텍스트 조각. 어느 요소에서 왔는지를 항상 들고 다닌다."""

    text: str
    elements: list[Element]
    clause_start: int | None = None
    clause_end: int | None = None
    flags: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- 블록 분해

_FIRST_BODY = re.compile(r"^제\s*1\s*[장조]")
# 헤딩이 아닌 요소가 조 시작으로 인정받으려면 괄호 제목(또는 `삭제`)까지 있어야 한다 —
# 본문 중 조문 참조(`제55조의2에 따른 …`)를 조 시작으로 오인하면 조문이 산산조각 난다.
_ARTICLE_START_STRICT = re.compile(r"^제\s*\d+\s*조(?:\s*의\s*\d+)?\s*(?:[(（]|삭제)")


def _front_matter_cut(elements: list[Element], profile: str, span: float = 0.15) -> int:
    """법령 표지가 끝나는 지점(첫 `제1장`/`제1조` 헤딩)의 인덱스. 못 찾으면 0.

    앞부분 `span` 이내에서만 찾는다 — 문서 중간의 `제1조`(부칙의 제1조)에 걸리면 본문
    전체가 표지로 삼켜지기 때문이다. 찾지 못하면 아무것도 하지 않는다(무해한 실패).
    """
    if profile != "LAW":
        return 0
    limit = max(int(len(elements) * span), 1)
    for idx, el in enumerate(elements[:limit]):
        if el.type in ("heading", "title") and _FIRST_BODY.match(el.text.strip()):
            return idx
    return 0


def _article_starts(elements: list[Element]) -> tuple[list[Element], set[int]]:
    """조가 시작되는 요소들과, 그중 오배치가 의심되는 것들(`id()` 집합).

    **조 헤딩만 보면 안 된다** 📏 — 법령 PDF에서는 조의 상당수가 `heading`이 아니라
    `paragraph`로 나온다(`제17조(자본거래로 인한 수익의 익금불산입) ① …`). 헤딩만 경계로
    삼으면 그 조가 **앞 조의 청크에 흡수돼 남의 조문으로 인용**된다(실측 64건).

    다만 본문 중간의 조문 **참조**(`제55조의2에 따른 토지등 양도소득`)를 조 시작으로 오인하면
    조문이 산산조각 난다. 그래서 헤딩이 아닌 요소에는 **괄호 제목까지** 요구하고, 그 위에
    번호 단조성 검사를 건다.
    """
    candidates: list[Element] = []
    for el in elements:
        text = el.text.strip()
        if el.type in ("heading", "title"):
            if serialize.ARTICLE_LABEL.match(text):
                candidates.append(el)
        elif _ARTICLE_START_STRICT.match(text):
            candidates.append(el)

    # 단조성 검사는 **별표·부칙 경계로 끊어서** 한다. 부칙은 조 번호가 제1조부터 다시
    # 시작하므로(파싱 C2와 같은 계약), 끊지 않으면 본문 마지막 조들이 전부 의심으로 몰린다.
    candidate_ids = {id(el) for el in candidates}
    segments: list[list[Element]] = [[]]
    for el in elements:
        if el.attrs.get("annex") or serialize.ANNEX_LABEL.match(el.text.strip()):
            segments.append([])
        if id(el) in candidate_ids:
            segments[-1].append(el)

    suspect: set[int] = set()
    for segment in segments:
        numbers = [int(serialize.ARTICLE_LABEL.match(c.text.strip()).group(1)) for c in segment]
        for i, (cand, num) in enumerate(zip(segment, numbers)):
            following = numbers[i + 1: i + 4]
            if following and num > min(following):
                # 뒤에 더 작은 번호가 온다 = 표지·러닝헤더·문장 중간 참조. 블록을 열지 않는다.
                suspect.add(id(cand))
    return candidates, suspect


def _blocks(doc: ParsedDoc, report: ChunkReport) -> list[_Block]:
    """요소 열 → 블록 열. 장은 블록이 아니라 **컨텍스트**다.

    실측 근거: 장 헤딩 단독 섹션은 규정 4종에서 6자짜리로 나온다(제목 한 줄뿐). 장을 청크로
    만들면 내용 없는 청크가 검색 상위에 뜬다. 장은 헤더 문자열과 메타로만 살린다.
    """
    blocks: list[_Block] = []
    cur: _Block | None = None
    chapter_no: int | None = None
    chapter_title: str | None = None
    chapter_el: Element | None = None
    pending_chapter: Element | None = None
    counters = {"article": 0, "annex": 0, "section": 0}

    def open_block(kind: ChunkType, heading: Element | None) -> _Block:
        nonlocal cur
        bucket = kind if kind in counters else "section"
        counters[bucket] += 1
        idx = counters[bucket]
        prefix = {"article": "a", "annex": "x", "section": "s", "preamble": "s"}[kind]
        key = f"c{chapter_no or 0:02d}{prefix}{idx:03d}" if kind == "article" else f"{prefix}{idx:03d}"
        cur = _Block(kind, heading, [], chapter_no, chapter_title, key, chapter_el)
        blocks.append(cur)
        return cur

    elements = [el for el in doc.body() if not el.attrs.get("dropped")]
    front = _front_matter_cut(elements, doc.profile)
    if front:
        report.bump(report.splits, "front_matter", front)
    starts, suspect = _article_starts(elements)
    start_ids = {id(el) for el in starts}

    for idx, el in enumerate(elements):
        text = el.text.strip()

        if idx < front:
            # 법령 표지(문서명·시행일·소관부서·`<picture>`)는 조문이 아니다. 조 헤딩처럼 생긴
            # 것이 표지에 섞여 있으면 뒤따르는 표지 전체가 그 조의 인용으로 둔갑한다
            # (실측: 법인세법 표지가 통째로 '제55조의2'로 인용됐다).
            if cur is None:
                open_block("preamble", None)
            cur.elements.append(el)
            continue

        if el.type in ("heading", "title") or (
            el.type == "caption" and serialize.ANNEX_LABEL.match(text)
        ):
            if el.attrs.get("annex") or serialize.ANNEX_LABEL.match(text):
                # 별표·부칙은 장 소속이 아닌 최상위 형제다 (파싱 §5 C2 예외 3과 같은 계약).
                chapter_no = chapter_title = chapter_el = None
                pending_chapter = None
                open_block("annex", el)
                continue
            if serialize.CHAPTER_LABEL.match(text):
                chapter_no = el.attrs.get("chapter_no")
                chapter_title, chapter_el = text, el
                pending_chapter, cur = el, None
                continue
            if serialize.ARTICLE_LABEL.match(text):
                if id(el) in suspect:
                    report.bump(report.splits, "suspect_article_heading")
                    if cur is None:
                        open_block("preamble", None)
                    cur.elements.append(el)
                    continue
                pending_chapter = None
                open_block("article", el)
                continue
            if doc.profile == "LAW" and cur is not None:
                # 법령 헤딩 오염(`12. 30.>`·문서명 반복 — 실측 188헤딩 vs 182조)에 블록을
                # 새로 열면 조문이 조각난다. 본문으로 흡수하고 세어만 둔다.
                cur.elements.append(el)
                report.bump(report.splits, "polluted_heading")
                continue
            pending_chapter = None
            open_block("section", el)
            continue

        if id(el) in start_ids:
            # 헤딩이 아닌 조 시작(법령 다수) — 앞 조에 흡수되면 남의 조문으로 인용된다.
            if id(el) in suspect:
                report.bump(report.splits, "suspect_article_ref")
            else:
                pending_chapter = None
                report.bump(report.splits, "article_start_in_body")
                open_block("article", el)
                continue

        if cur is None:
            open_block("section" if pending_chapter else "preamble", pending_chapter)
            pending_chapter = None
        cur.elements.append(el)

    return blocks


# ---------------------------------------------------------------- 텍스트 단위 분할

def _clause_groups(elements: list[Element]) -> list[list[Element]]:
    """항/호 마커가 붙은 요소에서 새 그룹을 연다. 마커 없는 요소는 앞 그룹에 붙는다."""
    groups: list[list[Element]] = []
    cur: list[Element] = []
    for el in elements:
        if el.attrs.get("clause_no") is not None and cur:
            groups.append(cur)
            cur = [el]
        else:
            cur.append(el)
    if cur:
        groups.append(cur)
    return groups


def _sentence_split(text: str, budget: Budget) -> list[str]:
    """최후 수단. 문장 경계로 자르고, 그래도 넘치면 문자로 자른다."""
    out: list[str] = []
    buf = ""
    for sent in _SENTENCE.split(text):
        if not sent:
            continue
        if buf and len(buf) + len(sent) > budget.target:
            out.append(buf.strip())
            buf = ""
        buf += sent
    if buf.strip():
        out.append(buf.strip())
    final: list[str] = []
    for piece in out:
        while len(piece) > budget.hard:
            final.append(piece[: budget.hard])
            piece = piece[budget.hard:]
        final.append(piece)
    return [p for p in final if p]


def _pack(groups: list[list[Element]], budget: Budget) -> list[list[Element]]:
    """항 그룹을 target까지 채워 담는다. 꼬리 조각(<min_merge)은 앞 청크에 붙인다."""
    packed: list[list[Element]] = []
    cur: list[Element] = []
    size = 0
    for group in groups:
        gsize = sum(len(e.text) + 1 for e in group)
        if cur and size + gsize > budget.max:
            packed.append(cur)
            cur, size = [], 0
        cur += group
        size += gsize
        if size >= budget.target:
            packed.append(cur)
            cur, size = [], 0
    if cur:
        if packed and size < budget.min_merge:
            packed[-1] += cur
        else:
            packed.append(cur)
    return packed


def _units(elements: list[Element], budget: Budget, report: ChunkReport) -> list[_Unit]:
    """요소 열 → 청크 단위 열. 계층 경계를 다 쓰고 나서야 문자 기준으로 내려간다."""
    text = "\n".join(e.text for e in elements if e.text.strip())
    if not text.strip():
        return []
    if len(text) <= budget.max:
        return [_make_unit(elements)]

    packed = _pack(_clause_groups(elements), budget)
    report.bump(report.splits, "clause", len(packed) - 1)

    def emit(group: list[Element]) -> list[_Unit]:
        joined = "\n".join(e.text for e in group if e.text.strip())
        if len(joined) <= budget.hard:
            return [_make_unit(group)]
        if len(group) > 1:
            # 호(list_item) 경계로 한 번 더 — 요소 경계는 절대 넘지 않는다.
            report.bump(report.splits, "list_item", len(group) - 1)
            return [u for el in group for u in emit([el])]
        # 요소 **하나**가 hard를 넘을 때만 문장 분할로 내려간다.
        pieces = _sentence_split(joined, budget)
        report.bump(report.splits, "sentence", len(pieces) - 1)
        return [_Unit(p, group, _clause_of(group), _clause_of(group, last=True), ["hard_split"])
                for p in pieces]

    return [unit for group in packed for unit in emit(group)]


def _clause_of(elements: list[Element], last: bool = False) -> int | None:
    """항 범위. 문서 순서가 아니라 **최소·최대**로 잡는다 — 순서로 잡으면 '제3~2항'이 나온다.

    실측: 법령에서 원문자 항이 뒤섞여 배치된 요소가 있어 `nums[-1] < nums[0]`인 묶음이 생긴다.
    """
    nums = [e.attrs["clause_no"] for e in elements if e.attrs.get("clause_no") is not None]
    if not nums:
        return None
    return max(nums) if last else min(nums)


def _clause_kind(profile: str, block: _Block) -> str:
    """이 조의 하위 단위를 뭐라 부르는가 — `항`인가 `호`인가 (전략 §11 ④ 확정).

    **프로파일로 뭉뚱그리지 않는다. 판정은 조 단위다.** 📏 검수 노트북이 관례를 추측하는
    대신 규정이 **자기 항목을 인용할 때의 표기**를 역산해 답을 냈다(`제4조제2항의 부서
    공용카드는 …`) — 규정 4종의 조 27개 중 **26개가 `항`**이고, `호`가 맞는 것은 도입부에
    `다음 각 호`가 있는 회식 제8조 **하나뿐**이었다. 프로파일 하나로 `호`를 박아 두면
    26개 조에서 틀린 호칭이 회계 담당자 화면의 인용 문자열로 그대로 나간다(FR-RV).

    그래서 근거는 **도입부**(항 번호가 안 붙은 요소들)의 `각 호` 유무 하나다. 법령은
    예외 없이 `항`이다 — `clause_no`의 원천이 원문자 `①②③`(파싱 C3)이라 애초에 항이다.
    """
    if profile == "LAW":
        return "항"
    intro = " ".join(e.text for e in block.all_elements()
                     if e.attrs.get("clause_no") is None)
    return "호" if _EACH_ITEM.search(intro) else "항"


def _toc_like(text: str) -> bool:
    """조 제목 나열(목차 잔재) 판정. C4가 걷어내지 못한 문단형 목차가 여기 걸린다.

    지우지 않고 **표시만** 한다 — 삭제 판단은 인덱싱 정책의 몫이고, 조용한 삭제는 금지다.
    """
    mentions = len(_ARTICLE_MENTION.findall(text))
    return mentions >= 3 and mentions * 40 > len(text)


def _make_unit(elements: list[Element]) -> _Unit:
    text = "\n".join(e.text for e in elements if e.text.strip())
    flags = ["marker_uncertain"] if any(e.attrs.get("marker_uncertain") for e in elements) else []
    return _Unit(text, elements, _clause_of(elements), _clause_of(elements, last=True), flags)


# ---------------------------------------------------------------- 청크 조립

def chunk_document(doc: ParsedDoc, budget: Budget = DEFAULT_BUDGET) -> tuple[list[Chunk], ChunkReport]:
    """`ParsedDoc` → 청크 열 + 리포트."""
    report = ChunkReport(doc_name=doc.name, profile=doc.profile, budget=budget)
    trust_chapter = not any(w.startswith("C2") for w in doc.report.warnings)
    if not trust_chapter:
        report.warnings.append("C2 경고 — 장 계층을 신뢰할 수 없어 조를 최상위로 둔다(파싱 §9)")

    chunks: list[Chunk] = []
    carry: list[Element] = []       # 본문 없는 헤딩 — 다음 청크의 경로·참조로 넘긴다

    for block in _blocks(doc, report):
        made = _chunk_block(doc, block, budget, report, trust_chapter,
                            [e.text.strip() for e in carry])
        if not made:
            carry += block.all_elements()
            continue
        for chunk in made:
            chunk.context_element_ids += [e.element_id for e in carry]
        carry = []
        chunks += made
    if carry and chunks:
        chunks[-1].context_element_ids += [e.element_id for e in carry]

    _link(chunks)
    _verify_coverage(doc, chunks, report)
    for chunk in chunks:
        report.bump(report.counts, chunk.chunk_type)
    return chunks, report


def _chunk_block(doc: ParsedDoc, block: _Block, budget: Budget, report: ChunkReport,
                 trust_chapter: bool,
                 carry_titles: list[str] | None = None) -> list[Chunk]:
    clause_kind = _clause_kind(doc.profile, block)
    heading = block.heading
    head_text = heading.text.strip() if heading else ""
    label = serialize.article_label(head_text, heading.attrs.get("article_no")) if heading else None
    title = serialize.article_title(head_text) if heading and label else head_text or None
    article_head = title if block.kind == "article" else head_text or None
    chapter_title = block.chapter_title if trust_chapter else None
    # 본문 없는 헤딩(문서 제목·`제1절 통칙`)은 청크가 되지 않고 다음 블록의 경로에 얹힌다.
    path_head = " > ".join([p for p in [chapter_title, *(carry_titles or [])] if p]) or None

    # 헤딩 텍스트가 제목 이상을 담고 있으면(법령은 조 제목 줄에 ①항 본문이 붙는다) 본문에 넣는다.
    body: list[Element] = list(block.elements)
    if heading and label and title and len(head_text) > len(title) + 2:
        body = [heading] + body

    # 표는 언제나 독립 청크다(§6.4). 룰 임계값의 원천이라 다른 문장과 섞이면 안 된다.
    runs: list[tuple[str, list[Element]]] = []
    for el in body:
        kind = "table" if el.type == "table" else "text"
        if runs and runs[-1][0] == kind == "text":
            runs[-1][1].append(el)
        else:
            runs.append((kind, [el]))

    made: list[Chunk] = []
    seq = 0

    def new_chunk(unit: _Unit, ctype: ChunkType, extra_flags: list[str] | None = None,
                  context_els: list[Element] | None = None) -> Chunk:
        nonlocal seq
        seq += 1
        owned = unit.elements
        pages = [e.page for e in owned if e.page]
        cite = serialize.citation(doc.name, label,
                                  clause_kind if unit.clause_start is not None else None,
                                  unit.clause_start, unit.clause_end)
        chunk = Chunk(
            chunk_id=f"{doc.doc_id}#{block.key}#{seq:02d}",
            doc_id=doc.doc_id, doc_name=doc.name, profile=doc.profile,
            chunk_type=ctype, chunk_role="atomic",
            text=unit.text,
            header=serialize.header(doc.name, doc.meta, path_head, article_head, cite),
            citation=cite,
            page_start=min(pages, default=0), page_end=max(pages, default=0),
            chapter_no=block.chapter_no if trust_chapter else None,
            chapter_title=chapter_title,
            article_no=heading.attrs.get("article_no") if heading else None,
            article_label=label, article_title=title,
            clause_kind=clause_kind if unit.clause_start is not None else None,
            clause_start=unit.clause_start, clause_end=unit.clause_end,
            element_ids=[e.element_id for e in owned],
            context_element_ids=[e.element_id for e in (context_els or [])],
            has_table=any(e.type == "table" for e in owned),
            has_list=any(e.type == "list_item" for e in owned),
            flags=unit.flags + (extra_flags or []),
            meta=dict(doc.meta),
        )
        made.append(chunk)
        return chunk

    for kind, els in runs:
        if kind == "text":
            for unit in _units(els, budget, report):
                if block.kind == "preamble" and _toc_like(unit.text):
                    unit.flags.append("toc_like")   # 목차 잔재 — 인덱싱에서 제외 대상(§9.2)
                new_chunk(unit, "clause" if block.kind == "article" else block.kind)
        else:
            _table_chunks(els[0], block, body, budget, report, new_chunk)

    if not made:
        # 본문 없는 조(`제50조의9 삭제 <2020. 3. 24.>`)는 그 자체가 답이다 — 작게라도 남긴다.
        if block.kind == "article" and head_text:
            new_chunk(_Unit(head_text, [heading]), "article")
        else:
            return []

    # 헤딩·장 헤딩은 본문에 다시 쓰이지 않아도 **유실이 아니다** — 헤더 문자열로 살아 있다.
    # 커버리지 계정을 정직하게 유지하려고 소유/참조를 명시해 둔다.
    if heading and not any(heading.element_id in c.element_ids for c in made):
        # 표 청크는 표 요소 하나만 소유한다(§6.4) — 헤딩은 본문 청크 쪽에 얹는다.
        host = next((c for c in made if not c.has_table), made[0])
        host.element_ids.insert(0, heading.element_id)
    if block.chapter_el and trust_chapter:
        for chunk in made:
            chunk.context_element_ids.append(block.chapter_el.element_id)

    # 조가 한 청크로 끝났으면 그게 곧 원자 단위다. 쪼개진 경우에만 parent를 만든다(§6.5).
    if len(made) == 1:
        if block.kind == "article" and made[0].chunk_type == "clause":
            made[0].chunk_type = "article"
        return made

    parent = _parent_chunk(doc, block, made, label, title, article_head, chapter_title,
                           trust_chapter, budget)
    for chunk in made:
        chunk.chunk_role = "child"
        chunk.parent_chunk_id = parent.chunk_id
    return [parent] + made


def _table_chunks(el: Element, block: _Block, body: list[Element], budget: Budget,
                  report: ChunkReport, new_chunk) -> None:
    """표 청크. 도입 문장을 복제해 붙이고, 40행을 넘으면 헤더행을 반복하며 행 분할한다.

    청크는 `new_chunk` 클로저가 블록 목록에 직접 담는다(반환값 없음).
    """
    prior = body[: body.index(el)]
    lead = serialize.lead_in(prior, budget.lead_in_max)
    rows = int(el.attrs.get("rows") or 0)
    header_rows = int(el.attrs.get("header_rows") or 1)
    body_rows = max(rows - header_rows, 0)
    ctype: ChunkType = "annex" if block.kind == "annex" else "table"

    if body_rows <= budget.table_max_rows and not el.attrs.get("split_on_chunk"):
        text = f"{lead}\n\n{serialize.table_markdown(el)}" if lead else serialize.table_markdown(el)
        new_chunk(_Unit(text, [el]), ctype, context_els=prior[-1:] if lead else None)
        return

    step = budget.table_max_rows
    parts = range(0, body_rows, step)
    for start in parts:
        part = serialize.table_markdown(el, (start, start + step))
        span = f"({start + 1}~{min(start + step, body_rows)}행 / 총 {body_rows}행)"
        text = f"{lead}\n{span}\n\n{part}" if lead else f"{span}\n\n{part}"
        new_chunk(_Unit(text, [el]), ctype, extra_flags=["table_row_split"],
                  context_els=prior[-1:] if lead else None)
    report.bump(report.splits, "table_rows", len(parts) - 1)


def _parent_chunk(doc: ParsedDoc, block: _Block, children: list[Chunk], label, title,
                  article_head, chapter_title, trust_chapter: bool, budget: Budget) -> Chunk:
    """조 전체를 담는 상위 청크. 자식이 검색되면 이걸로 문맥을 넓힌다(§6.5)."""
    cite = serialize.citation(doc.name, label, None, None, None)
    pages = [c.page_start for c in children if c.page_start] + [c.page_end for c in children]
    return Chunk(
        chunk_id=f"{doc.doc_id}#{block.key}#P",
        doc_id=doc.doc_id, doc_name=doc.name, profile=doc.profile,
        chunk_type="article" if block.kind == "article" else block.kind,
        chunk_role="parent",
        text="\n\n".join(c.text for c in children),
        header=serialize.header(doc.name, doc.meta, chapter_title, article_head, cite),
        citation=cite,
        page_start=min(pages, default=0), page_end=max(pages, default=0),
        chapter_no=block.chapter_no if trust_chapter else None,
        chapter_title=chapter_title,
        article_no=block.heading.attrs.get("article_no") if block.heading else None,
        article_label=label, article_title=title,
        element_ids=[],                                   # 소유는 자식이 한다 — 커버리지 이중계상 방지
        context_element_ids=[i for c in children for i in c.element_ids],
        has_table=any(c.has_table for c in children),
        has_list=any(c.has_list for c in children),
        flags=["parent"],
        meta=dict(doc.meta),
    )


def _link(chunks: list[Chunk]) -> None:
    """이웃 링크. 오버랩 대신 **검색 시점 이웃 확장**으로 문맥을 넓힌다(§8)."""
    chain = [c for c in chunks if c.chunk_role != "parent"]
    for prev, nxt in zip(chain, chain[1:]):
        prev.next_chunk_id = nxt.chunk_id
        nxt.prev_chunk_id = prev.chunk_id


def _verify_coverage(doc: ParsedDoc, chunks: list[Chunk], report: ChunkReport) -> None:
    """본문 요소가 하나라도 청크에 안 들어갔으면 리포트에 남긴다 — 조용한 유실 금지."""
    owned = {eid for c in chunks for eid in c.element_ids}
    owned |= {eid for c in chunks for eid in c.context_element_ids}
    for el in doc.body():
        if el.attrs.get("dropped") or not el.text.strip():
            continue
        if el.element_id not in owned:
            report.uncovered_elements.append(el.element_id)
    if report.uncovered_elements:
        report.warnings.append(f"청크에 담기지 않은 요소 {len(report.uncovered_elements)}건")

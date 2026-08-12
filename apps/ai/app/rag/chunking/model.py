"""청크 중간 표현 — `llm_wiki/_context/chunking-strategy.md` §5·§7.

파싱이 `ParsedDoc`으로 docling 이질성을 끊는 것과 같은 이유로, 청킹도 벡터 스토어에
직접 붙지 않는다. `Chunk` 하나를 사이에 두고 Chroma 어댑터는 `to_chroma()` 한 지점에만
있다. 임베딩 모델·컬렉션 매핑이 바뀌어도 청킹 규칙은 무변경이다.

**임베딩 텍스트 ≠ 컨텍스트 텍스트**가 이 표현의 핵심이다(§7.3). 검색은 짧고 신호가 진한
문자열로 하고, LLM에는 전문을 준다. 그래서 Chroma upsert는 `documents=`(전문)와
`embeddings=`(우리가 계산한 벡터)를 **따로** 넘겨야 한다 — 컬렉션에 임베딩 함수를 맡기면
이 분리가 무너진다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

ChunkType = Literal["article", "clause", "table", "annex", "section", "preamble"]
ChunkRole = Literal["atomic", "parent", "child"]

# 문서 메타 중 청크마다 복제할 가치가 없는 것. `revision_history`는 최대 500자인데
# 📏 법인세법은 청크가 425개라 같은 문자열이 425벌 실린다. 검색에도 필터에도 안 쓰인다.
_META_DROP = frozenset({"revision_history"})

_DATE = re.compile(r"(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})")


def _as_date_int(raw: str) -> int | None:
    """`'2026.8.1'` → `20260801`.

    **날짜를 문자열로 저장하면 범위 비교가 뒤집힌다** — `'2026.8.1' > '2026.10.1'`이
    사전순으로 참이다. Chroma 메타 필터에 `$lte`를 걸 수 있으려면 정렬 가능한 정수여야
    한다. 저장 시점에 바꾸지 않으면 나중엔 전량 재적재다.
    """
    if (m := _DATE.match(raw.strip())) is None:
        return None
    return int(f"{m[1]}{int(m[2]):02d}{int(m[3]):02d}")


@dataclass(frozen=True)
class Budget:
    """청크 크기 예산 — 단위는 **문자**(§6.1).

    토큰이 아니라 문자로 두는 이유: 임베딩 모델이 아직 미확정이라 토큰 환산비를 지어낼 수
    없다(전략 §11 결정대기 ①). 모델이 확정되면 `calibrate()`로 실측해 이 값을 토큰 기준
    으로 환산한다. 기본값의 근거는 전부 실측이다 — 조 블록 381개 중앙 449자, 항 서브블록
    p90 420자, 1,200자 컷이면 조의 79%가 통째로 남는다.
    """

    target: int = 800           # 분할 시 채우기 목표
    max: int = 1_200            # 이 값을 넘으면 항 경계에서 분할 시도
    hard: int = 2_000           # 항으로도 안 쪼개지면 호→문장→문자 순으로 강제 분할
    min_merge: int = 250        # 이보다 짧은 항 그룹은 다음 그룹과 합친다
    parent_embed_head: int = 400    # parent 청크의 임베딩 텍스트 앞부분 길이
    lead_in_max: int = 300      # 표 청크에 복제해 붙이는 도입 문장 최대 길이
    table_max_rows: int = 40    # 넘으면 행 분할 + 헤더행 반복

    def __post_init__(self) -> None:
        """예산이 조용히 뒤집히는 것을 막는다 — 손잡이는 **틀리면 멈춰야** 한다.

        두 가지가 실제로 일어난다.
          ① `--max 600`만 주면 `target`은 기본 800으로 남아 **target > max**가 된다.
             `_pack`의 채우기 목표가 영영 안 걸려 예산 손잡이가 말없이 다르게 동작한다.
          ② `max > hard`면 분할 사다리의 마지막 칸이 죽는다 — `_units`가 `max` 이하를
             통째로 통과시키므로 `hard`가 도달 불가능해진다. 📏 §10.2 스윕의 max=2,400
             행에서 2,392자 청크가 나온 경로가 이것이다.
        """
        if not 0 < self.min_merge < self.target < self.max <= self.hard:
            raise ValueError(
                "예산이 어긋났다 — "
                f"0 < min_merge({self.min_merge}) < target({self.target}) "
                f"< max({self.max}) <= hard({self.hard}) 여야 한다"
            )


DEFAULT_BUDGET = Budget()


@dataclass
class Chunk:
    """검색 단위 하나. 본문(`text`)과 계층 헤더(`header`)를 분리해 들고 있는다."""

    chunk_id: str
    doc_id: str
    doc_name: str
    profile: str
    chunk_type: ChunkType
    chunk_role: ChunkRole
    text: str                                   # 본문 (헤더 미포함)
    header: str                                 # 계층 컨텍스트 문자열 (§7.1)
    citation: str                               # "법인카드_사용규정 제9조" — 인용 문자열
    page_start: int
    page_end: int
    chapter_no: int | None = None
    chapter_title: str | None = None
    article_no: int | None = None
    article_label: str | None = None            # "제9조" / "제55조의2" (원문 표기 보존)
    article_title: str | None = None
    clause_kind: str | None = None              # "항" 기본 / 도입부에 `각 호`인 조만 "호"
    clause_start: int | None = None
    clause_end: int | None = None
    parent_chunk_id: str | None = None
    prev_chunk_id: str | None = None
    next_chunk_id: str | None = None
    element_ids: list[str] = field(default_factory=list)         # 소유 요소 (커버리지 검증 대상)
    context_element_ids: list[str] = field(default_factory=list)  # 복제해 붙인 요소 (중복 허용)
    has_table: bool = False
    has_list: bool = False
    flags: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)            # doc_no·effective_date·revision
    chunker_version: str = "chunk-v1"

    @property
    def size(self) -> int:
        return len(self.text)

    def context_text(self) -> str:
        """LLM에 넣는 전문. 헤더를 포함해 청크 하나만 봐도 소속을 알 수 있게 한다."""
        return f"{self.header}\n\n{self.text}" if self.header else self.text

    def embedding_text(self) -> str:
        """임베딩 대상 문자열. parent는 앞부분만 쓴다 — §7.3.

        parent 전문을 그대로 임베딩하면 긴 조문에서 벡터가 평균화돼 무엇과도 안 닮는다.
        검색 신호는 조 제목과 도입부에 몰려 있으므로 거기까지만 태운다.
        """
        body = self.text
        if self.chunk_role == "parent":
            body = body[: DEFAULT_BUDGET.parent_embed_head]
        return f"{self.header}\n\n{body}" if self.header else body

    def to_chroma(self, embedder_version: str | None = None) -> tuple[str, str, dict[str, Any]]:
        """(id, document, metadata). Chroma 메타데이터는 스칼라만 허용하므로 리스트는 접는다.

        `embedder_version`은 **벡터를 만든 주체의 신원**이다(`openai/…@1024/B_heading`).
        없으면 한 컬렉션에 두 모델의 벡터가 섞여도 알아낼 방법이 없다 — 하필 재검토
        트리거로 남겨 둔 `bge-m3`와 채택안 `3-large@1024`가 **똑같이 1024차원**이라
        Chroma도 못 막는다. 부분 재임베딩·마이그레이션도 이 필드가 있어야 가능하다.
        """
        meta: dict[str, Any] = {
            "doc_id": self.doc_id,
            "doc_name": self.doc_name,
            "profile": self.profile,
            "chunk_type": self.chunk_type,
            "chunk_role": self.chunk_role,
            "citation": self.citation,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "has_table": self.has_table,
            "has_list": self.has_list,
            "chunker_version": self.chunker_version,
            "size": self.size,
        }
        for key in (
            "chapter_no", "chapter_title", "article_no", "article_label", "article_title",
            "clause_kind", "clause_start", "clause_end", "parent_chunk_id",
            "prev_chunk_id", "next_chunk_id",
        ):
            value = getattr(self, key)
            if value is not None:
                meta[key] = value
        if self.flags:
            meta["flags"] = ",".join(self.flags)
        meta["element_ids"] = ",".join(self.element_ids)
        if embedder_version:
            meta["embedder_version"] = embedder_version
        for key, value in self.meta.items():
            if key in _META_DROP or not isinstance(value, (str, int, float, bool)):
                continue
            if key.endswith("_date") and (as_int := _as_date_int(str(value))) is not None:
                meta[f"doc_{key}"] = as_int     # 정렬·범위비교 가능해야 한다
                continue
            meta[f"doc_{key}"] = value
        return self.chunk_id, self.context_text(), meta


@dataclass
class ChunkReport:
    """무엇을 어떻게 잘랐는지. `ParseReport`와 같은 이유로 존재한다 — 조용한 실패 방지."""

    doc_name: str = ""
    profile: str = ""
    budget: Budget = DEFAULT_BUDGET
    counts: dict[str, int] = field(default_factory=dict)         # chunk_type별
    splits: dict[str, int] = field(default_factory=dict)         # clause/list/sentence/hard
    warnings: list[str] = field(default_factory=list)
    uncovered_elements: list[str] = field(default_factory=list)  # 어느 청크에도 안 들어간 요소

    def bump(self, bucket: dict[str, int], key: str, n: int = 1) -> None:
        bucket[key] = bucket.get(key, 0) + n

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_name": self.doc_name,
            "profile": self.profile,
            "counts": self.counts,
            "splits": self.splits,
            "warnings": self.warnings,
            "uncovered_elements": self.uncovered_elements,
        }

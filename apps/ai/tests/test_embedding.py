"""임베딩·Chroma 적재 회귀 — `embedding-strategy.md` §1·§7·§8.

**API도 Chroma도 부르지 않는다.** 인코더 클라이언트와 Chroma 클라이언트를 주입 가능하게
둔 이유가 이것이다 — 계약(무엇을 태우고, 무엇을 저장하고, 어디로 보내는가)은 네트워크
없이 고정할 수 있어야 한다.
"""
from __future__ import annotations

import math

import pytest

from app.rag.chunking.model import Chunk
from app.rag.embedding import config as emb_config
from app.rag.embedding.encoder import OpenAIEncoder, _l2_normalize
from app.rag.embedding.store import collection_for, upsert_chunks


def _chunk(chunk_id="d#a01#01", doc_name="법인카드_사용규정", profile="REGULATION",
           role="atomic", meta=None) -> Chunk:
    return Chunk(
        chunk_id=chunk_id, doc_id="d", doc_name=doc_name, profile=profile,
        chunk_type="article", chunk_role=role, text="본문", header="헤더",
        citation=f"{doc_name} 제1조", page_start=1, page_end=1,
        meta=meta if meta is not None else {},
    )


# ── 벡터 계약 ──────────────────────────────────────────────────────────────

def test_reduced_dimension_vectors_are_renormalized():
    """`dimensions`로 줄여 받은 벡터는 노름이 1이 아니다 — cosine=내적 등식이 깨진다."""
    got = _l2_normalize([3.0, 4.0])
    assert math.isclose(math.sqrt(sum(x * x for x in got)), 1.0)
    assert _l2_normalize([0.0, 0.0]) == [0.0, 0.0]      # 0벡터는 나눗셈 없이 통과


class _FakeClient:
    """OpenAI 임베딩 응답 흉내. 입력 문자열을 그대로 기록한다."""

    def __init__(self):
        self.seen: list[list[str]] = []
        self.embeddings = self

    def create(self, model, input, dimensions):          # noqa: A002
        self.seen.append(list(input))
        data = [type("D", (), {"index": i, "embedding": [1.0] * dimensions})()
                for i in range(len(input))]
        return type("R", (), {"data": data, "usage": type("U", (), {"prompt_tokens": 7})()})()


def test_document_and_query_inputs_differ():
    """문서는 헤더+본문(`embedding_text`), 질의는 `Q_ctx` 접두 — 이 비대칭이 계약이다."""
    fake = _FakeClient()
    enc = OpenAIEncoder(client=fake)

    enc.encode_documents([_chunk()])
    assert fake.seen[-1] == ["헤더\n\n본문"]

    enc.encode_queries(["분실 신고"])
    assert fake.seen[-1] == [f"{emb_config.DEFAULT.query_prefix}분실 신고"]
    assert enc.billed_tokens == 14                        # 두 호출 누적


def test_parent_chunk_embeds_only_the_head():
    """parent 전문을 태우면 벡터가 평균화돼 무엇과도 안 닮는다 — 앞부분만 태운다."""
    fake = _FakeClient()
    parent = _chunk(role="parent")
    object.__setattr__(parent, "text", "가" * 900)
    OpenAIEncoder(client=fake).encode_documents([parent])
    assert len(fake.seen[-1][0]) < 900


# ── 컬렉션 라우팅 ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("profile,expected", [
    ("REGULATION", "policy_docs"), ("LAW", "tax_refs"), ("DIAGRAM", "org_docs"),
])
def test_collection_routing(profile, expected):
    assert collection_for(profile) == expected


def test_org_docs_is_outside_the_judgement_path():
    """조직도가 정산 판정 근거로 인용되면 안 된다 — 결재선의 SoR은 Django다."""
    assert "org_docs" not in emb_config.JUDGEMENT_COLLECTIONS
    assert "org_docs" in emb_config.ALL_COLLECTIONS


def test_unknown_profile_fails_loudly():
    """모르는 유형을 조용히 policy_docs로 흘리면 규정 검색이 오염된다."""
    with pytest.raises(ValueError, match="컬렉션이 정해지지 않은"):
        collection_for("SLIDE_DECK")


# ── 메타데이터 계약 ────────────────────────────────────────────────────────

def test_metadata_carries_embedder_identity():
    """신원이 없으면 같은 1024차원인 bge-m3 벡터가 섞여도 감지할 수 없다."""
    _, _, meta = _chunk().to_chroma(embedder_version="openai/x@1024/B_heading")
    assert meta["embedder_version"] == "openai/x@1024/B_heading"


def test_dates_are_stored_as_sortable_ints():
    """문자열 날짜는 범위 비교가 뒤집힌다 — `'2026.8.1' > '2026.10.1'`이 참이다."""
    _, _, meta = _chunk(meta={"effective_date": "2026.8.1", "enacted_date": "2026.7.20"}).to_chroma()
    assert meta["doc_effective_date"] == 20260801
    assert meta["doc_enacted_date"] == 20260720
    assert 20260801 < 20261001                            # 정수라야 성립한다


def test_revision_history_is_not_replicated_per_chunk():
    """📏 법인세법은 청크 425개 — 500자 문자열이 425벌 실릴 이유가 없다."""
    _, _, meta = _chunk(meta={"revision_history": "v1.0 제정 / v1.1 …", "revision": "v1.1"}).to_chroma()
    assert not any("revision_history" in k for k in meta)
    assert meta["doc_revision"] == "v1.1"                  # 버전 자체는 남는다


# ── upsert 계약 ────────────────────────────────────────────────────────────

class _FakeCollection:
    def __init__(self, name): self.name, self.calls = name, []
    def upsert(self, **kw): self.calls.append(kw)


class _FakeChroma:
    def __init__(self): self.collections: dict[str, _FakeCollection] = {}
    def get_or_create_collection(self, name, metadata=None, embedding_function="MISSING"):
        assert embedding_function is None, (
            "컬렉션에 임베딩을 맡기면 저장 문서로 벡터를 계산해 다른 벡터가 들어간다"
        )
        assert metadata == {"hnsw:space": "cosine"}
        return self.collections.setdefault(name, _FakeCollection(name))


def test_upsert_routes_and_stores_document_not_embedding_text():
    """저장 문서는 `context_text()`(전문), 임베딩은 `embedding_text()` — 다른 문자열이다."""
    chroma = _FakeChroma()
    chunks = [_chunk("a", profile="REGULATION"),
              _chunk("b", doc_name="조직도", profile="DIAGRAM")]
    profile_of = {"법인카드_사용규정": "REGULATION", "조직도": "DIAGRAM"}

    report = upsert_chunks(chunks, profile_of, client=chroma,
                           encoder=OpenAIEncoder(client=_FakeClient()))

    assert report.per_collection == {"policy_docs": 1, "org_docs": 1}
    assert report.embedder_version == emb_config.DEFAULT.version
    call = chroma.collections["policy_docs"].calls[0]
    assert call["documents"] == ["헤더\n\n본문"]           # context_text()
    assert len(call["embeddings"][0]) == emb_config.DEFAULT.dimensions
    assert call["metadatas"][0]["embedder_version"] == emb_config.DEFAULT.version

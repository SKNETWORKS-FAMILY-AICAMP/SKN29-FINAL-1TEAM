"""Chroma 저장·검색 계약 — `embedding-strategy.md` §8.

**컬렉션에 `embedding_function`을 맡기지 않는다.** 저장 문서는 `context_text()`(전문)이고
임베딩은 `embedding_text()`(parent는 앞부분만)라 서로 다르다. Chroma에 맡기면 저장 문서로
벡터를 계산해 **에러 없이 다른 벡터**가 들어가고, 검색 품질만 애매하게 나빠진다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from app.rag.embedding.config import DEFAULT, COLLECTION_OF, EmbeddingConfig
from app.rag.embedding.encoder import OpenAIEncoder


def get_client(host: str | None = None, port: int | None = None, persist_dir: str | None = None):
    """Chroma 클라이언트.

    운영은 compose의 `chroma` 서비스(호스트 8001 → 컨테이너 8000)에 HTTP로 붙는다.
    `persist_dir`(또는 `CHROMA_PERSIST_DIR`)이 주어지면 **로컬 영속 클라이언트**를 쓴다 —
    docker 없이 인덱싱·검증을 돌리기 위한 경로다. 저장 형식·계약은 양쪽이 같다.
    """
    import chromadb

    from app.config import settings

    target = persist_dir or settings.chroma_persist_dir
    if target:
        return chromadb.PersistentClient(path=target)
    return chromadb.HttpClient(
        host=host or settings.chroma_host,
        port=port or settings.chroma_port,
    )


def get_collection(client, name: str):
    """cosine 공간으로 생성/조회. `embedding_function=None`이 계약의 핵심이다."""
    return client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
        embedding_function=None,
    )


def collection_for(profile: str) -> str:
    """문서 유형 → 컬렉션. 모르는 유형은 **조용히 넘기지 않고** 멈춘다."""
    try:
        return COLLECTION_OF[profile]
    except KeyError:                                    # noqa: TRY203
        raise ValueError(
            f"컬렉션이 정해지지 않은 문서 유형: {profile!r} — "
            "`embedding/config.py:COLLECTION_OF`에 매핑을 추가할 것"
        ) from None


@dataclass
class UpsertReport:
    """무엇을 어디에 넣었는지. 조용한 실패를 막는 것이 `ParseReport`와 같은 이유다."""

    embedder_version: str = ""
    per_collection: dict[str, int] = field(default_factory=dict)
    skipped_parents: int = 0
    billed_tokens: int = 0

    @property
    def total(self) -> int:
        return sum(self.per_collection.values())

    def lines(self) -> list[str]:
        out = [f"embedder  {self.embedder_version}"]
        for name, n in sorted(self.per_collection.items()):
            out.append(f"  {name:<14}{n:>5}청크")
        out.append(f"  {'합계':<13}{self.total:>5}청크 · 과금 토큰 {self.billed_tokens:,}")
        return out


def upsert_chunks(
    chunks: Iterable,
    profile_of: dict[str, str],
    *,
    client=None,
    encoder: OpenAIEncoder | None = None,
    config: EmbeddingConfig = DEFAULT,
) -> UpsertReport:
    """청크를 유형별 컬렉션에 적재한다.

    `profile_of`는 `{doc_name: profile}`. 청크가 자기 프로파일을 들고 있지만, 라우팅
    결정을 청크 필드가 아니라 **호출자가 넘긴 표**로 두어 컬렉션 정책이 바뀔 때
    청킹을 건드리지 않게 한다.
    """
    client = client or get_client()
    encoder = encoder or OpenAIEncoder(config)
    report = UpsertReport(embedder_version=config.version)

    buckets: dict[str, list] = {}
    for chunk in chunks:
        profile = profile_of.get(chunk.doc_name, chunk.profile)
        buckets.setdefault(collection_for(profile), []).append(chunk)

    for name, group in buckets.items():
        vectors = encoder.encode_documents(group)
        ids, documents, metadatas = [], [], []
        for chunk in group:
            cid, document, meta = chunk.to_chroma(embedder_version=config.version)
            ids.append(cid)
            documents.append(document)
            metadatas.append(meta)

        collection = get_collection(client, name)
        for start in range(0, len(ids), config.batch_size):
            end = start + config.batch_size
            collection.upsert(
                ids=ids[start:end],
                documents=documents[start:end],
                embeddings=vectors[start:end],
                metadatas=metadatas[start:end],
            )
        report.per_collection[name] = len(ids)

    report.billed_tokens = encoder.billed_tokens
    return report


def search(
    query: str,
    collection_name: str = "policy_docs",
    top_k: int = 5,
    *,
    client=None,
    encoder: OpenAIEncoder | None = None,
    config: EmbeddingConfig = DEFAULT,
    expand_parent: bool = True,
) -> list[dict[str, Any]]:
    """검색 3단 계약 — ① parent 제외 ② 부모 확장 ③ (호출자 판단) 이웃 확장.

    parent 청크를 결과에서 빼는 이유: 부모는 조 전문이라 **무엇과도 어중간하게 닮는다**.
    검색은 잎으로 하고, 맞은 잎의 부모를 붙여 LLM에 넘길 문맥을 만든다.
    """
    client = client or get_client()
    encoder = encoder or OpenAIEncoder(config)
    collection = get_collection(client, collection_name)

    vector = encoder.encode_queries([query])[0]
    res = collection.query(
        query_embeddings=[vector],
        n_results=top_k,
        where={"chunk_role": {"$ne": "parent"}},
        include=["documents", "metadatas", "distances"],
    )

    hits: list[dict[str, Any]] = []
    for cid, doc, meta, dist in zip(
        res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0]
    ):
        hit = {
            "chunk_id": cid,
            "citation": meta.get("citation"),
            "document": doc,
            "metadata": meta,
            "score": 1.0 - dist,                    # cosine 거리 → 유사도
        }
        if expand_parent and (pid := meta.get("parent_chunk_id")):
            got = collection.get(ids=[pid], include=["documents"])
            if got["documents"]:
                hit["parent_document"] = got["documents"][0]
        hits.append(hit)
    return hits


def peek(collection_name: str, *, client=None) -> dict[str, Any]:
    """적재 결과 확인용 — 건수와 임베딩 신원 분포."""
    client = client or get_client()
    collection = get_collection(client, collection_name)
    count = collection.count()
    versions: dict[str, int] = {}
    if count:
        got = collection.get(include=["metadatas"], limit=min(count, 10_000))
        for meta in got["metadatas"]:
            key = meta.get("embedder_version", "(없음)")
            versions[key] = versions.get(key, 0) + 1
    return {"collection": collection_name, "count": count, "embedder_versions": versions}


def assert_single_embedder(collections: Sequence[str], *, client=None) -> None:
    """한 컬렉션에 두 모델의 벡터가 섞이지 않았는지 본다.

    차원이 다르면 Chroma가 막아 주지만, 하필 재검토 트리거로 남겨 둔 `bge-m3`와 채택안
    `3-large@1024`가 **똑같이 1024차원**이라 못 막는다. 그래서 여기서 명시적으로 센다.
    """
    for name in collections:
        info = peek(name, client=client)
        if len(info["embedder_versions"]) > 1:
            raise RuntimeError(
                f"{name}: 임베딩 신원이 섞였다 — {info['embedder_versions']}. "
                "컬렉션을 비우고 한 모델로 다시 적재할 것"
            )

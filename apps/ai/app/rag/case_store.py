"""과거 승인/반려 사례 검색·적재 — `case_history` 컬렉션 (Risk Review 2차 검증용).

`embedding/store.py::search()`는 규정 조문 전제(청크 계층·`chunk_role`/`parent_chunk_id`
메타)로 설계돼 있어 그대로 못 쓴다. 사례는 조문 구조가 없는 평문 레코드라 이 모듈에서
별도로 다루되, 클라이언트·컬렉션 접근·임베딩 계약(`app/rag/embedding`)은 그대로 재사용해
정책 문서 검색과 같은 Chroma 인스턴스·같은 임베딩 모델을 쓴다(운영 경로와 분리된 별도
스토어를 만들지 않는다 — `apps/ai/app/agents/rule_agent_v0/vector_store.py`가 겪은 문제,
`get_tx_features` 조사 세션에서 그 store가 실제 데이터와 연결되지 않은 고립된 로컬
Chroma(1건)였음을 확인했다).
"""
from __future__ import annotations

import argparse
from typing import Any

from app.rag.embedding.config import DEFAULT, EmbeddingConfig
from app.rag.embedding.encoder import OpenAIEncoder
from app.rag.embedding.store import get_client, get_collection, peek

COLLECTION = "case_history"


def upsert_cases(
    cases: list[dict],
    *,
    client=None,
    encoder: OpenAIEncoder | None = None,
    config: EmbeddingConfig = DEFAULT,
) -> int:
    """cases: [{"case_id", "text", "outcome", "category", "citation"}]. text만 임베딩한다."""
    if not cases:
        return 0
    client = client or get_client()
    encoder = encoder or OpenAIEncoder(config)
    vectors = encoder.encode_texts([c["text"] for c in cases])
    collection = get_collection(client, COLLECTION)
    collection.upsert(
        ids=[c["case_id"] for c in cases],
        documents=[c["text"] for c in cases],
        embeddings=vectors,
        metadatas=[
            {
                "outcome": c.get("outcome", ""),
                "category": c.get("category", ""),
                "citation": c.get("citation", c["case_id"]),
                "embedder_version": config.version,
            }
            for c in cases
        ],
    )
    return len(cases)


def search_cases(
    query: str,
    top_k: int = 5,
    *,
    client=None,
    encoder: OpenAIEncoder | None = None,
    config: EmbeddingConfig = DEFAULT,
) -> list[dict[str, Any]]:
    """빈 컬렉션이면 빈 리스트(호출부가 INSUFFICIENT_INFO로 처리해야 한다 — 여기서 지어내지 않는다)."""
    client = client or get_client()
    collection = get_collection(client, COLLECTION)
    count = collection.count()
    if count == 0:
        return []
    encoder = encoder or OpenAIEncoder(config)
    vector = encoder.encode_queries([query])[0]
    res = collection.query(
        query_embeddings=[vector],
        n_results=min(top_k, count),
        include=["documents", "metadatas", "distances"],
    )
    out: list[dict[str, Any]] = []
    for cid, doc, meta, dist in zip(
        res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0]
    ):
        out.append({"case_id": cid, "text": doc, "metadata": meta, "score": 1.0 - dist})
    return out


def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upsert", action="store_true", help="app/rag/golden_cases.py의 골든 데이터를 적재")
    parser.add_argument("--peek", action="store_true", help="현재 적재 현황만 출력")
    args = parser.parse_args()

    if args.peek or not args.upsert:
        print(peek(COLLECTION))
        return

    from app.rag.golden_cases import GOLDEN_CASES

    n = upsert_cases(GOLDEN_CASES)
    print(f"적재 완료: case_history {n}건")
    print(peek(COLLECTION))


if __name__ == "__main__":
    _main()

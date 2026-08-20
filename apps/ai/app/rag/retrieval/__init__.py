"""검색 질의 조립 + 결과 재선별 — Rule/Risk Agent가 policy_docs를 검색하는 앞뒤 층.

파싱(`parsing`) → 청킹(`chunking`) → 임베딩·색인(`embedding`) 다음, 색인된 것을 "어떤
문장으로 찾을지"(`query_builder`)와 "뽑힌 후보 중 실제로 쓸지"(`rerank`)를 다루는 칸.
검색 실행 자체(코사인 유사도 계산·상위 k개 반환)는 `embedding.store.search`가 맡는다.
"""
from app.rag.retrieval.query_builder import (
    FALLBACK_FEATURE_HINT_NL,
    FEATURE_HINT_NL,
    build_query,
    facts_nl,
    feature_hint_nl,
)
from app.rag.retrieval.rerank import rerank

__all__ = [
    "FALLBACK_FEATURE_HINT_NL",
    "FEATURE_HINT_NL",
    "build_query",
    "facts_nl",
    "feature_hint_nl",
    "rerank",
]
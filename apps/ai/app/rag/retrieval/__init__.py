"""검색 질의 조립 — Rule/Risk Agent가 policy_docs를 검색하기 전에 "무엇을 검색어로 쓸지" 결정하는 층.

파싱(`parsing`) → 청킹(`chunking`) → 임베딩·색인(`embedding`) 다음, 색인된 것을 "어떤 문장으로
찾을지"를 다루는 칸. 검색 실행 자체(코사인 유사도 계산·상위 k개 반환)는 `embedding.store.search`가
맡고, 여기는 그 앞단인 질의 문자열 조립만 책임진다.
"""
from app.rag.retrieval.query_builder import (
    FALLBACK_FEATURE_HINT_NL,
    FEATURE_HINT_NL,
    build_query,
    facts_nl,
    feature_hint_nl,
)

__all__ = [
    "FALLBACK_FEATURE_HINT_NL",
    "FEATURE_HINT_NL",
    "build_query",
    "facts_nl",
    "feature_hint_nl",
]
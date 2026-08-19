"""Risk Review 2차 검증 — LLM 프롬프트 조립 회귀. `risk_review_agent.py::_format_chunks()`.

`store.search()`가 잎 청크의 부모(조문 전체)를 이미 가져오고 있었는데, 프롬프트 조립
단계에서 그걸 안 쓰고 잎 원문 400자만 쓰던 문맥 손실 버그를 막는다(2026-08-19 발견·수정).
"""
from __future__ import annotations

from app.agents.risk_review_agent import _format_chunks


def test_format_chunks_uses_full_parent_article_when_available():
    chunks = [{"citation": "법인카드_사용규정 제6조", "text": "1. 사용자는...(잘린 잎 조각)",
               "parent_text": "1. 사용자는 법인카드를 선량한 관리자의 주의로 보관·사용하여야 하며... 2. 퇴사, 휴직, 부서 이동 시..."}]
    result = _format_chunks(chunks)
    assert "1. 사용자는 법인카드를 선량한 관리자의 주의로" in result
    assert "2. 퇴사, 휴직, 부서 이동 시" in result


def test_format_chunks_falls_back_to_leaf_text_when_no_parent():
    """atomic 청크(원래 짧아 부모-자식 분할이 없는 조)는 parent_text가 빈 문자열이다."""
    chunks = [{"citation": "법인카드_사용규정 제1조", "text": "이 규정은 임직원에게 발급하는...",
               "parent_text": ""}]
    result = _format_chunks(chunks)
    assert "이 규정은 임직원에게 발급하는" in result


def test_format_chunks_caps_length_to_avoid_runaway_prompt():
    long_text = "가" * 5000
    chunks = [{"citation": "테스트", "text": "짧은 잎", "parent_text": long_text}]
    result = _format_chunks(chunks)
    assert len(result) < 1300


def test_format_chunks_empty_list():
    assert _format_chunks([]) == "(검색 결과 없음)"
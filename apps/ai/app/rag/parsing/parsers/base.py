"""PageParser Protocol — 파싱 전략 §4.3.

파서 이질성은 여기서 끊긴다. 새 유형 대응은 파이프라인 수정이 아니라
`PageParser` 구현 1개 추가로 끝난다.
"""
from __future__ import annotations

from typing import Any, Protocol

from app.rag.parsing.model import DocElement, PageProfile


class PageParser(Protocol):
    name: str

    def can_handle(self, profile: PageProfile) -> float:
        """0.0~1.0 확신도."""
        ...

    def parse(self, page: Any, profile: PageProfile, ctx: dict[str, Any]) -> list[DocElement]:
        ...


class ParserUnavailable(Exception):
    """파서가 이 환경에 설치되지 않음 — 문서를 죽이지 않고 quarantine으로 보낸다."""

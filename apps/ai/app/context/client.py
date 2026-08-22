"""core `/api/internal/agent-context/` 조회 + TTL 캐시.

## 왜 TTL인가

기존 `_action_schema_cache`는 **프로세스 수명 동안 영구**였다. 그래서 런타임에 추가된
플래그·별표는 ai를 재시작할 때까지 프롬프트에 영영 안 들어왔다(규정 문서를 올려 룰을
만드는 게 제품의 주된 흐름인데, 그 흐름이 만든 어휘를 다음 생성이 모르는 상태였다).
짧은 TTL이면 매 호출 왕복 없이도 몇 분 안에 따라잡는다.

## 실패는 열어두되, 반드시 티를 낸다

카탈로그 조회 실패가 룰 생성 전체를 막으면 안 된다(기존 동작과 같은 판단). 대신
`stale=True`를 달아 프롬프트·trace·AI-LAB에 그대로 노출한다 — 예전엔 조용히 옛
하드코딩 값으로 대체돼서 "왜 이 목록으로 돌았지"를 나중에 따질 수 없었다.

`_STALE_ACTION_SCHEMA`가 **유일하게 남은 사본**이다. OpenAI structured output의
`enum`은 빈 배열일 수 없어서(스키마 자체가 거부된다) 이것만은 로컬 기본값이 필요하다.
경로 목록·플래그는 비어도 프롬프트가 "조회 실패"로 안내하면 되므로 사본을 두지 않는다.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import settings as core_settings

log = logging.getLogger(__name__)

TIMEOUT = 10.0
TTL_SECONDS = 180.0

#: 조회 실패 시에만 쓰는 최소 기본값 — 위 docstring 참조.
_STALE_ACTION_SCHEMA = {
    "decisions": ["PASS", "REJECT", "RETURN", "REVIEW", "PASS_THROUGH"],
    "severities": ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"],
    "pass_through": "PASS_THROUGH",
    "decision_effect": {},
}


@dataclass
class Bundle:
    """한 번의 조회 결과. 프롬프트 블록과 검증 기준을 **같은 객체**에서 꺼낸다."""

    profile: str
    sections: list[dict[str, Any]] = field(default_factory=list)
    etag: str = ""
    stale: bool = False
    error: str = ""

    # ── 섹션 접근 ────────────────────────────────────────────────────────
    def section(self, section_id: str) -> dict[str, Any] | None:
        for s in self.sections:
            if s.get("id") == section_id:
                return s
        return None

    def data(self, section_id: str) -> dict[str, Any]:
        s = self.section(section_id)
        return (s or {}).get("data") or {}

    # ── 검증기가 쓰는 값 (프롬프트와 같은 출처여야 한다) ──────────────────
    @property
    def paths(self) -> list[str]:
        """룰 조건이 참조할 수 있는 dot-path 전체."""
        return [
            f["path"]
            for sec in self.data("eval_context.paths").get("sections", [])
            for f in sec.get("fields", [])
        ]

    @property
    def operators(self) -> set[str]:
        g = self.data("dsl.grammar")
        if not g:
            return set()
        return set(g["logic_operators"]) | set(g["compare_operators"]) | {g["value_operator"]}

    @property
    def action_schema(self) -> dict[str, Any]:
        return self.data("action.schema") or dict(_STALE_ACTION_SCHEMA)

    @property
    def decisions(self) -> list[str]:
        return list(self.action_schema["decisions"])

    @property
    def severities(self) -> list[str]:
        return list(self.action_schema["severities"])

    @property
    def flag_codes(self) -> list[str]:
        return [f["code"] for f in self.data("flags.registry").get("rule_flags", [])]

    # ── 프롬프트 ────────────────────────────────────────────────────────
    def prompt(self, *section_ids: str) -> str:
        from .render import render

        picked = [s for s in self.sections if not section_ids or s["id"] in section_ids]
        return render(picked, stale=self.stale, error=self.error)


# ─────────────────────────────────────────────────────────────── 캐시

_lock = threading.Lock()
_cache: dict[str, tuple[float, Bundle]] = {}


def _fetch(profile: str, params: dict[str, str] | None) -> Bundle:
    url = f"{core_settings.core_base_url.rstrip('/')}/api/internal/agent-context/"
    query = {"profile": profile, **(params or {})}
    try:
        r = httpx.get(url, params=query, timeout=TIMEOUT)
        r.raise_for_status()
        payload = r.json()
        return Bundle(
            profile=profile,
            sections=payload.get("sections", []),
            etag=payload.get("etag", ""),
        )
    except Exception as exc:  # noqa: BLE001
        # 여기서 멈추지 않는다(생성 전체가 막힌다). 대신 stale을 달아 프롬프트에 드러낸다.
        log.warning("agent-context 조회 실패 (profile=%s): %s", profile, exc)
        return Bundle(profile=profile, sections=[], stale=True, error=str(exc))


def get_context(profile: str, params: dict[str, str] | None = None) -> Bundle:
    """프로파일 카탈로그를 가져온다. TTL 안이면 캐시."""
    key = f"{profile}|{sorted((params or {}).items())}"
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < TTL_SECONDS:
            return hit[1]

    bundle = _fetch(profile, params)
    if not bundle.stale:            # 실패한 결과를 TTL 동안 붙들지 않는다
        with _lock:
            _cache[key] = (now, bundle)
    return bundle


def invalidate() -> None:
    """캐시 비우기 — 테스트·AI-LAB 진단용."""
    with _lock:
        _cache.clear()

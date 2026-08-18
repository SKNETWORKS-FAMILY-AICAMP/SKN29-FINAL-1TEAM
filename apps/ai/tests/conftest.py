"""ai 테스트 공용 설정.

**주변 개발 스위치를 테스트에 새어 들어오지 않게 막는다.** `DOCLING_MOCK=1`을 켠 채로
컨테이너를 띄우면 실제 파싱 경로를 검증하는 테스트(`tests/rag/test_ingest_pipeline.py`)가
덤프 로더로 갈아끼워져 엉뚱하게 실패한다 — 테스트가 "지금 이 컨테이너의 env"에 따라
결과가 달라지면 회귀 신호로 쓸 수 없다.

모킹 자체를 시험하는 테스트는 `monkeypatch.setenv`로 **명시적으로 켠다**
(`tests/test_docling_mock.py`) — 그쪽은 이 픽스처 이후에 적용되므로 영향받지 않는다.
"""
from __future__ import annotations

import pytest

# 테스트 실행 중에는 꺼져 있어야 하는 개발 전용 env.
AMBIENT_DEV_SWITCHES = ("DOCLING_MOCK",)


@pytest.fixture(autouse=True)
def _isolate_dev_switches(monkeypatch):
    for name in AMBIENT_DEV_SWITCHES:
        monkeypatch.delenv(name, raising=False)

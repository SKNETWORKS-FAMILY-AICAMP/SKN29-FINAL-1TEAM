"""파싱 덤프(`docling_eval/output`) 위치 찾기 — 호스트·컨테이너 양쪽에서 동작한다.

예전에는 각 테스트가 `Path(__file__).resolve().parents[3]`로 레포 루트를 짚었는데,
컨테이너에서는 `/app`이 곧 `apps/ai`라 조상이 3단계까지 없어 **IndexError로 수집 자체가
실패**했다(테스트가 skip되는 게 아니라 파일을 못 읽는다). 경로 깊이를 가정하지 않고
위로 훑으며 실제로 존재하는 덤프를 찾는다.
"""
from __future__ import annotations

from pathlib import Path

MARKER = Path("layout") / "layout_result.csv"


def find_dump() -> Path | None:
    """덤프 루트(`.../docling_eval/output`) 또는 None."""
    bases = [*Path(__file__).resolve().parents, Path("/data")]
    for base in bases:
        candidate = base / "docling_eval" / "output"
        if (candidate / MARKER).is_file():
            return candidate
    return None

"""관측 불확실성 마커 — 모델이 quote/문자열값에 "모른다"를 스스로 적어놓고도
확정값을 함께 내는 자기모순을 잡는다(QA 2026-08-24 실측: M08 "대략 여럿명"→8,
PL04 "훼손/누락"→3, T04 지역등급에 "?" 문자열).

프롬프트 지시("확인했는데 없음 vs 안 보임 구분")는 텍스트 지시일 뿐이라 모델이
안 지킬 수 있다 — 여기서 quote·문자열값에 이 마커가 있으면 기계적으로 드롭한다.
"""
from __future__ import annotations

UNCERTAIN_MARKERS = (
    "대략", "여럿", "훼손", "누락", "생략", "미정", "불명", "확인 불가", "확인불가",
    "알 수 없", "안 보임", "언급이 없", "명시되지 않", "명시되어 있지 않", "명시가 없",
    "판단 불가", "판단불가", "미상", "?",
)


def is_uncertain(*texts: str | None) -> bool:
    """quote·문자열값 중 하나라도 불확실성 마커를 담고 있으면 True."""
    return any(t and any(marker in t for marker in UNCERTAIN_MARKERS) for t in texts)

"""Draft Agent 계약 타입 — `api/draft.py`와 `agents/draft_agent.py`가 공유한다.

두 모듈이 서로를 import하는 순환 참조를 피하기 위해 공용 타입만 이 파일로 분리했다.
"""
from typing import Literal

CardType = Literal["PERSONAL", "TEAM", "SHARED", "POST_PAID", "PREPAID"]
Evidence = Literal["OK", "MISSING"]
Category = Literal["업무활성", "회의", "식대", "출장", "접대", "비품"]

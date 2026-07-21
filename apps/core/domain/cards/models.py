"""카드 (기술명세서 §3.1).

테이블: cards(card_type[개인/팀/공용/후정산/선불], owner_id)
- 카드 구분에 따라 사용자 귀속·증빙 요구 수준이 달라진다(요구사항 §4.1).
TODO: 모델 구현.
"""
from django.db import models  # noqa: F401

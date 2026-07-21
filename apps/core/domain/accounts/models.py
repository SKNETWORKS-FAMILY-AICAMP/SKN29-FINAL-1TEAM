"""조직/사용자/권한 (기술명세서 §3.1).

테이블: users, teams, team_members, roles
- role, team_id(제출 단위) 중심. RBAC 경계는 요구사항 §9 Open Issue.
TODO: 모델 구현.
"""
from django.db import models  # noqa: F401

"""규정/Rule/판정로그 (기술명세서 §3.1).

테이블:
- policies, policy_docs(category, limit, required_evidence)
- rules, rule_versions(condition JSON/DSL, action, status, sim_result)
- rule_hits(tx_id, rule_id, decision, confidence)

원칙: Rule 적용은 결정론적 엔진, LLM은 Rule '생성' 단계에서만(재현성).
      승인된 Rule만 status=ACTIVE.
TODO: 모델 구현.
"""
from django.db import models  # noqa: F401

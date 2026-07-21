"""정산/상태이력 — SoR의 핵심 (기술명세서 §3.1, §3.3).

테이블:
- settlements(tx_id, category, status[상태머신], submitted_by)
- settlement_events(from_state, to_state, actor, reason, ts)

상태머신:
  DRAFT → SUBMITTED → RPA_JUDGED
    ├─(auto-pass)──► PENDING_CONFIRM ─(사람 확정)─► CONFIRMED → ERP_VOUCHER_DRAFTED
    ├─(auto-reject)► RETURNED ─(재제출)─► SUBMITTED
    └─(needs-review)► IN_REVIEW ─► APPROVED / RETURNED / CORRECTED

원칙: 모든 상태 전이는 Django 서비스 레이어에서만 수행하고
      settlement_events + audit_logs에 기록. 확신 통과도 사람 확정 없이는 CONFIRMED 불가.
TODO: 모델 + 상태전이 서비스 구현.
"""
from django.db import models  # noqa: F401

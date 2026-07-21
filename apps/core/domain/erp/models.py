"""ERP 전표(안) / 감사로그 (기술명세서 §3.1).

테이블:
- erp_vouchers(settlement_id, voucher_payload JSONB, status[안/확정])
    ※ MVP는 전표(안) 생성까지만. 실제 ERP 적재·연동은 범위 밖.
- audit_logs(actor, action, target, before/after, ts)
    ※ 모든 상태전이·Agent Job·확정 액션을 변경불가 지향으로 기록.
TODO: 모델 구현.
"""
from django.db import models  # noqa: F401

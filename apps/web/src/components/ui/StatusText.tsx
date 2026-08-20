import { STATUS_META, type SettlementStatus } from '../../types/domain'

/** S-01 지출 증빙 테이블 전용 — 뱃지(pill)가 아니라 톤 색상의 굵은 텍스트로 검토상태를 표시(시안 실측). */
export function StatusText({ status, label }: { status: SettlementStatus; label?: string }) {
  const meta = STATUS_META[status]
  return (
    <span className="status-text" style={{ color: `var(--tone-${meta.tone})` }}>
      {label ?? meta.label}
    </span>
  )
}
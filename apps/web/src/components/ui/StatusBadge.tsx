import { STATUS_META, type SettlementStatus } from '../../types/domain'

const toneStyle = (tone: string) => ({
  color: `var(--tone-${tone})`,
  background: `var(--tone-${tone}-bg)`,
})

export function StatusBadge({ status }: { status: SettlementStatus }) {
  const meta = STATUS_META[status]
  return (
    <span className="badge" style={toneStyle(meta.tone)}>
      {meta.label}
    </span>
  )
}

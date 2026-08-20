import type { CSSProperties } from 'react'

export function KpiCard({
  label,
  value,
  unit,
  warn,
  /** 값이 아니라 라벨을 톤 색으로 강조(예: S-01 "반려" 카드 — 값은 그대로, 라벨만 강조). */
  labelWarn,
  /** 상단 색상 바 없이 흰 카드만(S-01 히어로 배너 KPI 실측). */
  flat,
  /** 상단 색상 바를 이 색으로(S-02 KPI 4개 — 채도 높은 accent 색, 예: 'var(--accent-purple)'). 지정 없으면 기본 primary. */
  accent,
}: {
  label: string
  value: string | number
  unit?: string
  warn?: boolean
  labelWarn?: boolean
  flat?: boolean
  accent?: string
}) {
  const cls = ['kpi', warn && 'warn', labelWarn && 'label-warn', flat && 'flat'].filter(Boolean).join(' ')
  return (
    <div className={cls} style={accent ? ({ '--kpi-accent': accent } as CSSProperties) : undefined}>
      <div className="label">{label}</div>
      <div className="value">
        {value}
        {unit && <small>{unit}</small>}
      </div>
    </div>
  )
}
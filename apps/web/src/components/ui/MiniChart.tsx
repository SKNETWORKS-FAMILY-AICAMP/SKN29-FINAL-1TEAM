// 의존성 없이 인라인 SVG로 그리는 경량 차트(대시보드용).

export function BarChart({
  data,
  height = 160,
}: {
  data: { label: string; value: number; warn?: boolean }[]
  height?: number
}) {
  const max = Math.max(...data.map((d) => d.value), 1)
  const bw = 100 / data.length
  return (
    <svg viewBox={`0 0 100 ${40}`} width="100%" height={height} preserveAspectRatio="none">
      {data.map((d, i) => {
        const h = (d.value / max) * 34
        return (
          <g key={d.label}>
            <rect
              x={i * bw + bw * 0.2}
              y={38 - h}
              width={bw * 0.6}
              height={h}
              rx={0.6}
              fill={d.warn ? 'var(--tone-red)' : 'var(--primary)'}
            />
          </g>
        )
      })}
    </svg>
  )
}

export function StackedTrend({
  data,
  keys,
}: {
  data: Record<string, number | string>[]
  keys: { key: string; color: string }[]
}) {
  const totals = data.map((row) => keys.reduce((s, k) => s + (row[k.key] as number), 0))
  const max = Math.max(...totals, 1)
  const bw = 100 / data.length
  return (
    <svg viewBox="0 0 100 40" width="100%" height={180} preserveAspectRatio="none">
      {data.map((row, i) => {
        let y = 38
        return (
          <g key={i}>
            {keys.map((k) => {
              const h = ((row[k.key] as number) / max) * 34
              y -= h
              return <rect key={k.key} x={i * bw + bw * 0.2} y={y} width={bw * 0.6} height={h} fill={k.color} />
            })}
          </g>
        )
      })}
    </svg>
  )
}

export function LabeledBars({ data }: { data: { label: string; rate: number }[] }) {
  return (
    <div className="stack">
      {data.map((d) => (
        <div key={d.label} className="row" style={{ gap: 12 }}>
          <div style={{ width: 110, fontSize: 12 }} className="muted">{d.label}</div>
          <div style={{ flex: 1, height: 10, background: 'var(--surface-2)', borderRadius: 999, overflow: 'hidden' }}>
            <div
              style={{
                width: `${Math.min(d.rate, 1) * 100}%`,
                height: '100%',
                background: d.rate >= 0.9 ? 'var(--tone-red)' : d.rate >= 0.75 ? 'var(--tone-amber)' : 'var(--tone-green)',
              }}
            />
          </div>
          <div style={{ width: 44, fontSize: 12, fontWeight: 700 }} className="right">
            {Math.round(d.rate * 100)}%
          </div>
        </div>
      ))}
    </div>
  )
}

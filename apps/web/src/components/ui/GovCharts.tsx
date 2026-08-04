// 거버넌스 대시보드 전용 경량 차트 — 의존성 없이 인라인 SVG로 그린다.
//
// 지키는 규칙(데이터 시각화 원칙):
//  · **이중축 금지** — 스케일이 다른 지표는 한 그림에 겹치지 않고 소형 다중 패널로 나눈다.
//  · 얇은 마크(2px, non-scaling-stroke) · 실선 헤어라인 그리드 · 값 라벨은 선택적으로만.
//  · 계열 색은 검증된 3색만 사용: 파랑 #2b5ce0 / 빨강 #c0392b / 초록 #17a06f
//    (validate_palette all-pairs 통과 — CVD ΔE 9.5, 일반시야 28.8, 대비 3:1 이상)
//  · 색만으로 뜻을 전달하지 않는다 — 화살표·부호·라벨을 항상 함께 붙인다.
import { useState } from 'react'

export const SERIES = {
  budget: '#2b5ce0',      // 예산 소진율
  attrition: '#c0392b',   // 퇴사율
  performance: '#17a06f', // 생산성 지수
} as const

const GRID = 'var(--border)'
const AXIS = 'var(--border-strong)'

/** 값에 맞는 눈금 간격(1·2·2.5·5·10 계열). 축 끝을 데이터 바로 위에서 끊기 위한 것. */
const niceStep = (range: number) => {
  if (range <= 0) return 1
  const magnitude = 10 ** Math.floor(Math.log10(range))
  const n = range / magnitude
  const step = n <= 1.2 ? 0.2 : n <= 2.5 ? 0.5 : n <= 5 ? 1 : 2
  return step * magnitude
}

/** 계열이 실제로 움직이는 구간에 축을 맞춘다.
 *  비율·지수는 0에서 시작할 이유가 없고, 0 고정이면 변화가 눌려 안 보인다.
 *  대신 축 양끝 값을 항상 표기해 기준선이 0이 아님을 드러낸다.
 *  참조선(한도 100% 등)은 축을 넓히기만 하고 눈금 간격 계산에는 넣지 않는다 —
 *  데이터에서 멀리 떨어진 참조값을 간격 계산에 넣으면 정작 계열이 납작해진다. */
const axisRange = (values: number[], reference?: number) => {
  const lo = Math.min(...values)
  const hi = Math.max(...values)
  const step = niceStep((hi - lo) || Math.abs(hi) || 1)
  let min = Math.max(0, Math.floor((lo - step) / step) * step)
  let max = Math.ceil((hi + step) / step) * step
  if (reference != null) {
    min = Math.min(min, Math.floor(reference / step) * step)
    max = Math.max(max, Math.ceil(reference / step) * step)
  }
  return { min, max: max === min ? min + step : max }
}

const fmt = (value: number) => (Number.isInteger(value) ? value.toLocaleString() : value.toFixed(1))

// ── 스파크라인 — KPI 타일·표 행에 들어가는 추세 힌트(축·라벨 없음) ──
export function Sparkline({ data, color = 'var(--primary)', width = 96, height = 28 }: {
  data: number[]; color?: string; width?: number; height?: number
}) {
  if (data.length < 2) return null
  const min = Math.min(...data)
  const max = Math.max(...data)
  const span = max - min || 1
  const x = (i: number) => (i / (data.length - 1)) * (width - 4) + 2
  const y = (v: number) => height - 3 - ((v - min) / span) * (height - 8)
  const path = data.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ')
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true" style={{ display: 'block' }}>
      <path d={path} fill="none" stroke={color} strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
      {/* 끝점만 찍어 "지금 어디인지"를 표시한다 */}
      <circle cx={x(data.length - 1)} cy={y(data[data.length - 1])} r={2.4} fill={color} />
    </svg>
  )
}

// ── 발산 막대 — 0을 가운데 두고 증가(빨강)/감소(파랑). 부호·화살표를 항상 함께 쓴다 ──
export function DeltaBar({ value, max, width = 132 }: { value: number; max: number; width?: number }) {
  const half = width / 2
  const ratio = Math.min(Math.abs(value) / (max || 1), 1)
  const barWidth = Math.max(ratio * half, value === 0 ? 0 : 2)
  const up = value > 0
  const color = value === 0 ? 'var(--muted)' : up ? SERIES.attrition : SERIES.budget
  return (
    <svg width={width} height={14} viewBox={`0 0 ${width} 14`} aria-hidden="true" style={{ display: 'block' }}>
      <line x1={half} y1={0} x2={half} y2={14} stroke={AXIS} strokeWidth={1} />
      <rect
        x={up ? half : half - barWidth} y={3.5} width={barWidth} height={7}
        rx={2} fill={color}
      />
    </svg>
  )
}

/** 증감 텍스트 — 색 + 화살표 + 부호를 함께 쓴다(색만으로 판단시키지 않는다). */
export function DeltaText({ value, suffix = '%', higherIsBetter = false, bold = true }: {
  value: number; suffix?: string; higherIsBetter?: boolean; bold?: boolean
}) {
  if (!Number.isFinite(value)) return <span className="text-meta">–</span>
  const up = value > 0
  const good = value === 0 ? null : up === higherIsBetter
  const color = good === null ? 'var(--muted)' : good ? SERIES.performance : SERIES.attrition
  return (
    <span style={{ color, fontWeight: bold ? 700 : 500, fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }}>
      {value === 0 ? '–' : `${up ? '▲' : '▼'} ${up ? '+' : ''}${value.toFixed(1)}${suffix}`}
    </span>
  )
}

// ── 라인 패널 — 소형 다중 패널의 한 칸. 한 패널에 한 계열만 그린다 ──
export interface LinePanelProps {
  title: string
  unit: string
  data: number[]
  labels: readonly string[]
  color: string
  /** 참조선(예: 예산 100%). 값과 라벨을 함께 준다. */
  reference?: { value: number; label: string }
  height?: number
}

// viewBox 폭은 실제 렌더 폭과 비슷하게 잡는다 — 크게 잡으면 축소되면서 글자가 뭉갠다.
const PAD = { top: 14, right: 42, bottom: 20, left: 34 }
const VIEW_W = 360

export function LinePanel({ title, unit, data, labels, color, reference, height = 122 }: LinePanelProps) {
  const [hover, setHover] = useState<number | null>(null)
  const plotW = VIEW_W - PAD.left - PAD.right
  const plotH = height - PAD.top - PAD.bottom

  const { min, max } = axisRange(data, reference?.value)
  const span = max - min || 1

  const x = (i: number) => PAD.left + (i / (data.length - 1)) * plotW
  const y = (v: number) => PAD.top + plotH - ((v - min) / span) * plotH
  const path = data.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ')

  const last = data[data.length - 1]
  const active = hover ?? data.length - 1

  // 포인터 위치 → 가장 가까운 데이터 인덱스(핀포인트 조준을 요구하지 않는다)
  const pick = (event: React.MouseEvent<SVGSVGElement>) => {
    const box = event.currentTarget.getBoundingClientRect()
    const ratio = ((event.clientX - box.left) / box.width) * VIEW_W
    const index = Math.round(((ratio - PAD.left) / plotW) * (data.length - 1))
    setHover(Math.max(0, Math.min(data.length - 1, index)))
  }

  return (
    <div className="gov-panel">
      <div className="gov-panel-head">
        <span className="gov-panel-title">
          <span className="gov-swatch" style={{ background: color }} aria-hidden="true" />
          {title}
        </span>
        <span className="gov-panel-value" style={{ color }}>
          {fmt(data[active])}<small>{unit}</small>
          <span className="text-meta" style={{ marginLeft: 6, fontWeight: 500 }}>{labels[active]}</span>
        </span>
      </div>
      <svg
        viewBox={`0 0 ${VIEW_W} ${height}`} width="100%" height={height} role="img"
        aria-label={`${title} 추이 — ${labels[0]}부터 ${labels[labels.length - 1]}까지, 현재 ${last}${unit}`}
        onMouseMove={pick}
        onMouseLeave={() => setHover(null)}
        style={{ display: 'block', overflow: 'visible' }}
      >
        {/* 그리드 — 실선 헤어라인. 축 양끝 값을 적어 기준선이 0이 아님을 드러낸다 */}
        {[0, 1].map((t) => (
          <g key={t}>
            <line x1={PAD.left} x2={PAD.left + plotW} y1={PAD.top + plotH * t} y2={PAD.top + plotH * t}
              stroke={GRID} strokeWidth={1} />
            <text x={PAD.left - 5} y={PAD.top + plotH * t + 3} fontSize={9} fill="var(--muted)" textAnchor="end">
              {fmt(t === 0 ? max : min)}
            </text>
          </g>
        ))}
        {/* 참조선 라벨은 왼쪽 위에 둔다 — 오른쪽에 두면 끝점 값 라벨과 겹친다 */}
        {reference && (
          <>
            <line x1={PAD.left} x2={PAD.left + plotW} y1={y(reference.value)} y2={y(reference.value)}
              stroke={AXIS} strokeWidth={1} />
            <text x={PAD.left + 3} y={y(reference.value) - 3} fontSize={9} fill="var(--muted)">
              {reference.label} {fmt(reference.value)}
            </text>
          </>
        )}
        <path d={path} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round"
          vectorEffect="non-scaling-stroke" />
        {/* 끝점 — 2px 표면 링으로 그리드와 분리 */}
        <circle cx={x(data.length - 1)} cy={y(last)} r={4} fill={color} stroke="var(--surface)" strokeWidth={2} />
        <text x={x(data.length - 1) + 7} y={y(last) + 4} fontSize={11} fontWeight={700} fill={color}>
          {fmt(last)}
        </text>
        {hover !== null && (
          <g>
            <line x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={PAD.top + plotH} stroke={AXIS} strokeWidth={1} />
            <circle cx={x(hover)} cy={y(data[hover])} r={4} fill={color} stroke="var(--surface)" strokeWidth={2} />
          </g>
        )}
        {/* x축 — 처음·중간·끝만 찍어 라벨 충돌을 막는다 */}
        {[0, Math.floor((data.length - 1) / 2), data.length - 1].map((i) => (
          <text key={i} x={x(i)} y={height - 6} fontSize={9} fill="var(--muted)"
            textAnchor={i === 0 ? 'start' : i === data.length - 1 ? 'end' : 'middle'}>
            {labels[i]}
          </text>
        ))}
      </svg>
    </div>
  )
}

// ── 소진율 미터 — 한도 대비 하나의 비율. 상태색 + 아이콘 + 라벨을 함께 쓴다 ──
export type BurnStatus = 'OVER' | 'TIGHT' | 'HEALTHY' | 'SLACK'
export const BURN_META: Record<BurnStatus, { label: string; color: string; icon: string }> = {
  OVER: { label: '초과', color: 'var(--tone-red)', icon: '▲' },
  TIGHT: { label: '임박', color: 'var(--tone-amber)', icon: '◆' },
  HEALTHY: { label: '적정', color: 'var(--tone-green)', icon: '●' },
  SLACK: { label: '과다 배정', color: 'var(--tone-teal)', icon: '○' },
}
export const burnStatus = (rate: number): BurnStatus =>
  rate > 100 ? 'OVER' : rate >= 85 ? 'TIGHT' : rate >= 55 ? 'HEALTHY' : 'SLACK'

export function BurnMeter({ label, rate, sub, selected, onClick }: {
  label: string; rate: number; sub?: string; selected?: boolean; onClick?: () => void
}) {
  const status = burnStatus(rate)
  const meta = BURN_META[status]
  return (
    <button type="button" className={'gov-meter' + (selected ? ' selected' : '')} onClick={onClick}
      aria-pressed={selected} title={`${label} — 소진율 ${rate}% (${meta.label})`}>
      <div className="gov-meter-top">
        <span className="gov-meter-label">{label}</span>
        <span className="gov-meter-rate" style={{ color: meta.color }}>
          {meta.icon} {rate}<small>%</small>
        </span>
      </div>
      <div className="gov-meter-track">
        {/* 100% 기준선 — 초과분은 트랙 밖으로 나가지 않고 색으로만 알린다 */}
        <div className="gov-meter-fill" style={{ width: `${Math.min(rate, 100)}%`, background: meta.color }} />
      </div>
      <div className="gov-meter-sub text-meta">{meta.label}{sub ? ` · ${sub}` : ''}</div>
    </button>
  )
}

/** 피어슨 상관계수 — 화면에 표시하는 r은 실제로 그려진 두 계열에서 계산한다. */
export function pearson(a: number[], b: number[]): number {
  const n = Math.min(a.length, b.length)
  if (n < 3) return 0
  const meanA = a.reduce((s, v) => s + v, 0) / n
  const meanB = b.reduce((s, v) => s + v, 0) / n
  let num = 0, devA = 0, devB = 0
  for (let i = 0; i < n; i += 1) {
    const da = a[i] - meanA
    const db = b[i] - meanB
    num += da * db
    devA += da * da
    devB += db * db
  }
  const den = Math.sqrt(devA * devB)
  return den === 0 ? 0 : num / den
}

export const correlationLabel = (r: number) => {
  const abs = Math.abs(r)
  const strength = abs >= 0.8 ? '매우 강한' : abs >= 0.6 ? '강한' : abs >= 0.4 ? '뚜렷한' : abs >= 0.2 ? '약한' : '거의 없는'
  return `${strength} ${r >= 0 ? '양(+)' : '음(−)'}의 상관`
}

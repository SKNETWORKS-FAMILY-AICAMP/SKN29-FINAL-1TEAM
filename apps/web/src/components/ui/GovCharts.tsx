// 경량 인라인 SVG 차트 — 의존성 없이 그린다(S-08 예산 관리 계정과목 추세 등에서 사용).
//
// 지키는 규칙(데이터 시각화 원칙):
//  · 얇은 마크(2px, non-scaling-stroke) · 실선 헤어라인 그리드 · 값 라벨은 선택적으로만.
//  · 계열 색은 검증된 3색만 사용: 파랑 #2b5ce0 / 빨강 #c0392b / 초록 #17a06f
//    (validate_palette all-pairs 통과 — CVD ΔE 9.5, 일반시야 28.8, 대비 3:1 이상)
//  · 색만으로 뜻을 전달하지 않는다 — 화살표·부호·라벨을 항상 함께 붙인다.
export const SERIES = {
  budget: '#2b5ce0',      // 예산 소진율
  attrition: '#c0392b',   // 퇴사율
  performance: '#17a06f', // 생산성 지수
} as const

const AXIS = 'var(--border-strong)'

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

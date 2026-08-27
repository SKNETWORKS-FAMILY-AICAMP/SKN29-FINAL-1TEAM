import type { CSSProperties } from 'react'

/** 로딩 자리표시자 — 불변식(settlement-ui-rules §2) "빈 상태에서도 레이아웃은 한 벌".
 *  내용이 올 자리를 같은 골격으로 채워, 로딩→도착 순간 화면이 펴지며 자리가 바뀌지 않게 한다.
 *  스크린리더에는 장식이므로 aria-hidden. 로딩 사실 자체는 쓰는 쪽이 텍스트로 함께 알린다. */
export function Skeleton({ width, height = 12, style }: { width?: number | string; height?: number | string; style?: CSSProperties }) {
  return <span className="skeleton" aria-hidden="true" style={{ width, height, ...style }} />
}

/** 문단·목록 자리 — 마지막 줄만 짧게 해 실제 텍스트 덩어리처럼 보이게 한다. */
export function SkeletonLines({ rows = 3 }: { rows?: number }) {
  return (
    <div aria-hidden="true">
      {Array.from({ length: rows }, (_, i) => (
        <span key={i} className="skeleton skeleton-line" style={{ width: i === rows - 1 ? '60%' : '100%' }} />
      ))}
    </div>
  )
}

/** 테이블 tbody 자리 — 열 수를 실제 테이블과 맞춰 골격을 유지한다. */
export function SkeletonRows({ rows = 3, cols }: { rows?: number; cols: number }) {
  return (
    <>
      {Array.from({ length: rows }, (_, r) => (
        <tr key={r} aria-hidden="true">
          {Array.from({ length: cols }, (_, c) => (
            <td key={c}><span className="skeleton skeleton-line" style={{ width: c === 0 ? '80%' : '60%' }} /></td>
          ))}
        </tr>
      ))}
    </>
  )
}

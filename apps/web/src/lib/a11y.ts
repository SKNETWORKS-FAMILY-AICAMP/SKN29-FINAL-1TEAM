import type { KeyboardEvent } from 'react'

// 클릭만 가능한 행/헤더(tr, div 등)에 키보드로도 접근할 수 있게 하는 공용 핸들러.
// 체크박스 등 내부 컨트롤 자체의 키 입력(e.g. space로 체크박스 토글)까지 상위로 전파돼
// 이중 동작하는 걸 막기 위해 이벤트가 요소 자신에서 발생했을 때만 반응한다.
export function activateOnEnterOrSpace(onActivate: () => void) {
  return (e: KeyboardEvent<HTMLElement>) => {
    if (e.target !== e.currentTarget) return
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      onActivate()
    }
  }
}

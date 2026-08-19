// "이번 달" 기준을 화면 간에 하나로 맞추는 유틸.
//  팀 통계 대시보드(S-02)·검토 이력(S-03)이 모두 같은 달 경계를 쓰도록 여기서만 정의한다.
//  toISOString()은 UTC 기준이라 월말·월초 자정 근처에서 한 달이 밀린다 — 로컬 시간으로 계산한다.

/** 오늘이 속한 달(`YYYY-MM`). */
export const currentMonth = (): string => {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
}

/** `YYYY-MM-DD` 날짜가 해당 달(`YYYY-MM`)에 속하는지. 날짜가 없으면 제외한다. */
export const isInMonth = (date: string | undefined, month: string): boolean =>
  Boolean(date) && date!.slice(0, 7) === month

/** 오늘 날짜(`YYYY-MM-DD`). 신규 등록 폼의 기본값 등에 쓴다.
 *  `toISOString()`을 쓰지 않는 이유는 위와 같다 — UTC라 자정 근처에서 하루가 밀린다. */
export const todayISO = (): string => {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}

/** `YYYY-MM` → "2026년 8월" 표기. */
export const monthLabel = (month: string): string => {
  const [year, mon] = month.split('-')
  return `${year}년 ${Number(mon)}월`
}

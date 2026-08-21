export const won = (n: number) => '₩' + n.toLocaleString('ko-KR')
export const pct = (n: number) => Math.round(n * 100) + '%'

/** ISO 타임스탬프(서버 응답)를 화면용 "YYYY-MM-DD HH:MM"으로. 파싱 실패 시 원문 그대로. */
export const formatDateTime = (iso: string): string => {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

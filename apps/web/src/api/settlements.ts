// 실제 Django 연동 시 정산 데이터 fetch 계층.
// GET /api/settlements/ 응답(camelCase, risk 평탄화 포함)을 화면 3분류로 나눈다.
import { endpoints } from './client'
import type { ReviewItem, Settlement } from '../types/domain'

export interface SettlementsData {
  myExpenses: Settlement[]
  teamMembers: { name: string; items: Settlement[] }[]
  reviewItems: ReviewItem[]
}

export async function fetchSettlementsData(currentUser?: string): Promise<SettlementsData> {
  const res = await endpoints.settlements()
  const all = (res.data as (Settlement & Partial<ReviewItem>)[]) ?? []

  // ⚠ 서버측 사용자/팀 바인딩(auth)이 없어 client-side로 분리한다 — gap(§ 리포트).
  const myExpenses = currentUser ? all.filter((s) => s.user === currentUser) : all
  const reviewItems = all.filter((s) => s.status === 'IN_REVIEW') as ReviewItem[]

  // S-02는 팀 단계(TEAM_*)에 머물러 있는 건을 노출한다 — 취합 대기 + 팀 보완요청·팀 반려 결과.
  //  회계로 제출(SUBMITTED)된 건은 팀 화면에서 빠진다.
  const teamCollecting = all.filter((s) => s.status.startsWith('TEAM_'))
  const byUser = new Map<string, Settlement[]>()
  for (const s of teamCollecting) {
    const key = s.user ?? '미지정'
    if (!byUser.has(key)) byUser.set(key, [])
    byUser.get(key)!.push(s)
  }
  const teamMembers = [...byUser.entries()].map(([name, items]) => ({ name, items }))

  return { myExpenses, teamMembers, reviewItems }
}

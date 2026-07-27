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

  const byUser = new Map<string, Settlement[]>()
  for (const s of all) {
    const key = s.user ?? '미지정'
    if (!byUser.has(key)) byUser.set(key, [])
    byUser.get(key)!.push(s)
  }
  const teamMembers = [...byUser.entries()].map(([name, items]) => ({ name, items }))

  return { myExpenses, teamMembers, reviewItems }
}

// 실제 Django 연동 시 정산 데이터 fetch 계층.
// GET /api/settlements/ 응답(camelCase, risk 평탄화 포함)을 화면 3분류로 나눈다.
import { endpoints } from './client'
import type { ReviewItem, Settlement, SettlementStatus } from '../types/domain'

export interface SettlementsData {
  /** 원본 전체 — 화면별 스코프(팀·월·상태)는 각 화면이 여기서 좁힌다. */
  all: Settlement[]
  myExpenses: Settlement[]
  teamMembers: { name: string; items: Settlement[] }[]
  reviewItems: ReviewItem[]
}

/** 회계 담당자가 이미 결정을 내린 상태 — S-03 "이전 처리"의 대상.
 *  APPROVE→PENDING_CONFIRM(→CONFIRMED→ERP_VOUCHER_DRAFTED) / RETURN→RETURNED / REJECT→REJECT */
export const REVIEW_DECIDED_STATUSES: SettlementStatus[] = [
  'PENDING_CONFIRM', 'RETURNED', 'REJECT', 'CONFIRMED', 'ERP_VOUCHER_DRAFTED',
]

/** 팀 단계에 머물러 있는 상태 — S-02 취합 목록의 대상. */
export const TEAM_STAGE_PREFIX = 'TEAM_'

/** 검토 화면은 Risk 필드를 전제로 렌더한다. 이상탐지가 돌지 않은 건(이미 처리된 과거 건 등)도
 *  같은 목록에 섞이므로, 빠진 필드를 안전한 기본값으로 채워 NaN·undefined 렌더를 막는다. */
function toReviewItem(row: Settlement & Partial<ReviewItem>): ReviewItem {
  return {
    ...row,
    anomalyScore: row.anomalyScore ?? 0,
    featureContribs: row.featureContribs ?? [],
    ragRefs: row.ragRefs ?? [],
    aiRecommendation: row.aiRecommendation ?? 'APPROVE',
    aiConfidence: row.aiConfidence ?? 0,
    anomalyReasons: row.anomalyReasons ?? [],
    // Risk Review가 아직 안 돈 건은 빈 문자열 — '문제없음'으로 접으면 안 된다.
    violationVerdict: row.violationVerdict ?? '',
  }
}

export async function fetchSettlementsData(currentUser?: string): Promise<SettlementsData> {
  const res = await endpoints.settlements()
  const all = (res.data as (Settlement & Partial<ReviewItem>)[]) ?? []

  // ⚠ 서버측 사용자/팀 바인딩(auth)이 없어 client-side로 분리한다 — gap(§ 리포트).
  const myExpenses = currentUser ? all.filter((s) => s.user === currentUser) : all

  // S-03은 검토 대기(IN_REVIEW) + 이미 처리된 건을 함께 싣는다.
  //  이전 처리 탭이 "이번 세션에서 처리한 건"만 보이던 문제 때문 — 달 필터는 화면에서 건다.
  const reviewItems = all
    .filter((s) => s.status === 'IN_REVIEW' || REVIEW_DECIDED_STATUSES.includes(s.status))
    .map(toReviewItem)

  // S-02는 팀 단계(TEAM_*)에 머물러 있는 건을 노출한다 — 취합 대기 + 팀 보완요청·팀 반려 결과.
  //  회계로 제출(SUBMITTED)된 건은 팀 화면에서 빠진다. 팀·월 스코프는 화면에서 좁힌다.
  const teamCollecting = all.filter((s) => s.status.startsWith(TEAM_STAGE_PREFIX))
  const byUser = new Map<string, Settlement[]>()
  for (const s of teamCollecting) {
    const key = s.user ?? '미지정'
    if (!byUser.has(key)) byUser.set(key, [])
    byUser.get(key)!.push(s)
  }
  const teamMembers = [...byUser.entries()].map(([name, items]) => ({ name, items }))

  return { all, myExpenses, teamMembers, reviewItems }
}

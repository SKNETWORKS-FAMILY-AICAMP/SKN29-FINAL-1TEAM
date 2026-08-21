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

/**
 * **확정 대기** — 아직 사람이 확정(CONFIRMED)하지 않은 건. S-03 "확정 대기" 탭의 대상.
 *
 * `PENDING_CONFIRM`에는 두 갈래가 도착한다: ① 룰 판정 PASS로 **자동** 도착한 건
 * (사람이 아직 아무것도 안 봤다) ② 회계 담당자가 승인한 건. 둘 다 `confirm()`을 눌러야
 * CONFIRMED가 된다(FR-ST-03 사람 확정 원칙) — 그래서 "처리 완료"가 아니라 **대기**다.
 * 예전엔 이 상태가 "이전 처리 · 승인"으로 묶여서, 아무도 안 본 건이 승인된 것처럼 보였다.
 */
export const AWAITING_CONFIRM_STATUSES: SettlementStatus[] = ['PENDING_CONFIRM']

/** 회계 처리가 실제로 끝난 상태 — S-03 "이전 처리"의 대상. */
export const REVIEW_HISTORY_STATUSES: SettlementStatus[] = [
  'CONFIRMED', 'ERP_VOUCHER_DRAFTED', 'RETURNED', 'REJECT',
]

/** 검토 화면이 싣는 전체 범위(대기 + 확정대기 + 이력). */
export const REVIEW_DECIDED_STATUSES: SettlementStatus[] = [
  ...AWAITING_CONFIRM_STATUSES, ...REVIEW_HISTORY_STATUSES,
]

/** 팀 단계에 머물러 있는 상태 — S-02 취합 목록의 대상. */
export const TEAM_STAGE_PREFIX = 'TEAM_'

/** 검토 화면은 Risk 필드를 전제로 렌더한다. 이상탐지가 돌지 않은 건(이미 처리된 과거 건 등)도
 *  같은 목록에 섞이므로, 빠진 필드를 안전한 기본값으로 채워 NaN·undefined 렌더를 막는다. */
function toReviewItem(row: Settlement & Partial<ReviewItem>): ReviewItem {
  return {
    ...row,
    // 정렬용 기본값이다. **화면 표시는 `riskReviewed`를 봐야 한다** — 0점과 미실시는 다르다.
    anomalyScore: row.anomalyScore ?? 0,
    riskTier: row.riskTier ?? '',
    riskReviewed: row.riskReviewed ?? false,
    //  결과가 있으면 상태가 뭐라 하든 DONE이다(옛 데이터 방어).
    riskReviewState: row.riskReviewed ? 'DONE' : (row.riskReviewState ?? 'NOT_STARTED'),
    riskReviewError: row.riskReviewError ?? '',
    featureContribs: row.featureContribs ?? [],
    ragRefs: row.ragRefs ?? [],
    // **기본값을 'APPROVE'로 채우지 않는다.** Risk Review가 안 돈 건이 "AI 권장: 승인"으로
    // 표시되면, 아무도 판단하지 않은 건을 담당자가 판단된 것으로 읽는다. 아래 violationVerdict가
    // 같은 이유로 이미 빈 문자열을 쓰고 있었는데 여기만 어긋나 있었다.
    aiRecommendation: row.aiRecommendation ?? '',
    aiConfidence: row.aiConfidence ?? 0,
    anomalyReasons: row.anomalyReasons ?? [],
    // Risk Review가 아직 안 돈 건은 빈 문자열 — '문제없음'으로 접으면 안 된다.
    violationVerdict: row.violationVerdict ?? '',
  }
}

export async function fetchSettlementsData(
  currentUser?: string, currentTeamId?: number,
): Promise<SettlementsData> {
  const res = await endpoints.settlements()
  const all = (res.data as (Settlement & Partial<ReviewItem>)[]) ?? []

  // ⚠ 서버측 사용자/팀 바인딩(auth)이 없어 client-side로 분리한다 — gap(§ 리포트).
  //
  // '내 지출' = 내게 귀속된 건 ∪ **같은 팀의 실사용자 미등록 건**.
  //  후자는 팀·공용 카드 결제라 주인이 없다(`user`가 비어 있다) — 주인 기준으로만 거르면
  //  아무에게도 안 보여서 실사용자가 본인 등록을 할 방법이 사라진다.
  const myExpenses = currentUser
    ? all.filter((s) => s.user === currentUser
        || (s.claimPending && (currentTeamId == null || s.teamId === currentTeamId)))
    : all

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

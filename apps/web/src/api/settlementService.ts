// 정산 상태전이 서비스 레이어 — 화면은 mock 배열을 직접 만지지 않고 이 함수들을 거친다.
// USE_MOCK=true인 동안은 실제 네트워크 호출 없이 지연만 흉내내고 새 상태를 돌려준다.
// 백엔드(Django)가 준비되면 이 파일 안쪽만 endpoints.* 실제 호출로 바꾸면 되고, 화면 컴포넌트는 그대로 둔다.
import { endpoints } from './client'
import { USE_MOCK } from './config'
import type { ImportResult, Settlement, SettlementStatus } from '../types/domain'

export async function fetchSettlementDetail(item: Settlement): Promise<Settlement> {
  if (USE_MOCK) return item
  const res = await endpoints.settlement(item.id)
  return res.data
}

const mockDelay = () => new Promise((resolve) => setTimeout(resolve, 250))

/** F-1: 신규 지출 등록(영수증 업로드 + AI 판독 확인 후 제출). id/status는 서버가 생성 — mock에서는 흉내낸다. */
export async function createSettlement(draft: Omit<Settlement, 'id' | 'status'>): Promise<Settlement> {
  if (USE_MOCK) {
    await mockDelay()
    // 신규 건은 '개인 보유중(DRAFT)'으로 생성 — 이후 목록에서 제출
    return { ...draft, id: `S-1${Math.floor(100 + Math.random() * 900)}`, status: 'DRAFT' }
  }
  const res = await endpoints.createSettlement(draft)
  return res.data
}

/**
 * 상세 화면에서 고친 값을 저장한다. **상태 전이(올림·제출) 직전에 먼저 부른다.**
 *
 * 여기서 보내는 `category`는 **사람이 확정한 분류**다 — 드롭다운에 AI 제안이 미리 채워져
 * 있어도, 저장하는 순간 「사람이 그 값으로 확정했다」는 기록이 된다. 서버의 `ai_category`
 * (AI가 원래 뭐라고 했는지)는 건드리지 않는다 — 제안↔확정을 대조해야 정확도를 잴 수 있다.
 */
export async function updateSettlement(
  id: string, patch: Record<string, unknown>,
): Promise<Settlement | null> {
  if (USE_MOCK) { await mockDelay(); return null }
  const { data } = await endpoints.updateSettlement(id, patch)
  return data
}

/**
 * S-01: ERP/카드사 결제기록 수집("내역 불러오기").
 *
 * 표본 3회분이 준비돼 있고 누를 때마다 다음 회차가 들어온다. 같은 결제는 두 번 들어오지
 * 않는다(서버가 원천 식별자로 막는다) — 화면이 중복 방지를 떠안지 않아도 된다.
 *
 * `minMillis`: 실제 ERP 연동은 수 초가 걸린다. 응답이 즉시 오면 "눌렸나?" 싶어서
 * 최소 표시 시간을 둔다 — 진행 상태를 **꾸며내는 게 아니라** 실제 호출을 기다리되
 * 너무 빨리 끝나면 그만큼만 더 보여준다.
 */
export async function importSettlements(minMillis = 1200): Promise<ImportResult> {
  const started = Date.now()
  const run = USE_MOCK
    ? Promise.resolve({ data: { batch: 1, totalBatches: 3, created: 3, skipped: 0, claimPending: 1, exhausted: false } })
    : endpoints.importSettlements()
  const { data } = await run
  const elapsed = Date.now() - started
  if (elapsed < minMillis) await new Promise((r) => setTimeout(r, minMillis - elapsed))
  return {
    batch: data.batch, totalBatches: data.totalBatches, created: data.created,
    skipped: data.skipped, claimPending: data.claimPending, exhausted: data.exhausted,
  }
}

/** S-01: 팀·공용 카드 결제의 실사용자 본인 등록("내가 사용했어요"). */
export async function claimSettlement(id: string): Promise<SettlementStatus> {
  if (USE_MOCK) { await mockDelay(); return 'DRAFT' }
  const { data } = await endpoints.claimSettlement(id)
  return data.status as SettlementStatus
}

/** S-01: 개인 '올림'(DRAFT → TEAM_COLLECTING). 팀 취합 단계로 넘긴다(1인 팀도 동일 경로). */
export async function raiseSettlements(ids: string[]): Promise<SettlementStatus> {
  if (USE_MOCK) {
    await mockDelay()
    return 'TEAM_COLLECTING'
  }
  await endpoints.raise(ids)
  return 'TEAM_COLLECTING'
}

/**
 * S-02: 팀 제출(TEAM_COLLECTING → SUBMITTED) · 회계 보완요청 재제출(RETURNED → SUBMITTED).
 *
 * 제출 직후 **룰 엔진 1차판정이 이어서 돌기 때문에** 최종 상태는 건마다 다르다
 * (PASS→`PENDING_CONFIRM` / RETURN·REJECT→`RETURNED` / REVIEW→`IN_REVIEW`).
 * 그래서 단일 상태가 아니라 id별 결과를 돌려준다 — 예전처럼 `'SUBMITTED'`를 그대로
 * 돌려주면 화면이 실제 상태와 다른 값을 그린다. 판정이 실패한 건은 `SUBMITTED`에 남는다.
 */
export type SubmitOutcome = {
  status: Record<string, SettlementStatus>
  /** 룰 판정 결정 — 검토 사유 표시용. */
  decision: Record<string, string>
  /** 판정에 실패한 건(제출 자체는 성공). 재판정이 필요하다. */
  failed: Record<string, string>
}

export async function submitSettlements(ids: string[]): Promise<SubmitOutcome> {
  if (USE_MOCK) {
    await mockDelay()
    return {
      status: Object.fromEntries(ids.map((id) => [id, 'SUBMITTED' as SettlementStatus])),
      decision: {}, failed: {},
    }
  }
  const { data } = await endpoints.submit(ids)
  const judged: Record<string, { decision: string; status: SettlementStatus }> = data?.judged ?? {}
  const status: Record<string, SettlementStatus> = {}
  const decision: Record<string, string> = {}
  for (const id of ids) {
    status[id] = judged[id]?.status ?? 'SUBMITTED'
    if (judged[id]) decision[id] = judged[id].decision
  }
  return { status, decision, failed: data?.judgeFailed ?? {} }
}

/** S-03/S-06: 회계 담당자의 승인·보완요청·반려 결정(FR-ST-03: 사람 확정 필수). */
export async function reviewSettlement(
  id: string,
  decision: 'APPROVE' | 'RETURN' | 'REJECT',
  reason?: string,
): Promise<SettlementStatus> {
  if (USE_MOCK) {
    await mockDelay()
    return decision === 'APPROVE' ? 'CONFIRMED' : decision === 'RETURN' ? 'RETURNED' : 'REJECT'
  }
  const res = await endpoints.review(id, decision, reason)
  return res.data.status
}

/**
 * FR-ST-03 사람 최종 확정 — PENDING_CONFIRM → CONFIRMED(→ ERP 전표(안) 자동 생성).
 *
 * 룰이 통과시킨 건도 **사람 확정 없이는 CONFIRMED가 될 수 없다**("사람 확정 원칙").
 * 이 함수가 없어서 확정 대기 건이 화면에서 어디로도 갈 수 없었다.
 * 실패 시 `null` — 상태를 임의로 바꿔 그리지 않는다.
 */
export async function confirmSettlement(id: string): Promise<SettlementStatus | null> {
  if (USE_MOCK) { await mockDelay(); return 'ERP_VOUCHER_DRAFTED' }
  try {
    const res = await endpoints.confirm(id)
    return res.data.status as SettlementStatus
  } catch { return null }
}

/** 보완요청·반려 사유 초안 (Draft Agent). `source`는 'ai' 또는 'fallback'(판정 플래그 기반). */
export interface DecisionReasonDraft {
  reason: string
  detail: string
  source: 'ai' | 'fallback'
  /** 사유 선택지 — **서버가 준다**. 화면과 LLM이 같은 목록을 봐야 어긋나지 않는다. */
  options: string[]
}

/**
 * 결정 모달이 열릴 때 사유 초안을 받아온다.
 *
 * 실패해도 모달을 막지 않는다 — 초안이 없으면 사람이 직접 쓰면 되고, 결정 자체가
 * 초안 생성에 묶이면 ai가 죽었을 때 정산이 멈춘다.
 */
export async function fetchDecisionReason(
  id: string, decision: 'RETURN' | 'REJECT',
): Promise<DecisionReasonDraft | null> {
  if (USE_MOCK) { await mockDelay(); return null }
  try {
    const { data } = await endpoints.decisionReason(id, decision)
    return data
  } catch {
    return null
  }
}

/** S-02/S-06: 팀 취합 단계의 보완요청·반려(회계 결정과 별도 상태). */
export async function decideTeamSettlement(
  id: string,
  decision: 'RETURN' | 'REJECT',
  reason?: string,
): Promise<SettlementStatus> {
  if (USE_MOCK) {
    await mockDelay()
    return decision === 'RETURN' ? 'TEAM_RETURNED' : 'TEAM_REJECTED'
  }
  const res = await endpoints.teamDecision(id, decision, reason)
  return res.data.status
}

// ── 초안 작성 Agent (플레이스홀더 API) ───────────────────────────
export interface PolicyHint { level: 'info' | 'warn'; clause: string; text: string; status: string }
export interface DraftSuggestion {
  mode: 'create' | 'revise'
  draft: Record<string, string | number | boolean>
  changes?: string[]
  confidence?: number
  comments: { icon: string; text: string }[]
  policyHints: PolicyHint[]
}

/** F-1: 영수증·거래 정보로 정산 초안을 생성한다(Draft Agent). */
export async function suggestDraft(input: Record<string, unknown>): Promise<DraftSuggestion | null> {
  if (USE_MOCK) { await mockDelay(); return null }
  try {
    const res = await endpoints.suggestDraft(input)
    return res.data as DraftSuggestion
  } catch { return null }
}

/** F-1: 자연어 지시로 초안을 수정한다(Draft Agent). */
export async function reviseDraft(
  instruction: string,
  current: Record<string, unknown>,
): Promise<DraftSuggestion | null> {
  if (USE_MOCK) { await mockDelay(); return null }
  try {
    const res = await endpoints.suggestDraft({ instruction, current })
    return res.data as DraftSuggestion
  } catch { return null }
}

export interface ReviewStats {
  autoProcessedRate: number | null // 0~1. 이번 달 판정 자체가 없으면 null(집계 불가 ≠ 0%)
  avgReviewMinutes: number | null  // 사람이 실제로 내린 결정이 없으면 null
}

/** S-03 헤더 요약(자동처리율·평균 검토시간) — 룰 판정·검토 이력 기반 서버 집계.
 *  실패해도 화면이 죽으면 안 된다(부가 지표라 숫자 대신 자리표시자로 대체). */
export async function fetchReviewStats(): Promise<ReviewStats | null> {
  if (USE_MOCK) {
    await mockDelay()
    return { autoProcessedRate: 0.82, avgReviewMinutes: 6.2 }
  }
  try {
    const res = await endpoints.reviewStats()
    return { autoProcessedRate: res.data.autoProcessedRate, avgReviewMinutes: res.data.avgReviewMinutes }
  } catch {
    return null
  }
}

/** '내 지출': 아직 올리지 않은 건 삭제. 성공 여부를 돌려준다. */
export async function deleteSettlement(id: string): Promise<boolean> {
  if (USE_MOCK) { await mockDelay(); return true }
  try {
    await endpoints.deleteSettlement(id)
    return true
  } catch { return false }
}

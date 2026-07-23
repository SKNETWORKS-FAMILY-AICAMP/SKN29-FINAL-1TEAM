// 정산 상태전이 서비스 레이어 — 화면은 mock 배열을 직접 만지지 않고 이 함수들을 거친다.
// USE_MOCK=true인 동안은 실제 네트워크 호출 없이 지연만 흉내내고 새 상태를 돌려준다.
// 백엔드(Django)가 준비되면 이 파일 안쪽만 endpoints.* 실제 호출로 바꾸면 되고, 화면 컴포넌트는 그대로 둔다.
import { endpoints } from './client'
import type { Settlement, SettlementStatus } from '../types/domain'

const USE_MOCK = true
const mockDelay = () => new Promise((resolve) => setTimeout(resolve, 250))

/** F-1: 신규 지출 등록(영수증 업로드 + AI 판독 확인 후 제출). id/status는 서버가 생성 — mock에서는 흉내낸다. */
export async function createSettlement(draft: Omit<Settlement, 'id' | 'status'>): Promise<Settlement> {
  if (USE_MOCK) {
    await mockDelay()
    return { ...draft, id: `S-1${Math.floor(100 + Math.random() * 900)}`, status: 'SUBMITTED' }
  }
  const res = await endpoints.createSettlement(draft)
  return res.data
}

/** S-01/S-02: 선택 건 일괄 제출(DRAFT → SUBMITTED). */
export async function submitSettlements(ids: string[]): Promise<SettlementStatus> {
  if (USE_MOCK) {
    await mockDelay()
    return 'SUBMITTED'
  }
  await endpoints.submit(ids)
  return 'SUBMITTED'
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

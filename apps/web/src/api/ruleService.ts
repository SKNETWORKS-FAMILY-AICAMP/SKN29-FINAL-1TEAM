// Rule 상태전이 서비스 레이어 — 화면은 endpoints.*를 직접 부르지 않고 이 함수들을 거친다.
// USE_MOCK=true인 동안은 실제 네트워크 호출 없이 지연만 흉내낸다.
import { endpoints } from './client'

const USE_MOCK = true
const mockDelay = () => new Promise((resolve) => setTimeout(resolve, 250))

/** Tab3: 승인대기 버전을 ACTIVE로 전환(팀장급 이상만 가능 — 화면단에서 권한 체크). */
export async function activateRule(id: string): Promise<void> {
  if (USE_MOCK) { await mockDelay(); return }
  await endpoints.activateRule(id)
}

/** Tab3: 과거 버전으로 롤백. */
export async function rollbackRule(id: string): Promise<void> {
  if (USE_MOCK) { await mockDelay(); return }
  await endpoints.rollbackRule(id)
}

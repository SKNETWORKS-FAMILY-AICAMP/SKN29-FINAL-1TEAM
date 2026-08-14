// Rule 상태전이 서비스 레이어 — 화면은 endpoints.*를 직접 부르지 않고 이 함수들을 거친다.
// USE_MOCK=true인 동안은 실제 네트워크 호출 없이 지연만 흉내낸다.
import { endpoints } from './client'
import { USE_MOCK } from './config'

const mockDelay = () => new Promise((resolve) => setTimeout(resolve, 250))

/** Tab3: 승인대기 버전을 ACTIVE로 전환(팀장급 이상만 가능 — 화면단에서 권한 체크). */
export async function activateRule(id: string): Promise<void> {
  if (USE_MOCK) { await mockDelay(); return }
  await endpoints.activateRule(id)
}

/** Tab3: 직전 승인 버전으로 롤백. */
export async function rollbackRule(id: string): Promise<void> {
  if (USE_MOCK) { await mockDelay(); return }
  await endpoints.rollbackRule(id)
}

/** Tab3: 버전 이력에서 고른 과거 버전으로 롤백. */
export async function rollbackRuleTo(id: string): Promise<void> {
  if (USE_MOCK) { await mockDelay(); return }
  await endpoints.rollbackRuleTo(id)
}

/** Rule Agent가 생성한 DRAFT 그래프의 요약 — 화면은 graphId로 그 그래프를 열면 된다. */
export type GeneratedRuleGraph = {
  graphId: string
  version: number
  scope: string
  /** 근거로 쓰인 조문 인용(「문서명」 제N조 …). */
  sources: string[]
  /** LLM이 만들었지만 검증에서 탈락한 노드 수 — 0이 아니면 담당자가 확인해야 한다. */
  rejectedCount: number
}

/**
 * Tab1: 규정 문서(RAG)에서 룰 그래프 DRAFT를 자동 생성한다.
 *
 * 생성물은 **항상 DRAFT**다 — 자동 승인은 없다(FR-RV-04). 담당자가 룰 콘솔에서 내용을
 * 검토·수정하고 시뮬레이션을 돌린 뒤에야 Active 요청으로 넘어간다.
 * 실패 사유(규정 미적재·인증·scope 불량)는 그대로 올려 화면이 이유를 보여주게 한다.
 */
export async function generateRuleGraph(
  input: { scope: string; name?: string; query?: string; includeLaw?: boolean },
): Promise<GeneratedRuleGraph> {
  if (USE_MOCK) {
    await mockDelay()
    return { graphId: 'mock-generated', version: 1, scope: input.scope, sources: [], rejectedCount: 0 }
  }
  const { data } = await endpoints.generateRuleGraph(input)
  if (data?.status !== 'DRAFT_SAVED') {
    // NO_SOURCE(규정 미적재) / NO_VALID_NODES(생성 노드 전건 탈락) — 둘 다 정상 응답이라
    // 여기서 예외로 바꿔야 화면이 성공으로 오해하지 않는다.
    throw new Error(data?.detail || '룰 생성에 실패했습니다.')
  }
  return {
    graphId: String(data.graph?.graph_id ?? ''),
    version: Number(data.graph?.version ?? 1),
    scope: String(data.graph?.scope ?? input.scope),
    sources: Array.isArray(data.sources) ? data.sources : [],
    rejectedCount: Array.isArray(data.rejected_nodes) ? data.rejected_nodes.length : 0,
  }
}

// 검증 시뮬레이션(POST /api/rules/{id}/simulate/) 요청·응답 계약 + 검증셋(에이전트 자동생성 전용) 모델.
// 사람이 자연어/폼으로 케이스를 직접 만들던 mock 모달(TestCaseModal)은 2026-08-18 제거했다
// — 검증셋은 "검증셋 자동생성"(§12, `_solve` 역산+LLM 라벨링+자체검증)이 유일한 생성 경로다.
export type Decision = 'PASS' | 'REVIEW' | 'RETURN' | 'REJECT'
export const DECISIONS: Decision[] = ['PASS', 'REVIEW', 'RETURN', 'REJECT']
export const DECISION_LABEL: Record<Decision, string> = {
  PASS: '통과', REVIEW: '검토 필요', RETURN: '보완요청', REJECT: '반려',
}
export const decisionTone = (decision: string) =>
  decision === 'PASS' ? 'ok' : decision === 'REVIEW' ? 'ai' : decision ? 'warn' : ''

export interface TestCase {
  id: string
  label: string
  merchant: string
  amount: number
  category: string
  merchantType: string
  paymentMethod: string
  /** 기대 판정 — 비우면 채점하지 않는다. */
  expected: '' | Decision
  facts: Record<string, boolean | number>
}

export interface SimResultRow {
  id: string
  source: 'test' | 'history'
  label: string
  merchant: string
  amount: number
  category: string
  date: string
  currentStatus: string
  /** 기존 처리 분류(정산 상태 기반). 비면 미처리. */
  baseline: string
  changed: boolean
  aiComment: string
  /** 플래그·평가경로 등 기술 상세 — "자세히 보기"에서만 펼쳐 보여준다. */
  aiCommentDetail: string
  commentVerdict: 'intended' | 'risk' | 'reversal' | ''
  decision: string
  path: string[]
  flags: string[]
  expected: string
  matchedExpectation: boolean | null
  risk: boolean
  auto: boolean
}

export type GradeLevel = 'poor' | 'warn' | 'good'
export interface Grade {
  level: GradeLevel; label: string; note: string; cause?: ('structure' | 'result')[]
  /** true면 이 등급(주로 action)이 결정론적 규칙이 아니라 Agent가 facts를 보고 재판단한 값 —
   * 단, 구조 오류가 있으면 서버가 poor로 강제해 이 값이 true여도 poor 밑으로는 못 내려간다. */
  aiAdjusted?: boolean
}
export const gradeTone = (level: GradeLevel) => level === 'good' ? 'ok' : level === 'warn' ? 'caution' : 'warn'

export interface SimReport {
  runId: number
  graphId: string
  graphName: string
  graphVersion: number
  ranAt: string
  ranBy: string
  periodLabel: string
  placeholder: boolean
  structureError: string
  /** 실행 이후 그래프가 바뀌었으면 true — 화면에 "낡은 결과"로 표시한다. */
  stale: boolean
  snapshotHash: string
  stats: {
    autoRate: number
    autoCount: number
    manualCount: number
    prevAutoRate: number
    prevVersionLabel: string
    hasPrevVersion: boolean
    /** 이전 버전 자동처리율 대비 증가폭(%p). */
    reviewReduction: number
    historyTotal: number
    reviewCount: number
    riskCount: number
    changedCount: number
    testTotal: number
    testGraded: number
    testPassed: number
    testFailed: number
    nodeCoverage: number
    visitedNodes: number
    /** 변경건 중 AI가 위험하다고 본 건(완전 반전 포함) / 의도된 정상 변경으로 본 건 */
    riskChangedCount: number
    /** 위험 변경 중에서도 "이미 사람이 반려/보완요청으로 확정했던 건이 통과로 뒤집힌" 최우선 확인 대상 */
    reversalChangedCount: number
    intendedChangedCount: number
  }
  grades: { structure: Grade; result: Grade; action: Grade }
  structure: { nodeCount: number; routingCount: number; maxDepth: number; unreachable: string[]; terminals: string[]; entry: string }
  agentReport: string
  testResults: SimResultRow[]
  historyResults: SimResultRow[]
}

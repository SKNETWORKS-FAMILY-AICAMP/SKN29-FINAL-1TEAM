// 검증 시뮬레이션(POST /api/rules/{id}/simulate/) 요청·응답 계약 + 테스트케이스 편집 모델.
export type Decision = 'PASS' | 'REVIEW' | 'RETURN' | 'REJECT'
export const DECISIONS: Decision[] = ['PASS', 'REVIEW', 'RETURN', 'REJECT']
export const DECISION_LABEL: Record<Decision, string> = {
  PASS: '통과', REVIEW: '검토 필요', RETURN: '보완요청', REJECT: '반려',
}
export const decisionTone = (decision: string) =>
  decision === 'PASS' ? 'ok' : decision === 'REVIEW' ? 'ai' : decision ? 'warn' : ''

/** 화면에서 직접 조정할 수 있는 판정 입력값(EvalContext dot-path). */
export const BOOLEAN_FACTS = [
  { path: 'evidence.has_valid_receipt', label: '적격증빙 있음' },
  { path: 'approval.pre_approval_obtained', label: '사전승인 받음' },
  { path: 'evidence.purpose_missing', label: '사용 목적 누락' },
  { path: 'derived.is_late_night', label: '심야 결제' },
  { path: 'derived.is_weekend', label: '주말 결제' },
  { path: 'derived.biz_days_over_7', label: '정산 지연(영업일 7일 초과)' },
] as const

export const NUMBER_FACTS = [
  { path: 'participants.participant_count', label: '참석 인원' },
  { path: 'participants.external_participant_count', label: '외부 참석자' },
  { path: 'history.same_vendor_count_3m', label: '동일 가맹점 3개월 결제 수' },
  { path: 'history.daily_cumulative_amount', label: '당일 누적 사용액(원)' },
  { path: 'policy.position_daily_limit', label: '직책 일일 한도(원)' },
] as const

export const CATEGORIES = ['업무활성', '회의', '식대', '출장', '접대', '비품'] as const

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
  commentVerdict: 'intended' | 'risk' | ''
  decision: string
  path: string[]
  flags: string[]
  expected: string
  matchedExpectation: boolean | null
  risk: boolean
  auto: boolean
}

export type GradeLevel = 'poor' | 'warn' | 'good'
export interface Grade { level: GradeLevel; label: string; note: string }
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
    /** 변경건 중 AI가 위험하다고 본 건 / 의도된 정상 변경으로 본 건 */
    riskChangedCount: number
    intendedChangedCount: number
  }
  grades: { structure: Grade; result: Grade; action: Grade }
  structure: { nodeCount: number; routingCount: number; maxDepth: number; unreachable: string[]; terminals: string[]; entry: string }
  agentReport: string
  testResults: SimResultRow[]
  historyResults: SimResultRow[]
}

const testCase = (
  id: string, label: string, merchant: string, amount: number, category: string,
  expected: TestCase['expected'], facts: Record<string, boolean | number>, merchantType = '',
): TestCase => ({ id, label, merchant, amount, category, merchantType, paymentMethod: '법인카드', expected, facts })

/** 기본 검증셋 — 사용자가 모달에서 자유롭게 수정·추가한다. */
export const DEFAULT_TEST_CASES: TestCase[] = [
  testCase('TC-1', '정상 소액 식대', '김밥천국', 32000, '식대', 'PASS',
    { 'evidence.has_valid_receipt': true, 'approval.pre_approval_obtained': true, 'participants.participant_count': 3 }),
  testCase('TC-2', '고액 결제 · 사전승인 누락', '한우마을', 820000, '접대', 'RETURN',
    { 'evidence.has_valid_receipt': false, 'approval.pre_approval_obtained': false, 'participants.participant_count': 6, 'participants.external_participant_count': 2 }),
  testCase('TC-3', '심야 주점 · 외부 참석', '강남 포차', 260000, '접대', 'REVIEW',
    { 'evidence.has_valid_receipt': true, 'derived.is_late_night': true, 'participants.external_participant_count': 1 }, '주점'),
  testCase('TC-4', '주말 회식 · 일일 한도 초과', '고기집', 450000, '식대', 'REVIEW',
    { 'evidence.has_valid_receipt': true, 'derived.is_weekend': true, 'participants.participant_count': 12,
      'history.daily_cumulative_amount': 1200000, 'policy.position_daily_limit': 500000 }),
  testCase('TC-5', '주말 결제 · 사용 목적 누락', '스타벅스 본사점', 48000, '회의', 'RETURN',
    { 'evidence.has_valid_receipt': true, 'derived.is_weekend': true, 'evidence.purpose_missing': true }),
  testCase('TC-6', '대규모 · 동일 가맹점 반복', '한식뷔페', 380000, '회의', 'REVIEW',
    { 'evidence.has_valid_receipt': true, 'participants.participant_count': 12, 'history.same_vendor_count_3m': 6 }),
]

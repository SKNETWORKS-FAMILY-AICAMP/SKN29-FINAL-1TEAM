// S-04 Rule 콘솔(v4~v6 통합) 전용 목업 데이터. 이 화면 밖에서는 재사용하지 않는다.

// ── Tab1: Rule 초안 대기 (v4, 대화형 AI 편집) ─────────────
export interface DraftRule {
  id: string
  title: string
  status: 'DRAFT'
  description: string
  logic: string
  sourceClause: string
  aiReason: string
}

export const DRAFT_RULES: DraftRule[] = [
  {
    id: 'R-102', title: '식대 30만원 초과 사전승인 필요', status: 'DRAFT',
    description: '식대 분류 지출 중 건당 30만원을 초과하는 경우, 사전승인 여부를 확인하도록 플래그를 지정합니다.',
    logic: 'IF category == "식대" AND amount > 300000\nTHEN flag = "PRE_APPROVAL_REQUIRED"',
    sourceClause: '법인카드 사용규정 제10조②',
    aiReason: 'RAG 검색 결과 제10조②항에서 식대·기업업무추진비는 직책과 무관하게 건당 30만원 초과 시 사전승인 대상으로 명시되어 있어, 해당 조건의 자동 판정 Rule을 제안합니다.',
  },
  { id: 'R-103', title: '경조사비 20만원 초과 소급경고', status: 'DRAFT', description: '경조사비 지급 후 20만원을 초과한 건에 소급 경고 플래그를 지정합니다.', logic: 'IF category == "경조사비" AND amount > 200000\nTHEN flag = "RETROSPECTIVE_WARNING"', sourceClause: '법인카드 사용규정 제13조', aiReason: '제13조에서 경조사비는 20만원까지 소명자료로 갈음 가능하다고 명시해, 초과분은 별도 경고가 필요합니다.' },
  { id: 'R-104', title: '공용카드 실사용자 확인 삽입', status: 'DRAFT', description: '공용카드 거래에는 실사용자·목적 입력 여부를 검증합니다.', logic: 'IF cardType == "SHARED" AND actualUser == null\nTHEN flag = "ACTUAL_USER_REQUIRED"', sourceClause: '요구사항 §4.1', aiReason: '공용/팀 카드는 실사용자·목적 지정이 필요하다는 요구사항을 Rule로 변환했습니다.' },
  { id: 'R-105', title: '접대비 3만원 초과 증빙플래그', status: 'DRAFT', description: '접대비 지출 중 3만원을 초과하는데 적격증빙이 없는 경우를 탐지합니다.', logic: 'IF category == "접대" AND amount > 30000 AND has_receipt == false\nTHEN flag = "NON_DEDUCTIBLE_RISK"', sourceClause: '법인카드 사용규정 제11조②', aiReason: '제11조②항의 3만원 초과 적격증빙 필수 규정을 근거로 제안합니다.' },
  { id: 'R-106', title: '후정산 지출 증빙 필수 검증', status: 'DRAFT', description: '후정산 카드구분 지출에 대해 증빙 첨부 여부를 필수로 검증합니다.', logic: 'IF cardType == "POST_PAID" AND evidence == "MISSING"\nTHEN flag = "EVIDENCE_REQUIRED"', sourceClause: '법인카드 사용규정 제9조', aiReason: '후정산 방식은 사후 증빙 누락 위험이 커 별도 검증 Rule을 제안합니다.' },
]

export interface ChatMessage {
  role: 'user' | 'ai'
  text: string
  appliedNote?: string
}

// R-102 선택 시 우측 "대화형 지시·수정" 패널의 초기 대화 로그(mock, 실제 LLM 호출 없음).
export const DRAFT_CHAT_SCRIPT: ChatMessage[] = [
  { role: 'user', text: '금액 기준을 40만원으로 올려주고, 출장 분류도 포함해줘' },
  {
    role: 'ai',
    text: '네, 반영했습니다.\n조건: amount > 300000 → amount > 400000\n조건: category == "식대" → category IN ("식대", "출장")\n설명 문구도 함께 갱신했습니다.',
    appliedNote: '로직·설명 필드에 적용됨',
  },
  { role: 'user', text: '30만원은 그대로 두고 출장만 추가해줘' },
  {
    role: 'ai',
    text: '금액 기준(30만원)은 유지하고, 분류 조건에 "출장"만 추가했습니다. 좌측 로직 코드에서 확인해주세요.',
    appliedNote: '로직·설명 필드에 적용됨',
  },
]

// ── Tab2: 시뮬레이션 검토 (v5 그래프 / v6 트리 — 둘 다 구현, 노드 로스터 공유) ─────
export interface RuleNode {
  id: string
  sub: string
  status: 'existing' | 'new'
  category: string
  graphX: number // 0~100, 자유배치(그래프 뷰)
  graphY: number // 0~100
}

export const RULE_CATEGORIES = ['카드/계정 검증', '이상거래 탐지', '비용 한도', '복리후생/경조사']

export const RULE_NODES: RuleNode[] = [
  { id: 'R-020', sub: '카드 미배정 확인', status: 'existing', category: '카드/계정 검증', graphX: 12, graphY: 30 },
  { id: 'R-021', sub: '해외결제 플래그', status: 'existing', category: '카드/계정 검증', graphX: 22, graphY: 55 },
  { id: 'R-025', sub: '심야결제 탐지', status: 'existing', category: '이상거래 탐지', graphX: 40, graphY: 18 },
  { id: 'R-030', sub: '소액 다건 탐지', status: 'existing', category: '이상거래 탐지', graphX: 48, graphY: 42 },
  { id: 'R-102', sub: '식대 30만원 초과', status: 'new', category: '이상거래 탐지', graphX: 38, graphY: 68 },
  { id: 'R-033', sub: '비용 한도 초과', status: 'existing', category: '비용 한도', graphX: 58, graphY: 72 },
  { id: 'R-040', sub: '회식비 한도', status: 'existing', category: '비용 한도', graphX: 68, graphY: 30 },
  { id: 'R-045', sub: '접대비 증빙 필수', status: 'existing', category: '비용 한도', graphX: 74, graphY: 55 },
  { id: 'R-105', sub: '접대비 3만원 초과', status: 'new', category: '비용 한도', graphX: 84, graphY: 62 },
  { id: 'R-055', sub: '복리후생 한도', status: 'existing', category: '복리후생/경조사', graphX: 88, graphY: 20 },
  { id: 'R-077', sub: '가맹점 반복 결제', status: 'existing', category: '복리후생/경조사', graphX: 92, graphY: 42 },
  { id: 'R-103', sub: '경조사비 20만원 초과', status: 'new', category: '복리후생/경조사', graphX: 96, graphY: 78 },
]

// 교차 분류(다른 카테고리) 충돌 1건 + 같은 분류 내 형제 노드 충돌 1건 — 화면설계서 기준
export const RULE_CONFLICTS: [string, string][] = [
  ['R-102', 'R-033'],
  ['R-105', 'R-045'],
]

// 그래프 뷰(v5)에서만 쓰는 "느슨한 관련" 엣지(충돌은 아니지만 서로 참조하는 사이)
export const GRAPH_RELATED_EDGES: [string, string][] = [
  ['R-020', 'R-021'], ['R-025', 'R-030'], ['R-030', 'R-102'],
  ['R-040', 'R-045'], ['R-045', 'R-105'], ['R-055', 'R-077'], ['R-077', 'R-103'],
]

export interface BatchCandidate { id: string; label: string; checked: boolean }
export const BATCH_CANDIDATES: BatchCandidate[] = [
  { id: 'R-102', label: '식대 30만원 초과 사전승인', checked: true },
  { id: 'R-103', label: '경조사비 20만원 초과 소급경고', checked: true },
  { id: 'R-104', label: '공용카드 실사용자 확인 삽입', checked: false },
  { id: 'R-105', label: '접대비 3만원 초과 증빙플래그', checked: true },
  { id: 'R-106', label: '후정산 지출 증빙 필수 검증', checked: false },
]

export const SIM_KPI = { matched: 356, falsePositiveRate: 0.051, reviewReduction: -0.27 }
export const SIM_RUN_META = { sampleSize: 12480, ranAt: '2026-07-22 14:03' }

export interface SimDiffRow { rule: string; date: string; merchant: string; amount: number; before: string; after: string; majorDiff: boolean }
export const SIM_DIFF_ROWS: SimDiffRow[] = [
  { rule: 'R-102', date: '07/16', merchant: '야근식대', amount: 320000, before: 'IN_REVIEW', after: 'PENDING_CONFIRM', majorDiff: true },
  { rule: 'R-105', date: '06/28', merchant: '거래처 접대', amount: 412000, before: 'IN_REVIEW', after: 'PENDING_CONFIRM', majorDiff: true },
  { rule: 'R-103', date: '06/20', merchant: '조카 결혼식', amount: 250000, before: 'IN_REVIEW', after: 'PENDING_CONFIRM', majorDiff: true },
  { rule: 'R-102', date: '06/11', merchant: '부서 회식', amount: 340000, before: 'IN_REVIEW', after: 'PENDING_CONFIRM', majorDiff: false },
]

export const SIM_REPORT = {
  summary: '선택된 3개 Rule(R-102, R-103, R-105)을 편입한 결과, 총 356건이 매칭되고 평균 오탐율은 5.1%입니다.',
  conflictTree: '충돌 2건 중 서로 다른 분류에 속한 R-102(이상거래 탐지)↔R-033(비용 한도)는 교차 분류 충돌이고, 같은 분류 내 형제 노드인 R-105↔R-045 충돌은 1건입니다. 형제 노드 충돌은 같은 분류 내 실행 순서 조정만으로 해결 가능합니다.',
  conflictGraph: '감지된 충돌 2건 중 R-102↔R-033은 카테고리만 겹치고 금액 임계값이 달라 실질적 충돌 위험은 낮습니다. R-105↔R-045는 금액 임계값이 3만원 이내로 근접해 있어 순서(위치) 조정 또는 조건 재정의가 필요합니다.',
  recommendation: 'R-102, R-105는 이대로 승인 대기로 전환을 권장합니다. R-103은 충돌 재검토 후 개별적으로 재상신하는 것을 권장합니다.',
}

// ── Tab3: Active Rule 버전관리 (v4) ─────────────────────
export const ACTIVE_RULE = {
  id: 'R-045', title: '접대비 3만원 초과 증빙 필수 플래그',
  sourceClause: '법인카드 사용규정 제11조②', firstApproved: '2026-05-02',
  totalVersions: 4, currentMatched: 412, currentFpRate: 0.031,
  currentLogic: 'IF category == "접대" AND amount > 30000 AND has_receipt == false\nTHEN flag = "NON_DEDUCTIBLE_RISK", severity = "HIGH"',
  currentChangeNote: 'v4(승인대기) 변경점: has_receipt 조건에 전자영수증 인식 추가, 오탐율 3.1%→2.4% 추가 개선 예상',
}

export const PENDING_VERSION = {
  version: 'v4', matched: 445, fpRate: 0.024, fpImprovement: -0.007, simulatedAt: '2026-07-21',
}

export interface VersionRow { version: string; approvedAt: string; approver: string; matched: number; fpRate: number; status: '승인대기' | '현재 활성' | '과거' }
export const VERSION_HISTORY: VersionRow[] = [
  { version: 'v.', approvedAt: '-', approver: '-(대기중)', matched: 445, fpRate: 0.024, status: '승인대기' },
  { version: 'v26.07.10', approvedAt: '2026-07-10', approver: '김회계', matched: 412, fpRate: 0.031, status: '현재 활성' },
  { version: 'v26.06.02', approvedAt: '2026-06-02', approver: '김회계', matched: 380, fpRate: 0.068, status: '과거' },
  { version: 'v26.05.02', approvedAt: '2026-05-02', approver: '박재무', matched: 290, fpRate: 0.094, status: '과거' },
]

// ── 규정 문서 업로드 모달 (v4) ────────────────────────────
export const POLICY_DOC_TYPES = ['법인카드 사용규정', '세법 시행령', '사내 정책', '기타'] as const
export const POLICY_UPLOAD_PROGRESS = { fileName: '법인카드_사용규정_v2.pdf', stage: 'chunking' as 'upload' | 'chunking' | 'embedding', percent: 67 }

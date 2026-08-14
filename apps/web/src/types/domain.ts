// 화면설계서 §0 핵심 도메인 객체 + §2 상태머신 기반 타입 정의.

// ── 역할(4종) ─────────────────────────────
export type Role = 'EMPLOYEE' | 'TEAM_LEAD' | 'ACCOUNTANT' | 'ACCOUNTANT_LEAD' | 'EXECUTIVE'

export const ROLE_LABEL: Record<Role, string> = {
  EMPLOYEE: '사용자(임직원)',
  TEAM_LEAD: '팀장(제출 단위)',
  ACCOUNTANT: '회계 담당자',
  ACCOUNTANT_LEAD: '회계팀장',
  EXECUTIVE: '회계·운영 상부',
}

// ── 기능 단위 권한(Capability) — 백엔드 accounts.Capability와 값 동기화 ──
//  인가는 역할이 아니라 이 4개 능력으로 판정한다(백 §3.1a). 실 모드는 /api/me의 capabilities,
//  mock 모드는 아래 역할 기본값을 사용(데모 역할 스위처를 따르도록).
export type Capability =
  | 'team_aggregate'
  | 'accounting_review'
  | 'rule_view'
  | 'rule_activate'
  | 'governance_view'
  | 'ai_lab'

export const ROLE_DEFAULT_CAPABILITIES: Record<Role, Capability[]> = {
  EMPLOYEE: [],
  TEAM_LEAD: ['team_aggregate'],
  ACCOUNTANT: ['accounting_review', 'rule_view'],
  ACCOUNTANT_LEAD: ['accounting_review', 'rule_view', 'rule_activate', 'ai_lab'],
  EXECUTIVE: ['governance_view'],
}

// ── 정산 상태머신(FR-ST-01) ───────────────
//  DRAFT → SUBMITTED → RPA_JUDGED → (PENDING_CONFIRM/RETURNED/IN_REVIEW/REJECT)
//        → CONFIRMED → ERP_VOUCHER_DRAFTED
//  REJECT=최종반려(재제출 불가), RETURNED=보완요청(재제출 가능)
export type SettlementStatus =
  | 'DRAFT'
  | 'TEAM_COLLECTING'
  | 'TEAM_RETURNED'
  | 'TEAM_REJECTED'
  | 'SUBMITTED'
  | 'RPA_JUDGED'
  | 'PENDING_CONFIRM'
  | 'RETURNED'
  | 'IN_REVIEW'
  | 'REJECT'
  | 'CONFIRMED'
  | 'ERP_VOUCHER_DRAFTED'

type Tone =
  | 'gray' | 'blue' | 'amber' | 'orange' | 'purple' | 'red' | 'green' | 'teal'

export const STATUS_META: Record<SettlementStatus, { label: string; tone: Tone }> = {
  DRAFT: { label: '개인 보유중', tone: 'gray' },
  TEAM_COLLECTING: { label: '팀 취합중', tone: 'blue' },
  TEAM_RETURNED: { label: '팀 보완요청', tone: 'orange' },
  TEAM_REJECTED: { label: '팀 반려', tone: 'red' },
  SUBMITTED: { label: '회계 제출', tone: 'blue' },
  RPA_JUDGED: { label: '1차판정', tone: 'blue' },
  PENDING_CONFIRM: { label: '승인대기', tone: 'amber' },
  RETURNED: { label: '보완요청', tone: 'orange' },
  IN_REVIEW: { label: '검토중', tone: 'purple' },
  REJECT: { label: '반려(최종)', tone: 'red' },
  CONFIRMED: { label: '확정', tone: 'green' },
  ERP_VOUCHER_DRAFTED: { label: '전표생성', tone: 'teal' },
}

// ── 카드 구분(5종) ────────────────────────
export type CardType = 'PERSONAL' | 'TEAM' | 'SHARED' | 'POST_PAID' | 'PREPAID'

export const CARD_TYPE_LABEL: Record<CardType, string> = {
  PERSONAL: '개인 배정',
  TEAM: '팀 카드',
  SHARED: '공용',
  POST_PAID: '후정산',
  PREPAID: '선결제·충전형',
}

/** 공용/팀 → 실사용자·목적 추가입력, 후정산 → 증빙 필수 (FR-DA-04) */
export const CARD_NEEDS_EXTRA_INPUT: Record<CardType, boolean> = {
  PERSONAL: false, TEAM: true, SHARED: true, POST_PAID: false, PREPAID: false,
}

// ── 비용 분류(6종 기본) ───────────────────
export type Category = '회식' | '회의' | '식대' | '출장' | '접대' | '비품'
export const CATEGORIES: Category[] = ['회식', '회의', '식대', '출장', '접대', '비품']

// ── 엔티티 ────────────────────────────────
export interface Settlement {
  id: string
  date: string
  merchant: string
  amount: number
  cardType: CardType
  aiCategory: Category
  /** AI 제안 분류가 저신뢰라 사용자 확인이 필요한지 */
  aiSuggested: boolean
  evidence: 'OK' | 'MISSING'
  status: SettlementStatus
  user: string
  purpose?: string // 지출 목적/사유
  time?: string
  dept?: string
  category?: Category
  merchantIndustry?: string
  additionalEvidence?: { id: number; name: string; status: string }[]
  facts?: Record<string, unknown>
  events?: { id: number; fromState: string; toState: string; actor?: string; reason?: string; createdAt: string }[]
  ruleHits?: { graph: string | null; graphVersion: number; path: string[]; decision: string; confidence: number }[]
}

/** S-03 검토 대상: 이상탐지(1차) + RAG 내규검증(2차) 결과 결합 */
export interface ReviewItem extends Settlement {
  anomalyScore: number // 0~1 (비지도 이상탐지)
  featureContribs: { feature: string; weight: number }[]
  ragRefs: { title: string; source: string; kind?: 'policy' | 'case'; excerpt?: string; relevance?: number }[]
  /** RAG 내규 검증 보고서(마크다운). 비면 요약 문장으로 대체 렌더링한다. */
  ragReport?: string
  aiRecommendation: 'APPROVE' | 'RETURN' | 'REJECT'
  aiConfidence: number // 0~1
  anomalyReasons: string[]
  /** 판정 시점 EvalContext 스냅샷(rule_hits). 있으면 fact.json이 이 원본을 보여준다. */
  evalContext?: Record<string, Record<string, unknown>> | null
  dept?: string // 부서
  time?: string // 결제 일시(HH:MM)
  department?: string // (main) 부서 별칭
  auditTrail?: AuditEvent[]
}

export interface AuditEvent {
  status: string
  actor: string
  timestamp: string
  note?: string
}

// ── 규정 문서 관리 (S-05 규정문서) ─────────────
export type EmbeddingStatus = 'EMBEDDING' | 'DONE' | 'FAILED'

export const EMBEDDING_STATUS_META: Record<EmbeddingStatus, { label: string; tone: 'amber' | 'green' | 'red' }> = {
  EMBEDDING: { label: '처리중', tone: 'amber' },
  DONE: { label: '임베딩 완료', tone: 'green' },
  FAILED: { label: '임베딩 실패', tone: 'red' },
}

export type PolicyDocType = '법인카드 사용규정' | '세법 시행령' | '사내 정책'

export interface PolicyDocument {
  id: string
  filename: string
  docType: PolicyDocType
  uploadedAt: string
  status: EmbeddingStatus
  extractedClauses: number
  linkedRules: number
  fileFormat: 'PDF' | 'DOC' | 'XLSX'
}

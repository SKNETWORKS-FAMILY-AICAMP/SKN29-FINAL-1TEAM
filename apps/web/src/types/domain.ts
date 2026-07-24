// 화면설계서 §0 핵심 도메인 객체 + §2 상태머신 기반 타입 정의.

// ── 역할(4종) ─────────────────────────────
export type Role = 'EMPLOYEE' | 'TEAM_LEAD' | 'ACCOUNTANT' | 'EXECUTIVE'

export const ROLE_LABEL: Record<Role, string> = {
  EMPLOYEE: '사용자(임직원)',
  TEAM_LEAD: '팀장(제출 단위)',
  ACCOUNTANT: '회계 담당자',
  EXECUTIVE: '회계·운영 상부',
}

// ── 정산 상태머신(FR-ST-01) ───────────────
//  DRAFT → SUBMITTED → RPA_JUDGED → (PENDING_CONFIRM/RETURNED/IN_REVIEW/REJECT)
//        → CONFIRMED → ERP_VOUCHER_DRAFTED
//  REJECT=최종반려(재제출 불가), RETURNED=보완요청(재제출 가능)
export type SettlementStatus =
  | 'DRAFT'
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
  DRAFT: { label: '초안', tone: 'gray' },
  SUBMITTED: { label: '제출됨', tone: 'blue' },
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
export type Category = '업무활성' | '회의' | '식대' | '출장' | '접대' | '비품'
export const CATEGORIES: Category[] = ['업무활성', '회의', '식대', '출장', '접대', '비품']

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
}

/** S-03 검토 대상: 이상탐지(1차) + RAG 내규검증(2차) 결과 결합 */
export interface ReviewItem extends Settlement {
  anomalyScore: number // 0~1 (비지도 이상탐지)
  featureContribs: { feature: string; weight: number }[]
  ragRefs: { title: string; source: string }[]
  aiRecommendation: 'APPROVE' | 'RETURN' | 'REJECT'
  aiConfidence: number // 0~1
  anomalyReasons: string[]
  department?: string
  purpose?: string
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

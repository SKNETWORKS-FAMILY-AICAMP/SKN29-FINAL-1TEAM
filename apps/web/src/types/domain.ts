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
  /** 귀속된 사용자(username). 팀·공용 카드 결제는 실사용자 등록 전까지 비어 있다. */
  user: string
  /**
   * 팀·공용 카드 결제인데 아직 실사용자가 정해지지 않음 → **팀원 전원에게 보인다.**
   * 주인이 없으니 `user` 기준으로는 아무에게도 안 보이기 때문에 이 플래그가 필요하다.
   */
  claimPending?: boolean
  teamId?: number | null
  purpose?: string // 지출 목적/사유
  time?: string
  dept?: string
  category?: Category
  merchantIndustry?: string
  additionalEvidence?: { id: number; name: string; status: string }[]
  facts?: Record<string, unknown>
  events?: { id: number; fromState: string; toState: string; actor?: string; reason?: string; createdAt: string }[]
  ruleHits?: { graph: string | null; graphVersion: number; path: string[]; decision: string; flags?: string[]; confidence: number }[]
  /**
   * 룰 판정 결과 — **팀 취합에 올라온 시점에 한 번** 돈다(제출 때 다시 돌지 않는다).
   * `''`이면 아직 판정 전이다. 팀 화면의 "이상 건"이 이 값으로 정해진다.
   */
  ruleDecision?: RuleDecision | ''
  /** 판정이 붙인 사유 코드(`PROHIBITED_MERCHANT` 등). "왜 걸렸는지"가 여기 있다. */
  ruleFlags?: string[]
  /**
   * 위 코드를 사람이 읽을 형태로 편 것. **라벨의 원천은 서버 레지스트리**
   * (`policies/flags.py`)다 — 프론트가 같은 사전을 복사해 두면 반드시 어긋난다.
   */
  ruleFlagInfo?: RuleFlagInfo[]
  ruleJudgedAt?: string | null
}

/** 룰 엔진 판정. 사람의 결정(APPROVE/RETURN/REJECT)이나 AI 권고와는 다른 축이다. */
export type RuleDecision = 'PASS' | 'RETURN' | 'REJECT' | 'REVIEW'

/**
 * 네임드 플래그 — 판정이 남긴 **사유**다. 상태를 정하지 않는다(상태는 `ruleDecision` 한 축).
 * `known=false`면 레지스트리에 없는 코드다 — 감추지 않고 코드 원문을 라벨로 쓴다.
 * `arg`는 인자가 붙은 시스템 플래그(`UNRESOLVED_FACT:approval.pre_approval_obtained`)의 뒷부분.
 */
export interface RuleFlagInfo {
  code: string
  arg: string
  /** 원본 문자열(`code` 또는 `code:arg`) — 그대로 서버에 되돌릴 때 쓴다. */
  flag: string
  label: string
  severity: string
  /** 해소 주체: SPENDER / TEAM_LEAD / APPROVER / ACCOUNTING / SYSTEM */
  owner: string
  category: string
  known: boolean
}

/** ERP 수집 1회분 결과. `exhausted`면 준비된 표본을 다 받은 것이다. */
export interface ImportResult {
  batch: number
  totalBatches: number
  created: number
  skipped: number
  claimPending: number
  exhausted: boolean
}

/** S-03 검토 대상: 이상탐지(1차) + RAG 내규검증(2차) 결과 결합 */
export interface ReviewItem extends Settlement {
  anomalyScore: number // 0~1 (비지도 이상탐지)
  featureContribs: { feature: string; weight: number }[]
  ragRefs: { title: string; source: string; kind?: 'policy' | 'case'; excerpt?: string; relevance?: number }[]
  /** RAG 내규 검증 보고서(마크다운). 비면 요약 문장으로 대체 렌더링한다. */
  ragReport?: string
  /**
   * Risk Review Agent(2차 RAG 검증)의 **권고**. 룰 엔진 판정이 아니다.
   * **Agent가 아직 안 돈 건은 `''`** — 예전엔 `'APPROVE'`로 기본값을 채워서
   * 돌지도 않은 건이 "AI 권장: 승인"으로 표시됐다(없는 판단을 지어낸 것).
   */
  aiRecommendation: 'APPROVE' | 'RETURN' | 'REJECT' | ''
  aiConfidence: number // 0~1
  anomalyReasons: string[]
  /**
   * 2차 RAG 내규검증의 **판정**. 권고(`aiRecommendation`)와 다른 축이다 —
   * `INSUFFICIENT_INFO`는 "문제없음"이 아니라 **판단 보류**라서, 권고만 보면 그 구분이 사라진다.
   * Risk Review가 아직 안 돈 건은 빈 문자열.
   */
  violationVerdict?: 'VIOLATION' | 'NO_VIOLATION' | 'INSUFFICIENT_INFO' | ''
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

// ── 규정 문서 관리 (RAG 소스) ─────────────
// 백엔드 `PolicyDoc.IngestStatus`와 같은 값이다. 진행 단계를 둘로 나눠 두는 이유는
// 파싱(수십 초)과 임베딩(API 호출)이 실패 원인이 달라서 — 어디서 막혔는지가 보여야 한다.
export type EmbeddingStatus = 'PENDING' | 'PARSING' | 'INDEXING' | 'DONE' | 'FAILED'

export const EMBEDDING_STATUS_META: Record<EmbeddingStatus, { label: string; tone: 'amber' | 'green' | 'red' }> = {
  PENDING: { label: '대기', tone: 'amber' },
  PARSING: { label: '파싱·청킹 중', tone: 'amber' },
  INDEXING: { label: '임베딩·적재 중', tone: 'amber' },
  DONE: { label: '적재 완료', tone: 'green' },
  FAILED: { label: '실패', tone: 'red' },
}

/** 진행 중 — 화면이 폴링을 계속해야 하는 상태. */
export const EMBEDDING_IN_PROGRESS: EmbeddingStatus[] = ['PENDING', 'PARSING', 'INDEXING']

export interface PolicyDocument {
  id: string
  title: string
  fileName: string
  fileSize: number
  /** 최종 적용된 문서 유형(지정값이 있으면 그것, 없으면 파서 자동 감지). 컬렉션 라우팅을 정한다. */
  profile: DocProfile | ''
  /** 업로더가 지정한 유형. 비면 자동 감지를 썼다는 뜻. */
  profileHint: DocProfile | ''
  profileLabel: string
  /** 적재된 Chroma 컬렉션. `org_docs`는 판정 근거로 검색되지 않는다. */
  collection: string
  status: EmbeddingStatus
  statusLabel: string
  chunkCount: number
  /** 검색 대상(부모 제외) 청크 수 — 실제로 검색에 걸리는 건 이 수다. */
  leafCount: number
  /** 조(條) 단위 조항 수. 사람이 보고 결정하는 단위는 청크가 아니라 조다. */
  clauseCount: number
  /** 룰도 없고 사람 결정도 없는 조항 수 — "확인이 필요한 조항". */
  reviewCount: number
  /** 실패 사유 또는 적재 경고. 감추지 않는다. */
  error: string
  folderId: number | null
  folderName: string
  /** 개정으로 대체된 구판. 지우지 않는 이유는 과거 판정이 인용한 조항 보존. */
  superseded: boolean
  ruleScope: string
  /**
   * 적재 후 룰 자동 생성 트리거 결과. `status`는 생성기의 것을 그대로 받는다
   * (`DRAFT_SAVED` / `NO_SOURCE` / `SKIPPED_NO_SCOPE`(비용분류 미지정) /
   *  `SKIPPED_REINDEX`(재색인은 자동 생성 안 함) / `ERROR` …).
   */
  ruleTrigger: { status?: string; detail?: string; hint?: string; scope?: string } | null
  uploadedAt: string
  indexedAt: string | null
  uploadedBy: string
}

/**
 * 문서 유형 = **실제 백엔드 분류**(`PolicyDoc.profile`). 컬렉션 라우팅을 결정한다:
 * REGULATION·GENERIC→`policy_docs` · LAW→`tax_refs` · DIAGRAM→`org_docs`.
 * `org_docs`는 정산 판정이 검색하지 않으므로, 유형이 틀리면 그 문서는 판정에 인용되지 않는다.
 */
export type DocProfile = 'REGULATION' | 'LAW' | 'DIAGRAM' | 'GENERIC'

export const DOC_PROFILE_LABEL: Record<DocProfile, { label: string; hint: string; judged: boolean }> = {
  REGULATION: { label: '사내 규정', hint: '조·항 구조의 사규 — 룰 생성·판정 근거로 인용', judged: true },
  LAW: { label: '법령·시행령', hint: '법인세법 등 외부 법령 — 세무 근거로 인용', judged: true },
  DIAGRAM: { label: '조직도·도해', hint: '표·그림 위주 — 판정 근거로는 인용되지 않음', judged: false },
  GENERIC: { label: '기타 문서', hint: '위에 해당하지 않는 문서 — 규정과 함께 검색됨', judged: true },
}

/** 폴더 트리에 실리는 문서 요약. */
export interface FolderDoc {
  id: string
  title: string
  status: EmbeddingStatus
  reviewCount: number
  superseded: boolean
}

export interface PolicyFolder {
  id: number
  name: string
  children: PolicyFolder[]
  documents: FolderDoc[]
  docCount: number
}

/**
 * 조항의 룰 연결 상태 — **백엔드가 저장하지 않고 계산**해서 준다.
 * 룰은 나중에 생기고 지워지므로 컬럼에 굳히면 곧 실제와 어긋난다.
 */
export type ClauseRuleStatus = 'LINKED' | 'SKIPPED' | 'NEEDS_REVIEW'

export const CLAUSE_STATUS_META: Record<ClauseRuleStatus, { label: string; tone: 'green' | 'amber' | 'gray' }> = {
  LINKED: { label: '규칙 연결됨', tone: 'green' },
  NEEDS_REVIEW: { label: '확인 필요', tone: 'amber' },
  SKIPPED: { label: '규칙 생성 안 함', tone: 'gray' },
}

export interface LinkedRule {
  graphId: string
  graphName: string
  graphStatus: string
  nodeKey: string
  title: string
  /** "언제 걸리나요 / 걸리면 어떻게 되나요" — 비개발자용 문장(DSL 아님). */
  conditionText: string
  decision: string
}

export interface PolicyClause {
  id: number
  articleLabel: string
  articleTitle: string
  citation: string
  body: string
  pageStart: number
  pageEnd: number
  ruleStatus: ClauseRuleStatus
  linkedRules: LinkedRule[]
  decision: string
  decisionReason: string
  decidedBy: string
  decidedAt: string | null
}

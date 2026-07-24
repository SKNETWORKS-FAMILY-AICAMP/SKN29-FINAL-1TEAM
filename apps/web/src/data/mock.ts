// 화면 렌더 확인용 목업 데이터. 백엔드 API 연동 전 임시 사용.
import type { PolicyDocument, ReviewItem, Settlement } from '../types/domain'

export const myExpenses: Settlement[] = [
  { id: 'S-1001', date: '2026-07-18', merchant: '스타벅스 강남점', amount: 28000, cardType: 'PERSONAL', aiCategory: '회의', aiSuggested: true, evidence: 'OK', status: 'DRAFT', user: '김민규' },
  { id: 'S-1002', date: '2026-07-18', merchant: '카카오T', amount: 14300, cardType: 'PERSONAL', aiCategory: '출장', aiSuggested: false, evidence: 'MISSING', status: 'DRAFT', user: '김민규' },
  { id: 'S-1003', date: '2026-07-17', merchant: '더본코리아', amount: 132000, cardType: 'TEAM', aiCategory: '식대', aiSuggested: true, evidence: 'OK', status: 'SUBMITTED', user: '김민규' },
  { id: 'S-1004', date: '2026-07-16', merchant: '교보문고', amount: 46500, cardType: 'PERSONAL', aiCategory: '비품', aiSuggested: false, evidence: 'OK', status: 'RETURNED', user: '김민규' },
  { id: 'S-1005', date: '2026-07-15', merchant: '롯데호텔', amount: 380000, cardType: 'POST_PAID', aiCategory: '접대', aiSuggested: true, evidence: 'MISSING', status: 'IN_REVIEW', user: '김민규' },
  { id: 'S-1006', date: '2026-07-14', merchant: '쿠팡', amount: 89000, cardType: 'PERSONAL', aiCategory: '비품', aiSuggested: false, evidence: 'OK', status: 'CONFIRMED', user: '김민규' },
]

export const teamMembers: { name: string; items: Settlement[] }[] = [
  {
    name: '이서준',
    items: [
      { id: 'S-2001', date: '2026-07-18', merchant: 'GS25', amount: 8200, cardType: 'PERSONAL', aiCategory: '식대', aiSuggested: false, evidence: 'OK', status: 'DRAFT', user: '이서준' },
      { id: 'S-2002', date: '2026-07-17', merchant: '신라스테이', amount: 450000, cardType: 'POST_PAID', aiCategory: '출장', aiSuggested: true, evidence: 'MISSING', status: 'DRAFT', user: '이서준' },
    ],
  },
  {
    name: '박도윤',
    items: [
      { id: 'S-2003', date: '2026-07-18', merchant: '배달의민족', amount: 96000, cardType: 'TEAM', aiCategory: '식대', aiSuggested: true, evidence: 'OK', status: 'DRAFT', user: '박도윤' },
      { id: 'S-2004', date: '2026-07-16', merchant: '이마트', amount: 49000, cardType: 'TEAM', aiCategory: '비품', aiSuggested: false, evidence: 'OK', status: 'DRAFT', user: '박도윤' },
      { id: 'S-2005', date: '2026-07-15', merchant: '한우명가', amount: 298000, cardType: 'SHARED', aiCategory: '접대', aiSuggested: true, evidence: 'MISSING', status: 'DRAFT', user: '박도윤' },
    ],
  },
]

// S-02 v2 팀 예산 현황 섹션
export const teamBudget = {
  total: 5000000,
  used: 1720000,
  categories: [
    { label: '식대', used: 280000, limit: 1000000 },
    { label: '출장', used: 540000, limit: 1200000 },
    { label: '접대', used: 680000, limit: 1000000 },
    { label: '비품', used: 120000, limit: 800000 },
    { label: '회의', used: 100000, limit: 500000 },
  ],
}

/** 이상 사유(태그) 판정 — 화면설계서 S-02 이상 사유 태그 로직 데모 */
export function anomalyTags(s: Settlement): string[] {
  const tags: string[] = []
  if (s.evidence === 'MISSING') tags.push('증빙누락')
  if (s.amount >= 300000) tags.push('건당한도초과')
  if (s.cardType === 'SHARED') tags.push('실사용자미지정')
  return tags
}

export const reviewItems: ReviewItem[] = [
  {
    id: 'S-3001', date: '2026-07-18', merchant: '강남한식당', amount: 452000, cardType: 'SHARED',
    aiCategory: '접대', aiSuggested: true, evidence: 'MISSING', status: 'IN_REVIEW', user: '이영희',
    department: 'AI플랫폼부', purpose: '거래처 A사 계약 논의 접대',
    anomalyScore: 0.92,
    featureContribs: [
      { feature: '전월대비 결제금액 급증', weight: 0.45 },
      { feature: '심야시간대 결제', weight: 0.32 },
      { feature: '증빙 서류 누락', weight: 0.23 },
    ],
    ragRefs: [
      { title: '3만원 초과 접대비 지출 시 적격증빙(신용카드매출전표 등) 수취가 의무이며, 미수취 시 전액 손금불산입', source: '법인카드 사용규정 제11조 ②' },
      { title: '유사사례 #1123(동일 가맹점·유사 금액대 접대비)는 적격증빙 미비로 반려 처리된 이력이 있으며, 현재 건과 91% 패턴이 일치', source: '과거 반려사례 DB' },
    ],
    aiRecommendation: 'RETURN', aiConfidence: 0.78,
    anomalyReasons: ['전월대비 결제금액 급증', '증빙 미첨부', '공용카드 실사용자 미지정'],
    auditTrail: [
      { status: 'DRAFT', actor: 'Draft Agent', timestamp: '07/18 10:02', note: '자동 초안 생성' },
      { status: 'SUBMITTED', actor: '이영희', timestamp: '07/18 10:05' },
      { status: 'RPA_JUDGED', actor: 'Rule Agent', timestamp: '07/18 10:05', note: 'confidence=0.61 → 미매칭' },
      { status: 'IN_REVIEW', actor: 'Risk Review Agent', timestamp: '07/18 10:06', note: '① 이상탐지 92% → ② RAG검증 이관' },
    ],
  },
  {
    id: 'S-3002', date: '2026-07-17', merchant: '박민수 영업본부', amount: 310000, cardType: 'TEAM',
    aiCategory: '접대', aiSuggested: false, evidence: 'OK', status: 'IN_REVIEW', user: '박민수',
    department: '영업본부', purpose: '신규 고객사 미팅',
    anomalyScore: 0.78,
    featureContribs: [
      { feature: '건당한도 근거·유사사례 있음', weight: 0.48 },
      { feature: '동일 가맹점 반복', weight: 0.30 },
    ],
    ragRefs: [
      { title: '건당 30만원 초과 접대비는 사전결재 필요', source: '법인카드 사용규정 §10조' },
    ],
    aiRecommendation: 'RETURN', aiConfidence: 0.64,
    anomalyReasons: ['한도 근거 유사사례 있음'],
    auditTrail: [
      { status: 'DRAFT', actor: 'Draft Agent', timestamp: '07/17 14:00' },
      { status: 'SUBMITTED', actor: '박민수', timestamp: '07/17 14:10' },
      { status: 'IN_REVIEW', actor: 'Risk Review Agent', timestamp: '07/17 14:11', note: '이상탐지 78%' },
    ],
  },
  {
    id: 'S-3003', date: '2026-07-16', merchant: '스타벅스 광화문점', amount: 128000, cardType: 'PERSONAL',
    aiCategory: '회의', aiSuggested: true, evidence: 'OK', status: 'IN_REVIEW', user: '최지우',
    department: '데이터부', purpose: '외부 파트너 미팅',
    anomalyScore: 0.65,
    featureContribs: [
      { feature: '가맹점 반복·소액 다건', weight: 0.42 },
    ],
    ragRefs: [
      { title: '분할결제 의심 시 원거래 통합 검토', source: 'TIGER-REG-2026-003 §8조' },
    ],
    aiRecommendation: 'RETURN', aiConfidence: 0.55,
    anomalyReasons: ['분할결제 의심'],
    auditTrail: [
      { status: 'DRAFT', actor: 'Draft Agent', timestamp: '07/16 09:00' },
      { status: 'SUBMITTED', actor: '최지우', timestamp: '07/16 09:15' },
      { status: 'IN_REVIEW', actor: 'Risk Review Agent', timestamp: '07/16 09:16', note: '이상탐지 65%' },
    ],
  },
  {
    id: 'S-3004', date: '2026-07-15', merchant: '롯데호텔 서울', amount: 95000, cardType: 'PERSONAL',
    aiCategory: '출장', aiSuggested: false, evidence: 'OK', status: 'IN_REVIEW', user: '김철수',
    department: '클라우드부', purpose: '출장 숙박',
    anomalyScore: 0.51,
    featureContribs: [
      { feature: '분류 신뢰도 낮음', weight: 0.35 },
    ],
    ragRefs: [],
    aiRecommendation: 'APPROVE', aiConfidence: 0.72,
    anomalyReasons: ['분류 신뢰도 낮음'],
    auditTrail: [
      { status: 'DRAFT', actor: 'Draft Agent', timestamp: '07/15 18:00' },
      { status: 'SUBMITTED', actor: '김철수', timestamp: '07/15 18:10' },
      { status: 'IN_REVIEW', actor: 'Risk Review Agent', timestamp: '07/15 18:11', note: '이상탐지 51%' },
    ],
  },
  {
    id: 'S-3005', date: '2026-07-14', merchant: '정하늘 전략기획부', amount: 60000, cardType: 'PERSONAL',
    aiCategory: '식대', aiSuggested: false, evidence: 'OK', status: 'IN_REVIEW', user: '정하늘',
    department: '전략기획부', purpose: '팀 회식',
    anomalyScore: 0.43,
    featureContribs: [
      { feature: '주말 결제·소액', weight: 0.28 },
    ],
    ragRefs: [],
    aiRecommendation: 'APPROVE', aiConfidence: 0.81,
    anomalyReasons: ['주말 결제'],
    auditTrail: [
      { status: 'DRAFT', actor: 'Draft Agent', timestamp: '07/14 12:00' },
      { status: 'SUBMITTED', actor: '정하늘', timestamp: '07/14 12:20' },
      { status: 'IN_REVIEW', actor: 'Risk Review Agent', timestamp: '07/14 12:21', note: '이상탐지 43%' },
    ],
  },
  {
    id: 'S-3006', date: '2026-07-13', merchant: '이도윤 공공사업부', amount: 42000, cardType: 'PERSONAL',
    aiCategory: '식대', aiSuggested: false, evidence: 'OK', status: 'IN_REVIEW', user: '이도윤',
    department: '공공사업부', purpose: '점심 식사',
    anomalyScore: 0.30,
    featureContribs: [
      { feature: '검이한 금액 편차', weight: 0.18 },
    ],
    ragRefs: [],
    aiRecommendation: 'APPROVE', aiConfidence: 0.91,
    anomalyReasons: ['금액 편차 낮음'],
    auditTrail: [
      { status: 'DRAFT', actor: 'Draft Agent', timestamp: '07/13 13:00' },
      { status: 'SUBMITTED', actor: '이도윤', timestamp: '07/13 13:05' },
      { status: 'IN_REVIEW', actor: 'Risk Review Agent', timestamp: '07/13 13:06', note: '이상탐지 30%' },
    ],
  },
]

// ── S-05 거버넌스 대시보드 ────────────────
export const spendTrend = [
  { label: '3월', 식대: 42, 출장: 31, 접대: 18 },
  { label: '4월', 식대: 48, 출장: 28, 접대: 22 },
  { label: '5월', 식대: 45, 출장: 35, 접대: 26 },
  { label: '6월', 식대: 51, 출장: 40, 접대: 19 },
  { label: '7월', 식대: 55, 출장: 44, 접대: 31 },
]

export const budgetByBU = [
  { bu: '전략기획본부', rate: 0.62 },
  { bu: 'AI사업본부', rate: 0.88 },
  { bu: '경영지원본부', rate: 0.47 },
  { bu: '영업본부', rate: 0.95 },
  { bu: '개발본부', rate: 0.71 },
]

export const rejectReasonsTop5 = [
  { reason: '증빙 미첨부', count: 48 },
  { reason: '한도 초과', count: 33 },
  { reason: '분류 오류', count: 27 },
  { reason: '실사용자 미지정', count: 19 },
  { reason: '출장 신청 미연결', count: 12 },
]

export const policyInsights = [
  { kind: 'Rule 추천', text: '"메가커피 x N건" 형태 분할결제가 반복됩니다. Rule화를 검토하세요.', action: 'S-04' },
  { kind: '한도 재검토', text: '접대비 한도 초과 건이 전월 대비 63% 증가했습니다.', action: 'policy' },
]

// ── F-3 알림함 ─────────────────────────────
export type NotificationKind = 'warn' | 'rule' | 'budget' | 'deadline' | 'success'
export interface AppNotification {
  id: string
  kind: NotificationKind
  title: string
  detail: string
  time: string
  unread: boolean
}
export const notifications: AppNotification[] = [
  { id: 'N-1', kind: 'warn', title: '보완요청 도착', detail: '"거래처 회식" 건이 보완요청 처리되었습니다 — 증빙을 재업로드해주세요.', time: '5분 전', unread: true },
  { id: 'N-2', kind: 'rule', title: 'Rule 승인 필요', detail: 'R-102 Rule 초안이 시뮬레이션을 통과해 승인 대기 중입니다.', time: '1시간 전', unread: true },
  { id: 'N-3', kind: 'budget', title: '예산 소진 경고', detail: 'AI플랫폼부 출장비 예산이 92% 소진되었습니다.', time: '3시간 전', unread: true },
  { id: 'N-4', kind: 'deadline', title: '제출 마감 임박', detail: '팀 취합 제출 마감이 2일 남았습니다.', time: '어제', unread: false },
  { id: 'N-5', kind: 'success', title: '정산 승인 완료', detail: '"XYZ호텔" 출장비 건이 승인 처리되어 ERP 전표가 생성되었습니다.', time: '2일 전', unread: false },
]

export const riskAlerts = [
  { title: '한도 회피성 분할결제 의심', detail: '최지우 — 스타벅스 12건 12.8만원 (7/16)', target: 'S-03', note: '회계팀에도 동일 노출 · Open Issue#11' },
  { title: '공용카드 실사용자 미지정', detail: '이영희 — 강남한식당 45.2만원 접대 (7/18)', target: 'S-03' },
]

// ── 규정 문서 관리 (S-05 규정문서) ──────────────
export const policyDocuments: PolicyDocument[] = [
  { id: 'PD-001', filename: '법인카드_사용규정_v2.pdf', docType: '법인카드 사용규정', uploadedAt: '2026-07-22', status: 'EMBEDDING', extractedClauses: 0, linkedRules: 0, fileFormat: 'PDF' },
  { id: 'PD-002', filename: '법인카드_사용규정_v1.pdf', docType: '법인카드 사용규정', uploadedAt: '2026-07-01', status: 'DONE', extractedClauses: 42, linkedRules: 18, fileFormat: 'PDF' },
  { id: 'PD-003', filename: '세법_시행령_발췌.docx', docType: '세법 시행령', uploadedAt: '2026-06-15', status: 'DONE', extractedClauses: 27, linkedRules: 9, fileFormat: 'DOC' },
  { id: 'PD-004', filename: '출장_경비_사내지침.pdf', docType: '사내 정책', uploadedAt: '2026-05-20', status: 'DONE', extractedClauses: 15, linkedRules: 4, fileFormat: 'PDF' },
  { id: 'PD-005', filename: '경조사비_지급기준.pdf', docType: '사내 정책', uploadedAt: '2026-04-10', status: 'DONE', extractedClauses: 8, linkedRules: 3, fileFormat: 'PDF' },
  { id: 'PD-006', filename: '복리후생_규정_v3.pdf', docType: '사내 정책', uploadedAt: '2026-03-02', status: 'FAILED', extractedClauses: 0, linkedRules: 0, fileFormat: 'PDF' },
]

// ── S-05 거버넌스 대시보드 갱신 수치 ─────────────
export const governanceKpi = {
  totalSpend: '8.4억원',
  budgetBurnRate: 68,
  autoProcessRate: 82,
  policyViolationCount: 3,
}

// 화면 렌더 확인용 목업 데이터. 백엔드 API 연동 전 임시 사용.
import type { PolicyDocument, ReviewItem, Settlement } from '../types/domain'

export const myExpenses: Settlement[] = [
  // ── 이번 달(2026-07) ──
  { id: 'S-1004', date: '2026-07-16', merchant: '교보문고', amount: 46500, cardType: 'PERSONAL', aiCategory: '비품', aiSuggested: false, evidence: 'OK', status: 'RETURNED', user: '김민규' },
  { id: 'S-1007', date: '2026-07-13', merchant: '갤러리아 백화점', amount: 210000, cardType: 'PERSONAL', aiCategory: '접대', aiSuggested: true, evidence: 'OK', status: 'REJECT', user: '김민규' },
  { id: 'S-1001', date: '2026-07-18', merchant: '스타벅스 강남점', amount: 28000, cardType: 'PERSONAL', aiCategory: '회의', aiSuggested: true, evidence: 'OK', status: 'DRAFT', user: '김민규' },
  { id: 'S-1002', date: '2026-07-18', merchant: '카카오T', amount: 14300, cardType: 'PERSONAL', aiCategory: '출장', aiSuggested: false, evidence: 'OK', status: 'DRAFT', user: '김민규' },
  { id: 'S-1003', date: '2026-07-17', merchant: '더본코리아', amount: 132000, cardType: 'TEAM', aiCategory: '식대', aiSuggested: true, evidence: 'OK', status: 'SUBMITTED', user: '김민규' },
  { id: 'S-1008', date: '2026-07-16', merchant: 'GS25 역삼점', amount: 8800, cardType: 'PERSONAL', aiCategory: '식대', aiSuggested: false, evidence: 'OK', status: 'PENDING_CONFIRM', user: '김민규' },
  { id: 'S-1005', date: '2026-07-15', merchant: '롯데호텔', amount: 380000, cardType: 'POST_PAID', aiCategory: '접대', aiSuggested: true, evidence: 'OK', status: 'IN_REVIEW', user: '김민규' },
  { id: 'S-1006', date: '2026-07-14', merchant: '쿠팡', amount: 89000, cardType: 'PERSONAL', aiCategory: '비품', aiSuggested: false, evidence: 'OK', status: 'CONFIRMED', user: '김민규' },
  // ── 지난 달(2026-06) 처리 완료 — 기본 숨김, 필터로 조회 ──
  { id: 'S-0927', date: '2026-06-27', merchant: '이디야커피 역삼', amount: 15000, cardType: 'PERSONAL', aiCategory: '회의', aiSuggested: false, evidence: 'OK', status: 'CONFIRMED', user: '김민규' },
  { id: 'S-0920', date: '2026-06-20', merchant: 'SRT 수서', amount: 96000, cardType: 'PERSONAL', aiCategory: '출장', aiSuggested: true, evidence: 'OK', status: 'ERP_VOUCHER_DRAFTED', user: '김민규' },
  { id: 'S-0911', date: '2026-06-11', merchant: '올리브영', amount: 34000, cardType: 'PERSONAL', aiCategory: '비품', aiSuggested: false, evidence: 'OK', status: 'CONFIRMED', user: '김민규' },
]

// S-02 팀 취합 — 팀원별 정산 건. 상태(TEAM_*)를 다양하게 구성해 취합 단계 흐름을 시연한다.
//  DRAFT=개인 보유 / TEAM_COLLECTING=취합중(팀장 검토 대기) / TEAM_RETURNED=팀 보완요청 / TEAM_REJECTED=팀 반려 / SUBMITTED=회계 제출됨
export const teamMembers: { name: string; items: Settlement[] }[] = [
  {
    name: '이서준',
    items: [
      { id: 'S-2001', date: '2026-07-18', merchant: 'GS25 삼성점', amount: 8200, cardType: 'PERSONAL', aiCategory: '식대', aiSuggested: false, evidence: 'OK', status: 'TEAM_COLLECTING', user: '이서준', purpose: '야근 간식' },
      { id: 'S-2002', date: '2026-07-17', merchant: '신라스테이', amount: 450000, cardType: 'POST_PAID', aiCategory: '출장', aiSuggested: true, evidence: 'OK', status: 'TEAM_COLLECTING', user: '이서준', purpose: '지방 출장 숙박' },
      { id: 'S-2006', date: '2026-07-14', merchant: '카카오T', amount: 12600, cardType: 'PERSONAL', aiCategory: '출장', aiSuggested: false, evidence: 'OK', status: 'DRAFT', user: '이서준', purpose: '고객사 방문 이동' },
    ],
  },
  {
    name: '박도윤',
    items: [
      { id: 'S-2003', date: '2026-07-18', merchant: '배달의민족', amount: 96000, cardType: 'TEAM', aiCategory: '식대', aiSuggested: true, evidence: 'OK', status: 'TEAM_COLLECTING', user: '박도윤', purpose: '팀 야근 식대' },
      { id: 'S-2004', date: '2026-07-16', merchant: '이마트 성수', amount: 49000, cardType: 'TEAM', aiCategory: '비품', aiSuggested: false, evidence: 'OK', status: 'TEAM_RETURNED', user: '박도윤', purpose: '팀 비품 — 사용목적 보완 필요' },
      { id: 'S-2005', date: '2026-07-15', merchant: '한우명가', amount: 298000, cardType: 'SHARED', aiCategory: '접대', aiSuggested: true, evidence: 'OK', status: 'TEAM_COLLECTING', user: '박도윤', purpose: '거래처 접대 (실사용자 지정 필요)' },
    ],
  },
  {
    name: '최유진',
    items: [
      { id: 'S-2007', date: '2026-07-17', merchant: '롯데시네마 건대', amount: 132000, cardType: 'SHARED', aiCategory: '접대', aiSuggested: true, evidence: 'OK', status: 'TEAM_REJECTED', user: '최유진', purpose: '접대 성격 불명확 — 팀 반려' },
      { id: 'S-2008', date: '2026-07-16', merchant: '스타벅스 코엑스', amount: 26000, cardType: 'TEAM', aiCategory: '회의', aiSuggested: false, evidence: 'OK', status: 'TEAM_COLLECTING', user: '최유진', purpose: '주간 회의 다과' },
      { id: 'S-2009', date: '2026-07-12', merchant: '교보문고', amount: 54000, cardType: 'PERSONAL', aiCategory: '비품', aiSuggested: false, evidence: 'OK', status: 'SUBMITTED', user: '최유진', purpose: '기술서적 구입' },
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

/** 이상 사유(태그) 판정 — 화면설계서 S-02 이상 사유 태그 로직 데모.
 *  ※ 증빙 유무는 하드 플래그가 아니라 AI가 유연 판단할 항목이라 태그에서 제외(영수증 없이도 자동처리 지원). */
export function anomalyTags(s: Settlement): string[] {
  const tags: string[] = []
  if (s.amount >= 300000) tags.push('건당한도초과')
  if (s.cardType === 'SHARED') tags.push('실사용자미지정')
  return tags
}

export const reviewItems: ReviewItem[] = [
  {
    id: 'S-3001', date: '2026-07-18', time: '19:20', merchant: '강남한식당', amount: 452000, cardType: 'SHARED',
    aiCategory: '접대', aiSuggested: true, evidence: 'OK', status: 'IN_REVIEW', user: '이영희', dept: 'AI플랫폼부',
    purpose: '거래처 A사 계약 논의 접대',
    anomalyScore: 0.92,
    featureContribs: [
      { feature: '전월대비 결제금액 급증', weight: 0.45 },
      { feature: '심야 시간대 결제', weight: 0.32 },
      { feature: '적격증빙 확인 필요(AI 검토)', weight: 0.23 },
    ],
    ragRefs: [
      { title: '3만원 초과 접대비 지출 시 적격증빙 수취 의무, 미수취 시 전액 손금불산입', source: '법인카드 사용규정 제11조', kind: 'policy' },
      { title: '유사사례 #1123 — 동일 가맹점·유사 금액대 접대비, 적격증빙 미비로 반려 (현재 건과 91% 패턴 일치)', source: '과거 반려사례 DB', kind: 'case' },
    ],
    aiRecommendation: 'REJECT', aiConfidence: 0.86,
    anomalyReasons: ['접대비·심야결제·적격증빙 확인'],
  },
  {
    id: 'S-3002', date: '2026-07-17', time: '21:05', merchant: '신라스테이', amount: 310000, cardType: 'POST_PAID',
    aiCategory: '접대', aiSuggested: true, evidence: 'OK', status: 'IN_REVIEW', user: '박민수', dept: '영업본부',
    purpose: '거래처 접대 후 숙박',
    anomalyScore: 0.78,
    featureContribs: [
      { feature: '건당 한도 근접', weight: 0.36 },
      { feature: '유사 반려사례 존재', weight: 0.28 },
    ],
    ragRefs: [
      { title: '접대비 건당 한도 50만원 초과 시 사전결재 필요', source: 'TIGER-REG-2026-003 §12조 2항', kind: 'policy' },
    ],
    aiRecommendation: 'RETURN', aiConfidence: 0.64,
    anomalyReasons: ['건당한도 근접·유사사례 있음'],
  },
  {
    id: 'S-3003', date: '2026-07-16', time: '14:30', merchant: '메가커피 x 12건', amount: 128000, cardType: 'TEAM',
    aiCategory: '회의', aiSuggested: false, evidence: 'OK', status: 'IN_REVIEW', user: '최지우', dept: '데이터부',
    purpose: '팀 회의 다과',
    anomalyScore: 0.65,
    featureContribs: [
      { feature: '동일 가맹점 빈도 급증', weight: 0.41 },
      { feature: '한도 임계값 바로 아래', weight: 0.22 },
    ],
    ragRefs: [
      { title: '분할결제 의심 시 원거래 통합 검토', source: 'TIGER-REG-2026-003 §8조', kind: 'policy' },
    ],
    aiRecommendation: 'RETURN', aiConfidence: 0.55,
    anomalyReasons: ['가맹점 반복·소액 다건'],
  },
  {
    id: 'S-3004', date: '2026-07-15', time: '11:10', merchant: '쿠팡', amount: 95000, cardType: 'PERSONAL',
    aiCategory: '비품', aiSuggested: false, evidence: 'OK', status: 'IN_REVIEW', user: '김철수', dept: '클라우드부',
    purpose: '사무용품 구매',
    anomalyScore: 0.51,
    featureContribs: [{ feature: '분류 신뢰도 낮음', weight: 0.28 }],
    ragRefs: [],
    aiRecommendation: 'APPROVE', aiConfidence: 0.72,
    anomalyReasons: ['분류 신뢰도 낮음'],
  },
  {
    id: 'S-3005', date: '2026-07-13', time: '13:40', merchant: '김밥천국', amount: 60000, cardType: 'PERSONAL',
    aiCategory: '식대', aiSuggested: false, evidence: 'OK', status: 'IN_REVIEW', user: '정하늘', dept: '전략기획부',
    purpose: '주말 근무 식대',
    anomalyScore: 0.43,
    featureContribs: [{ feature: '주말 결제', weight: 0.19 }],
    ragRefs: [],
    aiRecommendation: 'APPROVE', aiConfidence: 0.81,
    anomalyReasons: ['주말 결제·소액'],
  },
  {
    id: 'S-3006', date: '2026-07-12', time: '12:15', merchant: '백반집', amount: 42000, cardType: 'PERSONAL',
    aiCategory: '식대', aiSuggested: false, evidence: 'OK', status: 'IN_REVIEW', user: '이도윤', dept: '공공사업부',
    purpose: '업무 오찬',
    anomalyScore: 0.30,
    featureContribs: [{ feature: '경미한 금액 편차', weight: 0.12 }],
    ragRefs: [],
    aiRecommendation: 'APPROVE', aiConfidence: 0.88,
    anomalyReasons: ['경미한 금액 편차'],
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
  { title: '한도 회피성 분할결제 의심', detail: '최지우 — 메가커피 12건 4.68만원 (7/16)', target: 'S-03', note: '회계팀에도 동일 노출 · Open Issue#11' },
  { title: '심야 고액 접대', detail: '정하윤 — 골든테이블 88만원 23:40 (7/17)', target: 'S-03' },
]

// ── 규정 문서 관리 (S-05, main) ─────────────
export const policyDocuments: PolicyDocument[] = [
  { id: 'PD-001', filename: '법인카드_사용규정_v2.pdf', docType: '법인카드 사용규정', uploadedAt: '2026-07-22', status: 'EMBEDDING', extractedClauses: 0, linkedRules: 0, fileFormat: 'PDF' },
  { id: 'PD-002', filename: '법인카드_사용규정_v1.pdf', docType: '법인카드 사용규정', uploadedAt: '2026-07-01', status: 'DONE', extractedClauses: 42, linkedRules: 18, fileFormat: 'PDF' },
  { id: 'PD-003', filename: '세법_시행령_발췌.docx', docType: '세법 시행령', uploadedAt: '2026-06-15', status: 'DONE', extractedClauses: 27, linkedRules: 9, fileFormat: 'DOC' },
  { id: 'PD-004', filename: '출장_경비_사내지침.pdf', docType: '사내 정책', uploadedAt: '2026-05-20', status: 'DONE', extractedClauses: 15, linkedRules: 4, fileFormat: 'PDF' },
  { id: 'PD-005', filename: '경조사비_지급기준.pdf', docType: '사내 정책', uploadedAt: '2026-04-10', status: 'DONE', extractedClauses: 8, linkedRules: 3, fileFormat: 'PDF' },
  { id: 'PD-006', filename: '복리후생_규정_v3.pdf', docType: '사내 정책', uploadedAt: '2026-03-02', status: 'FAILED', extractedClauses: 0, linkedRules: 0, fileFormat: 'PDF' },
]

// ── S-05 거버넌스 대시보드 갱신 수치 (main) ─────────────
export const governanceKpi = {
  totalSpend: '8.4억원',
  budgetBurnRate: 68,
  autoProcessRate: 82,
  policyViolationCount: 3,
}

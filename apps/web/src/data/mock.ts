// 화면 렌더 확인용 목업 데이터. 백엔드 API 연동 전 임시 사용.
import type { ReviewItem, Settlement } from '../types/domain'

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
    id: 'S-3001', date: '2026-07-17', merchant: '골든테이블 룸살롱', amount: 880000, cardType: 'SHARED',
    aiCategory: '접대', aiSuggested: true, evidence: 'MISSING', status: 'IN_REVIEW', user: '정하윤',
    anomalyScore: 0.92,
    featureContribs: [
      { feature: '심야 사용(23:40)', weight: 0.34 },
      { feature: '건당 금액 상위 1%', weight: 0.29 },
      { feature: '접대 한도 초과', weight: 0.21 },
    ],
    ragRefs: [
      { title: '접대비 건당 한도 50만원 초과 시 사전결재 필요', source: 'TIGER-REG-2026-003 §12조 2항' },
      { title: '유흥업소 사용분 손금 불산입', source: '법인세법 시행령 §41' },
    ],
    aiRecommendation: 'REJECT', aiConfidence: 0.86,
    anomalyReasons: ['심야 시간대 고액 접대', '증빙 미첨부', '한도 초과'],
  },
  {
    id: 'S-3002', date: '2026-07-16', merchant: '메가커피 x 12건', amount: 46800, cardType: 'TEAM',
    aiCategory: '회의', aiSuggested: false, evidence: 'OK', status: 'IN_REVIEW', user: '최지우',
    anomalyScore: 0.71,
    featureContribs: [
      { feature: '동일 가맹점 빈도 급증', weight: 0.41 },
      { feature: '한도 임계값 바로 아래', weight: 0.22 },
    ],
    ragRefs: [
      { title: '분할결제 의심 시 원거래 통합 검토', source: 'TIGER-REG-2026-003 §8조' },
    ],
    aiRecommendation: 'RETURN', aiConfidence: 0.64,
    anomalyReasons: ['한도 회피성 분할결제 의심'],
  },
  {
    id: 'S-3003', date: '2026-07-15', merchant: '제주항공', amount: 210000, cardType: 'POST_PAID',
    aiCategory: '출장', aiSuggested: true, evidence: 'MISSING', status: 'IN_REVIEW', user: '한서연',
    anomalyScore: 0.58,
    featureContribs: [
      { feature: '출장 신청 미매칭', weight: 0.38 },
      { feature: '증빙 미첨부', weight: 0.20 },
    ],
    ragRefs: [
      { title: '출장비는 출장 신청·일정과 대사 필요', source: 'TIGER-REG-2026-003 §15조' },
    ],
    aiRecommendation: 'RETURN', aiConfidence: 0.55,
    anomalyReasons: ['출장 신청서 미연결'],
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

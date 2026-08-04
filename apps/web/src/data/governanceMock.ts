// S-05 거버넌스 대시보드 목업 데이터 (임원 보고용).
//  금액 단위는 전부 **만원**. 13개월(전년 동월 비교를 위해 T-12 ~ T)치를 담는다.
//  숫자는 서로 맞물리게 구성했다 — 계정과목 합계 = 팀 합계 = KPI 분기 총액.
import type { Category } from '../types/domain'

/** 25.08 ~ 26.08 (13개월). 마지막이 이번 달. */
export const GOV_MONTHS = [
  '25.08', '25.09', '25.10', '25.11', '25.12',
  '26.01', '26.02', '26.03', '26.04', '26.05', '26.06', '26.07', '26.08',
] as const

export const MONTH_COUNT = GOV_MONTHS.length
export const IDX_NOW = MONTH_COUNT - 1        // 이번 달
export const IDX_PREV_MONTH = MONTH_COUNT - 2 // 전월
export const IDX_PREV_YEAR = 0                // 전년 동월

export type CompareMode = 'MOM' | 'YOY'
export const COMPARE_LABEL: Record<CompareMode, string> = {
  MOM: '전월 대비',
  YOY: '전년 동월 대비',
}
export const compareIndex = (mode: CompareMode) => (mode === 'MOM' ? IDX_PREV_MONTH : IDX_PREV_YEAR)

// ── ① 계정과목별 월 지출(만원) ──────────────────────────────
//  접대·출장이 가파르게 오르고 회의·비품은 평탄 — "어디서 새는지"가 한눈에 보이도록 구성.
export const CATEGORY_SPEND: Record<Category, number[]> = {
  식대:   [380, 402, 395, 430, 455, 412, 388, 405, 441, 468, 452, 489, 501],
  출장:   [290, 315, 342, 301, 288, 275, 330, 358, 372, 395, 410, 438, 472],
  접대:   [180, 205, 232, 198, 176, 165, 210, 244, 268, 291, 322, 358, 431],
  업무활성: [210, 225, 218, 240, 252, 231, 245, 260, 272, 285, 298, 310, 336],
  비품:   [140, 132, 155, 148, 139, 144, 151, 138, 146, 159, 142, 150, 148],
  회의:   [88, 92, 85, 90, 96, 84, 89, 93, 87, 95, 91, 88, 79],
}

export const CATEGORY_ORDER: Category[] = ['접대', '출장', '식대', '업무활성', '비품', '회의']

export const monthTotal = (index: number) =>
  CATEGORY_ORDER.reduce((sum, cat) => sum + CATEGORY_SPEND[cat][index], 0)

// ── ② 팀별 시계열 — 예산 소진율 / 퇴사율 / 생산성 지수 ──────────
//  소진율·퇴사율은 %, 생산성은 지수(100 = 전년 평균). 세 지표를 한 축에 겹치지 않고
//  소형 다중 패널로 나눠 그린다(스케일이 달라 이중축은 쓰지 않는다).
export interface TeamSeries {
  team: string
  bu: string
  headcount: number
  burnRate: number[]    // 예산 소진율 %
  attrition: number[]   // 월 퇴사율 %
  performance: number[] // 생산성 지수(100 기준)
  /** 임원이 바로 읽을 한 줄 해석. */
  readout: string
}

export const TEAM_SERIES: TeamSeries[] = [
  {
    team: '영업팀', bu: '영업본부', headcount: 24,
    burnRate: [68, 71, 74, 70, 76, 72, 78, 83, 88, 94, 101, 106, 112],
    attrition: [0.8, 0.9, 1.1, 0.9, 1.3, 1.2, 1.6, 1.9, 2.2, 2.6, 2.9, 3.1, 3.4],
    performance: [104, 103, 105, 102, 101, 103, 100, 98, 96, 94, 92, 90, 88],
    readout: '예산 소진율이 12개월 연속 올라 한도를 넘겼고, 같은 기간 퇴사율은 4배가 됐습니다. 생산성 지수는 16p 떨어졌습니다.',
  },
  {
    team: 'AI·개발팀', bu: 'AI·개발본부', headcount: 31,
    burnRate: [62, 65, 61, 68, 72, 64, 67, 70, 66, 71, 74, 69, 73],
    attrition: [0.6, 0.5, 0.7, 0.6, 0.9, 0.7, 0.6, 0.8, 0.5, 0.7, 0.6, 0.9, 0.7],
    performance: [98, 100, 99, 102, 101, 104, 106, 105, 108, 111, 113, 114, 116],
    readout: '소진율이 60~70%대에서 안정적이고 퇴사율도 1% 아래입니다. 생산성은 18p 올랐습니다 — 예산 배분이 잘 맞는 팀입니다.',
  },
  {
    team: '재무회계팀', bu: '경영지원본부', headcount: 12,
    burnRate: [70, 73, 76, 71, 82, 75, 74, 78, 72, 77, 80, 76, 79],
    attrition: [0.7, 0.6, 0.8, 0.9, 1.0, 0.8, 0.7, 0.9, 0.8, 0.6, 0.9, 0.8, 1.0],
    performance: [100, 101, 99, 103, 98, 102, 104, 103, 101, 105, 104, 106, 105],
    readout: '결산·세무 성수기(12월·3월)에만 소진율이 튀고 나머지는 평탄합니다. 세 지표 모두 안정 구간입니다.',
  },
  {
    team: '전략기획팀', bu: '전략기획본부', headcount: 9,
    burnRate: [48, 52, 45, 58, 62, 50, 47, 55, 51, 49, 57, 53, 46],
    attrition: [1.0, 1.2, 1.1, 1.4, 1.3, 1.5, 1.2, 1.6, 1.4, 1.3, 1.5, 1.4, 1.2],
    performance: [96, 98, 97, 100, 99, 101, 98, 100, 102, 99, 101, 100, 102],
    readout: '소진율이 12개월 내내 60% 아래입니다. 배정 한도가 실제 필요보다 크게 잡혀 있을 가능성이 높습니다.',
  },
  {
    team: '인사팀', bu: '경영지원본부', headcount: 7,
    burnRate: [42, 46, 40, 51, 58, 44, 41, 48, 45, 43, 52, 47, 44],
    attrition: [0.5, 0.4, 0.6, 0.5, 0.7, 0.4, 0.5, 0.6, 0.4, 0.5, 0.7, 0.6, 0.5],
    performance: [99, 100, 101, 99, 100, 102, 101, 100, 103, 101, 102, 103, 101],
    readout: '가장 여유 있는 팀입니다. 소진율 44%, 퇴사율 0.5% — 예산 이관 여력이 있습니다.',
  },
]

// ── ③ 예산 산정 지표 — 최근 6개월 기준 ─────────────────────
//  "자주 남는다/모자란다"가 반복되면 그건 집행 문제가 아니라 **한도 산정 문제**다.
export interface BudgetPatternRow {
  category: Category
  months: number   // 최근 6개월 중 해당한 개월 수
  avgGap: number   // 평균 과부족률(%) — 양수=남음, 음수=부족
  amount: number   // 6개월 누적 과부족액(만원)
}

export const OFTEN_SURPLUS: BudgetPatternRow[] = [
  { category: '회의', months: 6, avgGap: 38, amount: 204 },
  { category: '비품', months: 5, avgGap: 26, amount: 158 },
  { category: '업무활성', months: 3, avgGap: 11, amount: 62 },
]

export const OFTEN_SHORT: BudgetPatternRow[] = [
  { category: '접대', months: 5, avgGap: -31, amount: -486 },
  { category: '출장', months: 4, avgGap: -19, amount: -274 },
  { category: '식대', months: 2, avgGap: -8, amount: -71 },
]

/** 위 두 표에서 곧바로 나오는 재배분 제안 — 총 한도를 늘리지 않고 옮기기만 한다. */
export const REALLOCATION = [
  { from: '회의' as Category, to: '접대' as Category, amount: 200, note: '회의비는 6개월 내내 남고 접대비는 5개월 모자랐습니다.' },
  { from: '비품' as Category, to: '출장' as Category, amount: 150, note: '비품 잔여가 안정적입니다. 출장 증가분을 흡수할 수 있습니다.' },
]

// ── ④ 상단 KPI — 법인카드·정산 시스템 핵심 지표 ──────────────
export interface GovKpi {
  key: string
  label: string
  value: string
  unit?: string
  /** 비교 기준 대비 변화량(표시용 문자열)과 방향. */
  delta: string
  /** 값이 오르는 게 좋은 지표인지 — 색·화살표 방향 판단에 쓴다. */
  higherIsBetter: boolean
  spark: number[]
  hint: string
}

export const GOV_KPIS: GovKpi[] = [
  {
    key: 'spend', label: '이번 달 총 지출', value: '1,967', unit: '만원',
    delta: '+7.3%', higherIsBetter: false,
    spark: GOV_MONTHS.map((_, i) => monthTotal(i)),
    hint: '전월 1,833만원 → 이번 달 1,967만원',
  },
  {
    key: 'burn', label: '전사 예산 소진율', value: '84', unit: '%',
    delta: '+6%p', higherIsBetter: false,
    spark: [66, 69, 68, 70, 74, 70, 71, 75, 77, 79, 82, 78, 84],
    hint: '경고성 지표 — 초과해도 자동 차단하지 않습니다',
  },
  {
    key: 'auto', label: '자동 처리율', value: '82', unit: '%',
    delta: '+5.4%p', higherIsBetter: true,
    spark: [58, 61, 63, 66, 68, 67, 70, 72, 74, 75, 77, 77, 82],
    hint: '룰 그래프가 사람 손 없이 끝낸 비율',
  },
  {
    key: 'lead', label: '평균 정산 처리기간', value: '3.2', unit: '일',
    delta: '-1.1일', higherIsBetter: false,
    spark: [7.1, 6.8, 6.4, 6.0, 5.7, 5.5, 5.2, 4.8, 4.6, 4.3, 4.3, 3.9, 3.2],
    hint: '제출 → 확정까지. 도입 전 7.1일',
  },
  {
    key: 'tax', label: '손금불산입 리스크', value: '2,840', unit: '만원',
    delta: '+18.2%', higherIsBetter: false,
    spark: [1620, 1710, 1780, 1850, 1920, 2010, 2140, 2230, 2350, 2420, 2560, 2400, 2840],
    hint: '적격증빙 누락 누적액 — 세무조사 시 비용 부인 대상',
  },
  {
    key: 'violation', label: '정책위반 의심', value: '12', unit: '건',
    delta: '+4건', higherIsBetter: false,
    spark: [5, 6, 4, 7, 9, 6, 5, 8, 7, 9, 10, 8, 12],
    hint: '금지업종·분할결제·심야 고액 등',
  },
]

// ── ⑤ 정책 인사이트 추천 (FR-DB-07) — 근거·예상효과·신뢰도까지 ──
export type InsightKind = 'RULE' | 'BUDGET' | 'PROCESS' | 'TAX'
export const INSIGHT_META: Record<InsightKind, { label: string; tone: string }> = {
  RULE: { label: 'Rule 추천', tone: 'ai' },
  BUDGET: { label: '한도 재산정', tone: '' },
  PROCESS: { label: '프로세스 개선', tone: '' },
  TAX: { label: '세무 리스크', tone: 'warn' },
}

export interface PolicyInsight {
  kind: InsightKind
  title: string
  evidence: string        // 근거 — 어떤 수치에서 나왔는지
  expected: string        // 예상 효과(정량)
  confidence: 'HIGH' | 'MEDIUM' | 'LOW'
  action: { label: string; to: string }
}

export const POLICY_INSIGHTS: PolicyInsight[] = [
  {
    kind: 'RULE',
    title: '분할결제 의심 패턴을 룰로 고정하세요',
    evidence: '최근 3개월 "동일 행사·다중 가맹점" 27건(1,240만원). 4개 팀에서 반복되고 매달 늘고 있습니다.',
    expected: '사람이 보던 건이 월 18건 줄고, 검토 리드타임이 0.6일 짧아질 것으로 추정합니다.',
    confidence: 'HIGH',
    action: { label: '룰 초안 만들기', to: '/rules' },
  },
  {
    kind: 'BUDGET',
    title: '접대비 한도를 올리고 회의비에서 옮기세요',
    evidence: '접대비는 전년 동월 대비 +139%, 최근 6개월 중 5개월 초과. 반면 회의비는 6개월 내내 평균 38% 남았습니다.',
    expected: '총 한도를 늘리지 않고 200만원을 옮기면 초과 경고가 62% 줄어듭니다.',
    confidence: 'HIGH',
    action: { label: '예산안 검토', to: '/governance' },
  },
  {
    kind: 'PROCESS',
    title: '영수증 첨부를 등록 시점으로 당기세요',
    evidence: '반려 사유 1위가 증빙 미첨부(48건, 전체의 34%)입니다. 재제출까지 평균 4.1일이 걸립니다.',
    expected: '등록 단계에서 막으면 반려 건수가 3분의 1로 줄고 처리기간이 1.4일 단축됩니다.',
    confidence: 'MEDIUM',
    action: { label: '정책 반영 검토', to: '/rules' },
  },
  {
    kind: 'TAX',
    title: '적격증빙 누락 누적액이 손금불산입 한계에 근접합니다',
    evidence: '3만원 초과 건 중 적격증빙 없는 금액이 2,840만원까지 쌓였습니다(전월 대비 +18.2%).',
    expected: '지금 소급 보완하면 약 620만원의 법인세 부담을 줄일 수 있습니다.',
    confidence: 'HIGH',
    action: { label: '대상 건 보기', to: '/review' },
  },
]

// ── ⑥ 리스크 패턴 알림 (FR-DB-08) — 심각도·영향범위·추세 ──────
export type RiskSeverity = 'CRITICAL' | 'HIGH' | 'MEDIUM'
export const SEVERITY_META: Record<RiskSeverity, { label: string; color: string; icon: string }> = {
  CRITICAL: { label: '심각', color: 'var(--tone-red)', icon: '●' },
  HIGH: { label: '높음', color: 'var(--tone-orange)', icon: '▲' },
  MEDIUM: { label: '보통', color: 'var(--tone-amber)', icon: '■' },
}

export interface RiskPattern {
  severity: RiskSeverity
  pattern: string
  title: string
  scope: string      // 영향 범위
  trend: string      // 추세
  spark: number[]    // 월별 발생 건수
  to: string
}

export const RISK_PATTERNS: RiskPattern[] = [
  {
    severity: 'CRITICAL', pattern: '한도 회피',
    title: '동일 행사 분할결제',
    scope: '4개 팀 · 27건 · 1,240만원',
    trend: '3개월 연속 증가 (9 → 12 → 27건)',
    spark: [3, 4, 2, 5, 6, 4, 5, 7, 8, 9, 12, 18, 27],
    to: '/review',
  },
  {
    severity: 'HIGH', pattern: '사적사용 의심',
    title: '심야·휴일 고액 접대',
    scope: '2개 팀 · 9건 · 680만원',
    trend: '전월 대비 +50% (6 → 9건)',
    spark: [2, 3, 2, 4, 5, 3, 2, 4, 5, 6, 7, 6, 9],
    to: '/review',
  },
  {
    severity: 'MEDIUM', pattern: '통제 취약',
    title: '승인자와 지출자가 같은 건',
    scope: '재무회계팀 · 6건 · 312만원',
    trend: '3개월째 같은 수준 유지',
    spark: [4, 5, 4, 6, 5, 4, 5, 6, 5, 6, 6, 6, 6],
    to: '/review',
  },
]

// ── ⑦ 반려 사유 Top 5 (전월 대비 변화 포함) ──────────────────
export const REJECT_REASONS = [
  { reason: '적격증빙 미첨부', count: 48, prev: 41, share: 0.34 },
  { reason: '한도 초과', count: 33, prev: 36, share: 0.23 },
  { reason: '비용분류 오류', count: 27, prev: 22, share: 0.19 },
  { reason: '실사용자 미지정', count: 19, prev: 19, share: 0.13 },
  { reason: '출장 신청 미연결', count: 15, prev: 11, share: 0.11 },
]

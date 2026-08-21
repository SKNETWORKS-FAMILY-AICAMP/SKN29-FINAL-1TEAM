// S-08 예산 관리 — 다개월 추세 목업 데이터.
//  실 API(`/api/team-budget/overview/`)는 이번 달 한 달치만 제공한다(seed가 과거 달 데이터를
//  만들지 않는다). 13개월 추세·6개월 빈도 분석은 과거 달 이력이 있어야 값이 차므로, 백엔드가
//  그 이력을 연동하기 전까지는 이 목업으로 화면 구조·시각화만 맞춘다(구 거버넌스 대시보드에서
//  이관 — 원본 시안이 이 숫자로 만들어졌다). 금액 단위는 전부 **만원**.
import type { Category } from '../types/domain'

/** 25.08 ~ 26.08 (13개월). 마지막이 이번 달. */
export const GOV_MONTHS = [
  '25.08', '25.09', '25.10', '25.11', '25.12',
  '26.01', '26.02', '26.03', '26.04', '26.05', '26.06', '26.07', '26.08',
] as const

export const IDX_NOW = GOV_MONTHS.length - 1
export const IDX_PREV_MONTH = GOV_MONTHS.length - 2

// 계정과목별 월 지출(만원) — 접대·출장이 가파르게 오르고 회의·비품은 평탄.
export const CATEGORY_SPEND: Record<Category, number[]> = {
  식대:   [380, 402, 395, 430, 455, 412, 388, 405, 441, 468, 452, 489, 501],
  출장:   [290, 315, 342, 301, 288, 275, 330, 358, 372, 395, 410, 438, 472],
  접대:   [180, 205, 232, 198, 176, 165, 210, 244, 268, 291, 322, 358, 431],
  회식:   [210, 225, 218, 240, 252, 231, 245, 260, 272, 285, 298, 310, 336],
  비품:   [140, 132, 155, 148, 139, 144, 151, 138, 146, 159, 142, 150, 148],
  회의:   [88, 92, 85, 90, 96, 84, 89, 93, 87, 95, 91, 88, 79],
}

export const CATEGORY_ORDER: Category[] = ['접대', '출장', '식대', '회식', '비품', '회의']

export const monthTotal = (index: number) =>
  CATEGORY_ORDER.reduce((sum, cat) => sum + CATEGORY_SPEND[cat][index], 0)

// 예산 산정 지표(최근 6개월) — "자주 남는다/모자란다"가 반복되면 집행이 아니라 한도 산정 문제다.
export interface BudgetPatternRow {
  category: Category
  months: number   // 최근 6개월 중 해당한 개월 수
  avgGap: number   // 평균 과부족률(%) — 양수=남음, 음수=부족
  amount: number   // 6개월 누적 과부족액(만원)
}

export const OFTEN_SURPLUS: BudgetPatternRow[] = [
  { category: '회의', months: 6, avgGap: 38, amount: 204 },
  { category: '비품', months: 5, avgGap: 26, amount: 158 },
  { category: '회식', months: 3, avgGap: 11, amount: 62 },
]

export const OFTEN_SHORT: BudgetPatternRow[] = [
  { category: '접대', months: 5, avgGap: -31, amount: -486 },
  { category: '출장', months: 4, avgGap: -19, amount: -274 },
  { category: '식대', months: 2, avgGap: -8, amount: -71 },
]

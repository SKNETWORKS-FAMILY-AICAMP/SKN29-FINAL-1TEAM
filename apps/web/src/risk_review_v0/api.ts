// apps/web/src/risk_review_v0/api.ts
// Review List v0 — 독립 개발 모듈. 기존 SettlementsContext/api/settlements.ts를 거치지 않고
// 신규 백엔드 엔드포인트(/api/risk-review-v0/*)를 직접 호출한다(rule_agent_v0와 동일하게 격리,
// 단 데이터 계층은 운영 DB 그대로 — Django domain/risk_review_v0/views.py 참조).
import { api } from '../api/client'

export interface Citation {
  doc: string
  article: string
  quote_summary: string
}

export interface SimilarCase {
  case_id: string
  outcome: string
  relevance: string
}

export interface Stage2Verdict {
  violation_verdict?: 'VIOLATION' | 'NO_VIOLATION' | 'INSUFFICIENT_INFO' | ''
  review_reasons?: string[]
  recommendation?: 'APPROVE' | 'SUPPLEMENT' | 'REJECT' | ''
  citations?: Citation[]
  similar_cases?: SimilarCase[]
}

export interface FeatureContrib {
  feature: string
  weight: number
}

export interface ReviewListItem {
  id: number
  merchant: string
  amount: number
  category: string
  purpose: string
  status: string
  submittedBy: string
  submittedAt: string
  anomalyScore: number
  featureContribs: FeatureContrib[]
  violationVerdict: Stage2Verdict['violation_verdict']
  recommendation: Stage2Verdict['recommendation']
  stage2Verdict: Stage2Verdict
}

export type Decision = 'APPROVE' | 'RETURN' | 'REJECT'

export const riskReviewV0Api = {
  list: () => api.get<ReviewListItem[]>('/risk-review-v0/reviews/'),
  decide: (settlementId: number, decision: Decision, reason?: string) =>
    api.post(`/risk-review-v0/reviews/${settlementId}/decision/`, { decision, reason }),
}

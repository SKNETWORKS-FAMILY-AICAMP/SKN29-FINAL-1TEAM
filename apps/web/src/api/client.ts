import axios from 'axios'

// Django(core) 대외 REST 진입점. 기본 /api → vite proxy 또는 Nginx 경유.
export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? '/api',
  withCredentials: true, // 세션 쿠키 전송(세션 로그인)
})

// 화면설계서 이벤트 스펙에 대응하는 엔드포인트 헬퍼(백엔드 구현 전 자리표시자).
// 실제 연동 전까지 화면은 mock 데이터를 사용한다.
export const endpoints = {
  health: () => api.get('/health/'),
  settlements: (params?: Record<string, unknown>) => api.get('/settlements/', { params }),
  settlement: (id: string) => api.get(`/settlements/${id}/`),
  createSettlement: (data: Record<string, unknown>) => api.post('/settlements/', data), // F-1 신규 지출 등록(비전 판독 후 확정 필드)
  raise: (ids: string[]) => api.post('/settlements/raise/', { ids }), // 개인 올림 DRAFT→TEAM_COLLECTING
  submit: (ids: string[]) => api.post('/settlements/submit/', { ids }), // 팀 제출 TEAM_COLLECTING→SUBMITTED / 재제출
  confirm: (id: string) => api.post(`/settlements/${id}/confirm/`), // FR-ST-03 사람 확정
  review: (id: string, decision: 'APPROVE' | 'RETURN' | 'REJECT', reason?: string) =>
    api.post(`/settlements/${id}/review/`, { decision, reason }),
  teamDecision: (id: string, decision: 'RETURN' | 'REJECT', reason?: string) =>
    api.post(`/settlements/${id}/team-decision/`, { decision, reason }),
  rules: () => api.get('/rules/'),
  activateRule: (id: string) => api.post(`/rules/${id}/activate/`),
  rollbackRule: (id: string) => api.post(`/rules/${id}/rollback/`),
  dashboard: (role: string) => api.get(`/dashboard/${role}/`),
  // S-02 팀 예산 현황 — 한도(DB) + 사용액(Settlement 집계). {total, used, categories:[{label,limit,used}]}
  teamBudget: (team: string | number, month: string) => api.get('/team-budget/', { params: { team, month } }),
  // 규정 문서 관리 (S-05 규정문서) — RAG 소스 문서 CRUD
  policyDocs: () => api.get('/policy-docs/'),
  uploadPolicyDoc: (data: FormData) => api.post('/policy-docs/', data, { headers: { 'Content-Type': 'multipart/form-data' } }),
  reembedPolicyDoc: (id: string) => api.post(`/policy-docs/${id}/reembed/`),
  deletePolicyDoc: (id: string) => api.delete(`/policy-docs/${id}/`),
  // Rule 버전 관리
  ruleVersions: (ruleId: string) => api.get(`/rules/${ruleId}/versions/`),
}

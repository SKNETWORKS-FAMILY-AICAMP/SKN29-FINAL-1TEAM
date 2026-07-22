import axios from 'axios'

// Django(core) 대외 REST 진입점. 기본 /api → vite proxy 또는 Nginx 경유.
export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? '/api',
})

// 화면설계서 이벤트 스펙에 대응하는 엔드포인트 헬퍼(백엔드 구현 전 자리표시자).
// 실제 연동 전까지 화면은 mock 데이터를 사용한다.
export const endpoints = {
  health: () => api.get('/health/'),
  settlements: (params?: Record<string, unknown>) => api.get('/settlements/', { params }),
  submit: (ids: string[]) => api.post('/settlements/submit/', { ids }), // FR-ST-01
  confirm: (id: string) => api.post(`/settlements/${id}/confirm/`), // FR-ST-03 사람 확정
  review: (id: string, decision: 'APPROVE' | 'RETURN' | 'REJECT', reason?: string) =>
    api.post(`/settlements/${id}/review/`, { decision, reason }),
  rules: () => api.get('/rules/'),
  activateRule: (id: string) => api.post(`/rules/${id}/activate/`),
  rollbackRule: (id: string) => api.post(`/rules/${id}/rollback/`),
  dashboard: (role: string) => api.get(`/dashboard/${role}/`),
}

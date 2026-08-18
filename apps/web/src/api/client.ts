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
  deleteSettlement: (id: string) => api.delete(`/settlements/${id}/`), // '내 지출' 미제출 건 삭제
  // F-1 초안 작성 Agent — instruction이 있으면 수정, 없으면 생성(플레이스홀더)
  suggestDraft: (data: Record<string, unknown>) => api.post('/settlements/draft-suggest/', data),
  raise: (ids: string[]) => api.post('/settlements/raise/', { ids }), // 개인 올림 DRAFT→TEAM_COLLECTING
  submit: (ids: string[]) => api.post('/settlements/submit/', { ids }), // 팀 제출 TEAM_COLLECTING→SUBMITTED / 재제출
  confirm: (id: string) => api.post(`/settlements/${id}/confirm/`), // FR-ST-03 사람 확정
  review: (id: string, decision: 'APPROVE' | 'RETURN' | 'REJECT', reason?: string) =>
    api.post(`/settlements/${id}/review/`, { decision, reason }),
  teamDecision: (id: string, decision: 'RETURN' | 'REJECT', reason?: string) =>
    api.post(`/settlements/${id}/team-decision/`, { decision, reason }),
  rules: (status?: string) => api.get('/rules/', { params: status ? { status } : undefined }),
  activateRule: (id: string) => api.post(`/rules/${id}/activate/`),
  rollbackRule: (id: string) => api.post(`/rules/${id}/rollback/`),
  // 버전 이력(같은 family 전체) 조회 · 특정 과거 버전으로 롤백
  ruleFamily: (id: string) => api.get(`/rules/${id}/family/`),
  rollbackRuleTo: (id: string) => api.post(`/rules/${id}/rollback-to/`),
  createRuleVersion: (id: string) => api.post(`/rules/${id}/versions/`),
  // 룰 그래프 검증 시뮬레이션 — 검증셋은 그래프(버전)에 저장되고, 실행 결과는 스냅샷과 함께 보존된다.
  // 룰 초안 작성 대화 로그 (Rule Agent 지시·반영 이력)
  ruleMessages: (id: string, nodeKey?: string) =>
    api.get(`/rules/${id}/messages/`, { params: nodeKey ? { nodeKey } : undefined }),
  addRuleMessages: (id: string, nodeKey: string, messages: unknown[]) =>
    api.post(`/rules/${id}/messages/`, { nodeKey, messages }),
  ruleTestCases: (id: string) => api.get(`/rules/${id}/test-cases/`),
  saveRuleTestCases: (id: string, testCases: unknown[]) => api.put(`/rules/${id}/test-cases/`, { testCases }),
  // 검증셋 자동생성 — 대화형 아님, 노드 조건을 역산해 완제품 검증셋을 한 번에 만들어
  // 기존 검증셋에 추가(append)한다. 노드마다 조건 역산 + 자체검증(최대 2회 simulate
  // 왕복)이 순차로 돌아 시간이 걸릴 수 있어 넉넉히 잡는다.
  generateRuleTestCases: (id: string) => api.post(`/rules/${id}/test-cases/generate/`, {}, { timeout: 200_000 }),
  simulateRule: (id: string, testCases?: unknown[]) => api.post(`/rules/${id}/simulate/`, testCases ? { testCases } : {}),
  ruleSimulation: (id: string) => api.get(`/rules/${id}/simulation/`),
  requestRuleActivation: (id: string, comment: string) => api.post(`/rules/${id}/request-activation/`, { comment }),
  rejectRuleActivation: (id: string, comment: string) => api.post(`/rules/${id}/reject-activation/`, { comment }),
  discardRuleDraft: (id: string) => api.delete(`/rules/${id}/draft/`),
  deleteRuleGraph: (id: string) => api.delete(`/rules/${id}/delete/`),
  createRuleGraph: (name: string, scope: string) => api.post('/rules/drafts/', { name, scope }),
  // 규정 문서(RAG)에서 룰 그래프 DRAFT 자동 생성 — Django가 FastAPI Rule Agent로 전달한다.
  // LLM+임베딩+저장이 직렬로 얹혀 수십 초가 걸릴 수 있어 axios 기본 타임아웃을 늘려 잡는다.
  generateRuleGraph: (data: { scope: string; name?: string; query?: string; topK?: number; includeLaw?: boolean }) =>
    api.post('/rules/generate/', {
      scope: data.scope,
      name: data.name,
      query: data.query || undefined,
      top_k: data.topK ?? 6,
      include_law: data.includeLaw ?? false,
    }, { timeout: 150_000 }),
  // 대화형 룰 수정 — 자연어 지시로 Agent가 그래프를 직접 고친다(LLM 툴콜링 여러 턴).
  // 대화 로그는 Agent가 서버에서 남기므로 화면은 addRuleMessages를 또 부르면 안 된다.
  // nodeKey: 화면에서 지금 선택 중인 노드 — 모호한 지시가 엉뚱한 노드에 적용되는 걸
  // 막는 힌트다(2026-08-18). Agent는 대화 이력도 서버(RuleAuthoringMessage)에서
  // 직접 불러 쓰므로 프론트가 이력을 따로 넘길 필요는 없다.
  converseRule: (graphId: string, message: string, nodeKey?: string) =>
    api.post(`/rules/${graphId}/converse/`, { message, nodeKey }, { timeout: 200_000 }),
  createRuleNode: (graphId: string, nodeKey: string) => api.post(`/rules/${graphId}/nodes/`, { nodeKey }),
  saveRuleNode: (graphId: string, nodeKey: string, data: Record<string, unknown>) =>
    api.patch(`/rules/${graphId}/nodes/${nodeKey}/`, data),
  deleteRuleNode: (graphId: string, nodeKey: string) => api.delete(`/rules/${graphId}/nodes/${nodeKey}/`),
  dashboard: (role: string) => api.get(`/dashboard/${role}/`),
  // S-02 팀 예산 현황 — 한도(DB) + 사용액(Settlement 집계). {total, used, categories:[{label,limit,used}]}
  teamBudget: (team: string | number, month: string) => api.get('/team-budget/', { params: { team, month } }),
  // 규정 문서 관리 — RAG 소스 문서 업로드·적재. 업로드는 접수만 하고 파싱·임베딩은
  // 백그라운드로 도므로, 화면은 목록을 폴링해 status가 DONE/FAILED가 되는 걸 지켜본다.
  policyDocs: () => api.get('/policy-docs/'),
  uploadPolicyDoc: (data: FormData) => api.post('/policy-docs/', data, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120_000,   // 업로드 자체(수십 MB)에 걸리는 시간. 적재는 여기 포함되지 않는다.
  }),
  reembedPolicyDoc: (id: string) => api.post(`/policy-docs/${id}/reembed/`),
  deletePolicyDoc: (id: string) => api.delete(`/policy-docs/${id}/`),
  // 폴더 트리(+ 폴더별 문서) · 폴더 생성 · 문서 이동
  policyFolders: () => api.get('/policy-docs/folders/'),
  createPolicyFolder: (name: string, parentId?: number | null) =>
    api.post('/policy-docs/folders/', { name, parentId: parentId ?? null }),
  // 끝 슬래시 필수 — 없으면 DRF 라우터가 301로 리다이렉트하고, PATCH/DELETE는 그 과정에서
  // 메서드·본문이 유실될 수 있다(테스트로 고정).
  renamePolicyFolder: (id: number, name: string) =>
    api.post(`/policy-docs/folders/${id}/`, { name }),
  // 비어 있지 않으면 400 — 문서·하위폴더를 먼저 옮겨야 한다(분류가 통째로 날아가는 걸 막는다).
  deletePolicyFolder: (id: number) => api.delete(`/policy-docs/folders/${id}/`),
  movePolicyDoc: (id: string, folderId: number | null) =>
    api.post(`/policy-docs/${id}/move/`, { folderId }),
  // 조 단위 조항 + 룰 연결 상태(계산값) · 조항 결정
  policyClauses: (id: string) => api.get(`/policy-docs/${id}/clauses/`),
  /**
   * 원본 PDF URL. `<iframe>`·다운로드 링크가 직접 쓰므로 axios가 아니라 **경로만** 만든다.
   * 세션 쿠키로 인가되므로(same-origin) 별도 토큰이 필요 없다 — baseURL이 `/api`라
   * vite proxy·nginx 어느 쪽이든 core로 간다.
   */
  policyDocFileUrl: (id: string, download = false) =>
    `${api.defaults.baseURL ?? '/api'}/policy-docs/${id}/file/${download ? '?download=1' : ''}`,
  decidePolicyClause: (docId: string, clauseId: number, decision: 'SKIP' | 'RESET', reason?: string) =>
    api.post(`/policy-docs/${docId}/clauses/${clauseId}/decision/`, { decision, reason }),
  // Rule 버전 관리
  ruleVersions: (ruleId: string) => api.get(`/rules/${ruleId}/versions/`),
}

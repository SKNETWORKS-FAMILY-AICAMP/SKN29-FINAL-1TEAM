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
  // S-03 헤더 요약(자동처리율·평균 검토시간) — 이번 달 집계, 서버가 계산한다.
  reviewStats: () => api.get('/settlements/review-stats/'),
  // F-1 신규 지출 등록 — **영수증 파일 필수**라 multipart로 보낸다(서버가 Receipt +
  //  Attachment(RECEIPT)를 만들고 비전 판독을 예약한다).
  createSettlement: (data: FormData) => api.post('/settlements/', data, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120_000,
  }),
  deleteSettlement: (id: string) => api.delete(`/settlements/${id}/`), // '내 지출' 미제출 건 삭제
  // 상세 화면 수정 저장. **제출·올림 버튼이 전이 전에 먼저 부른다** — 이게 없던 동안
  //  모달은 제목만 '수정'이었고 고친 값이 서버에 닿지 않았다(판정이 옛 값으로 돌았다).
  updateSettlement: (id: string, patch: Record<string, unknown>) =>
    api.patch(`/settlements/${id}/`, patch),
  // F-1 초안 작성 Agent — instruction이 있으면 수정, 없으면 생성(플레이스홀더)
  suggestDraft: (data: Record<string, unknown>) => api.post('/settlements/draft-suggest/', data),
  // ERP/카드사 결제기록 수집("내역 불러오기") — 다음 회차 표본을 가져온다(멱등).
  importSettlements: () => api.post('/settlements/import/'),
  // 팀·공용 카드 결제의 실사용자 본인 등록
  claimSettlement: (id: string) => api.post(`/settlements/${id}/claim/`),
  raise: (ids: string[]) => api.post('/settlements/raise/', { ids }), // 개인 올림 DRAFT→TEAM_COLLECTING
  submit: (ids: string[]) => api.post('/settlements/submit/', { ids }), // 팀 제출 TEAM_COLLECTING→SUBMITTED / 재제출
  confirm: (id: string) => api.post(`/settlements/${id}/confirm/`), // FR-ST-03 사람 확정
  review: (id: string, decision: 'APPROVE' | 'RETURN' | 'REJECT', reason?: string) =>
    api.post(`/settlements/${id}/review/`, { decision, reason }),
  teamDecision: (id: string, decision: 'RETURN' | 'REJECT', reason?: string) =>
    api.post(`/settlements/${id}/team-decision/`, { decision, reason }),
  // 보완요청·반려 **사유 초안** — Draft Agent가 판정 사유와 내역을 보고 문장을 채운다.
  //  결정 모달이 열릴 때 부른다. ai가 없어도 서버가 판정 플래그로 폴백하므로 항상 응답한다.
  // AI 위험 검토 재실행 — 실패했거나 결과가 안 온 IN_REVIEW 건만.
  //  `/judge/`로는 안 된다(판정 재실행은 SUBMITTED→RPA_JUDGED 전이를 전제한다).
  rerunRiskReview: (id: string) => api.post(`/settlements/${id}/risk-review/`),
  decisionReason: (id: string, decision: 'APPROVE' | 'RETURN' | 'REJECT') =>
    api.post(`/settlements/${id}/decision-reason/`, { decision }, { timeout: 40_000 }),
  rules: (status?: string) => api.get('/rules/', { params: status ? { status } : undefined }),
  // 네임드 플래그 레지스트리 — 라벨·선택지의 단일 원천(policies/flags.py).
  //  시스템 플래그는 기본 제외한다(룰이 `NO_ACTIVE_RULE_GRAPH`를 붙이면 의미가 뒤집힌다).
  ruleFlags: () => api.get('/rules/flags/'),
  // decision/severity 선택지 카탈로그 — Django `engine.py`가 소스(§8 후속, 2026-08-19).
  // 이전엔 이 화면이 <option>을 하드코딩해서 AI 서비스가 쓰던 목록과 독립적으로 존재했다.
  ruleActionSchema: () => api.get('/rules/action-schema/'),
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
  // 검증셋 자동생성 — 대화형 아님, 노드 조건을 역산해 완제품 검증셋을 한 번에 만들고
  // **통째로 교체**한다(replace, 2026-08-19 이전엔 append). 이제 "시뮬레이션 실행"의
  // 유일한 경로 — 노드마다 조건 역산 + 자체검증(최대 2회 simulate 왕복)이 순차로 돌아
  // 시간이 걸릴 수 있어 넉넉히 잡는다.
  generateRuleTestCases: (id: string) => api.post(`/rules/${id}/test-cases/generate/`, {}, { timeout: 200_000 }),
  ruleSimulation: (id: string) => api.get(`/rules/${id}/simulation/`),
  requestRuleActivation: (id: string, comment: string) => api.post(`/rules/${id}/request-activation/`, { comment }),
  rejectRuleActivation: (id: string, comment: string) => api.post(`/rules/${id}/reject-activation/`, { comment }),
  discardRuleDraft: (id: string) => api.delete(`/rules/${id}/draft/`),
  deleteRuleGraph: (id: string) => api.delete(`/rules/${id}/delete/`),
  //  정산 기반 초안 — 기본 내역은 서버가 읽는다(화면이 보내지 않는다).
  draftForSettlement: (id: string, instruction: string) =>
    api.post(`/settlements/${id}/draft/`, { instruction }),
  //  제출 직전 문체 다듬기 + 판정 미리보기.
  prepareSubmit: (id: string) => api.post(`/settlements/${id}/prepare-submit/`, {}),
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
  // 결정 사례(월별) — 문서 관리의 「결정 사례」 트리. `PolicyDoc`이 아니라 `DecisionCase`를
  //  읽는다(사례는 이미 case_history에 적재돼 있어 문서 파이프라인에 태우면 이중 적재된다).
  decisionCases: (month?: string) => api.get('/policy-docs/cases/', { params: month ? { month } : undefined }),
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
  /**
   * 조항 하나를 근거로 룰 그래프 DRAFT 생성. **AI가 `SKIP`으로 본 조항에서도 부를 수 있다** —
   * 분류는 제안이지 차단이 아니다. 질의는 서버가 조항에서 만든다(화면마다 달라지지 않게).
   */
  generateRuleFromClause: (docId: string, clauseId: number, scope?: string) =>
    api.post(`/policy-docs/${docId}/clauses/${clauseId}/generate-rule/`, { scope }),
  // 별표 후보 — 승인 전까지 판정에 쓰이지 않는다. 축 목록을 함께 받아 드롭다운에 쓴다.
  policyTableProposals: (docId: string) => api.get(`/policy-docs/${docId}/table-proposals/`),
  // POST다 — PolicyDocViewSet이 PATCH/PUT을 의도적으로 막아 두었다(문서는 제자리 수정 대상이 아님).
  updatePolicyTableProposal: (docId: string, id: number, patch: Record<string, unknown>) =>
    api.post(`/policy-docs/${docId}/table-proposals/${id}/`, patch),
  // 승인은 **화면이 고친 값과 함께** 보낸다 — 따로 저장하지 않고 누르면 서버가 옛 값으로
  // 검사해 400이 나는데, 화면에는 고친 값이 보여서 왜 막혔는지 알 수 없다.
  decidePolicyTableProposal: (
    docId: string, id: number, action: 'APPROVE' | 'REJECT', note?: string,
    patch?: Record<string, unknown>,
  ) => api.post(`/policy-docs/${docId}/table-proposals/${id}/decision/`,
    { ...(patch || {}), action, note }),
  // Rule 버전 관리
  ruleVersions: (ruleId: string) => api.get(`/rules/${ruleId}/versions/`),

  // ── S-08 예산 관리 — 전 팀 한도·사용액. 팀 하나짜리 teamBudget과 응답 셰이프가 다르다.
  budgetOverview: (month?: string) => api.get('/team-budget/overview/', { params: month ? { month } : undefined }),

  // ── S-09 법인카드 관리 — 조회는 사용액·조치필요 여부(계산값)를 함께 받는다.
  cards: (params?: Record<string, unknown>) => api.get('/cards/', { params }),
  cardsAttention: () => api.get('/cards/attention/'),
  // 지출 등록·수정 화면의 카드 선택지 — **본인이 쓸 수 있는 카드만**(개인 배정 + 소속 팀·공용).
  //  회계 권한 없이도 호출된다(지출 등록은 임직원 누구나 한다).
  myCards: () => api.get('/cards/mine/'),
  assignCard: (id: number, data: { mode: 'TEAM' | 'PERSONAL'; teamId?: number; userId?: number; reason?: string }) =>
    api.post(`/cards/${id}/assign/`, data),
  stopCard: (id: number, reason: string) => api.post(`/cards/${id}/stop/`, { reason }),
  reactivateCard: (id: number) => api.post(`/cards/${id}/reactivate/`),

  // ── ERP 전표(안) — 화면은 정산 id만 들고 있으므로 전표 id 없이 조회한다.
  //  전표가 없으면 404다(빈 껍데기를 받아 "있는데 비었다"로 그리지 않게).
  erpVoucherBySettlement: (settlementId: string) => api.get(`/erp/vouchers/by-settlement/${settlementId}/`),

  // ── 증빙 첨부 — **업로드가 곧 판독 트리거**다(서버가 커밋 후 비전 판독을 돌린다).
  //  판독은 비동기라 업로드 응답의 extractionStatus는 대개 PENDING/RUNNING이다 → 목록을 폴링한다.
  settlementAttachments: (id: string) => api.get(`/settlements/${id}/attachments/`),
  uploadAttachment: (id: string, form: FormData) =>
    api.post(`/settlements/${id}/attachments/`, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120_000,
    }),
  deleteAttachment: (id: string, attachmentId: number) =>
    api.delete(`/settlements/${id}/attachments/${attachmentId}/`),
  reextractAttachment: (id: string, attachmentId: number) =>
    api.post(`/settlements/${id}/attachments/${attachmentId}/reextract/`),
}

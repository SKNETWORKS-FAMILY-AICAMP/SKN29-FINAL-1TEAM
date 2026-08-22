// AI-LAB API 클라이언트 — Django `/api/ai-lab/*` → FastAPI `/lab/*` 프록시.
//  화면이 FastAPI를 직접 부르지 않는 이유: FastAPI는 내부 전용이고, 인가(Capability `ai_lab`)는
//  Django가 판정한다. 여기서는 응답을 가공하지 않고 그대로 흘린다 — 실험 도구는 서버가 낸 것을
//  그대로 보여줘야 값을 한다.
import { api } from '../../../api/client'

// ── 상태 ──────────────────────────────────────────────
export interface CollectionStat {
  name: string
  count: number
  embedderVersions: Record<string, number>
  mixedEmbedder?: boolean
  judgement?: boolean
  error: string | null
}

export interface LabStatus {
  service: string
  latencyMs: number
  openai: {
    configured: boolean
    draftModel: string
    embeddingModel: string
    dimensions: number
    queryPrefix: string
    embedderVersion: string
  }
  chroma: { reachable: boolean; endpoint: string; collections: CollectionStat[] }
  core: { reachable: boolean; baseUrl: string; error: string | null }
  anomalyModel: { loaded: boolean; fitted: boolean }
}

// ── Draft Agent ───────────────────────────────────────
//  분류 어휘 정본은 서버다(`GET /api/meta/categories/`). 여기서 유니언으로 못 박으면
//  서버가 분류를 늘렸을 때 AI-LAB만 옛 목록으로 남는다 — 이 화면은 "운영과 같은 것을
//  본다"는 게 존재 이유라 그 어긋남이 특히 나쁘다. 빈 문자열은 미분류(선택 필요).
export type DraftCategory = string

export interface DraftResult {
  mode: 'create' | 'revise'
  draft: {
    merchant: string
    amount: number
    category: DraftCategory
    aiCategory: DraftCategory
    aiSuggested: boolean
    merchantIndustry: string
    merchantIndustryCode: string
    purpose: string
    evidence: 'OK' | 'MISSING'
    headcount: number
  }
  confidence: number
  changes?: string[]
  comments: { icon: string; text: string }[]
  policyHints: { level: string; clause: string; text: string; status: string }[]
}

/** 실행 추적 — 결과가 "왜 그렇게 나왔는지". 폴백이 돌면 error/fallbackUsed가 채워진다. */
export interface DraftTrace {
  model?: string
  temperature?: number
  systemPrompt?: string
  userPrompt?: string
  rawOutput?: string | null
  refusal?: string | null
  finishReason?: string | null
  usage?: { promptTokens: number | null; completionTokens: number | null; totalTokens: number | null }
  latencyMs?: number
  totalMs?: number
  fallbackUsed?: boolean
  error?: string
  policy?: { source: 'core' | 'fallback'; value?: Record<string, unknown>; reason?: string }
}

export interface DraftRunResponse {
  request: Record<string, unknown>
  result: DraftResult
  trace: DraftTrace
}

// ── RAG ───────────────────────────────────────────────
export interface RagHit {
  chunk_id: string
  citation: string
  document: string
  parent_document?: string
  score: number
  metadata: Record<string, unknown>
}

export interface RagSearchResponse {
  query: string
  collection: string
  embedderVersion: string
  queryPrefix: string
  latencyMs: number
  hits: RagHit[]
  judgementCollection: boolean
}

export interface RagEmbedResponse {
  mode: string
  model: string
  dimensions: number
  embedderVersion: string
  appliedPrefix: string
  billedTokens: number
  latencyMs: number
  vectors: { text: string; dim: number; head: number[] }[]
  similarity: number[][]
}

export interface RagSampleResponse {
  collection: string
  count: number
  items: { chunkId: string; document: string; metadata: Record<string, unknown> }[]
}

// ── ② Rule Agent ──────────────────────────────────────
export interface RuleGenerateLabRequest {
  scope: string
  query?: string
  topK: number
  name?: string
  includeLaw: boolean
}

export interface RuleGenerateLabResponse {
  request: RuleGenerateLabRequest
  result: {
    status: string
    graph?: { id: string; name: string; scope: string; version: number; status: string } | Record<string, unknown>
    entry_node_key?: string
    query?: string
    sources?: unknown[]
    rejected_nodes?: unknown[]
    llm_skipped?: boolean
    attempts?: number
  }
  latencyMs: number
  sideEffectNote: string
}

// ── ③ Risk Review Agent ───────────────────────────────
export interface RiskRunLabResponse {
  request: { settlementId: number }
  result: {
    settlement_id: number
    stage1_anomaly: Record<string, unknown>
    stage2_rag_review: Record<string, unknown>
  }
  latencyMs: number
}

// ── 증빙자료 추출 Agent ───────────────────────────────
export interface ExtractRunLabResponse {
  fileRef: string
  kind: string
  latencyMs: number
  result: {
    extraction_status: string
    extracted: Record<string, unknown>
    field_confidence: Record<string, number>
    evidence_spans: { path: string; quote: string; source: string }[]
    extractor_version: string
    warnings: string[]
    document_summary?: string
    // read_receipt 전용 필드(kind=RECEIPT일 때만)
    merchant?: string
    amount?: number | null
  }
}

// ── 호출 래퍼 ─────────────────────────────────────────
/** 서버가 준 실패 사유를 문장 하나로. 422(pydantic)는 배열로 오므로 필드까지 풀어 쓴다. */
export function labErrorMessage(err: unknown): string {
  const res = (err as { response?: { status?: number; data?: unknown } })?.response
  const detail = (res?.data as { detail?: unknown })?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((d) => {
        const loc = Array.isArray((d as { loc?: unknown[] }).loc) ? (d as { loc: unknown[] }).loc.join('.') : ''
        return `${loc}: ${(d as { msg?: string }).msg ?? JSON.stringify(d)}`
      })
      .join(' / ')
  }
  if (res?.status === 403) return 'AI-LAB 사용 권한이 없습니다(Capability: ai_lab).'
  if (res?.data) return JSON.stringify(res.data)
  return (err as Error)?.message ?? '알 수 없는 오류'
}

export const labApi = {
  status: () => api.get<LabStatus>('/ai-lab/status').then((r) => r.data),
  runDraft: (payload: Record<string, unknown>) =>
    api.post<DraftRunResponse>('/ai-lab/draft/run', payload).then((r) => r.data),
  ragSearch: (body: {
    query: string
    collection: string
    topK: number
    expandParent: boolean
    useQueryPrefix: boolean
  }) => api.post<RagSearchResponse>('/ai-lab/rag/search', body).then((r) => r.data),
  ragEmbed: (body: { texts: string[]; mode: 'query' | 'raw' }) =>
    api.post<RagEmbedResponse>('/ai-lab/rag/embed', body).then((r) => r.data),
  ragCollections: () =>
    api.get<{ collections: CollectionStat[] }>('/ai-lab/rag/collections').then((r) => r.data),
  ragSample: (collection: string, limit: number, docName?: string) =>
    api
      .get<RagSampleResponse>(`/ai-lab/rag/collections/${collection}/sample`, {
        params: { limit, ...(docName ? { docName } : {}) },
      })
      .then((r) => r.data),
  // 룰 생성은 실제 DRAFT 그래프를 만들므로(부작용), 대화형 API 타임아웃(200s)과 맞춘다.
  runRuleGenerate: (payload: RuleGenerateLabRequest) =>
    api.post<RuleGenerateLabResponse>('/ai-lab/rule/generate', payload, { timeout: 200_000 }).then((r) => r.data),
  runRisk: (settlementId: number) =>
    api.post<RiskRunLabResponse>('/ai-lab/risk/run', { settlementId }, { timeout: 90_000 }).then((r) => r.data),
  runExtract: (fileRef: string, kind: string) =>
    api.post<ExtractRunLabResponse>('/ai-lab/extract/run', { fileRef, kind }, { timeout: 90_000 }).then((r) => r.data),
}

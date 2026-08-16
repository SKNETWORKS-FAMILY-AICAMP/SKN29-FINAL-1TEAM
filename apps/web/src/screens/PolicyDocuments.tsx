// 규정 문서 관리 (목업 S-05 v4 ③ 폴더보기 - 문서 미리보기)
//
// 좌: 폴더 트리 / 우: 선택한 문서의 조(條) 단위 미리보기.
// 목업 하단의 "확인 필요(3)" 노란 박스는 제외했다 — 같은 정보가 우측 조항 카드에 이미
// 있고(확인 필요 배지 + 결정 버튼), 두 곳에서 같은 결정을 내릴 수 있으면 어느 쪽이
// 최신인지 모르게 된다.
//
// 업로드는 **접수만** 하고 파싱·청킹·임베딩·적재는 백그라운드로 돈다(문서당 수십 초~분).
// 그래서 진행 중인 문서가 있을 때만 목록을 폴링한다.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AlertTriangle, RefreshCw, Search, Trash2, Upload } from 'lucide-react'
import { endpoints } from '../api/client'
import {
  EMBEDDING_IN_PROGRESS, EMBEDDING_STATUS_META,
  type FolderDoc, type PolicyClause, type PolicyDocument, type PolicyFolder,
} from '../types/domain'
import { KpiCard } from '../components/ui/KpiCard'
import { FolderTree } from './policy-docs/FolderTree'
import { ClauseCard } from './policy-docs/ClauseAccordion'
import './policy-docs/policy-docs.css'

const POLL_MS = 4000
// GLOBAL ∪ settlements.Category. SoT는 Django `Category` — "업무활성"은 폐지되고
// "회식"이 독립 카테고리로 대체됐다(2026-08-14).
const RULE_SCOPES = ['GLOBAL', '회식', '회의', '식대', '출장', '접대', '비품'] as const
// 판정 근거로 인용되는 컬렉션. org_docs(조직도·직급체계)는 여기 없다 — 결재선의 SoR은
// 문서가 아니라 Django이고, 조직도가 정산 판정 근거로 인용되면 안 된다.
const JUDGEMENT_COLLECTIONS = ['policy_docs', 'case_history', 'tax_refs']

const fmtSize = (bytes: number) =>
  bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)}MB` : `${Math.max(1, Math.round(bytes / 1024))}KB`

export function PolicyDocuments() {
  const [folders, setFolders] = useState<PolicyFolder[]>([])
  const [unfiled, setUnfiled] = useState<FolderDoc[]>([])
  const [docs, setDocs] = useState<PolicyDocument[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [clauses, setClauses] = useState<PolicyClause[]>([])
  const [expanded, setExpanded] = useState<Set<number>>(new Set())
  const [query, setQuery] = useState('')
  const [scope, setScope] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)

  const selected = docs.find((d) => d.id === selectedId) ?? null

  const load = useCallback(async () => {
    try {
      const [tree, list] = await Promise.all([endpoints.policyFolders(), endpoints.policyDocs()])
      setFolders(tree.data.folders ?? [])
      setUnfiled(tree.data.unfiled ?? [])
      setDocs(list.data as PolicyDocument[])
      setError('')
    } catch {
      setError('규정 문서를 불러오지 못했습니다. 권한(룰 콘솔)과 API 연결을 확인해주세요.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  // 진행 중인 문서가 있을 때만 폴링한다 — 다 끝났는데 계속 두드릴 이유가 없다.
  useEffect(() => {
    if (!docs.some((d) => EMBEDDING_IN_PROGRESS.includes(d.status))) return
    const timer = setInterval(() => { void load() }, POLL_MS)
    return () => clearInterval(timer)
  }, [docs, load])

  // 선택한 문서의 조항. 첫 '확인 필요' 조항을 펼쳐 둔다 — 담당자가 할 일이 그것이다.
  const loadClauses = useCallback(async (id: string) => {
    try {
      const { data } = await endpoints.policyClauses(id)
      const rows = data as PolicyClause[]
      setClauses(rows)
      const first = rows.find((c) => c.ruleStatus === 'NEEDS_REVIEW')
      setExpanded(new Set(first ? [first.id] : []))
    } catch {
      setClauses([])
      setError('조항을 불러오지 못했습니다.')
    }
  }, [])

  useEffect(() => {
    if (!selectedId) { setClauses([]); return }
    void loadClauses(selectedId)
  }, [selectedId, loadClauses])

  const upload = async (file: File) => {
    setBusy(true); setError('')
    const form = new FormData()
    form.append('file', file)
    form.append('title', file.name.replace(/\.[^.]+$/, ''))
    if (scope) form.append('ruleScope', scope)
    try {
      const { data } = await endpoints.uploadPolicyDoc(form)
      await load()
      setSelectedId(String(data.id))
    } catch (exc) {
      setError((exc as { response?: { data?: { detail?: string } } }).response?.data?.detail
        || '업로드에 실패했습니다.')
    } finally {
      setBusy(false)
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  const withBusy = async (fn: () => Promise<unknown>, fail: string) => {
    setBusy(true); setError('')
    try { await fn() } catch { setError(fail) } finally { setBusy(false) }
  }

  const decide = (clauseId: number, decision: 'SKIP' | 'RESET', reason?: string) =>
    withBusy(async () => {
      if (!selectedId) return
      await endpoints.decidePolicyClause(selectedId, clauseId, decision, reason)
      await Promise.all([loadClauses(selectedId), load()])
    }, '결정을 저장하지 못했습니다.')

  const kpi = useMemo(() => ({
    total: docs.length,
    done: docs.filter((d) => d.status === 'DONE').length,
    busy: docs.filter((d) => EMBEDDING_IN_PROGRESS.includes(d.status)).length,
    review: docs.reduce((sum, d) => sum + (d.reviewCount || 0), 0),
  }), [docs])

  const toggle = (id: number) => setExpanded((prev) => {
    const next = new Set(prev)
    next.has(id) ? next.delete(id) : next.add(id)
    return next
  })

  return (
    <>
      <div className="page-head row" style={{ justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <span className="screen-id">규정문서</span>
          <h1>규정 문서 관리</h1>
          <div className="sub">회사 규정을 등록하면 AI가 조항을 정리하고, 자동 판단 규칙과 연결해드려요.</div>
        </div>
        <div className="row" style={{ gap: 8 }}>
          <select value={scope} onChange={(e) => setScope(e.target.value)} title="룰 생성 대상 비용분류">
            <option value="">비용분류 미지정</option>
            {RULE_SCOPES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <input ref={fileInput} type="file" accept=".pdf" style={{ display: 'none' }}
                 onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(f) }} />
          <button className="btn primary" disabled={busy} onClick={() => fileInput.current?.click()}>
            <Upload size={14} /> {busy ? '처리 중…' : '+ 문서 업로드'}
          </button>
        </div>
      </div>

      {error && (
        <div className="note" style={{ marginBottom: 12, color: 'var(--tone-red)', borderColor: 'var(--tone-red-bg)' }}>
          <AlertTriangle size={13} style={{ verticalAlign: -2, marginRight: 4 }} />{error}
        </div>
      )}

      <div className="kpi-grid">
        <KpiCard label="등록한 문서" value={kpi.total} unit="건" />
        <KpiCard label="분석 완료" value={kpi.done} unit="건" />
        <KpiCard label="분석 중" value={kpi.busy} unit="건" warn={kpi.busy > 0} />
        <KpiCard label="확인이 필요한 조항" value={kpi.review} unit="개" warn={kpi.review > 0} />
      </div>

      <div className="pd-layout">
        <aside className="card pd-tree">
          <div className="pd-search">
            <Search size={13} color="var(--muted)" />
            <input placeholder="폴더나 문서 찾기" value={query} onChange={(e) => setQuery(e.target.value)} />
          </div>
          {loading
            ? <div className="text-meta" style={{ padding: 16 }}>불러오는 중…</div>
            : <FolderTree folders={folders} unfiled={unfiled} selectedId={selectedId}
                          onSelect={setSelectedId} query={query} />}
        </aside>

        <section className="card pd-preview">
          {!selected ? (
            <div className="pd-empty">
              <div style={{ fontSize: 40 }} aria-hidden>📄</div>
              <b>왼쪽에서 문서를 선택하면 상세 정보를 볼 수 있어요</b>
              <p className="text-meta">
                문서를 열면 어떤 조항이 자동 규칙으로 연결됐는지, 어떤 조항을 확인해야 하는지 한눈에 볼 수 있어요.
              </p>
            </div>
          ) : (
            <>
              <div className="pd-preview-head">
                <div className="row" style={{ gap: 8, alignItems: 'center' }}>
                  <span aria-hidden>📄</span>
                  <b style={{ fontSize: 15 }}>{selected.title}</b>
                  <span className="pd-badge green">{EMBEDDING_STATUS_META[selected.status]?.label}</span>
                  {selected.superseded && <span className="pd-badge gray">이전 버전</span>}
                </div>
                <div className="row" style={{ gap: 6 }}>
                  <button className="btn sm" disabled={busy || EMBEDDING_IN_PROGRESS.includes(selected.status)}
                          onClick={() => void withBusy(async () => {
                            await endpoints.reembedPolicyDoc(selected.id); await load()
                          }, '재색인을 시작하지 못했습니다.')}>
                    <RefreshCw size={11} /> {selected.status === 'FAILED' ? '재처리' : '재색인'}
                  </button>
                  <button className="btn sm" disabled={busy}
                          style={{ color: 'var(--tone-red)', borderColor: 'var(--tone-red-bg)' }}
                          onClick={() => {
                            if (!window.confirm(`"${selected.title}"을 삭제하시겠습니까?\n(이미 적재된 벡터는 재색인 전까지 남습니다)`)) return
                            void withBusy(async () => {
                              await endpoints.deletePolicyDoc(selected.id)
                              setSelectedId(null); await load()
                            }, '삭제하지 못했습니다.')
                          }}>
                    <Trash2 size={11} /> 삭제
                  </button>
                </div>
              </div>

              <div className="pd-meta text-meta">
                등록일 {selected.uploadedAt?.slice(0, 10)}
                {selected.fileSize > 0 && <> · 크기 {fmtSize(selected.fileSize)}</>}
                · 조항 {selected.clauseCount}개
                {selected.reviewCount > 0 && <> · 확인이 필요한 조항 {selected.reviewCount}개</>}
                {selected.collection && (
                  <> · {selected.collection}
                    {!JUDGEMENT_COLLECTIONS.includes(selected.collection) && (
                      <span style={{ color: 'var(--tone-amber)' }}> (판정 미인용)</span>
                    )}
                  </>
                )}
              </div>

              {selected.error && (
                <div className="note" style={{ margin: '8px 0', whiteSpace: 'pre-wrap', color: selected.status === 'FAILED' ? 'var(--tone-red)' : 'var(--tone-amber)' }}>
                  {selected.error}
                </div>
              )}
              {selected.ruleTrigger?.detail && (
                <div className="note" style={{ margin: '8px 0' }}>
                  {selected.ruleTrigger.detail}
                  {selected.ruleTrigger.hint && <div className="text-meta">{selected.ruleTrigger.hint}</div>}
                </div>
              )}

              <div className="pd-section-title">최근 조항 살펴보기</div>

              {EMBEDDING_IN_PROGRESS.includes(selected.status) && (
                <div className="text-meta" style={{ padding: 16 }}>
                  문서를 분석하고 있어요. 끝나면 조항이 여기에 나타납니다.
                </div>
              )}
              {!EMBEDDING_IN_PROGRESS.includes(selected.status) && clauses.length === 0 && (
                <div className="text-meta" style={{ padding: 16 }}>
                  조 단위로 인식된 조항이 없어요. 표·별표만 있는 문서이거나 파싱이 실패했을 수 있어요.
                </div>
              )}

              {clauses.map((clause) => (
                <ClauseCard
                  key={clause.id}
                  clause={clause}
                  expanded={expanded.has(clause.id)}
                  onToggle={() => toggle(clause.id)}
                  busy={busy}
                  onSkip={(reason) => void decide(clause.id, 'SKIP', reason)}
                  onReset={() => void decide(clause.id, 'RESET')}
                  // 규칙 생성은 룰 콘솔이 주인이다 — 여기서 두 번째 생성 경로를 만들지 않는다.
                  onCreateRule={() => {
                    const target = selected.ruleScope || scope
                    window.location.href = `/rules?generate=1&scope=${encodeURIComponent(target)}`
                      + `&query=${encodeURIComponent(clause.articleLabel + ' ' + clause.articleTitle)}`
                  }}
                />
              ))}
            </>
          )}
        </section>
      </div>

      <div className="note" style={{ marginTop: 16 }}>
        등록된 문서 {kpi.total}개 · {folders.length}개 폴더로 정리되어 있어요.
        업로드된 문서는 <b>파싱 → 조(條) 단위 청킹 → 임베딩 → 적재</b>를 거쳐 Rule Agent의 RAG 검색과
        Risk Review의 내규검증 근거로 인용됩니다.
      </div>
    </>
  )
}

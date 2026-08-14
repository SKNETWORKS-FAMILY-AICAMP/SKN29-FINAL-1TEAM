// 규정 문서 관리 — RAG 소스 문서를 올리고 적재 상태를 지켜본다.
//
// 업로드는 **접수만** 하고 파싱·청킹·임베딩·적재는 백그라운드로 돈다(문서당 수십 초~분).
// 그래서 화면은 목록을 폴링해 status가 DONE/FAILED가 될 때까지 지켜본다 — 업로드 응답을
// 기다리는 구조로 만들면 브라우저가 먼저 끊긴다.
//
// 적재된 문서는 Rule Agent의 RAG 검색(search_policy)과 Risk Review의 내규검증 근거가 된다.
import { useCallback, useEffect, useRef, useState } from 'react'
import { AlertTriangle, FileText, RefreshCw, Trash2, Upload } from 'lucide-react'
import { endpoints } from '../api/client'
import {
  EMBEDDING_IN_PROGRESS, EMBEDDING_STATUS_META,
  type EmbeddingStatus, type PolicyDocument,
} from '../types/domain'
import { KpiCard } from '../components/ui/KpiCard'

const POLL_MS = 4000
// GLOBAL ∪ settlements.Category. 비우면 룰 생성 트리거 대상이 정해지지 않는다.
const RULE_SCOPES = ['GLOBAL', '업무활성', '회의', '식대', '출장', '접대', '비품'] as const

// 판정 근거로 인용되는 컬렉션. org_docs(조직도·직급체계)는 여기 없다 — 결재선의 SoR은
// 문서가 아니라 Django이고, 조직도가 정산 판정 근거로 인용되면 안 된다.
const JUDGEMENT_COLLECTIONS = ['policy_docs', 'case_history', 'tax_refs']

function StatusBadge({ status }: { status: EmbeddingStatus }) {
  const meta = EMBEDDING_STATUS_META[status] ?? EMBEDDING_STATUS_META.FAILED
  const toneMap = {
    amber: { bg: 'var(--tone-amber-bg)', color: 'var(--tone-amber)', border: '#e8d5a3' },
    green: { bg: 'var(--tone-green-bg)', color: 'var(--tone-green)', border: '#bfe6d1' },
    red: { bg: 'var(--tone-red-bg)', color: 'var(--tone-red)', border: '#f3c9c5' },
  }
  const t = toneMap[meta.tone]
  const busy = EMBEDDING_IN_PROGRESS.includes(status)
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, padding: '2px 8px', borderRadius: 999, fontSize: 11, fontWeight: 700, background: t.bg, color: t.color, border: `1px solid ${t.border}` }}>
      {busy && <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--tone-amber)', animation: 'pulse 1.5s infinite' }} />}
      {meta.label}
    </span>
  )
}

export function PolicyDocuments() {
  const [docs, setDocs] = useState<PolicyDocument[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('전체')
  const [scope, setScope] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)

  const load = useCallback(async () => {
    try {
      const { data } = await endpoints.policyDocs()
      setDocs(data as PolicyDocument[])
      setError('')
    } catch {
      setError('규정 문서 목록을 불러오지 못했습니다. 권한(룰 콘솔)과 API 연결을 확인해주세요.')
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

  const upload = async (file: File) => {
    setBusy(true)
    setError('')
    const form = new FormData()
    form.append('file', file)
    form.append('title', file.name.replace(/\.[^.]+$/, ''))
    if (scope) form.append('ruleScope', scope)
    try {
      await endpoints.uploadPolicyDoc(form)
      await load()
    } catch (exc) {
      const detail = (exc as { response?: { data?: { detail?: string } } }).response?.data?.detail
      setError(detail || '업로드에 실패했습니다.')
    } finally {
      setBusy(false)
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  const reembed = async (id: string) => {
    setBusy(true)
    try {
      await endpoints.reembedPolicyDoc(id)
      await load()
    } catch {
      setError('재색인을 시작하지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }

  const remove = async (doc: PolicyDocument) => {
    if (!window.confirm(`"${doc.title}"을 삭제하시겠습니까?\n(이미 적재된 벡터는 재색인 전까지 남습니다)`)) return
    setBusy(true)
    try {
      await endpoints.deletePolicyDoc(doc.id)
      await load()
    } catch {
      setError('삭제하지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }

  const visible = docs.filter((d) => {
    if (statusFilter !== '전체' && (EMBEDDING_STATUS_META[d.status]?.label ?? '') !== statusFilter) return false
    if (search && !d.title.includes(search) && !d.fileName.includes(search)) return false
    return true
  })

  const stats = {
    total: docs.length,
    done: docs.filter((d) => d.status === 'DONE').length,
    busy: docs.filter((d) => EMBEDDING_IN_PROGRESS.includes(d.status)).length,
    chunks: docs.reduce((sum, d) => sum + (d.leafCount || 0), 0),
  }

  return (
    <>
      <div className="page-head row" style={{ justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <span className="screen-id">규정문서</span>
          <h1>규정 문서 관리</h1>
          <div className="sub">사내 규정을 올리면 파싱·청킹·임베딩을 거쳐 AI가 검색할 수 있게 적재됩니다</div>
        </div>
        <div className="row" style={{ gap: 8 }}>
          <select value={scope} onChange={(e) => setScope(e.target.value)} title="룰 생성 대상 비용분류">
            <option value="">비용분류 미지정</option>
            {RULE_SCOPES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <input
            ref={fileInput} type="file" accept=".pdf" style={{ display: 'none' }}
            onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(f) }}
          />
          <button className="btn primary" disabled={busy} onClick={() => fileInput.current?.click()}>
            <Upload size={14} /> {busy ? '처리 중…' : '+ 문서 업로드 (PDF)'}
          </button>
        </div>
      </div>

      {error && (
        <div className="note" style={{ marginBottom: 12, color: 'var(--tone-red)', borderColor: 'var(--tone-red-bg)' }}>
          <AlertTriangle size={13} style={{ verticalAlign: -2, marginRight: 4 }} />{error}
        </div>
      )}

      <div className="kpi-grid">
        <KpiCard label="총 문서 수" value={stats.total} unit="건" />
        <KpiCard label="적재 완료" value={stats.done} unit="건" />
        <KpiCard label="처리 중" value={stats.busy} unit="건" warn={stats.busy > 0} />
        <KpiCard label="검색 대상 청크" value={stats.chunks} unit="개" />
      </div>

      <div className="filter-bar">
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option>전체 상태</option>
          {Object.values(EMBEDDING_STATUS_META).map((m) => <option key={m.label} value={m.label}>{m.label}</option>)}
        </select>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 12px', border: '1px solid var(--border-strong)', borderRadius: 'var(--radius-control)', background: 'var(--surface)', flex: 1, maxWidth: 240 }}>
          <FileText size={13} color="var(--muted)" />
          <input
            placeholder="문서명 검색" value={search} onChange={(e) => setSearch(e.target.value)}
            style={{ border: 'none', outline: 'none', background: 'none', fontSize: 13, flex: 1, padding: 0 }}
          />
        </div>
      </div>

      <div className="card">
        <table className="table">
          <thead>
            <tr>
              <th>문서명</th>
              <th>유형 · 컬렉션</th>
              <th>업로드일</th>
              <th>상태</th>
              <th className="num">청크(검색대상)</th>
              <th>룰 생성</th>
              <th>액션</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((d) => (
              <tr key={d.id}>
                <td>
                  <div style={{ fontWeight: 600, fontSize: 13 }}>{d.title}</div>
                  <div className="text-meta">{d.fileName}</div>
                  {d.error && (
                    <div className="text-meta" style={{ color: d.status === 'FAILED' ? 'var(--tone-red)' : 'var(--tone-amber)', whiteSpace: 'pre-wrap', marginTop: 4 }}>
                      {d.error}
                    </div>
                  )}
                </td>
                <td>
                  <div className="text-meta">{d.profile || '-'}</div>
                  <div className="text-meta">
                    {d.collection || '-'}
                    {d.collection && !JUDGEMENT_COLLECTIONS.includes(d.collection) && (
                      <span style={{ color: 'var(--tone-amber)' }}> · 판정 미인용</span>
                    )}
                  </div>
                </td>
                <td className="text-meta">{d.uploadedAt?.slice(0, 10)}</td>
                <td><StatusBadge status={d.status} /></td>
                <td className="num">
                  {d.chunkCount > 0 ? `${d.chunkCount} (${d.leafCount})` : '-'}
                </td>
                <td className="text-meta" style={{ maxWidth: 260 }}>
                  {d.ruleTrigger?.detail || (d.ruleScope ? `${d.ruleScope} 대기` : '-')}
                </td>
                <td>
                  <div className="row" style={{ gap: 4 }}>
                    <button
                      className="btn sm" title="재색인"
                      disabled={busy || EMBEDDING_IN_PROGRESS.includes(d.status)}
                      onClick={() => void reembed(d.id)}
                    >
                      <RefreshCw size={11} /> {d.status === 'FAILED' ? '재처리' : '재색인'}
                    </button>
                    <span style={{ color: 'var(--border-strong)' }}>·</span>
                    <button
                      className="btn sm" disabled={busy}
                      style={{ color: 'var(--tone-red)', borderColor: 'var(--tone-red-bg)' }}
                      onClick={() => void remove(d)}
                    >
                      <Trash2 size={11} /> 삭제
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {!loading && visible.length === 0 && (
              <tr><td colSpan={7} className="text-meta" style={{ textAlign: 'center', padding: 32 }}>
                적재된 규정 문서가 없습니다. PDF를 업로드하면 AI가 검색할 수 있게 됩니다.
              </td></tr>
            )}
            {loading && (
              <tr><td colSpan={7} className="text-meta" style={{ textAlign: 'center', padding: 32 }}>불러오는 중…</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="note" style={{ marginTop: 16 }}>
        ※ 업로드된 문서는 <b>파싱 → 조(條) 단위 청킹 → 임베딩 → Chroma 적재</b>를 거칩니다(문서당 수십 초~수 분).
        적재된 조항은 Rule Agent의 RAG 검색과 Risk Review의 내규검증 근거로 인용됩니다.
        <br />
        ※ 적재 후 <b>룰 자동 생성은 아직 개발 중</b>입니다 — 지금은 룰 콘솔 → 신규 그래프 생성 →
        「규정 문서에서 생성」으로 직접 실행하세요.
      </div>
    </>
  )
}

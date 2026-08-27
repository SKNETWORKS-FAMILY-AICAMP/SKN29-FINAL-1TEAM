// 규정 문서 관리 — S-05, 작업 중심으로 재구성(v5).
//
// 예전엔 문서 메타·상태·별표·안내문·AI 설명·조항 원문·연결 규칙·버튼이 한 화면에
// 세로로 계속 쌓여 글자가 많고 지금 뭘 해야 하는지 잘 안 보였다. 지금은 세 가지를
// 빨리 알 수 있게 나눴다: ① 어떤 문서를 보고 있나(헤더) ② 지금 확인할 게 뭔가(탭+목록)
// ③ 무엇을 해야 하나(상세 패널의 상태·버튼). 실제 목록·상세 렌더링은
// `DocumentWorkspace`(조항)·`DecisionCasePanel`(사례)에 있고, 여기는 데이터 로딩과
// 문서/폴더 선택만 맡는다.
//
// 업로드는 **접수만** 하고 파싱·청킹·임베딩·적재는 백그라운드로 돈다(문서당 수십 초~분).
// 그래서 진행 중인 문서가 있을 때만 목록을 폴링한다.
import { Suspense, lazy, useCallback, useEffect, useMemo, useState } from 'react'
import { AlertTriangle, Scale, Search, Upload } from 'lucide-react'
import { endpoints } from '../api/client'
import {
  EMBEDDING_IN_PROGRESS,
  type AxisOption, type FolderDoc, type PolicyClause, type PolicyDocument,
  type PolicyFolder, type PolicyTableProposal,
} from '../types/domain'
import { SkeletonLines } from '../components/ui/Skeleton'
import { FolderTree } from './policy-docs/FolderTree'
import { DecisionCasePanel, monthLabel, useDecisionCases } from './policy-docs/DecisionCasePanel'
import { UploadModal, type UploadInput } from './policy-docs/UploadModal'
import { DocumentWorkspace } from './policy-docs/DocumentWorkspace'
import './policy-docs/policy-docs.css'

// pdfjs-dist는 무겁다(수백KB) — 열 때만 불러온다. 목록·조항 화면은 대부분의 방문에서
// 원본 뷰어를 아예 열지 않으므로, 정적 import로 두면 아무도 안 쓰는 무게를 매번 진다.
const DocumentRenderModal = lazy(() => import('./policy-docs/DocumentRenderModal').then((m) => ({ default: m.DocumentRenderModal })))

const POLL_MS = 4000

export function PolicyDocuments() {
  const [folders, setFolders] = useState<PolicyFolder[]>([])
  const [unfiled, setUnfiled] = useState<FolderDoc[]>([])
  const [docs, setDocs] = useState<PolicyDocument[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [clauses, setClauses] = useState<PolicyClause[]>([])
  const [proposals, setProposals] = useState<PolicyTableProposal[]>([])
  const [axisOptions, setAxisOptions] = useState<AxisOption[]>([])
  //  제안 하나에 대한 실패 사유 — 카드 안에서 보여주려고 id와 함께 들고 있는다.
  const [proposalError, setProposalError] = useState<{ id: number; message: string } | null>(null)
  const [query, setQuery] = useState('')
  const [uploadOpen, setUploadOpen] = useState(false)
  const [rendering, setRendering] = useState(false)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const selected = docs.find((d) => d.id === selectedId) ?? null

  //  「결정 사례」는 문서 트리와 **다른 종류**라 선택 상태를 따로 둔다(문서 id와 섞으면
  //  둘 중 무엇이 선택됐는지 화면이 매번 되물어야 한다). ''=전체 월.
  const [caseMonth, setCaseMonth] = useState<string | null>(null)
  const casesOpen = caseMonth !== null
  const cases = useDecisionCases(caseMonth ?? '', casesOpen)

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

  const loadClauses = useCallback(async (id: string) => {
    try {
      const [clauseRes, tableRes] = await Promise.all([
        endpoints.policyClauses(id),
        // 별표는 조에 속하지 않아 조항 목록에 안 뜬다 — 임계값의 원천인데 화면에서
        // 보이지 않던 자리라, 조항과 **함께** 가져온다.
        endpoints.policyTableProposals(id),
      ])
      setClauses(clauseRes.data as PolicyClause[])
      setProposals(tableRes.data.proposals ?? [])
      setAxisOptions(tableRes.data.axisOptions ?? [])
    } catch {
      setClauses([]); setProposals([])
      setError('조항을 불러오지 못했습니다.')
    }
  }, [])

  useEffect(() => {
    if (!selectedId) { setClauses([]); setProposals([]); return }
    void loadClauses(selectedId)
  }, [selectedId, loadClauses])

  const upload = async (input: UploadInput) => {
    setBusy(true); setError('')
    const form = new FormData()
    form.append('file', input.file)
    form.append('title', input.title)
    if (input.profileHint) form.append('profileHint', input.profileHint)
    if (input.ruleScope) form.append('ruleScope', input.ruleScope)
    if (input.folderId != null) form.append('folderId', String(input.folderId))
    try {
      const { data } = await endpoints.uploadPolicyDoc(form)
      await load()
      setSelectedId(String(data.id))
      setUploadOpen(false)
    } catch (exc) {
      setError((exc as { response?: { data?: { detail?: string } } }).response?.data?.detail
        || '업로드에 실패했습니다.')
    } finally {
      setBusy(false)
    }
  }

  /** 폴더·이동 조작은 전부 서버가 정본이라, 성공하면 트리를 다시 읽는다. */
  const treeActions = {
    // 문서를 고르면 사례 보기를 끈다 — 오른쪽 패널의 주인은 하나여야 한다.
    onSelect: (id: string | null) => { setCaseMonth(null); setSelectedId(id) },
    onCreateFolder: (name: string, parentId: number | null) =>
      withBusy(async () => { await endpoints.createPolicyFolder(name, parentId); await load() },
        '폴더를 만들지 못했습니다.'),
    onRenameFolder: (id: number, name: string) =>
      withBusy(async () => { await endpoints.renamePolicyFolder(id, name); await load() },
        '이름을 바꾸지 못했습니다.'),
    onDeleteFolder: (id: number) =>
      withBusy(async () => { await endpoints.deletePolicyFolder(id); await load() },
        '폴더를 삭제하지 못했습니다.'),
    onMoveDoc: (docId: string, folderId: number | null) =>
      withBusy(async () => { await endpoints.movePolicyDoc(docId, folderId); await load() },
        '문서를 옮기지 못했습니다.'),
  }

  const withBusy = async (fn: () => Promise<unknown>, fail: string) => {
    setBusy(true); setError('')
    try {
      await fn()
    } catch (exc) {
      // 서버가 이유를 주면 그걸 쓴다 — "비어 있지 않습니다(문서 3건)"처럼 다음 행동이 보인다.
      const detail = (exc as { response?: { data?: { detail?: string } } }).response?.data?.detail
      setError(detail || fail)
    } finally {
      setBusy(false)
    }
  }

  const decide = (clauseId: number, decision: 'SKIP' | 'RESET', reason?: string) =>
    withBusy(async () => {
      if (!selectedId) return
      await endpoints.decidePolicyClause(selectedId, clauseId, decision, reason)
      await Promise.all([loadClauses(selectedId), load()])
    }, '결정을 저장하지 못했습니다.')

  // 별표 제안 — 수정 저장 / 승인·반려. 결정 뒤에는 다시 읽는다: 승인은 `PolicyTable`을
  // 만들고 `problems`도 서버가 다시 계산하므로, 화면이 낙관적으로 그리면 어긋난다.
  const saveProposal = (id: number, patch: Record<string, unknown>) =>
    withBusy(async () => {
      if (!selectedId) return
      await endpoints.updatePolicyTableProposal(selectedId, id, patch)
      await loadClauses(selectedId)
    }, '별표 수정을 저장하지 못했습니다.')

  //  ⚠️ 결정 실패는 **패널 안에서** 보여준다. 페이지 상단 배너로만 띄우면 스크롤해
  //     내려간 상태에서 승인을 누른 사람에게는 화면 밖에서 뜬다.
  const decideProposal = async (
    id: number, action: 'APPROVE' | 'REJECT', note: string, patch?: Record<string, unknown>,
  ) => {
    if (!selectedId) return
    setBusy(true); setProposalError(null)
    try {
      await endpoints.decidePolicyTableProposal(selectedId, id, action, note, patch)
      await loadClauses(selectedId)
    } catch (exc) {
      const detail = (exc as { response?: { data?: { detail?: string } } }).response?.data?.detail
      setProposalError({ id, message: detail || '별표 결정을 저장하지 못했습니다.' })
    } finally {
      setBusy(false)
    }
  }

  // 조항 하나로 룰 생성. **AI가 제외로 본 조항에서도 부를 수 있다** — 분류는 제안이다.
  // 생성물의 편집·승인은 룰 콘솔이 주인이라, 여기서는 만들고 링크만 안내한다.
  const createRule = (clause: PolicyClause) =>
    withBusy(async () => {
      if (!selectedId || !selected) return
      const { data } = await endpoints.generateRuleFromClause(selectedId, clause.id, selected.ruleScope)
      const graphId = data?.graph?.graph_id
      if (graphId) {
        setError('')
        window.location.href = `/rules?graph=${graphId}`
        return
      }
      // 생성이 실패해도 사유를 그대로 보여준다(NO_SOURCE·검증 소진 등).
      setError(data?.detail || '규칙을 만들지 못했습니다 — 룰 콘솔에서 직접 만들어 주세요.')
    }, '규칙 생성에 실패했습니다.')

  const kpi = useMemo(() => ({
    total: docs.length,
    busy: docs.filter((d) => EMBEDDING_IN_PROGRESS.includes(d.status)).length,
    review: docs.reduce((sum, d) => sum + (d.reviewCount || 0), 0),
  }), [docs])

  return (
    <>
      <div className="hero-band pd-hero">
        <div className="page-head row" style={{ justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            <span className="screen-id">규정문서</span>
            <h1>규정 문서 관리</h1>
            <div className="sub">회사 규정을 등록하면 AI가 조항을 정리하고, 자동 판단 규칙과 연결해드려요.</div>
          </div>
          {/* 문서명·유형·폴더·비용분류는 업로드 모달에서 함께 고른다 — 올린 뒤 다시 손볼 일이 없게. */}
          <button className="btn primary" disabled={busy} onClick={() => setUploadOpen(true)}>
            <Upload size={14} /> {busy ? '처리 중…' : '문서 업로드'}
          </button>
        </div>

        {/* 예전의 4칸 KPI 카드 대신 한 줄 요약 — 값이 0인 상태는 아예 안 보여준다.
            지금 처리해야 하는 「확인 필요」만 눈에 띄게 강조한다. */}
        <div className="pd-status-row">
          <span>등록 문서 <b>{kpi.total}</b>건</span>
          {kpi.busy > 0 && <span className="pd-status-pill busy">분석 중 {kpi.busy}건</span>}
          {kpi.review > 0 && <span className="pd-status-pill review">확인 필요 {kpi.review}건</span>}
        </div>
      </div>

      {error && (
        <div className="page-inner">
          <div className="note error" style={{ marginTop: 16 }}>
            <AlertTriangle size={13} style={{ verticalAlign: -2, marginRight: 4 }} />{error}
          </div>
        </div>
      )}

      <div className="page-inner">
        <div className={'pd-shell' + (selectedId || casesOpen ? ' has-selection' : '')}>
          <aside className="card pd-tree-pane">
            <div className="pd-search">
              <Search size={13} color="var(--muted)" />
              <input placeholder="폴더나 문서 찾기" value={query} onChange={(e) => setQuery(e.target.value)} />
            </div>
            {loading
              ? <div style={{ padding: 16 }}><SkeletonLines rows={5} /></div>
              : (
                <>
                  <FolderTree folders={folders} unfiled={unfiled} selectedId={selectedId}
                              query={query} actions={treeActions} busy={busy} />
                  <CaseTree
                    months={cases.months}
                    selected={caseMonth}
                    onSelect={(m) => { setCaseMonth(m); setSelectedId(null) }}
                  />
                  {/* 문서 행에도 같은 안내가 title 툴팁으로 있지만(FolderTree.tsx),
                      호버해야만 보여 놓치기 쉽다 — 트리 하단에 한 줄로 짧게 남긴다.
                      문서가 있을 때만: 옮길 게 없으면 필요 없는 안내다. */}
                  {(folders.length > 0 || unfiled.length > 0) && (
                    <div className="pd-tree-hint text-meta">문서를 드래그하면 폴더로 옮길 수 있어요</div>
                  )}
                </>
              )}
          </aside>

          <div className="pd-content-pane">
            {casesOpen ? (
              <div className="card pd-cases-card">
                <button type="button" className="pd-back-to-tree" onClick={() => setCaseMonth(null)}>← 문서함</button>
                <DecisionCasePanel
                  month={caseMonth ?? ''}
                  months={cases.months}
                  cases={cases.cases}
                  total={cases.total}
                  loading={cases.loading}
                />
              </div>
            ) : !selected ? (
              <div className="card pd-empty-card">
                <div className="pd-empty">
                  <div style={{ fontSize: 40 }} aria-hidden>📄</div>
                  <b>왼쪽에서 문서를 선택하면 상세 정보를 볼 수 있어요</b>
                  <p className="text-meta">
                    문서를 열면 어떤 조항이 자동 규칙으로 연결됐는지, 어떤 조항을 확인해야 하는지 한눈에 볼 수 있어요.
                  </p>
                </div>
              </div>
            ) : (
              <>
                <button type="button" className="pd-back-to-tree" onClick={() => setSelectedId(null)}>← 문서함</button>
                <DocumentWorkspace
                  doc={selected}
                  clauses={clauses}
                  proposals={proposals}
                  axisOptions={axisOptions}
                  busy={busy}
                  proposalError={proposalError}
                  onOpenRender={() => setRendering(true)}
                  onReembed={() => void withBusy(async () => {
                    await endpoints.reembedPolicyDoc(selected.id); await load()
                  }, '재색인을 시작하지 못했습니다.')}
                  onDelete={() => {
                    if (!window.confirm(`"${selected.title}"을 삭제하시겠습니까?\n(이미 적재된 벡터는 재색인 전까지 남습니다)`)) return
                    void withBusy(async () => {
                      await endpoints.deletePolicyDoc(selected.id)
                      setSelectedId(null); await load()
                    }, '삭제하지 못했습니다.')
                  }}
                  onDecideClause={decide}
                  onCreateRule={createRule}
                  onSaveProposal={saveProposal}
                  onDecideProposal={decideProposal}
                />
              </>
            )}
          </div>
        </div>
      </div>

      {uploadOpen && (
        <UploadModal
          folders={folders}
          // 문서를 보고 있으면 그 문서가 있는 폴더를 기본값으로 — 대개 같은 자리에 올린다.
          defaultFolderId={selected?.folderId ?? null}
          busy={busy}
          onClose={() => setUploadOpen(false)}
          onSubmit={(input) => void upload(input)}
        />
      )}

      {rendering && selected && (
        <Suspense fallback={
          <div className="modal-backdrop" onClick={() => setRendering(false)}>
            <div className="text-meta" style={{ color: 'var(--sidebar-text)', margin: 'auto' }}>뷰어를 불러오는 중…</div>
          </div>
        }>
          <DocumentRenderModal
            doc={selected}
            onClose={() => setRendering(false)}
            onViewClauses={() => setRendering(false)}
          />
        </Suspense>
      )}
    </>
  )
}

/** 트리 하단의 「결정 사례」 — 문서와 다른 종류라 폴더 트리와 나란히 둔다. */
function CaseTree({ months, selected, onSelect }: {
  months: { key: string; count: number; indexed: number }[]
  selected: string | null
  onSelect: (month: string | null) => void
}) {
  const total = months.reduce((s, m) => s + m.count, 0)
  return (
    <div style={{ borderTop: '1px solid var(--border)', marginTop: 8, paddingTop: 8 }}>
      <button
        type="button"
        className="pd-node"
        style={{ width: '100%', fontWeight: 700, ...(selected === '' ? { background: 'var(--primary-soft)' } : {}) }}
        onClick={() => onSelect(selected === null ? '' : null)}
      >
        <Scale size={13} /> 결정 사례
        <span className="text-meta" style={{ marginLeft: 'auto' }}>{total}</span>
      </button>
      {selected !== null && (
        <div style={{ paddingLeft: 18 }}>
          {months.length === 0 ? (
            <div className="text-meta" style={{ padding: '6px 8px' }}>아직 기록된 사례가 없습니다.</div>
          ) : months.map((m) => (
            <button
              key={m.key}
              type="button"
              className="pd-node"
              style={{ width: '100%', ...(selected === m.key ? { background: 'var(--primary-soft)' } : {}) }}
              onClick={() => onSelect(m.key)}
            >
              {monthLabel(m.key)}
              <span className="text-meta" style={{ marginLeft: 'auto' }}>
                {m.count}
                {/* 미적재는 검색에 안 잡힌다 — 숨기면 "왜 인용이 안 되지"를 아무도 못 본다. */}
                {m.indexed < m.count && ` (미적재 ${m.count - m.indexed})`}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
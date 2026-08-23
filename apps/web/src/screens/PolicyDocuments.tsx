// 규정 문서 관리 (목업 S-05 v4 ③ 폴더보기 - 문서 미리보기)
//
// 좌: 폴더 트리 / 우: 선택한 문서의 조(條) 단위 미리보기.
// 목업 하단의 "확인 필요(3)" 노란 박스는 제외했다 — 같은 정보가 우측 조항 카드에 이미
// 있고(확인 필요 배지 + 결정 버튼), 두 곳에서 같은 결정을 내릴 수 있으면 어느 쪽이
// 최신인지 모르게 된다.
//
// 업로드는 **접수만** 하고 파싱·청킹·임베딩·적재는 백그라운드로 돈다(문서당 수십 초~분).
// 그래서 진행 중인 문서가 있을 때만 목록을 폴링한다.
import { Suspense, lazy, useCallback, useEffect, useMemo, useState } from 'react'
import { AlertTriangle, FileText, RefreshCw, Scale, Search, Trash2, Upload } from 'lucide-react'
import { endpoints } from '../api/client'
import {
  EMBEDDING_IN_PROGRESS, EMBEDDING_STATUS_META, PRIORITY_META,
  type AxisOption, type FolderDoc, type PolicyClause, type PolicyDocument,
  type PolicyFolder, type PolicyTableProposal,
} from '../types/domain'
import { KpiCard } from '../components/ui/KpiCard'
import { FolderTree } from './policy-docs/FolderTree'
import { DecisionCasePanel, monthLabel, useDecisionCases } from './policy-docs/DecisionCasePanel'
import { UploadModal, type UploadInput } from './policy-docs/UploadModal'
import { ClauseCard } from './policy-docs/ClauseAccordion'
import { TableProposalCard } from './policy-docs/TableProposalPanel'
import './policy-docs/policy-docs.css'

// pdfjs-dist는 무겁다(수백KB) — 열 때만 불러온다. 목록·조항 화면은 대부분의 방문에서
// 원본 뷰어를 아예 열지 않으므로, 정적 import로 두면 아무도 안 쓰는 무게를 매번 진다.
const DocumentRenderModal = lazy(() => import('./policy-docs/DocumentRenderModal').then((m) => ({ default: m.DocumentRenderModal })))

const POLL_MS = 4000
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
  const [proposals, setProposals] = useState<PolicyTableProposal[]>([])
  const [axisOptions, setAxisOptions] = useState<AxisOption[]>([])
  // 조항이 수십 개인 문서에서 "지금 할 일"만 보기 위한 필터. 기본은 전체 —
  // 필터를 기본값으로 켜두면 안 보이는 조항이 있다는 걸 아무도 모른다.
  const [onlyActionable, setOnlyActionable] = useState(false)
  const [expanded, setExpanded] = useState<Set<number>>(new Set())
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

  // 선택한 문서의 조항. 첫 '확인 필요' 조항을 펼쳐 둔다 — 담당자가 할 일이 그것이다.
  const loadClauses = useCallback(async (id: string) => {
    try {
      const [clauseRes, tableRes] = await Promise.all([
        endpoints.policyClauses(id),
        // 별표는 조에 속하지 않아 조항 목록에 안 뜬다 — 임계값의 원천인데 화면에서
        // 보이지 않던 자리라, 조항과 **함께** 가져온다.
        endpoints.policyTableProposals(id),
      ])
      const rows = clauseRes.data as PolicyClause[]
      setClauses(rows)
      setProposals(tableRes.data.proposals ?? [])
      setAxisOptions(tableRes.data.axisOptions ?? [])
      // 담당자가 먼저 볼 것 = 자동 생성됐거나 1순위인 확인 필요 조항. 분류가 없으면
      // 예전대로 첫 '확인 필요'를 편다.
      const first = rows.find((c) => c.ruleStatus === 'NEEDS_REVIEW' && c.triagePriority === 'P1')
        ?? rows.find((c) => c.ruleStatus === 'NEEDS_REVIEW')
      setExpanded(new Set(first ? [first.id] : []))
    } catch {
      setClauses([]); setProposals([])
      setError('조항을 불러오지 못했습니다.')
    }
  }, [])

  useEffect(() => {
    if (!selectedId) { setClauses([]); return }
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

  const decideProposal = (
    id: number, action: 'APPROVE' | 'REJECT', note: string, patch?: Record<string, unknown>,
  ) =>
    withBusy(async () => {
      if (!selectedId) return
      await endpoints.decidePolicyTableProposal(selectedId, id, action, note, patch)
      await loadClauses(selectedId)
    }, '별표 결정을 저장하지 못했습니다.')

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

  // 우선순위 순으로 다시 세운다 — 순위를 보여주기만 하고 순서를 안 바꾸면 목록은
  // 여전히 조 번호 순이라 아무 도움이 안 된다. 같은 순위면 원래 조 순서를 지킨다.
  const orderedClauses = useMemo(() => {
    const rows = onlyActionable
      ? clauses.filter((c) => c.ruleStatus === 'NEEDS_REVIEW' && c.triagePriority !== 'SKIP')
      : clauses
    return [...rows].sort((a, b) =>
      PRIORITY_META[a.triagePriority].rank - PRIORITY_META[b.triagePriority].rank)
  }, [clauses, onlyActionable])

  const triaged = clauses.some((c) => c.triagePriority)
  const pendingTables = proposals.filter((p) => p.status === 'PENDING').length

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
      <div className="hero-band">
        <div className="page-head row" style={{ justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            <span className="screen-id">규정문서</span>
            <h1>규정 문서 관리</h1>
            <div className="sub">회사 규정을 등록하면 AI가 조항을 정리하고, 자동 판단 규칙과 연결해드려요.</div>
          </div>
          {/* 문서명·유형·폴더·비용분류는 업로드 모달에서 함께 고른다 — 올린 뒤 다시 손볼 일이 없게. */}
          <button className="btn primary" disabled={busy} onClick={() => setUploadOpen(true)}>
            <Upload size={14} /> {busy ? '처리 중…' : '+ 문서 업로드'}
          </button>
        </div>

        <div className="kpi-grid" style={{ gridTemplateColumns: 'repeat(4, 1fr)' }}>
          <KpiCard flat label="등록한 문서" value={kpi.total} unit="건" />
          <KpiCard flat label="분석 완료" value={kpi.done} unit="건" />
          <KpiCard flat warn={kpi.busy > 0} label="분석 중" value={kpi.busy} unit="건" />
          <KpiCard flat warn={kpi.review > 0} label="확인이 필요한 조항" value={kpi.review} unit="개" />
        </div>
      </div>

      {error && (
        <div className="page-inner">
          <div className="note" style={{ marginTop: 16, color: 'var(--tone-red)', borderColor: 'var(--tone-red-bg)' }}>
            <AlertTriangle size={13} style={{ verticalAlign: -2, marginRight: 4 }} />{error}
          </div>
        </div>
      )}

      <div className="page-inner">
      <div className="pd-layout">
        <aside className="card pd-tree">
          <div className="pd-search">
            <Search size={13} color="var(--muted)" />
            <input placeholder="폴더나 문서 찾기" value={query} onChange={(e) => setQuery(e.target.value)} />
          </div>
          {loading
            ? <div className="text-meta" style={{ padding: 16 }}>불러오는 중…</div>
            : (
              <>
                <FolderTree folders={folders} unfiled={unfiled} selectedId={selectedId}
                            query={query} actions={treeActions} busy={busy} />
                <CaseTree
                  months={cases.months}
                  selected={caseMonth}
                  onSelect={(m) => { setCaseMonth(m); setSelectedId(null) }}
                />
              </>
            )}
        </aside>

        <section className="card pd-preview">
          {casesOpen ? (
            <DecisionCasePanel
              month={caseMonth ?? ''}
              months={cases.months}
              cases={cases.cases}
              total={cases.total}
              loading={cases.loading}
            />
          ) : !selected ? (
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
                  {/* 문서 렌더링(모달) — 페이지 단위 원본 보기. 적재 상태와 무관하게 열 수 있다:
                      파싱이 실패했을 때야말로 원본을 봐야 한다. 새 탭·다운로드는 모달 안에 있다. */}
                  <button className="btn sm" disabled={!selected.fileName}
                          title={selected.fileName ? '문서를 페이지 단위로 봅니다' : '원본 파일이 없습니다'}
                          onClick={() => setRendering(true)}>
                    <FileText size={11} /> 원본 보기
                  </button>
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
                {selected.profile && (
                  // 유형이 컬렉션을 정하고, 컬렉션이 "판정에 인용되는가"를 정한다.
                  // 사람이 지정한 값이면 자동 감지가 아니라는 것도 같이 밝힌다.
                  <> · {selected.profileLabel || selected.profile}
                    {selected.profileHint && <span className="pd-badge gray" style={{ marginLeft: 4 }}>지정</span>}
                  </>
                )}
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

              {/* ── 별표(한도표) — 조에 속하지 않아 조항 목록에는 안 뜬다. 임계값의
                     원천이라 위에 둔다: 별표를 승인하기 전에 만든 룰은 그 값을 참조해도
                     미해소로 떨어져 전건 검토가 된다. */}
              {proposals.length > 0 && (
                <>
                  <div className="pd-section-title">
                    별표 — 판정 임계값
                    {pendingTables > 0 && (
                      <span className="pd-badge" style={{ marginLeft: 8, background: 'var(--tone-amber-bg)', color: 'var(--tone-amber)' }}>
                        승인 대기 {pendingTables}
                      </span>
                    )}
                  </div>
                  <div className="note">
                    승인하면 이 표의 값이 <b>모든 정산 판정</b>에 쓰입니다. 표 원문과 값을 대조한 뒤 눌러주세요.
                  </div>
                  {proposals.map((proposal) => (
                    <TableProposalCard
                      key={proposal.id}
                      proposal={proposal}
                      axisOptions={axisOptions}
                      busy={busy}
                      onSave={(patch) => void saveProposal(proposal.id, patch)}
                      onDecide={(action, note, patch) =>
                        void decideProposal(proposal.id, action, note, patch)}
                    />
                  ))}
                </>
              )}

              <div className="pd-section-title row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
                <span>조항 {triaged && <span className="text-meta">· 우선순위 순</span>}</span>
                {triaged && (
                  <label className="row text-meta" style={{ gap: 6, alignItems: 'center', fontWeight: 400 }}>
                    <input type="checkbox" checked={onlyActionable}
                           onChange={(e) => setOnlyActionable(e.target.checked)} />
                    규칙이 필요한 조항만
                  </label>
                )}
              </div>

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
              {/* 필터로 비었을 때와 원래 없을 때를 구분한다 — 같은 빈 화면으로 두면
                  "규칙 만들 게 없다"와 "필터를 켜뒀다"가 섞인다. */}
              {clauses.length > 0 && orderedClauses.length === 0 && (
                <div className="text-meta" style={{ padding: 16 }}>
                  규칙이 필요한 조항이 없어요. 필터를 끄면 전체 {clauses.length}개가 보입니다.
                </div>
              )}

              {orderedClauses.map((clause) => (
                <ClauseCard
                  key={clause.id}
                  clause={clause}
                  expanded={expanded.has(clause.id)}
                  onToggle={() => toggle(clause.id)}
                  busy={busy}
                  onSkip={(reason) => void decide(clause.id, 'SKIP', reason)}
                  onReset={() => void decide(clause.id, 'RESET')}
                  // 생성은 서버가 조항에서 질의를 만들어 돌린다(화면마다 다른 질의가
                  // 나가지 않게). 만들어진 그래프의 편집·승인은 룰 콘솔이 주인이라
                  // 생성 직후 그쪽으로 넘긴다 — 여기에 두 번째 편집 화면을 만들지 않는다.
                  onCreateRule={() => void createRule(clause)}
                />
              ))}
            </>
          )}
        </section>
      </div>

      <div className="note" style={{ marginTop: 16 }}>
        등록된 문서 {kpi.total}개 · {folders.length}개 폴더로 정리되어 있어요.
        문서는 드래그해서 폴더로 옮길 수 있고, 폴더는 비어 있을 때만 삭제됩니다.
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

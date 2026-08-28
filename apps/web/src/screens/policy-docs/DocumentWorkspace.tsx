// 선택한 문서 하나의 작업 공간(S-05) — 조항·별표를 "목록에서 고르고 상세에서 처리"하는
// 가운데·오른쪽 두 칸. 예전엔 조항·별표가 한 세로줄에 전부 펼쳐진 채 쌓여, 문서 하나가
// 조항 20개짜리면 스크롤이 화면 몇 장 분량이었다. 지금은:
//   ① 문서 헤더 — 이름·상태·꼭 필요한 메타만, 나머지는 "문서 정보" 탭으로
//   ② 탭 — 확인 필요 / 전체 조항 / 별표 / 문서 정보. 다른 조항이 있다는 사실이
//      가려지면 안 되므로 "확인 필요"만 남기지 않고 "전체 조항"을 따로 둔다.
//   ③ 목록(가운데) → 상세(오른쪽) — 목록에서 고른 항목 하나만 상세에 집중해서 보여준다.
//
// 좁은 화면에서는 이 두 칸을 세로로 쌓고, 상세를 열면 목록 대신 그것만 보여준다
// (`.pd-workspace.has-active`, policy-docs.css) — 3단을 억지로 유지하지 않는다.
import { type ReactNode, useEffect, useMemo, useRef, useState } from 'react'
import { AlertTriangle, FileText, MoreVertical, RefreshCw, Search, Trash2 } from 'lucide-react'
import {
  EMBEDDING_IN_PROGRESS, EMBEDDING_STATUS_META, PRIORITY_META,
  type AxisOption, type PolicyClause, type PolicyDocument, type PolicyTableProposal,
} from '../../types/domain'
import { ClauseDetail, ClauseListRow, clauseMatchesQuery } from './ClauseAccordion'
import { TableProposalDetail, TableProposalListRow, orderProposals } from './TableProposalPanel'

const fmtSize = (bytes: number) =>
  bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)}MB` : `${Math.max(1, Math.round(bytes / 1024))}KB`

// 판정 근거로 인용되는 컬렉션. org_docs(조직도·직급체계)는 여기 없다 — 결재선의 SoR은
// 문서가 아니라 Django이고, 조직도가 정산 판정 근거로 인용되면 안 된다.
const JUDGEMENT_COLLECTIONS = ['policy_docs', 'case_history', 'tax_refs']

type Tab = 'REVIEW' | 'ALL' | 'TABLES' | 'INFO'

/** 우선순위 순 — 정렬 순서가 곧 담당자의 작업 순서다. */
function byPriority(rows: PolicyClause[]): PolicyClause[] {
  return [...rows].sort((a, b) => PRIORITY_META[a.triagePriority].rank - PRIORITY_META[b.triagePriority].rank)
}

/** 더보기 메뉴 — 재색인·삭제처럼 자주 안 쓰는 문서 작업을 여기 모은다. 자주 쓰는
 *  「원본 보기」는 밖에 그대로 둔다(검토 중 빈번히 눌린다). 바깥을 클릭하거나 안의
 *  버튼을 누르면 닫는다(네이티브 `<details>`는 둘 다 저절로 안 닫혀서 직접 처리). */
function MoreMenu({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLDetailsElement>(null)
  useEffect(() => {
    const onDocClick = (e: MouseEvent) => {
      if (ref.current?.open && !ref.current.contains(e.target as Node)) ref.current.open = false
    }
    document.addEventListener('click', onDocClick)
    return () => document.removeEventListener('click', onDocClick)
  }, [])
  return (
    <details className="pd-more" ref={ref}
              onClick={(e) => {
                if ((e.target as HTMLElement).closest('button')) {
                  requestAnimationFrame(() => { if (ref.current) ref.current.open = false })
                }
              }}>
      <summary className="btn sm" aria-label="더보기"><MoreVertical size={14} /></summary>
      <div className="pd-more-menu">{children}</div>
    </details>
  )
}

/** 적재 경고 배너 — 백엔드가 주는 문구(`doc.error`)는 최대 20건까지 줄바꿈으로 이어
 *  붙는 원본 로그라 그대로 쏟아내면 한 번에 문단 몇 줄이 된다. 문구 자체를 고치지
 *  않고(백엔드 정본), **첫 줄만 기본 노출**하고 나머지는 접어 둔다 — docling 모킹
 *  경고처럼 "켠 걸 잊으면 안 되는" 신호는 첫 줄에 이미 있다(§rag-ingestion). */
function DocErrorBanner({ doc }: { doc: PolicyDocument }) {
  const [open, setOpen] = useState(false)
  if (!doc.error) return null
  // 백엔드 문구가 이미 "⚠ "로 시작한다 — 아이콘과 겹치지 않게 선행 기호만 걷어낸다.
  const lines = doc.error.replace(/^[⚠️\s]+/, '').split('\n').filter(Boolean)
  const isMock = lines[0]?.includes('docling 모킹 모드')
  const heading = doc.status === 'FAILED' ? '적재 실패' : isMock ? '테스트 데이터로 적재됨' : '확인할 내용이 있어요'

  return (
    <div className={`note ${doc.status === 'FAILED' ? 'error' : 'caution'} pd-warn`}>
      <div className="pd-warn-head">
        <AlertTriangle size={13} style={{ flexShrink: 0 }} />
        <b>{heading}</b>
        {lines.length > 1 && (
          <button type="button" className="pd-warn-toggle" onClick={() => setOpen((v) => !v)}>
            {open ? '접기' : `자세히 (${lines.length})`}
          </button>
        )}
      </div>
      <div className="pd-warn-body">
        {(open ? lines : lines.slice(0, 1)).map((line, i) => <div key={i}>{line}</div>)}
      </div>
    </div>
  )
}

export function DocumentWorkspace({
  doc, clauses, proposals, axisOptions, busy, proposalError,
  onOpenRender, onReembed, onDelete,
  onDecideClause, onCreateRule, onSaveProposal, onDecideProposal,
}: {
  doc: PolicyDocument
  clauses: PolicyClause[]
  proposals: PolicyTableProposal[]
  axisOptions: AxisOption[]
  busy: boolean
  proposalError: { id: number; message: string } | null
  onOpenRender: () => void
  onReembed: () => void
  onDelete: () => void
  onDecideClause: (clauseId: number, decision: 'SKIP' | 'RESET', reason?: string) => void
  onCreateRule: (clause: PolicyClause) => void
  onSaveProposal: (id: number, patch: Record<string, unknown>) => void
  onDecideProposal: (id: number, action: 'APPROVE' | 'REJECT', note: string, patch?: Record<string, unknown>) => void
}) {
  const reviewClauses = useMemo(() => byPriority(clauses.filter((c) => c.ruleStatus === 'NEEDS_REVIEW')), [clauses])
  // 전체 조항은 기본이 **조 번호순**이다(백엔드가 이미 그 순서로 준다 — `PolicyClause.Meta.ordering`).
  // 우선순위순은 "다음에 뭘 처리할까"용 보조 정렬이라 토글로만 둔다 — 문서를 목차처럼
  // 훑어보려는 사람에게 조 순서를 뺏으면 안 된다.
  const [allOrder, setAllOrder] = useState<'article' | 'priority'>('article')
  const allClauses = useMemo(
    () => (allOrder === 'priority' ? byPriority(clauses) : clauses),
    [clauses, allOrder],
  )
  const [clauseQuery, setClauseQuery] = useState('')
  const visibleAllClauses = useMemo(
    () => (clauseQuery.trim() ? allClauses.filter((c) => clauseMatchesQuery(c, clauseQuery)) : allClauses),
    [allClauses, clauseQuery],
  )
  const orderedProposals = useMemo(() => orderProposals(proposals), [proposals])

  // 처음 여는 탭 — 확인할 게 있으면 그것부터, 없으면 전체를 보여준다(문서의 조항 수는
  // 목록 API 응답을 기다릴 필요 없이 `doc`에 이미 있다 — 탭을 고르는 데 조항 배열의
  // 도착을 기다리지 않아도 된다).
  const [tab, setTab] = useState<Tab>(() => (doc.reviewCount > 0 ? 'REVIEW' : doc.clauseCount > 0 ? 'ALL' : 'INFO'))
  const [activeClauseId, setActiveClauseId] = useState<number | null>(null)
  const [activeProposalId, setActiveProposalId] = useState<number | null>(null)

  // 조항이 하나도 없는 문서(별표만 있는 문서)는 위 초기값으로 'INFO'를 골랐을 텐데,
  // 별표가 도착하면 그쪽을 먼저 보여준다. 한 번만 보정한다 — 사용자가 그 뒤 직접
  // 고른 탭을 되돌리면 안 된다.
  const autoFixed = useRef(false)
  useEffect(() => {
    if (autoFixed.current) return
    if (doc.clauseCount === 0 && proposals.length > 0) setTab('TABLES')
    if (clauses.length > 0 || proposals.length > 0) autoFixed.current = true
  }, [clauses.length, proposals.length, doc.clauseCount])

  // 탭이 바뀌거나(예: 확인 필요 → 전체 조항) 방금 결정한 조항이 목록에서 빠지면
  // (확인 필요 탭에서 결정하면 그 조항은 더 이상 "확인 필요"가 아니다) 그 목록의
  // 첫 항목으로 옮겨간다 — 다음에 볼 것을 고르지 않아도 되게.
  useEffect(() => {
    if (tab === 'REVIEW' || tab === 'ALL') {
      const list = tab === 'REVIEW' ? reviewClauses : allClauses
      if (!list.some((c) => c.id === activeClauseId)) setActiveClauseId(list[0]?.id ?? null)
    } else if (tab === 'TABLES') {
      if (!orderedProposals.some((p) => p.id === activeProposalId)) setActiveProposalId(orderedProposals[0]?.id ?? null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, reviewClauses, allClauses, orderedProposals])

  const activeClause = (tab === 'REVIEW' ? reviewClauses : allClauses).find((c) => c.id === activeClauseId) ?? null
  const activeProposal = orderedProposals.find((p) => p.id === activeProposalId) ?? null
  const hasActive = tab === 'TABLES' ? activeProposal != null : tab !== 'INFO' && activeClause != null

  return (
    <>
      <section className="card pd-doc-card">
        <div className="pd-doc-head">
          <div className="pd-doc-head-title">
            <FileText size={15} style={{ flexShrink: 0, color: 'var(--muted)' }} />
            <b className="ellipsis" title={doc.title}>{doc.title}</b>
          </div>
          <div className="row" style={{ gap: 6, flexShrink: 0 }}>
            <span className="pd-badge green">{EMBEDDING_STATUS_META[doc.status]?.label}</span>
            {doc.superseded && <span className="pd-badge gray">이전 버전</span>}
          </div>
        </div>

        {/* 조항·별표 수는 바로 아래 탭 배지가 이미 보여준다 — 같은 화면 안에서
            두 번 세지 않는다. 여기는 문서를 구분하는 최소 정보만 남긴다. */}
        <div className="pd-doc-meta text-meta">
          {doc.version && <>버전 {doc.version} · </>}
          등록일 {doc.uploadedAt?.slice(0, 10)}
        </div>

        <div className="row" style={{ gap: 6, marginTop: 10 }}>
          <button className="btn sm" disabled={!doc.fileName}
                  title={doc.fileName ? '문서를 페이지 단위로 봅니다' : '원본 파일이 없습니다'}
                  onClick={onOpenRender}>
            <FileText size={11} /> 원본 보기
          </button>
          <MoreMenu>
            <button className="btn sm" disabled={busy || EMBEDDING_IN_PROGRESS.includes(doc.status)} onClick={onReembed}>
              <RefreshCw size={11} /> {doc.status === 'FAILED' ? '재처리' : '재색인'}
            </button>
            <button className="btn sm outline-danger" disabled={busy} onClick={onDelete}>
              <Trash2 size={11} /> 삭제
            </button>
          </MoreMenu>
        </div>

        <DocErrorBanner doc={doc} />

        <div className="pd-tabs">
          <button type="button" className={'btn' + (tab === 'REVIEW' ? ' primary' : '')} onClick={() => setTab('REVIEW')}>
            확인 필요 <span className="pd-tab-count">{reviewClauses.length}</span>
          </button>
          <button type="button" className={'btn' + (tab === 'ALL' ? ' primary' : '')} onClick={() => setTab('ALL')}>
            전체 조항 <span className="pd-tab-count">{clauses.length}</span>
          </button>
          {proposals.length > 0 && (
            <button type="button" className={'btn' + (tab === 'TABLES' ? ' primary' : '')} onClick={() => setTab('TABLES')}>
              별표 <span className="pd-tab-count">{proposals.length}</span>
            </button>
          )}
          <button type="button" className={'btn' + (tab === 'INFO' ? ' primary' : '')} onClick={() => setTab('INFO')}>
            문서 정보
          </button>
        </div>

        {/* 조 번호순↔우선순위순 전환 + 지금 위치 + 본문 검색은 "전체 조항"에서만 의미가
            있다 — "확인 필요"는 이미 작업 순서(우선순위)로 짧게 추려진 목록이라 여기서
            정렬·탐색을 또 고민하게 하지 않는다. */}
        {tab === 'ALL' && (
          <div className="pd-clause-toolbar">
            <div className="seg-toggle">
              <button type="button" className={allOrder === 'article' ? 'active' : ''} onClick={() => setAllOrder('article')}>
                조 번호순
              </button>
              <button type="button" className={allOrder === 'priority' ? 'active' : ''} onClick={() => setAllOrder('priority')}>
                AI 우선순위순
              </button>
            </div>
            <div className="search-box" style={{ flex: '0 1 220px' }}>
              <Search size={13} />
              <input
                placeholder="이 문서의 조항 내용 찾기"
                value={clauseQuery}
                onChange={(e) => setClauseQuery(e.target.value)}
              />
            </div>
            <span className="text-meta pd-clause-pos">
              지금 보는 위치 · <b>{activeClauseId && tab === 'ALL' ? allClauses.find((c) => c.id === activeClauseId)?.articleLabel ?? '—' : '—'}</b> / 전체 {clauses.length}개 조
            </span>
          </div>
        )}

        <div className={'pd-workspace' + (hasActive ? ' has-active' : '')}>
          <div className="pd-list-col">
            {tab === 'INFO' ? (
              <DocInfo doc={doc} />
            ) : tab === 'TABLES' ? (
              <ProposalList proposals={orderedProposals} activeId={activeProposalId} onSelect={setActiveProposalId} />
            ) : (
              <ClauseList
                doc={doc}
                list={tab === 'REVIEW' ? reviewClauses : visibleAllClauses}
                total={clauses.length} query={tab === 'ALL' ? clauseQuery : ''}
                activeId={activeClauseId} onSelect={setActiveClauseId}
              />
            )}
          </div>

          {tab !== 'INFO' && (
            <div className="pd-detail-col">
              {tab === 'TABLES' ? (
                activeProposal ? (
                  <TableProposalDetail
                    key={activeProposal.id}
                    proposal={activeProposal}
                    axisOptions={axisOptions}
                    busy={busy}
                    onSave={(patch) => onSaveProposal(activeProposal.id, patch)}
                    onDecide={(action, note, patch) => onDecideProposal(activeProposal.id, action, note, patch)}
                    error={proposalError?.id === activeProposal.id ? proposalError.message : ''}
                  />
                ) : (
                  <EmptyDetail text="왼쪽에서 별표를 고르면 여기에 상세가 보여요." />
                )
              ) : activeClause ? (
                <ClauseDetail
                  key={activeClause.id}
                  clause={activeClause}
                  query={tab === 'ALL' ? clauseQuery : ''}
                  busy={busy}
                  onSkip={(reason) => onDecideClause(activeClause.id, 'SKIP', reason)}
                  onReset={() => onDecideClause(activeClause.id, 'RESET')}
                  onCreateRule={() => onCreateRule(activeClause)}
                />
              ) : (
                <EmptyDetail text="왼쪽에서 조항을 고르면 여기에 상세가 보여요." />
              )}
              {(tab === 'REVIEW' || tab === 'ALL') && (
                <button type="button" className="pd-back-to-list" onClick={() => setActiveClauseId(null)}>
                  ← 목록으로
                </button>
              )}
              {tab === 'TABLES' && (
                <button type="button" className="pd-back-to-list" onClick={() => setActiveProposalId(null)}>
                  ← 목록으로
                </button>
              )}
            </div>
          )}
        </div>
      </section>
    </>
  )
}

function EmptyDetail({ text }: { text: string }) {
  return <div className="pd-empty" style={{ padding: '48px 16px' }}><p className="text-meta">{text}</p></div>
}

function ClauseList({ doc, list, total, query, activeId, onSelect }: {
  doc: PolicyDocument; list: PolicyClause[]; total: number; query: string
  activeId: number | null; onSelect: (id: number) => void
}) {
  if (EMBEDDING_IN_PROGRESS.includes(doc.status)) {
    return <div className="text-meta" style={{ padding: 16 }}>문서를 분석하고 있어요. 끝나면 조항이 여기에 나타납니다.</div>
  }
  if (total === 0) {
    return <div className="text-meta" style={{ padding: 16 }}>조 단위로 인식된 조항이 없어요. 표·별표만 있는 문서이거나 파싱이 실패했을 수 있어요.</div>
  }
  if (list.length === 0 && query.trim()) {
    return <div className="text-meta" style={{ padding: 16 }}>"{query.trim()}"와 일치하는 조항이 없어요.</div>
  }
  if (list.length === 0) {
    // 확인 필요 탭이 비었을 때 — 필터로 비었을 뿐이라는 걸 분명히 한다("전체 조항"이 사라진 게 아니다).
    return <div className="text-meta" style={{ padding: 16 }}>확인할 조항이 없어요. 전체 {total}개는 「전체 조항」 탭에서 볼 수 있어요.</div>
  }
  return (
    <div className="pd-list-scroll">
      {list.map((clause) => (
        <ClauseListRow key={clause.id} clause={clause} active={clause.id === activeId} query={query} onSelect={() => onSelect(clause.id)} />
      ))}
    </div>
  )
}

function ProposalList({ proposals, activeId, onSelect }: {
  proposals: PolicyTableProposal[]; activeId: number | null; onSelect: (id: number) => void
}) {
  return (
    <div className="pd-list-scroll">
      {/* 문서마다 항상 같은 고정 안내문 — 캡션 한 줄로 낮춘다(예전엔 항상 뜨는 박스였다). */}
      <div className="text-meta" style={{ padding: '4px 2px 10px' }}>
        승인하면 이 표의 값이 모든 정산 판정에 쓰여요.
      </div>
      {proposals.map((proposal) => (
        <TableProposalListRow key={proposal.id} proposal={proposal} active={proposal.id === activeId}
                               onSelect={() => onSelect(proposal.id)} />
      ))}
    </div>
  )
}

/** 「문서 정보」 탭 — 파일 크기·컬렉션·profile 원본 값 등, 감사·오류 확인에는 필요하지만
 *  평소 결정에는 필요 없는 기술 정보를 여기 모은다(메인 화면에서는 지웠다). */
function DocInfo({ doc }: { doc: PolicyDocument }) {
  const rows: [string, ReactNode][] = [
    ['문서명', doc.title],
    ['버전', doc.version || '표기 안 함'],
    ['원본 파일', doc.fileName || '—'],
    ['파일 크기', doc.fileSize > 0 ? fmtSize(doc.fileSize) : '—'],
    ['문서 유형', (
      <>
        {doc.profileLabel || doc.profile || '—'}
        {doc.profileHint && <span className="pd-badge gray" style={{ marginLeft: 6 }}>사람이 지정</span>}
      </>
    )],
    ['적재 컬렉션', (
      <>
        {doc.collection || '—'}
        {doc.collection && !JUDGEMENT_COLLECTIONS.includes(doc.collection) && (
          <span style={{ color: 'var(--tone-amber)' }}> (정산 판정에 인용되지 않음)</span>
        )}
      </>
    )],
    ['비용분류(룰 생성 대상)', doc.ruleScope || '지정 안 함'],
    ['조항 / 청크', `${doc.clauseCount}개 / ${doc.chunkCount}개 (검색 대상 ${doc.leafCount}개)`],
    // 적재 후 룰 자동 생성이 어떻게 됐는지 — 업로드 시점 한 번 일어나는 배경 이벤트라
    // 상시 배너보다 감사용 기록에 가깝다. 없으면(정상 생성 등) 굳이 한 줄 차지하지 않는다.
    ...(doc.ruleTrigger?.detail ? [['룰 자동 생성', (
      <>
        {doc.ruleTrigger.detail}
        {doc.ruleTrigger.hint && <div className="text-meta" style={{ marginTop: 4 }}>{doc.ruleTrigger.hint}</div>}
      </>
    )] as [string, ReactNode]] : []),
    ['업로더', doc.uploadedBy || '—'],
    ['등록일', doc.uploadedAt?.slice(0, 10) || '—'],
    ['적재 완료', doc.indexedAt?.slice(0, 10) || '—'],
    ['문서 ID', <code key="id">{doc.id}</code>],
  ]
  return (
    <div className="pd-info-grid">
      {rows.map(([label, value]) => (
        <div key={label} className="pd-info-row">
          <div className="pd-info-label">{label}</div>
          <div className="pd-info-value">{value}</div>
        </div>
      ))}
    </div>
  )
}
// Tab1 — 실제 API의 DRAFT RuleGraph 버전 조회 + 노드 상세 편집 플레이스홀더.
import { useEffect, useMemo, useRef, useState } from 'react'
import { ChevronDown, ChevronRight, Code2, Plus, Send, Trash2 } from 'lucide-react'
import { endpoints } from '../../api/client'
import { activateOnEnterOrSpace } from '../../lib/a11y'
import { NewRuleGraphModal, type NewRuleChoice } from './NewRuleGraphModal'
import { describeDsl, nodeStatusLabel, nodeStatusTone, toGraph, type ApiGraph } from './data/graphApi'
import {
  DRAFT_CHAT_SCRIPT, GRAPH_STATUS_LABEL,
  type ChatMessage, type GraphNode, type RuleGraph,
} from './data/ruleConsoleMock'

const emptyNode = (nodeKey: string): GraphNode => ({
  nodeKey, title: '(제목 미설정)', origin: 'new', description: '',
  plain: { action: '' }, conditionExpr: '', sourceClause: '',
  actionDetail: { decision: '', severity: '', flag: '', note: '' },
  workflowStatus: 'DRAFT',
  priority: 0,
  aiReason: '대화 또는 직접 입력으로 조건·액션을 설정하세요.',
})

export function DraftTab({ newRuleOpen, setNewRuleOpen }: { newRuleOpen: boolean; setNewRuleOpen: (b: boolean) => void }) {
  const [allGraphs, setAllGraphs] = useState<RuleGraph[]>([])
  const [graphs, setGraphs] = useState<RuleGraph[]>([])
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [sel, setSel] = useState<{ graphId: string; nodeKey: string } | null>(null)
  const [nodeFilter, setNodeFilter] = useState<'all' | 'modified'>('all')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [seq, setSeq] = useState(1)
  const [chat, setChat] = useState<ChatMessage[]>(DRAFT_CHAT_SCRIPT)
  const [input, setInput] = useState('')
  const [deleteMode, setDeleteMode] = useState(false)

  useEffect(() => {
    let cancelled = false
    endpoints.rules().then(({ data }) => {
      if (cancelled) return
      const loaded = (data as ApiGraph[]).map(toGraph)
      setAllGraphs(loaded)
      setGraphs(loaded)
      setExpanded(new Set(loaded.map((graph) => graph.id)))
      const first = loaded.find((graph) => graph.nodes.length)?.nodes[0]
      const firstGraph = loaded.find((graph) => graph.nodes.length)
      setSel(first && firstGraph ? { graphId: firstGraph.id, nodeKey: first.nodeKey } : null)
    }).catch(() => {
      if (!cancelled) setError('룰 그래프를 불러오지 못했습니다. Core API 연결을 확인해주세요.')
    }).finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  const visibleGraphs = useMemo(() => nodeFilter === 'all'
    ? graphs
    : graphs.filter((graph) => graph.status === 'DRAFT'), [graphs, nodeFilter])
  const visibleScopes = useMemo(() => Object.entries(visibleGraphs.reduce<Record<string, RuleGraph[]>>((groups, graph) => {
    ;(groups[graph.scope] ??= []).push(graph)
    return groups
  }, {})), [visibleGraphs])
  const nodesFor = (graph: RuleGraph) => graph.nodes
  const selGraph = graphs.find((graph) => graph.id === sel?.graphId)
  const selNode = selGraph?.nodes.find((node) => node.nodeKey === sel?.nodeKey)

  const toggle = (id: string) => setExpanded((previous) => {
    const next = new Set(previous)
    next.has(id) ? next.delete(id) : next.add(id)
    return next
  })
  const selectNode = (graphId: string, nodeKey: string) => { setSel({ graphId, nodeKey }); setChat([]) }

  const send = () => {
    const text = input.trim()
    if (!text) return
    setChat((previous) => [...previous, { role: 'user', text }, {
      role: 'ai', text: '네, 반영했습니다. 가운데 조건·액션·라우팅에서 변경 내용을 확인해주세요.', appliedNote: '노드 설정에 적용됨',
    }])
    setInput('')
  }

  const createRule = async (choice: NewRuleChoice) => {
    const key = `R-N${seq}`
    setSeq((value) => value + 1)
    try {
      const response = choice.kind === 'existing'
        ? await endpoints.createRuleVersion(choice.graphId)
        : await endpoints.createRuleGraph(choice.name, choice.scope)
      const draft = toGraph(response.data as ApiGraph)
      await endpoints.createRuleNode(draft.id, key)
      draft.nodes = [...draft.nodes, emptyNode(key)]
      if (!draft.entryNodeKey) draft.entryNodeKey = key
      setAllGraphs((previous) => [draft, ...previous])
      setGraphs((previous) => [draft, ...previous])
      setExpanded((previous) => new Set(previous).add(draft.id))
      setSel({ graphId: draft.id, nodeKey: key })
      setChat([])
      setNewRuleOpen(false)
    } catch {
      setError('새 룰 버전을 만들지 못했습니다. 권한과 API 연결을 확인해주세요.')
    }
  }

  const createWorkingVersion = async (graph: RuleGraph) => {
    const existingDraft = graphs.find((candidate) => candidate.familyKey === graph.familyKey && candidate.status === 'DRAFT')
    if (existingDraft) return existingDraft
    const response = await endpoints.createRuleVersion(graph.id)
    const draft = toGraph(response.data as ApiGraph)
    setGraphs((previous) => [draft, ...previous])
    setAllGraphs((previous) => [draft, ...previous])
    return draft
  }

  const addNode = async (source: RuleGraph) => {
    const key = `R-N${seq}`
    setSeq((value) => value + 1)
    try {
      const graph = source.status === 'DRAFT' ? source : await createWorkingVersion(source)
      await endpoints.createRuleNode(graph.id, key)
      const node = emptyNode(key)
      setGraphs((previous) => previous.map((item) => item.id === graph.id ? { ...item, nodes: [...item.nodes, node] } : item))
      setAllGraphs((previous) => previous.map((item) => item.id === graph.id ? { ...item, nodes: [...item.nodes, node] } : item))
      setExpanded((previous) => new Set(previous).add(graph.id))
      setSel({ graphId: graph.id, nodeKey: key })
    } catch {
      setError('노드를 추가하지 못했습니다.')
    }
  }

  const startNodeEdit = async (graph: RuleGraph, nodeKey: string) => {
    try {
      const draft = await createWorkingVersion(graph)
      setExpanded((previous) => new Set(previous).add(draft.id))
      setSel({ graphId: draft.id, nodeKey })
    } catch {
      setError('수정 버전을 만들지 못했습니다.')
    }
  }

  const sameAsActive = (draft: RuleGraph, nextNodes: GraphNode[]) => {
    const active = graphs.find((candidate) => candidate.familyKey === draft.familyKey && candidate.status === 'ACTIVE')
    if (!active || active.nodes.length !== nextNodes.length) return false
    const compact = (nodes: GraphNode[]) => nodes.map((node) => ({
      key: node.nodeKey, title: node.title, description: node.description,
      condition: node.conditionExpr, action: node.actionDetail,
    }))
    return JSON.stringify(compact(active.nodes)) === JSON.stringify(compact(nextNodes))
      && JSON.stringify(active.routings) === JSON.stringify(draft.routings)
  }

  const deleteNode = async (graph: RuleGraph, node: GraphNode) => {
    try {
      await endpoints.deleteRuleNode(graph.id, node.nodeKey)
      const nextNodes = graph.nodes.filter((candidate) => candidate.nodeKey !== node.nodeKey)
      if (sameAsActive(graph, nextNodes)) {
        await endpoints.discardRuleDraft(graph.id)
        setGraphs((previous) => previous.filter((candidate) => candidate.id !== graph.id))
        setAllGraphs((previous) => previous.filter((candidate) => candidate.id !== graph.id))
        const active = graphs.find((candidate) => candidate.familyKey === graph.familyKey && candidate.status === 'ACTIVE')
        setSel(active?.nodes[0] ? { graphId: active.id, nodeKey: active.nodes[0].nodeKey } : null)
      } else {
        setGraphs((previous) => previous.map((candidate) => candidate.id === graph.id ? { ...candidate, nodes: nextNodes } : candidate))
        setSel(nextNodes[0] ? { graphId: graph.id, nodeKey: nextNodes[0].nodeKey } : null)
      }
    } catch {
      setError('노드를 삭제하지 못했습니다.')
    }
  }

  const revertToActive = (draft: RuleGraph, activeId: string) => {
    setGraphs((previous) => previous.filter((candidate) => candidate.id !== draft.id))
    setAllGraphs((previous) => previous.filter((candidate) => candidate.id !== draft.id))
    const active = graphs.find((candidate) => candidate.id === activeId)
    setSel(active?.nodes[0] ? { graphId: active.id, nodeKey: active.nodes[0].nodeKey } : null)
  }

  const reflectNode = (graphId: string, nodeKey: string, patch: Partial<GraphNode>) => {
    const apply = (items: RuleGraph[]) => items.map((graph) => graph.id === graphId ? {
      ...graph, nodes: graph.nodes.map((node) => node.nodeKey === nodeKey ? { ...node, ...patch } : node),
    } : graph)
    setGraphs(apply)
    setAllGraphs(apply)
  }

  const deleteGraph = async (graph: RuleGraph) => {
    if (graph.status === 'ACTIVE') {
      window.alert('Active된 그래프는 삭제할 수 없습니다. 다른 버전을 Active로 전환한 뒤 삭제해주세요.')
      return
    }
    if (!window.confirm(`“${graph.name} v${graph.version ?? 1}” 그래프를 삭제하시겠습니까?`)) return
    try {
      await endpoints.deleteRuleGraph(graph.id)
      setGraphs((previous) => previous.filter((candidate) => candidate.id !== graph.id))
      setAllGraphs((previous) => previous.filter((candidate) => candidate.id !== graph.id))
      if (sel?.graphId === graph.id) setSel(null)
      setDeleteMode(false)
    } catch { setError('그래프를 삭제하지 못했습니다.') }
  }

  return (
    <>
      <div className="rule-draft-grid">
        <div className="card">
          <div className="card-head" style={{ alignItems: 'flex-start' }}>
            <div><h3>룰 그래프 보기 ({visibleGraphs.length})</h3><div className="text-meta">실제 그래프와 버전별 노드</div></div>
          </div>
          <div className="row" style={{ padding: '0 12px 8px', gap: 6 }}>
            <button className={'btn sm' + (nodeFilter === 'all' ? ' primary' : '')} onClick={() => setNodeFilter('all')}>전체보기</button>
            <button className={'btn sm' + (nodeFilter === 'modified' ? ' primary' : '')} onClick={() => setNodeFilter('modified')}>수정건 보기</button>
            <div className="spacer" />
            <button className={'btn sm' + (deleteMode ? ' primary' : '')} onClick={() => setDeleteMode((value) => !value)}>
              <Trash2 size={11} /> {deleteMode ? '삭제 취소' : '그래프 삭제'}
            </button>
          </div>
          {loading && <div className="text-meta" style={{ padding: 16 }}>룰 그래프를 불러오는 중입니다.</div>}
          {error && <div className="note" style={{ margin: 12, color: 'var(--tone-red)' }}>{error}</div>}
          {!loading && !error && visibleGraphs.length === 0 && <div className="text-meta" style={{ padding: 16 }}>표시할 룰 그래프가 없습니다.</div>}
          <div className="stack" style={{ padding: 8, gap: 8 }}>
            {visibleScopes.map(([scope, scopeGraphs]) => <div key={scope} style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius-control)', padding: 4 }}>
              <div style={{ padding: '7px 10px 4px', fontSize: 12, fontWeight: 700 }}>{scope}</div>
              {scopeGraphs.sort((a, b) => (b.version ?? 0) - (a.version ?? 0)).map((graph) => {
              const open = expanded.has(graph.id)
              const nodes = nodesFor(graph)
              return (
                <div key={graph.id}>
                  <div className="rule-graph-row" role="button" tabIndex={0}
                    onClick={() => toggle(graph.id)} onKeyDown={activateOnEnterOrSpace(() => toggle(graph.id))}>
                    {open ? <ChevronDown size={14} className="muted" /> : <ChevronRight size={14} className="muted" />}
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div className="row" style={{ gap: 10, justifyContent: 'flex-start', flexWrap: 'wrap' }}>
                        <span className={'tag ' + (graph.status === 'ACTIVE' ? 'ok' : graph.status === 'DRAFT' ? 'ai' : '')}>v{graph.version ?? 1} · {graph.status === 'ACTIVE' ? 'Active' : graph.status === 'DRAFT' ? '수정중' : GRAPH_STATUS_LABEL[graph.status]}</span>
                        <b style={{ fontSize: 13 }}>{graph.name}</b>
                        {deleteMode
                          ? <button className="btn sm" style={{ marginLeft: 6 }} onClick={(event) => { event.stopPropagation(); void deleteGraph(graph) }}><Trash2 size={11} /> 그래프 삭제</button>
                          : (graph.status === 'DRAFT' || graph.status === 'ACTIVE') && <button className="btn sm" style={{ marginLeft: 6 }} onClick={(event) => { event.stopPropagation(); void addNode(graph) }}><Plus size={11} /> 노드 추가</button>}
                      </div>
                    </div>
                  </div>
                  {open && <div className="rule-node-list">{nodes.map((node) => (
                    <div key={node.nodeKey}
                      className={'rule-node-item' + (sel?.graphId === graph.id && sel?.nodeKey === node.nodeKey ? ' selected' : '')}
                      role="button" tabIndex={0} onClick={() => selectNode(graph.id, node.nodeKey)}
                      onKeyDown={activateOnEnterOrSpace(() => selectNode(graph.id, node.nodeKey))}>
                      <div className="row" style={{ justifyContent: 'flex-start', gap: 6 }}>
                        <span className={'tag ' + nodeStatusTone(node.workflowStatus)}>{nodeStatusLabel(node.workflowStatus)}</span>
                        <span style={{ fontSize: 12.5 }}>{node.title}</span>
                      </div>
                    </div>
                  ))}</div>}
                </div>
              )
            })}</div>)}
          </div>
        </div>

        {selGraph && selNode
          ? <NodeDetail key={`${selGraph.id}-${selNode.nodeKey}`} graph={selGraph} node={selNode}
              onStartEdit={() => void startNodeEdit(selGraph, selNode.nodeKey)} onDelete={() => void deleteNode(selGraph, selNode)}
              onReverted={(activeId) => revertToActive(selGraph, activeId)}
              onNodeChanged={(patch) => reflectNode(selGraph.id, selNode.nodeKey, patch)} />
          : <div className="card"><div className="card-body text-meta">좌측에서 노드를 선택하거나 신규 룰을 생성하세요.</div></div>}

        <div className="card" style={{ borderColor: 'var(--primary)' }}>
          <div className="card-head"><h3>대화형 지시·수정</h3></div>
          <div className="text-meta" style={{ padding: '0 16px' }}>자연어로 말하면 AI가 노드 필드를 직접 수정합니다.</div>
          <div className="stack" style={{ padding: 16, maxHeight: 420, overflowY: 'auto' }}>
            {chat.length === 0 && <div className="text-meta">예) “금액 기준을 40만원으로 올리고 보완요청으로 바꿔줘”</div>}
            {chat.map((message, index) => <div key={index} style={{ alignSelf: message.role === 'user' ? 'flex-end' : 'flex-start', maxWidth: '92%' }}>
              <div style={{ padding: '8px 12px', borderRadius: 'var(--radius-control)', fontSize: 12.5, whiteSpace: 'pre-line', background: message.role === 'user' ? 'var(--primary)' : 'var(--surface-2)', color: message.role === 'user' ? '#fff' : 'var(--text)' }}>{message.text}</div>
              {message.appliedNote && <div className="text-meta" style={{ color: 'var(--tone-green)', marginTop: 4 }}>✓ {message.appliedNote}</div>}
            </div>)}
          </div>
          <div className="row" style={{ padding: 16, borderTop: '1px solid var(--border)', gap: 8 }}>
            <input placeholder="예) 액션을 RETURN으로 바꿔줘" value={input} onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => { if (event.key === 'Enter') send() }} style={{ flex: 1 }} />
            <button className="btn primary" onClick={send} aria-label="전송"><Send size={14} /></button>
          </div>
        </div>
      </div>

      {newRuleOpen && <NewRuleGraphModal graphs={allGraphs} onClose={() => setNewRuleOpen(false)} onConfirm={createRule} />}
    </>
  )
}

function NodeDetail({ graph, node, onStartEdit, onDelete, onReverted, onNodeChanged }: {
  graph: RuleGraph; node: GraphNode; onStartEdit: () => void; onDelete: () => void
  onReverted: (activeId: string) => void; onNodeChanged: (patch: Partial<GraphNode>) => void
}) {
  const editable = graph.status === 'DRAFT'
  const [showCode, setShowCode] = useState(false)
  const [title, setTitle] = useState(node.title)
  const [description, setDescription] = useState(node.description ?? '')
  const [conditionText, setConditionText] = useState(node.conditionExpr)
  const [routes, setRoutes] = useState(() => graph.routings.filter((route) => route.from === node.nodeKey))
  const [action, setAction] = useState(node.actionDetail ?? {})
  const [workflowStatus, setWorkflowStatus] = useState<GraphNode['workflowStatus']>(node.workflowStatus ?? 'DRAFT')
  const [saveState, setSaveState] = useState<'saved' | 'saving' | 'error'>('saved')
  const dirty = useRef(false)
  const saveRef = useRef<() => Promise<void>>(async () => undefined)

  const saveNow = async (override?: { routes?: typeof routes; workflowStatus?: GraphNode['workflowStatus'] }) => {
    if (!editable || (!dirty.current && !override)) return
    setSaveState('saving')
    let condition: unknown = {}
    try { condition = conditionText.trim() ? JSON.parse(conditionText) : {} } catch { setSaveState('error'); return }
    try {
      const { data } = await endpoints.saveRuleNode(graph.id, node.nodeKey, {
        condition,
        action: {
          ...action, title, description, origin: node.origin,
          workflow_status: override?.workflowStatus ?? workflowStatus, ai_reason: node.aiReason, source_clause: node.sourceClause,
        },
        routings: (override?.routes ?? routes).map((route) => ({ onResult: route.onResult, toNodeKey: route.to })),
      })
      dirty.current = false
      if (data?.revertedToGraphId) onReverted(String(data.revertedToGraphId))
      else setSaveState('saved')
    } catch { setSaveState('error') }
  }
  saveRef.current = saveNow

  useEffect(() => {
    if (!editable) return
    const interval = window.setInterval(() => { if (dirty.current) void saveRef.current() }, 60_000)
    return () => { window.clearInterval(interval); if (dirty.current) void saveRef.current() }
  }, [editable])

  const naturalCondition = useMemo(() => {
    try { return conditionText.trim() ? describeDsl(JSON.parse(conditionText)) : '조건이 아직 설정되지 않았습니다.' }
    catch { return 'DSL 형식을 확인해주세요.' }
  }, [conditionText])
  const markDirty = () => { dirty.current = true; setSaveState('saved') }
  const addRoute = () => {
    const next = [...routes, { from: node.nodeKey, onResult: 'MATCH' as const, to: '' }]
    setRoutes(next); dirty.current = true; void saveNow({ routes: next })
  }
  const removeRoute = (index: number) => {
    const next = routes.filter((_route, routeIndex) => routeIndex !== index)
    setRoutes(next); dirty.current = true; void saveNow({ routes: next })
  }
  const toggleWaiting = () => {
    const next = workflowStatus === 'WAITING' ? 'DRAFT' : 'WAITING'
    setWorkflowStatus(next); onNodeChanged({ workflowStatus: next }); dirty.current = true
    void saveNow({ workflowStatus: next })
  }

  return <div className="card">
    <div className="card-head">
      <div><h3>{title}</h3><div className="text-meta">{graph.scope} · v{graph.version ?? 1}</div></div>
      <span className={'tag ' + nodeStatusTone(workflowStatus)}>{nodeStatusLabel(workflowStatus)}</span>
    </div>
    <div className="card-body stack">
      <div className="field"><label>제목</label><input value={title} disabled={!editable} onBlur={() => void saveNow()} onChange={(event) => { setTitle(event.target.value); onNodeChanged({ title: event.target.value }); markDirty() }} /></div>
      <div className="field"><label>설명</label><textarea rows={3} value={description} disabled={!editable} onBlur={() => void saveNow()} onChange={(event) => { setDescription(event.target.value); onNodeChanged({ description: event.target.value }); markDirty() }} placeholder="이 룰의 목적과 적용 대상을 설명하세요." /></div>

      <div className="field">
        <label>이 Rule이 하는 일</label>
        <div className="note" style={{ lineHeight: 1.7, color: 'var(--text)', whiteSpace: 'pre-line' }}>{naturalCondition}</div>
        <div className="dsl-disclosure" role="button" tabIndex={0} onClick={() => setShowCode((value) => !value)}><Code2 size={13} /> DSL 코드 {showCode ? '접기' : '펼치기'} <span>{showCode ? '⌃' : '⌄'}</span></div>
        {showCode && <textarea rows={7} value={conditionText} disabled={!editable} onBlur={() => void saveNow()} onChange={(event) => { setConditionText(event.target.value); onNodeChanged({ conditionExpr: event.target.value }); markDirty() }} placeholder="JSON DSL 조건" style={{ fontFamily: 'monospace' }} />}
      </div>

      <div className="field"><label>액션</label><div className="grid-2" style={{ gap: 8 }}>
        <select disabled={!editable} value={action.decision ?? ''} onBlur={() => void saveNow()} onChange={(event) => { const next = { ...action, decision: event.target.value }; setAction(next); onNodeChanged({ actionDetail: next }); markDirty() }}><option value="">결정 선택</option><option>PASS</option><option>REJECT</option><option>REVIEW</option><option>RETURN</option><option>PASS_THROUGH</option></select>
        <select disabled={!editable} value={action.severity ?? ''} onBlur={() => void saveNow()} onChange={(event) => { const next = { ...action, severity: event.target.value }; setAction(next); onNodeChanged({ actionDetail: next }); markDirty() }}><option value="">심각도 선택</option><option>CRITICAL</option><option>HIGH</option><option>MEDIUM</option><option>LOW</option><option>INFO</option></select>
        <input disabled={!editable} value={action.flag ?? ''} onBlur={() => void saveNow()} onChange={(event) => { const next = { ...action, flag: event.target.value }; setAction(next); onNodeChanged({ actionDetail: next }); markDirty() }} placeholder="플래그" />
        <input disabled={!editable} value={action.note ?? ''} onBlur={() => void saveNow()} onChange={(event) => { const next = { ...action, note: event.target.value }; setAction(next); onNodeChanged({ actionDetail: next }); markDirty() }} placeholder="처리 안내/메모" />
        <input disabled={!editable} value={action.approver ?? ''} onBlur={() => void saveNow()} onChange={(event) => { const next = { ...action, approver: event.target.value }; setAction(next); onNodeChanged({ actionDetail: next }); markDirty() }} placeholder="확인·승인 주체" />
        <input value={`평가 우선순위 ${node.priority ?? 0}`} readOnly aria-label="평가 우선순위" />
      </div></div>

      <div className="field">
        <label>라우팅</label>
        <div className="stack" style={{ gap: 8 }}>
          {routes.length === 0 && <div className="text-meta">등록된 라우팅이 없습니다. 현재 노드의 액션으로 종료됩니다.</div>}
          {routes.map((route, index) => <div className="routing-row" key={`${route.onResult}-${index}`}>
            <span className="routing-order" title="라우팅 우선순위">#{route.priority ?? index}</span>
            <select disabled={!editable} style={{ flex: 1 }} value={route.onResult} onBlur={() => void saveNow()} onChange={(event) => { setRoutes((previous) => previous.map((item, i) => i === index ? { ...item, onResult: event.target.value as 'MATCH' | 'NO_MATCH' } : item)); markDirty() }}><option>MATCH</option><option>NO_MATCH</option></select>
            <select disabled={!editable} style={{ flex: 2 }} value={route.to} onBlur={() => void saveNow()} onChange={(event) => { setRoutes((previous) => previous.map((item, i) => i === index ? { ...item, to: event.target.value } : item)); markDirty() }}><option value="">종료</option>{graph.nodes.filter((candidate) => candidate.nodeKey !== node.nodeKey).map((candidate) => <option key={candidate.nodeKey} value={candidate.nodeKey}>{candidate.title}</option>)}</select>
            {editable && <button className="btn sm" onClick={() => removeRoute(index)} aria-label="라우팅 제거"><Trash2 size={12} /></button>}
          </div>)}
          {editable && <button className="routing-add" onClick={addRoute}><Plus size={13} /> 라우팅 추가</button>}
        </div>
      </div>

      <div className="field"><label>생성 이유 · 근거</label><div className="note"><div>{node.aiReason || '생성 이유가 아직 입력되지 않았습니다.'}</div>{node.sourceClause && <a href="/governance" style={{ display: 'inline-block', marginTop: 8 }}>📎 관련 조항: {node.sourceClause}</a>}</div></div>
    </div>
    <div className="modal-foot">
      <span className="text-meta">{!editable ? '읽기 전용' : saveState === 'saving' ? '저장 중…' : saveState === 'error' ? '저장 실패 또는 DSL 오류' : '변경사항 자동 저장됨'}</span>
      <div className="spacer" />
      {!editable && graph.status === 'ACTIVE' && <button className="btn primary" onClick={onStartEdit}>v{(graph.version ?? 1) + 1} 수정 시작</button>}
      {editable && <button className="btn warn" onClick={onDelete}><Trash2 size={12} /> 노드 삭제</button>}
      {editable && <button className={'btn ' + (workflowStatus === 'WAITING' ? '' : 'primary')} onClick={toggleWaiting}>{workflowStatus === 'WAITING' ? '초안으로 전환' : '초안 완료 · 검증 대기로 전환'}</button>}
    </div>
  </div>
}

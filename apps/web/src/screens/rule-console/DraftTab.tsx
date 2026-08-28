// Tab1 — 실제 API의 DRAFT RuleGraph 버전 조회 + 노드 상세 편집 플레이스홀더.
import { useEffect, useMemo, useRef, useState } from 'react'
import { ChevronDown, ChevronRight, Code2, Plus, Send, Trash2 } from 'lucide-react'
import { endpoints } from '../../api/client'
import { converseRule, generateRuleGraph } from '../../api/ruleService'
import { SkeletonLines } from '../../components/ui/Skeleton'
import { activateOnEnterOrSpace } from '../../lib/a11y'
import { NewRuleGraphModal, type NewRuleChoice } from './NewRuleGraphModal'
import { describeDsl, nodeStatusLabel, nodeStatusTone, toGraph, type ApiGraph } from './data/graphApi'
import { GRAPH_STATUS_LABEL, type ChatMessage, type GraphNode, type RuleGraph } from './data/ruleConsoleMock'
import { useReadOpenTarget } from '../../lib/notifications'

type ApiMessage = { role: 'user' | 'ai'; text: string; appliedNote: string }

const emptyNode = (nodeKey: string): GraphNode => ({
  nodeKey, title: '(제목 미설정)', origin: 'new', description: '',
  plain: { action: '' }, conditionExpr: '', sourceClause: '',
  actionDetail: { decision: '', severity: '', flag: '', note: '' },
  workflowStatus: 'DRAFT',
  priority: 0,
  aiReason: '대화 또는 직접 입력으로 조건·액션을 설정하세요.',
})

export function DraftTab({ newRuleOpen, setNewRuleOpen }: { newRuleOpen: boolean; setNewRuleOpen: (b: boolean) => void }) {
  const [graphs, setGraphs] = useState<RuleGraph[]>([])
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [sel, setSel] = useState<{ graphId: string; nodeKey: string } | null>(null)
  const [nodeFilter, setNodeFilter] = useState<'all' | 'modified'>('all')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [seq, setSeq] = useState(1)
  const [chat, setChat] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [deleteMode, setDeleteMode] = useState(false)
  const [generating, setGenerating] = useState(false)
  // 대화 1턴은 LLM 여러 턴 + 그래프 CRUD 왕복이라 수십 초 걸린다 — 중복 전송을 막는다.
  const [chatting, setChatting] = useState(false)
  // decision/severity 선택지 — 서버 카탈로그(§8 후속). 조회 실패 시 이전 하드코딩 값과
  // 같은 기본값으로 대체해 화면이 빈 드롭다운이 되지 않게 한다.
  const [decisionOptions, setDecisionOptions] = useState<string[]>(['PASS', 'REJECT', 'REVIEW', 'RETURN', 'PASS_THROUGH'])
  const [severityOptions, setSeverityOptions] = useState<string[]>(['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO'])

  useEffect(() => {
    endpoints.ruleActionSchema().then(({ data }) => {
      const result = data as { decisions?: string[]; severities?: string[] }
      if (result.decisions?.length) setDecisionOptions(result.decisions)
      if (result.severities?.length) setSeverityOptions(result.severities)
    }).catch(() => undefined)
  }, [])

  useEffect(() => {
    let cancelled = false
    endpoints.rules().then(({ data }) => {
      if (cancelled) return
      const loaded = (data as ApiGraph[]).map(toGraph)
      setGraphs(loaded)
      setExpanded(new Set())  // 기본 접힘 — 필요한 그래프만 펼쳐서 본다
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
  //  **화면에 열려 있으면 알림을 접는다.** 「룰 수정 완료는 그래프 수정 화면을 벗어나
  //  있을 때만 알린다」를 서버가 판단할 수 없어서(서버는 화면이 어디 있는지 모른다)
  //  알림은 항상 만들고 여기서 읽음 처리한다.
  useReadOpenTarget(sel?.graphId ? `rulegraph:${sel.graphId}` : null)
  const selNode = selGraph?.nodes.find((node) => node.nodeKey === sel?.nodeKey)

  const toggle = (id: string) => setExpanded((previous) => {
    const next = new Set(previous)
    next.has(id) ? next.delete(id) : next.add(id)
    return next
  })
  const selectNode = (graphId: string, nodeKey: string) => setSel({ graphId, nodeKey })

  /** 서버가 그래프를 고친 뒤(생성·대화형 수정) 목록을 다시 읽어 화면을 맞춘다. */
  const reloadGraphs = async (focusGraphId?: string, focusNodeKey?: string) => {
    const { data } = await endpoints.rules()
    const loaded = (data as ApiGraph[]).map(toGraph)
    setGraphs(loaded)
    if (!focusGraphId) return loaded
    setExpanded((previous) => new Set(previous).add(focusGraphId))
    const graph = loaded.find((item) => item.id === focusGraphId)
    // 보고 있던 노드가 지워졌을 수 있다 — 그러면 그 그래프의 첫 노드로 옮긴다.
    const stillThere = focusNodeKey && graph?.nodes.some((n) => n.nodeKey === focusNodeKey)
    const nextKey = stillThere ? focusNodeKey : graph?.nodes[0]?.nodeKey
    setSel(graph && nextKey ? { graphId: graph.id, nodeKey: nextKey } : null)
    return loaded
  }

  /**
   * 작성 대화 로그 — **그래프 단위로 읽는다.**
   *
   * 예전엔 선택 노드로 걸러 읽었는데(`?nodeKey=...`), 대화형 Agent는 로그를
   * `node_key=""`(그래프 단위)로 남긴다 — 어느 노드를 고칠지는 Agent가 판단하고
   * 한 번에 여러 노드를 건드릴 수도 있기 때문이다. 그래서 필터가 항상 0건과 매칭돼
   * **AI는 동작하는데 대화 내역만 안 보이는** 상태였다.
   */
  useEffect(() => {
    if (!sel) { setChat([]); return }
    let cancelled = false
    endpoints.ruleMessages(sel.graphId).then(({ data }) => {
      if (cancelled) return
      setChat((data as ApiMessage[]).map((row) => ({
        role: row.role, text: row.text, appliedNote: row.appliedNote || undefined,
      })))
    }).catch(() => { if (!cancelled) setChat([]) })
    return () => { cancelled = true }
    // 그래프가 바뀔 때만 다시 읽는다 — 같은 그래프 안에서 노드를 옮겨도 대화는 이어진다.
  }, [sel?.graphId])

  /**
   * 대화형 수정 — Agent가 툴콜링으로 **실제 노드를 고친다**.
   *
   * 예전에는 여기서 "네, 반영했습니다"라는 **고정 문구를 만들어 로그에 저장**했다.
   * 아무것도 안 고쳤는데 고쳤다고 기록하는 셈이라, 대화 로그가 실제 그래프와 어긋났다.
   *
   * 로그 저장은 서버(Agent)가 한다 — 여기서 또 저장하면 같은 대화가 두 번 쌓인다.
   * 그래서 보내고 나서 **대화 로그와 그래프를 둘 다 다시 읽는다**.
   */
  const send = async () => {
    const text = input.trim()
    if (!text || !sel || chatting) return
    const { graphId, nodeKey } = sel
    setInput('')
    setChatting(true)
    // 낙관적 표시 — 사용자 발화만. AI 답은 실제 응답이 와야 붙인다.
    setChat((previous) => [...previous, { role: 'user', text }])
    try {
      const result = await converseRule(graphId, text, nodeKey)
      // 서버가 남긴 로그가 정본이다. 실패하면 방금 받은 답이라도 화면에 남긴다.
      // 저장도 조회도 **그래프 단위** — Agent가 node_key="" 로 남기기 때문(위 useEffect 참조).
      try {
        const { data } = await endpoints.ruleMessages(graphId)
        setChat((data as ApiMessage[]).map((row) => ({
          role: row.role, text: row.text, appliedNote: row.appliedNote || undefined,
        })))
      } catch {
        setChat((previous) => [...previous, {
          role: 'ai', text: result.answer,
          appliedNote: result.appliedChanges.length ? `${result.appliedChanges.length}건 반영됨` : undefined,
        }])
      }
      // Agent가 노드를 고쳤을 수 있으므로 그래프를 다시 읽는다.
      if (result.appliedChanges.length) await reloadGraphs(graphId, nodeKey)
    } catch (exc) {
      const detail = (exc as { response?: { data?: { detail?: string } }; message?: string })
      const reason = detail.response?.data?.detail || detail.message || '요청을 처리하지 못했습니다.'
      setError(reason)
      setChat((previous) => [...previous, { role: 'ai', text: reason }])
    } finally {
      setChatting(false)
    }
  }

  /** Rule Agent 생성 — 그래프·노드·라우팅이 전부 서버에서 만들어지므로 목록을 다시 읽어 붙인다. */
  const generateRule = async (choice: Extract<NewRuleChoice, { kind: 'generate' }>) => {
    setGenerating(true)
    setError('')
    try {
      const result = await generateRuleGraph(choice)
      await reloadGraphs(result.graphId)
      setChat([])
      setNewRuleOpen(false)
      if (result.rejectedCount > 0) {
        // 조용히 넘기지 않는다 — 생성 시도했지만 검증에서 떨어진 룰이 있다는 사실 자체가
        // 담당자가 규정 원문과 대조해봐야 할 신호다.
        setError(`초안을 만들었습니다(근거 조문 ${result.sources.length}건). `
          + `다만 ${result.rejectedCount}개 노드가 검증에서 제외됐습니다 — 규정 원문과 대조해주세요.`)
      }
    } catch (exc) {
      const detail = (exc as { response?: { data?: { detail?: string } }; message?: string })
      setError(detail.response?.data?.detail || detail.message || '규정에서 룰을 생성하지 못했습니다.')
    } finally {
      setGenerating(false)
    }
  }

  const createRule = async (choice: NewRuleChoice) => {
    if (choice.kind === 'generate') return generateRule(choice)
    const key = `R-N${seq}`
    setSeq((value) => value + 1)
    try {
      const response = await endpoints.createRuleGraph(choice.name, choice.scope)
      const draft = toGraph(response.data as ApiGraph)
      await endpoints.createRuleNode(draft.id, key)
      draft.nodes = [...draft.nodes, emptyNode(key)]
      if (!draft.entryNodeKey) draft.entryNodeKey = key
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
    const active = graphs.find((candidate) => candidate.id === activeId)
    setSel(active?.nodes[0] ? { graphId: active.id, nodeKey: active.nodes[0].nodeKey } : null)
  }

  const reflectNode = (graphId: string, nodeKey: string, patch: Partial<GraphNode>) => {
    const apply = (items: RuleGraph[]) => items.map((graph) => graph.id === graphId ? {
      ...graph, nodes: graph.nodes.map((node) => node.nodeKey === nodeKey ? { ...node, ...patch } : node),
    } : graph)
    setGraphs(apply)
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
          <div className="row" style={{ padding: '12px 12px 8px', gap: 6 }}>
            <button className={'btn sm' + (nodeFilter === 'all' ? ' primary' : '')} onClick={() => setNodeFilter('all')}>전체보기</button>
            <button className={'btn sm' + (nodeFilter === 'modified' ? ' primary' : '')} onClick={() => setNodeFilter('modified')}>수정건 보기</button>
            <div className="spacer" />
            <button className={'btn sm' + (deleteMode ? ' primary' : '')} onClick={() => setDeleteMode((value) => !value)}>
              <Trash2 size={11} /> {deleteMode ? '삭제 취소' : '그래프 삭제'}
            </button>
          </div>
          {loading && (
            <div style={{ padding: 16 }}>
              <span className="text-meta">룰 그래프를 불러오는 중…</span>
              <div style={{ marginTop: 8 }}><SkeletonLines rows={3} /></div>
            </div>
          )}
          {error && <div className="note error" style={{ margin: 12 }}>{error}</div>}
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
              onNodeChanged={(patch) => reflectNode(selGraph.id, selNode.nodeKey, patch)}
              decisionOptions={decisionOptions} severityOptions={severityOptions} />
          : <div className="card"><div className="card-body text-meta">좌측에서 노드를 선택하거나 신규 룰을 생성하세요.</div></div>}

        <div className="card" style={{ borderColor: 'var(--primary)' }}>
          <div className="card-head"><h3>대화형 지시·수정</h3></div>
          {/* 대화는 그래프 단위다 — 어느 노드를 고칠지는 Agent가 판단하고, 한 번에 여러 노드를
              건드릴 수도 있다. 노드를 옮겨도 같은 대화가 이어지는 이유를 화면에 밝혀 둔다. */}
          <div className="text-meta" style={{ padding: '0 16px' }}>
            자연어로 말하면 AI가 노드를 직접 수정합니다. 대화는 <b>그래프 단위</b>로 기록됩니다
            {selGraph ? ` — ${selGraph.name} v${selGraph.version}` : ''}.
          </div>
          <div className="stack" style={{ padding: 16, maxHeight: 420, overflowY: 'auto' }}>
            {chat.length === 0 && <div className="text-meta">예) “금액 기준을 40만원으로 올리고 보완요청으로 바꿔줘”</div>}
            {chat.map((message, index) => <div key={index} style={{ alignSelf: message.role === 'user' ? 'flex-end' : 'flex-start', maxWidth: '92%' }}>
              <div style={{ padding: '8px 12px', borderRadius: 'var(--radius-control)', fontSize: 12.5, whiteSpace: 'pre-line', background: message.role === 'user' ? 'var(--primary)' : 'var(--surface-2)', color: message.role === 'user' ? '#fff' : 'var(--text)' }}>{message.text}</div>
              {message.appliedNote && <div className="text-meta" style={{ color: 'var(--tone-green)', marginTop: 4 }}>✓ {message.appliedNote}</div>}
            </div>)}
            {/* 응답이 수십 초 걸린다 — 아무 표시가 없으면 사용자가 같은 지시를 다시 보낸다. */}
            {chatting && <div className="text-meta" style={{ alignSelf: 'flex-start' }}>AI가 규칙을 확인하고 수정하는 중…</div>}
          </div>
          <div className="row" style={{ padding: 16, borderTop: '1px solid var(--border)', gap: 8 }}>
            <input
              placeholder={selGraph && selGraph.status !== 'DRAFT'
                ? '활성 그래프는 대화로 수정할 수 없습니다 (초안에서 수정하세요)'
                : '예) 액션을 RETURN으로 바꿔줘'}
              value={input} onChange={(event) => setInput(event.target.value)}
              disabled={chatting || !sel || (!!selGraph && selGraph.status !== 'DRAFT')}
              onKeyDown={(event) => { if (event.key === 'Enter') void send() }} style={{ flex: 1 }} />
            <button className="btn primary" onClick={() => void send()} aria-label="전송"
                    disabled={chatting || !sel || !input.trim() || (!!selGraph && selGraph.status !== 'DRAFT')}>
              <Send size={14} />
            </button>
          </div>
        </div>
      </div>

      {newRuleOpen && (
        <NewRuleGraphModal
          onClose={() => setNewRuleOpen(false)}
          onConfirm={createRule}
          busy={generating}
        />
      )}
    </>
  )
}

/** 네임드 플래그 어휘 — 서버 레지스트리가 단일 원천이라 화면은 받아 쓰기만 한다.
 *  실패해도 빈 목록으로 둔다: 제안이 없을 뿐 자유 입력은 그대로 되므로 편집을 막지 않는다. */
function useFlagRegistry() {
  const [rows, setRows] = useState<{ code: string; label: string }[]>([])
  useEffect(() => {
    let cancelled = false
    endpoints.ruleFlags()
      .then(({ data }) => { if (!cancelled) setRows(data ?? []) })
      .catch(() => undefined)
    return () => { cancelled = true }
  }, [])
  return rows
}


function NodeDetail({ graph, node, onStartEdit, onDelete, onReverted, onNodeChanged, decisionOptions, severityOptions }: {
  graph: RuleGraph; node: GraphNode; onStartEdit: () => void; onDelete: () => void
  onReverted: (activeId: string) => void; onNodeChanged: (patch: Partial<GraphNode>) => void
  decisionOptions: string[]; severityOptions: string[]
}) {
  const editable = graph.status === 'DRAFT'
  const flagRegistry = useFlagRegistry()
  const [showCode, setShowCode] = useState(false)
  const [title, setTitle] = useState(node.title)
  const [description, setDescription] = useState(node.description ?? '')
  const [conditionText, setConditionText] = useState(node.conditionExpr)
  const [routes, setRoutes] = useState(() => graph.routings.filter((route) => route.from === node.nodeKey))
  const [action, setAction] = useState(node.actionDetail ?? {})
  const [workflowStatus, setWorkflowStatus] = useState<GraphNode['workflowStatus']>(node.workflowStatus ?? 'DRAFT')
  const [saveState, setSaveState] = useState<'saved' | 'saving' | 'error'>('saved')
  // 저장 실패 사유를 구분한다 — DSL 문법 오류(로컬)와 저장 요청 실패(네트워크/서버)는
  // 사람이 할 다음 행동이 다르다("DSL 코드를 고쳐라" vs "다시 시도하라").
  const [saveErrorDetail, setSaveErrorDetail] = useState('')
  // 쉽게보기 문장은 Agent가 조건과 함께 써 둔 값이라, DSL을 손으로 고치면 설명이 뒤처진다(마운트 시점 원문과 비교).
  const openedConditionExpr = useRef(node.conditionExpr)
  const dirty = useRef(false)
  const saveRef = useRef<() => Promise<void>>(async () => undefined)

  const saveNow = async (override?: { routes?: typeof routes; workflowStatus?: GraphNode['workflowStatus'] }) => {
    if (!editable || (!dirty.current && !override)) return
    setSaveState('saving')
    setSaveErrorDetail('')
    let condition: unknown = {}
    try { condition = conditionText.trim() ? JSON.parse(conditionText) : {} } catch {
      setSaveState('error')
      setSaveErrorDetail('DSL 코드가 올바른 JSON 형식이 아닙니다 — 아래 "DSL 코드"를 펼쳐 문법을 확인하세요.')
      return
    }
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
    } catch {
      setSaveState('error')
      setSaveErrorDetail('저장 요청이 실패했습니다 — 네트워크 연결을 확인하고 다시 시도하세요.')
    }
  }
  saveRef.current = saveNow

  useEffect(() => {
    if (!editable) return
    const interval = window.setInterval(() => { if (dirty.current) void saveRef.current() }, 60_000)
    return () => { window.clearInterval(interval); if (dirty.current) void saveRef.current() }
  }, [editable])

  // 쉽게보기 = Agent가 저장해 둔 문장(node.conditionText). 없는 노드만 DSL 기계 번역으로 폴백한다.
  const naturalCondition = useMemo(() => {
    if (node.conditionText?.trim()) return node.conditionText
    try { return conditionText.trim() ? describeDsl(JSON.parse(conditionText)) : '조건이 아직 설정되지 않았습니다.' }
    catch { return 'DSL 형식을 확인해주세요.' }
  }, [node.conditionText, conditionText])
  const conditionTextStale = Boolean(node.conditionText?.trim()) && conditionText !== openedConditionExpr.current
  const markDirty = () => { dirty.current = true; setSaveState('saved'); setSaveErrorDetail('') }
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
        {conditionTextStale && <div className="text-meta" style={{ marginTop: 6, color: 'var(--tone-amber)' }}>DSL 코드를 직접 수정했습니다. 위 설명은 수정 전 기준이며, Rule Agent가 다시 생성할 때 갱신됩니다.</div>}
        <div className="dsl-disclosure" role="button" tabIndex={0} onClick={() => setShowCode((value) => !value)}><Code2 size={13} /> DSL 코드 {showCode ? '접기' : '펼치기'} <span>{showCode ? '⌃' : '⌄'}</span></div>
        {showCode && <textarea rows={7} value={conditionText} disabled={!editable} onBlur={() => void saveNow()} onChange={(event) => { setConditionText(event.target.value); onNodeChanged({ conditionExpr: event.target.value }); markDirty() }} placeholder="JSON DSL 조건" style={{ fontFamily: 'monospace' }} />}
      </div>

      <div className="field"><label>액션</label><div className="grid-2" style={{ gap: 8 }}>
        <select disabled={!editable} value={action.decision ?? ''} onBlur={() => void saveNow()} onChange={(event) => { const next = { ...action, decision: event.target.value }; setAction(next); onNodeChanged({ actionDetail: next }); markDirty() }}>
          <option value="">결정 선택</option>
          {decisionOptions.map((value) => <option key={value}>{value}</option>)}
        </select>
        <select disabled={!editable} value={action.severity ?? ''} onBlur={() => void saveNow()} onChange={(event) => { const next = { ...action, severity: event.target.value }; setAction(next); onNodeChanged({ actionDetail: next }); markDirty() }}>
          <option value="">심각도 선택</option>
          {severityOptions.map((value) => <option key={value}>{value}</option>)}
        </select>
        {/* 플래그는 자유 입력이되 **등록된 어휘를 먼저 제안**한다. 닫으면(select) 고객 규정에서
            생성된 새 어휘를 못 쓰고, 완전히 열어두면 같은 개념에 다른 이름이 생긴다
            (실제로 `EVIDENCE_MISSING` vs `MISSING_RECEIPT`로 갈렸었다). */}
        <input disabled={!editable} list="rule-flag-registry" value={action.flag ?? ''} onBlur={() => void saveNow()} onChange={(event) => { const next = { ...action, flag: event.target.value }; setAction(next); onNodeChanged({ actionDetail: next }); markDirty() }} placeholder="플래그 (등록 어휘 제안)" />
        <datalist id="rule-flag-registry">
          {flagRegistry.map((f) => <option key={f.code} value={f.code}>{f.label}</option>)}
        </datalist>
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

      <div className="field"><label>생성 이유 · 근거</label><div className="note"><div>{node.aiReason || '생성 이유가 아직 입력되지 않았습니다.'}</div>{node.sourceClause && <a href="/policy-docs" style={{ display: 'inline-block', marginTop: 8 }}>관련 조항: {node.sourceClause}</a>}</div></div>
    </div>
    <div className="modal-foot">
      <span className="text-meta" style={saveState === 'error' ? { color: 'var(--tone-red)' } : undefined}>
        {!editable ? '읽기 전용' : saveState === 'saving' ? '저장 중…' : saveState === 'error' ? saveErrorDetail : '변경사항 자동 저장됨'}
      </span>
      <div className="spacer" />
      {!editable && graph.status === 'ACTIVE' && <button className="btn primary" onClick={onStartEdit}>v{(graph.version ?? 1) + 1} 수정 시작</button>}
      {editable && <button className="btn warn" onClick={onDelete}><Trash2 size={12} /> 노드 삭제</button>}
      {editable && <button className={'btn ' + (workflowStatus === 'WAITING' ? '' : 'primary')} onClick={toggleWaiting}>{workflowStatus === 'WAITING' ? '초안으로 전환' : '초안 완료 · 검증 대기로 전환'}</button>}
    </div>
  </div>
}

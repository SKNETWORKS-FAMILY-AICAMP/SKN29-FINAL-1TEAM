// Tab1 — Rule 초안 대기 · 그래프 단위 묶음(버전 표현, 접기/펼치기) + 노드 상세 세부설정.
//  좌: 초안 룰그래프 트리(그래프→노드) / 중: 선택 노드 세부설정 / 우: 대화형 지시.
//  룰 노드는 이 상세에서만 유효하며, 시뮬레이션·활성은 그래프 단위(다른 탭)에서 처리한다.
import { useMemo, useState } from 'react'
import { ChevronDown, ChevronRight, Code2, Send, Sparkles, Wand2 } from 'lucide-react'
import {
  DRAFT_CHAT_SCRIPT, GRAPH_STATUS_LABEL, graphsByStatus, workingVersion,
  RULE_GRAPHS, type ChatMessage, type GraphNode, type RuleGraph,
} from './data/ruleConsoleMock'
import { NewRuleGraphModal, type NewRuleChoice } from './NewRuleGraphModal'
import { activateOnEnterOrSpace } from '../../lib/a11y'

const emptyNode = (nodeKey: string): GraphNode => ({
  nodeKey, title: '(제목 미설정)', origin: 'new',
  plain: { action: '' }, conditionExpr: '', sourceClause: '',
  aiReason: '대화 또는 직접 입력으로 조건·액션을 설정하세요.',
})

export function DraftTab({ newRuleOpen, setNewRuleOpen }: { newRuleOpen: boolean; setNewRuleOpen: (b: boolean) => void }) {
  const [graphs, setGraphs] = useState<RuleGraph[]>(() => graphsByStatus('DRAFT').map((g) => ({ ...g, nodes: [...g.nodes] })))
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(graphs.map((g) => g.id)))
  const [sel, setSel] = useState<{ graphId: string; nodeKey: string } | null>(
    graphs[0] ? { graphId: graphs[0].id, nodeKey: graphs[0].nodes[0].nodeKey } : null,
  )
  const [seq, setSeq] = useState(1)
  const [chat, setChat] = useState<ChatMessage[]>(DRAFT_CHAT_SCRIPT)
  const [input, setInput] = useState('')

  const selGraph = graphs.find((g) => g.id === sel?.graphId)
  const selNode = selGraph?.nodes.find((n) => n.nodeKey === sel?.nodeKey)

  const toggle = (id: string) => setExpanded((prev) => {
    const next = new Set(prev)
    next.has(id) ? next.delete(id) : next.add(id)
    return next
  })
  const selectNode = (graphId: string, nodeKey: string) => { setSel({ graphId, nodeKey }); setChat([]) }

  const send = () => {
    const text = input.trim()
    if (!text) return
    setChat((prev) => [
      ...prev,
      { role: 'user', text },
      { role: 'ai', text: '네, 반영했습니다. 가운데 "이 Rule이 하는 일"에서 변경 내용을 확인해주세요.', appliedNote: '노드 조건·액션에 적용됨' },
    ])
    setInput('')
  }

  // 신규 룰 생성 확정 → 빈 노드 추가/빈 그래프 생성 → 상세로 이동
  const createRule = (choice: NewRuleChoice) => {
    const key = `R-N${seq}`
    setSeq((s) => s + 1)
    if (choice.kind === 'existing') {
      const source = RULE_GRAPHS.find((g) => g.id === choice.graphId)
      if (!source) return
      const nextVersion = Math.max(...source.versions.map((v) => v.version), source.versions[0]?.version ?? 0) + 1
      const gid = `${source.id}-v${nextVersion}`
      const draft: RuleGraph = {
        ...source,
        id: gid,
        status: 'DRAFT',
        nodes: [...source.nodes.map((node) => ({ ...node })), emptyNode(key)],
        routings: [...source.routings],
        versions: [
          { version: nextVersion, label: `v${nextVersion}`, status: '초안', note: `v${source.versions[0]?.version ?? nextVersion - 1}에서 버전업` },
          ...source.versions,
        ],
      }
      setGraphs((prev) => [draft, ...prev])
      setExpanded((prev) => new Set(prev).add(gid))
      setSel({ graphId: gid, nodeKey: key })
    } else {
      const gid = `G-N${seq}`
      const g: RuleGraph = {
        id: gid, name: choice.name, scope: choice.scope, status: 'DRAFT',
        sourceClause: '(미지정)', entryNodeKey: key, nodes: [emptyNode(key)],
        routings: [{ from: key, onResult: 'MATCH', to: '' }],
        versions: [{ version: 1, label: 'v1', status: '초안', note: '신규 그래프' }],
      }
      setGraphs((prev) => [g, ...prev])
      setExpanded((prev) => new Set(prev).add(gid))
      setSel({ graphId: gid, nodeKey: key })
    }
    setChat([])
    setNewRuleOpen(false)
  }

  return (
    <>
      <div className="note" style={{ marginBottom: 16, display: 'flex', gap: 8, alignItems: 'center' }}>
        <Sparkles size={14} />
        룰은 <b>그래프 단위</b>로 묶여 버전으로 관리됩니다. 좌측에서 그래프를 펼쳐 노드를 선택해 세부 설정하고, 검증·활성은 그래프 단위로 진행합니다.
      </div>

      <div className="rule-draft-grid">
        {/* ── 좌: 초안 그래프 트리 (그래프 → 노드, 접기/펼치기) ── */}
        <div className="card">
          <div className="card-head"><h3>대기 중 룰그래프 ({graphs.length})</h3></div>
          <div className="stack" style={{ padding: 8, gap: 4 }}>
            {graphs.map((g) => {
              const open = expanded.has(g.id)
              const wv = workingVersion(g)
              return (
                <div key={g.id}>
                  <div
                    className="rule-graph-row" role="button" tabIndex={0}
                    onClick={() => toggle(g.id)} onKeyDown={activateOnEnterOrSpace(() => toggle(g.id))}
                  >
                    {open ? <ChevronDown size={14} className="muted" /> : <ChevronRight size={14} className="muted" />}
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div className="row" style={{ gap: 6 }}>
                        <b style={{ fontSize: 13 }}>{g.name}</b>
                        <span className="tag">{wv?.label} {wv?.status}</span>
                      </div>
                      <div className="text-meta">{g.scope} · 노드 {g.nodes.length} · {GRAPH_STATUS_LABEL[g.status]}</div>
                    </div>
                  </div>
                  {open && (
                    <div className="rule-node-list">
                      {g.nodes.map((n) => (
                        <div
                          key={n.nodeKey}
                          className={'rule-node-item' + (sel?.graphId === g.id && sel?.nodeKey === n.nodeKey ? ' selected' : '')}
                          role="button" tabIndex={0}
                          onClick={() => selectNode(g.id, n.nodeKey)}
                          onKeyDown={activateOnEnterOrSpace(() => selectNode(g.id, n.nodeKey))}
                        >
                          <div className="row" style={{ justifyContent: 'space-between', gap: 6 }}>
                            <span style={{ fontSize: 12.5 }}>{n.title}</span>
                            {n.origin === 'new' && <span className="tag ai" style={{ flexShrink: 0 }}>신규</span>}
                          </div>
                          <div className="text-meta">{n.nodeKey}</div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>

        {/* ── 중: 선택 노드 세부 설정 ── */}
        {selGraph && selNode ? (
          <NodeDetail key={`${selGraph.id}-${selNode.nodeKey}`} graph={selGraph} node={selNode} />
        ) : (
          <div className="card"><div className="card-body text-meta">좌측에서 노드를 선택하거나 신규 룰을 생성하세요.</div></div>
        )}

        {/* ── 우: 대화형 지시·수정 ── */}
        <div className="card" style={{ borderColor: 'var(--primary)' }}>
          <div className="card-head"><h3>대화형 지시·수정</h3></div>
          <div className="text-meta" style={{ padding: '0 16px' }}>자연어로 말하면 AI가 노드 필드를 직접 수정합니다.</div>
          <div className="stack" style={{ padding: 16, maxHeight: 420, overflowY: 'auto' }}>
            {chat.length === 0 && <div className="text-meta">예) "식대 30만원 초과면 사전승인 필요로 표시해줘" 처럼 입력하면 조건·액션이 채워집니다.</div>}
            {chat.map((m, i) => (
              <div key={i} style={{ alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start', maxWidth: '92%' }}>
                <div style={{
                  padding: '8px 12px', borderRadius: 'var(--radius-control)', fontSize: 12.5, whiteSpace: 'pre-line',
                  background: m.role === 'user' ? 'var(--primary)' : 'var(--surface-2)',
                  color: m.role === 'user' ? '#fff' : 'var(--text)',
                }}>{m.text}</div>
                {m.appliedNote && <div className="text-meta" style={{ color: 'var(--tone-green)', marginTop: 4 }}>✓ {m.appliedNote}</div>}
              </div>
            ))}
          </div>
          <div className="row" style={{ padding: 16, borderTop: '1px solid var(--border)', gap: 8 }}>
            <input placeholder='예) 금액 기준을 40만원으로 올려줘' value={input}
              onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') send() }} style={{ flex: 1 }} />
            <button className="btn primary" onClick={send} aria-label="전송"><Send size={14} /></button>
          </div>
        </div>
      </div>

      {newRuleOpen && (
        <NewRuleGraphModal graphs={RULE_GRAPHS} onClose={() => setNewRuleOpen(false)} onConfirm={createRule} />
      )}
    </>
  )
}

// 선택 노드 세부 설정 — key로 노드 전환 시 입력값 초기화. 검증/활성은 그래프 단위라 여기선 노드 편집만.
function NodeDetail({ graph, node }: { graph: RuleGraph; node: GraphNode }) {
  const [showCode, setShowCode] = useState(false)
  const [threshold, setThreshold] = useState<number | undefined>(node.plain.threshold)
  const plain = node.plain
  const wv = useMemo(() => workingVersion(graph), [graph])

  return (
    <div className="card">
      <div className="card-head">
        <div>
          <h3>{node.title}</h3>
          <div className="text-meta">{node.nodeKey} · {graph.name} · {wv?.label} {wv?.status}</div>
        </div>
        {node.origin === 'new' && <span className="tag ai">신규 노드</span>}
      </div>
      <div className="card-body stack">
        <div className="field">
          <label className="row" style={{ justifyContent: 'space-between' }}>제목 <button className="btn sm"><Wand2 size={11} /> 수정</button></label>
          <input defaultValue={node.title} placeholder="예) 식대 30만원 초과 사전승인" />
        </div>

        <div className="field">
          <label className="row" style={{ justifyContent: 'space-between' }}>
            이 Rule이 하는 일
            <button className="btn sm" onClick={() => setShowCode((v) => !v)}>
              <Code2 size={11} /> {showCode ? '코드 숨기기' : '개발자용 코드로 보기'}
            </button>
          </label>
          <div className="note" style={{ lineHeight: 2, color: 'var(--text)' }}>
            {plain.category && <>비용 분류가 <span className="tag ai">{plain.category}</span> 이고, 지출 금액이{' '}</>}
            {plain.threshold !== undefined && (
              <input type="number" value={threshold ?? plain.threshold} onChange={(e) => setThreshold(Number(e.target.value))}
                style={{ width: 130, display: 'inline-block', margin: '0 4px', padding: '4px 8px' }} />
            )}
            {plain.threshold !== undefined && <>원을 초과{plain.extraCondition ? '하고, ' : '하면 '}</>}
            {plain.extraCondition && <><b>{plain.extraCondition}</b> </>}
            {plain.action ? <>→ <b style={{ color: 'var(--primary)' }}>{plain.action}</b> 합니다.</> : <span className="text-meta">아직 설정되지 않았습니다 — 우측 대화 또는 코드로 조건·액션을 설정하세요.</span>}
          </div>
          {showCode && (
            <pre style={{ margin: '8px 0 0', padding: '10px 12px', background: 'var(--sidebar-bg)', color: '#d1fae5', borderRadius: 'var(--radius-control)', fontSize: 12, whiteSpace: 'pre-wrap' }}>
              {node.conditionExpr || '// 조건 미설정'}
            </pre>
          )}
        </div>

        <div className="field"><label>관련 조항</label><div><span className="tag">📎 {node.sourceClause || '(미지정)'}</span></div></div>
        <div className="field"><label>생성 이유 (AI 근거)</label><div className="note">{node.aiReason ?? '—'}</div></div>
      </div>
      <div className="modal-foot">
        <button className="btn">임시저장</button>
        <div className="spacer" />
        <span className="text-meta" style={{ alignSelf: 'center' }}>검증·활성은 그래프 단위</span>
        <button className="btn primary">이 그래프를 시뮬레이션으로 보내기 →</button>
      </div>
    </div>
  )
}

// 노드 상세보기 — 읽기 전용. 초안 탭의 노드 상세와 같은 구성이되 편집·저장은 없다.
import { useMemo, useState } from 'react'
import { Code2 } from 'lucide-react'
import { describeDsl, nodeStatusLabel, nodeStatusTone } from './data/graphApi'
import type { GraphNode, RuleGraph } from './data/ruleConsoleMock'

export function NodeDetailRead({ graph, node }: { graph: RuleGraph; node: GraphNode }) {
  const [showCode, setShowCode] = useState(false)
  const routes = graph.routings.filter((route) => route.from === node.nodeKey)
  const action = node.actionDetail ?? {}
  const titleOf = (nodeKey: string) => graph.nodes.find((candidate) => candidate.nodeKey === nodeKey)?.title ?? nodeKey

  const naturalCondition = useMemo(() => {
    try { return node.conditionExpr.trim() ? describeDsl(JSON.parse(node.conditionExpr)) : '조건이 아직 설정되지 않았습니다.' }
    catch { return node.conditionExpr }
  }, [node.conditionExpr])

  return <div className="card">
    <div className="card-head">
      <div><h3>{node.title}</h3><div className="text-meta">{node.nodeKey} · {graph.scope} · v{graph.version ?? 1}</div></div>
      <span className={'tag ' + nodeStatusTone(node.workflowStatus)}>{nodeStatusLabel(node.workflowStatus)}</span>
    </div>
    <div className="card-body stack">
      <div className="field"><label>제목</label><input value={node.title} readOnly /></div>
      <div className="field"><label>설명</label><textarea rows={3} value={node.description || '등록된 설명이 없습니다.'} readOnly /></div>

      <div className="field">
        <label>이 Rule이 하는 일</label>
        <div className="note" style={{ lineHeight: 1.7, color: 'var(--text)', whiteSpace: 'pre-line' }}>{naturalCondition}</div>
        <div className="dsl-disclosure" role="button" tabIndex={0} onClick={() => setShowCode((value) => !value)}>
          <Code2 size={13} /> DSL 코드 {showCode ? '접기' : '펼치기'} <span>{showCode ? '⌃' : '⌄'}</span>
        </div>
        {showCode && <textarea rows={7} value={node.conditionExpr} readOnly style={{ fontFamily: 'monospace' }} />}
      </div>

      <div className="field"><label>액션</label><div className="grid-2" style={{ gap: 8 }}>
        <input value={action.decision || '결정 미설정'} readOnly aria-label="결정" />
        <input value={action.severity || '심각도 미설정'} readOnly aria-label="심각도" />
        <input value={action.flag || '플래그 없음'} readOnly aria-label="플래그" />
        <input value={action.note || '처리 안내 없음'} readOnly aria-label="처리 안내/메모" />
        <input value={action.approver || '확인·승인 주체 미지정'} readOnly aria-label="확인·승인 주체" />
        <input value={`평가 우선순위 ${node.priority ?? 0}`} readOnly aria-label="평가 우선순위" />
      </div></div>

      <div className="field">
        <label>라우팅</label>
        <div className="stack" style={{ gap: 8 }}>
          {routes.length === 0 && <div className="text-meta">등록된 라우팅이 없습니다. 현재 노드의 액션으로 종료됩니다.</div>}
          {routes.map((route, index) => <div className="routing-row" key={`${route.onResult}-${index}`}>
            <span className="routing-order" title="라우팅 우선순위">#{route.priority ?? index}</span>
            <span className={'tag ' + (route.onResult === 'MATCH' ? 'ok' : '')}>{route.onResult}</span>
            <span className="text-meta">→</span>
            <b style={{ fontSize: 12.5 }}>{route.to ? titleOf(route.to) : '종료'}</b>
          </div>)}
        </div>
      </div>

      <div className="field" style={{ marginBottom: 0 }}>
        <label>생성 이유 · 근거</label>
        <div className="note">
          <div>{node.aiReason || '생성 이유가 아직 입력되지 않았습니다.'}</div>
          {node.sourceClause && <a href="/governance" style={{ display: 'inline-block', marginTop: 8 }}>📎 관련 조항: {node.sourceClause}</a>}
        </div>
      </div>
    </div>
    <div className="modal-foot" style={{ justifyContent: 'flex-start' }}><span className="text-meta">읽기 전용 — 수정은 초안 그래프 탭에서 진행합니다.</span></div>
  </div>
}

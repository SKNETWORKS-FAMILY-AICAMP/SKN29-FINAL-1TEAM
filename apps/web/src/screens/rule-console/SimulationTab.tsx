// Tab2 — 시뮬레이션 검증 (그래프 단위). 검증할 룰그래프를 선택해 과거 이력으로 시뮬레이션한다.
//  매칭/오탐율/검토감소·분류차이·Agent 보고서는 모두 선택한 "그래프"의 결과다.
import { useState } from 'react'
import { won } from '../../lib/format'
import {
  GRAPH_STATUS_LABEL, SIM_AGENT_ROWS, SIM_AGENT_SUMMARY, SIM_DIFF_ROWS, SIM_REPORT, SIM_RUN_META,
  simulatableGraphs, workingVersion, type GraphSim, type SimAgentRow,
} from './data/ruleConsoleMock'
import { RuleGraphExplorer, RuleGraphMini } from './RuleGraphView'
import { RuleTreeExplorer, RuleTreeMini } from './RuleTreeView'

type VizMode = 'tree' | 'graph'
const DEFAULT_SIM: GraphSim = { matched: 356, fpRate: 0.051, reviewReduction: 0.27, sampleSize: SIM_RUN_META.sampleSize, ranAt: SIM_RUN_META.ranAt }

export function SimulationTab() {
  const graphs = simulatableGraphs()
  const [graphId, setGraphId] = useState(graphs[0]?.id ?? '')
  const [vizMode, setVizMode] = useState<VizMode>('tree')
  const [explorerOpen, setExplorerOpen] = useState(false)

  const g = graphs.find((x) => x.id === graphId) ?? graphs[0]
  if (!g) return <div className="card"><div className="card-body text-meta">시뮬레이션할 초안/시뮬 그래프가 없습니다.</div></div>
  const sim = g.sim ?? DEFAULT_SIM
  const ran = !!g.sim

  return (
    <>
      <div className="note" style={{ marginBottom: 16 }}>
        💡 검증은 <b>그래프 단위</b>입니다. 그래프를 선택해 과거 이력으로 시뮬레이션하고, 결과를 검토한 뒤 그래프를 승인대기로 전환합니다.
      </div>

      {/* 검증할 룰그래프 선택 */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-head"><h3>검증할 룰그래프 선택</h3><span className="text-meta">{graphs.length}개 대상</span></div>
        <div className="card-body" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 12 }}>
          {graphs.map((x) => {
            const wv = workingVersion(x)
            return (
              <label key={x.id} className="row" style={{
                gap: 8, alignItems: 'flex-start', padding: 12, border: '1px solid var(--border)',
                borderRadius: 'var(--radius-control)', background: x.id === g.id ? 'var(--primary-soft)' : undefined, cursor: 'pointer',
              }}>
                <input type="radio" checked={x.id === g.id} onChange={() => setGraphId(x.id)} style={{ marginTop: 3 }} />
                <div style={{ minWidth: 0 }}>
                  <div className="row" style={{ gap: 6 }}><b style={{ fontSize: 12.5 }}>{x.name}</b><span className="tag">{wv?.label}</span></div>
                  <div className="text-meta">{x.scope} · 노드 {x.nodes.length} · {GRAPH_STATUS_LABEL[x.status]}</div>
                </div>
              </label>
            )
          })}
        </div>
      </div>

      {/* 그래프 구조 시각화 (노드 로스터) */}
      <div className="row" style={{ gap: 8, marginBottom: 8 }}>
        <button className={'btn sm' + (vizMode === 'tree' ? ' primary' : '')} onClick={() => setVizMode('tree')}>트리 구조</button>
        <button className={'btn sm' + (vizMode === 'graph' ? ' primary' : '')} onClick={() => setVizMode('graph')}>그래프 구조</button>
      </div>
      <div style={{ marginBottom: 16 }}>
        {vizMode === 'tree' ? <RuleTreeMini onExpand={() => setExplorerOpen(true)} /> : <RuleGraphMini onExpand={() => setExplorerOpen(true)} />}
      </div>
      {explorerOpen && (vizMode === 'tree'
        ? <RuleTreeExplorer onClose={() => setExplorerOpen(false)} />
        : <RuleGraphExplorer onClose={() => setExplorerOpen(false)} />)}

      <div className="row" style={{ justifyContent: 'space-between', marginBottom: 8 }}>
        <span className="text-meta">
          <b>{g.name}</b> — 과거 이력 {sim.sampleSize.toLocaleString('ko-KR')}건으로 시뮬레이션 {ran ? `완료 (${sim.ranAt})` : '미실행 — ▶ 다시 실행으로 재검증'}
        </span>
        <button className="btn sm">↻ 다시 실행</button>
      </div>

      <div className="kpi-grid" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
        <div className="kpi"><div className="label">그래프 매칭 건수</div><div className="value">{sim.matched}건</div></div>
        <div className="kpi"><div className="label">평균 오탐율 (FP)</div><div className="value">{(sim.fpRate * 100).toFixed(1)}%</div></div>
        <div className="kpi warn"><div className="label">예상 검토 감소량</div><div className="value">{(sim.reviewReduction * 100).toFixed(0)}%</div></div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-head"><h3>분류 차이 시각화 — 그래프 적용 전/후</h3></div>
        <table className="table">
          <thead><tr><th>적용 노드</th><th>거래일자</th><th>가맹점</th><th className="num">금액</th><th>기존 처리</th><th>적용 시</th><th>차이</th></tr></thead>
          <tbody>
            {SIM_DIFF_ROWS.map((r, i) => (
              <tr key={i}>
                <td><span className="tag ai">{r.rule}</span></td>
                <td>{r.date}</td><td>{r.merchant}</td><td className="num">{won(r.amount)}</td>
                <td className="text-meta">{r.before}</td><td><b>{r.after}</b></td>
                <td>{r.majorDiff ? <span className="tag warn">주요 차이</span> : <span className="text-meta">-</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-head">
          <h3>🤖 Agent 검토 보고서 — 판단이 달라진 건 검토</h3>
          <span className="tag ai">사람 확인 필요 {SIM_AGENT_ROWS.filter((r) => r.verdict === 'check').length}건</span>
        </div>
        <div className="card-body stack" style={{ gap: 16 }}>
          <div className="text-meta">{SIM_REPORT.summary}</div>
          <div>
            <div style={{ fontWeight: 700, marginBottom: 8 }}>① 자동분류되어 승인대기로 전환된 건 ({SIM_AGENT_ROWS.filter((r) => r.group === 'auto').length}건)</div>
            <div className="stack">{SIM_AGENT_ROWS.filter((r) => r.group === 'auto').map((r) => <AgentReportRow key={r.merchant} row={r} />)}</div>
          </div>
          <div>
            <div style={{ fontWeight: 700, marginBottom: 8 }}>② 이전 판단과 다르게 분류된 건 ({SIM_AGENT_ROWS.filter((r) => r.group === 'reclassified').length}건)</div>
            <div className="stack">{SIM_AGENT_ROWS.filter((r) => r.group === 'reclassified').map((r) => <AgentReportRow key={r.merchant} row={r} />)}</div>
          </div>
          <div className="note"><b>종합 권고</b> — {SIM_AGENT_SUMMARY}</div>
        </div>
      </div>

      <div className="row" style={{ gap: 8, marginTop: 16, justifyContent: 'flex-end' }}>
        <button className="btn reject">그래프 반려 (재작성 요청)</button>
        <button className="btn approve">이 그래프를 승인대기로 전환 →</button>
      </div>
    </>
  )
}

function AgentReportRow({ row }: { row: SimAgentRow }) {
  const ok = row.verdict === 'ok'
  return (
    <div style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius-control)', padding: '10px 12px', background: 'var(--surface-2)' }}>
      <div className="row" style={{ justifyContent: 'space-between', gap: 8 }}>
        <span className="row" style={{ gap: 8 }}><b>{row.merchant}</b><span className="text-meta">{won(row.amount)}</span><span className="tag ai">{row.rule}</span></span>
        {ok ? <span className="tag ok">✅ Rule 정상 동작</span> : <span className="tag warn">⚠ 사람 확인 필요</span>}
      </div>
      <div className="text-meta" style={{ marginTop: 6, lineHeight: 1.6 }}>{row.note}</div>
    </div>
  )
}

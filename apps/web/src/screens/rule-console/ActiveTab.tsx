// Tab3 — Active 그래프 · 버전 이력 (그래프 단위). 승인대기 버전 승인(ACTIVE 전환) / 과거 버전 롤백.
import { useState } from 'react'
import { Lock, RotateCcw } from 'lucide-react'
import { useRole } from '../../context/RoleContext'
import { useAuth } from '../../context/AuthContext'
import { useCan } from '../../lib/capabilities'
import { ROLE_LABEL } from '../../types/domain'
import { activateRule, rollbackRule } from '../../api/ruleService'
import { graphsByStatus, type GraphVersion, type RuleGraph } from './data/ruleConsoleMock'

const todayKST = () => new Date().toISOString().slice(0, 10)

export function ActiveTab() {
  const graphs = graphsByStatus('ACTIVE')
  const [graphId, setGraphId] = useState(graphs[0]?.id ?? '')
  const g = graphs.find((x) => x.id === graphId) ?? graphs[0]
  if (!g) return <div className="card"><div className="card-body text-meta">활성 상태의 룰그래프가 없습니다.</div></div>

  return (
    <>
      {graphs.length > 1 && (
        <div className="filter-bar">
          {graphs.map((x) => (
            <button key={x.id} className={'btn sm' + (x.id === g.id ? ' primary' : '')} onClick={() => setGraphId(x.id)}>{x.name}</button>
          ))}
        </div>
      )}
      <ActiveGraphPanel key={g.id} graph={g} />
    </>
  )
}

function ActiveGraphPanel({ graph }: { graph: RuleGraph }) {
  const { role } = useRole()
  const { user } = useAuth()
  const canApprove = useCan()('rule_activate') // ACTIVE 전환/롤백 권한
  const approverName = user?.name ?? ROLE_LABEL[role]

  const [versions, setVersions] = useState<GraphVersion[]>(graph.versions)
  const [busy, setBusy] = useState(false)
  const current = versions.find((v) => v.status === '현재 활성')
  const pending = versions.find((v) => v.status === '승인대기')
  const totalNodes = graph.nodes.length

  const promote = async (label: string) => {
    setBusy(true)
    await activateRule(graph.id)
    setVersions((prev) => prev.map((v) => {
      if (v.label === label) return { ...v, status: '현재 활성', approvedAt: todayKST(), approver: approverName }
      if (v.status === '현재 활성') return { ...v, status: '과거' }
      return v
    }))
    setBusy(false)
  }
  const rollback = async (label: string) => { await rollbackRule(graph.id); await promote(label) }

  return (
    <>
      <div className="row" style={{ justifyContent: 'space-between', marginBottom: 16 }}>
        <div>
          <h2 style={{ fontSize: 15 }}>{graph.name} · 버전 이력</h2>
          <div className="text-meta">{graph.scope} · {graph.sourceClause}</div>
        </div>
        <span className="tag ok">현재 ACTIVE · {current?.label ?? '-'}</span>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-body row" style={{ justifyContent: 'space-between' }}>
          <div><b>{graph.name}</b><div className="text-meta">노드 {totalNodes}개 · entry {graph.entryNodeKey}</div></div>
          <div className="row" style={{ gap: 24 }}>
            <div style={{ textAlign: 'right' }}><div className="text-meta">총 버전</div><b>{versions.length}개</b></div>
            <div style={{ textAlign: 'right' }}><div className="text-meta">현재 매칭(월)</div><b>{current?.matched ?? '-'}건</b></div>
            <div style={{ textAlign: 'right' }}><div className="text-meta">현재 오탐율</div><b>{current?.fpRate !== undefined ? (current.fpRate * 100).toFixed(1) + '%' : '-'}</b></div>
          </div>
        </div>
      </div>

      {pending && (
        <div className="card" style={{ borderColor: 'var(--tone-orange)', marginBottom: 16 }}>
          <div className="card-head">
            <h3>{pending.label} (승인 대기) <span className="tag warn" style={{ marginLeft: 8 }}>승인대기</span></h3>
            {pending.note && <span className="text-meta">{pending.note}</span>}
          </div>
          <div className="card-body">
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 12 }}>
              <div className="kpi"><div className="label">매칭 건수</div><div className="value">{pending.matched ?? '-'}건</div></div>
              <div className="kpi"><div className="label">오탐율</div><div className="value">{pending.fpRate !== undefined ? (pending.fpRate * 100).toFixed(1) + '%' : '-'}</div></div>
              <div className="kpi"><div className="label">개선폭 (현행 대비)</div><div className="value" style={{ color: 'var(--tone-green)' }}>
                {(pending.fpRate !== undefined && current?.fpRate !== undefined) ? ((pending.fpRate - current.fpRate) * 100).toFixed(1) + '%p' : '-'}
              </div></div>
            </div>
            <div className="row" style={{ justifyContent: 'space-between', background: 'var(--surface-2)', borderRadius: 'var(--radius-control)', padding: 12 }}>
              <div>
                <b style={{ fontSize: 12.5 }}>ACTIVE 전환 권한: 룰 활성(rule_activate)</b>
                <div className="text-meta">현재 계정: {ROLE_LABEL[role]} — {canApprove ? '승인 권한 있음' : '승인 권한 없음'}</div>
              </div>
              <button className="btn primary" disabled={!canApprove || busy} onClick={() => promote(pending.label)}>
                {!canApprove && <Lock size={12} />} 승인 (ACTIVE 전환)
              </button>
            </div>
            <p className="text-meta" style={{ marginTop: 8 }}>
              ※ 승인 즉시 {pending.label}가 그래프의 ACTIVE 버전으로 전환되고, 이전 활성 버전은 과거로 이동합니다(롤백 가능).
            </p>
          </div>
        </div>
      )}

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-head"><h3>버전별 지표 요약</h3></div>
        <table className="table">
          <thead><tr><th>버전</th><th>승인일</th><th>승인자</th><th className="num">매칭 건수</th><th>오탐율</th><th>상태</th><th>처리</th></tr></thead>
          <tbody>
            {versions.map((v) => (
              <tr key={v.label}>
                <td><b>{v.label}</b></td>
                <td className="text-meta">{v.approvedAt ?? '-'}</td>
                <td className="text-meta">{v.approver ?? '-'}</td>
                <td className="num">{v.matched ?? '-'}건</td>
                <td>{v.fpRate !== undefined ? (v.fpRate * 100).toFixed(1) + '%' : '-'}</td>
                <td><span className={'tag' + (v.status === '현재 활성' ? ' ok' : v.status === '승인대기' ? ' ai' : '')}>{v.status}</span></td>
                <td>{v.status === '과거' && (
                  <button className="btn sm" disabled={busy || !canApprove} onClick={() => rollback(v.label)}><RotateCcw size={11} /> 롤백</button>
                )}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <div className="card-head"><h3>현재 활성 버전({current?.label ?? '-'}) 그래프 로직</h3></div>
        <div className="card-body stack">
          {graph.nodes.map((n) => (
            <div key={n.nodeKey}>
              <div className="text-meta" style={{ marginBottom: 4 }}>{n.nodeKey} · {n.title}</div>
              <pre style={{ margin: 0, padding: '8px 12px', background: 'var(--sidebar-bg)', color: '#d1fae5', borderRadius: 'var(--radius-control)', fontSize: 12, whiteSpace: 'pre-wrap' }}>{n.conditionExpr}</pre>
            </div>
          ))}
        </div>
      </div>
    </>
  )
}

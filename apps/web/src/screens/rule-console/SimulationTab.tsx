// Tab2 — 시뮬레이션 검토 (v5 그래프 구조 / v6 트리 구조를 토글로 둘 다 제공, 추후 팀 결정 시 하나로 정리 예정)
import { useState } from 'react'
import { won } from '../../lib/format'
import {
  BATCH_CANDIDATES, SIM_DIFF_ROWS, SIM_KPI, SIM_REPORT, SIM_RUN_META, type BatchCandidate,
} from './data/ruleConsoleMock'
import { RuleGraphExplorer, RuleGraphMini } from './RuleGraphView'
import { RuleTreeExplorer, RuleTreeMini } from './RuleTreeView'

type VizMode = 'tree' | 'graph'

export function SimulationTab() {
  const [candidates, setCandidates] = useState<BatchCandidate[]>(BATCH_CANDIDATES)
  const [vizMode, setVizMode] = useState<VizMode>('tree')
  const [explorerOpen, setExplorerOpen] = useState(false)

  const toggle = (id: string) => setCandidates((prev) => prev.map((c) => (c.id === id ? { ...c, checked: !c.checked } : c)))
  const selectedCount = candidates.filter((c) => c.checked).length

  return (
    <>
      <div className="note" style={{ marginBottom: 16 }}>
        💡 v5/v6 반영사항: 다중 Rule 배치 온보딩 + 그래프(v5) / 트리(v6) 구조 중 택1 예정 — 지금은 토글로 둘 다 볼 수 있습니다.
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-head">
          <h3>검토 대상 Rule 선택 (배치 온보딩)</h3>
          <span className="text-meta">선택 {selectedCount}건 · 미선택 {candidates.length - selectedCount}건</span>
        </div>
        <div className="card-body" style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12 }}>
          {candidates.map((c) => (
            <label
              key={c.id}
              className="row"
              style={{
                gap: 8, alignItems: 'flex-start', padding: 12, border: '1px solid var(--border)',
                borderRadius: 'var(--radius-control)', background: c.checked ? 'var(--primary-soft)' : undefined, cursor: 'pointer',
              }}
            >
              <input type="checkbox" checked={c.checked} onChange={() => toggle(c.id)} style={{ marginTop: 2 }} />
              <div>
                <b style={{ fontSize: 12.5 }}>{c.id}</b>
                <div className="text-meta">{c.label}</div>
              </div>
            </label>
          ))}
        </div>
      </div>

      <div className="row" style={{ gap: 8, marginBottom: 8 }}>
        <button className={'btn sm' + (vizMode === 'tree' ? ' primary' : '')} onClick={() => setVizMode('tree')}>트리 구조(v6)</button>
        <button className={'btn sm' + (vizMode === 'graph' ? ' primary' : '')} onClick={() => setVizMode('graph')}>그래프 구조(v5)</button>
      </div>
      <div style={{ marginBottom: 16 }}>
        {vizMode === 'tree'
          ? <RuleTreeMini onExpand={() => setExplorerOpen(true)} />
          : <RuleGraphMini onExpand={() => setExplorerOpen(true)} />}
      </div>
      {explorerOpen && (
        vizMode === 'tree'
          ? <RuleTreeExplorer onClose={() => setExplorerOpen(false)} />
          : <RuleGraphExplorer onClose={() => setExplorerOpen(false)} />
      )}

      <div className="row" style={{ justifyContent: 'space-between', marginBottom: 8 }}>
        <span className="text-meta">과거 이력 샘플 {SIM_RUN_META.sampleSize.toLocaleString('ko-KR')}건으로 {selectedCount}개 Rule 배치 시뮬레이션 실행됨 ({SIM_RUN_META.ranAt})</span>
        <button className="btn sm">↻ 다시 실행</button>
      </div>

      <div className="kpi-grid" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
        <div className="kpi"><div className="label">배치 전체 매칭 건수</div><div className="value">{SIM_KPI.matched}건</div></div>
        <div className="kpi"><div className="label">평균 오탐율 (FP)</div><div className="value">{(SIM_KPI.falsePositiveRate * 100).toFixed(1)}%</div></div>
        <div className="kpi warn"><div className="label">예상 검토 감소량</div><div className="value">{(SIM_KPI.reviewReduction * 100).toFixed(0)}%</div></div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-head"><h3>분류 차이 시각화 — 배치 내 어떤 Rule이 적용됐는지 포함</h3></div>
        <table className="table">
          <thead><tr><th>적용 Rule</th><th>거래일자</th><th>가맹점</th><th className="num">금액</th><th>기존 처리</th><th>Rule 적용 시</th><th>차이</th></tr></thead>
          <tbody>
            {SIM_DIFF_ROWS.map((r, i) => (
              <tr key={i}>
                <td><span className="tag ai">{r.rule}</span></td>
                <td>{r.date}</td>
                <td>{r.merchant}</td>
                <td className="num">{won(r.amount)}</td>
                <td className="text-meta">{r.before}</td>
                <td><b>{r.after}</b></td>
                <td>{r.majorDiff ? <span className="tag warn">주요 차이</span> : <span className="text-meta">-</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-head"><h3>🤖 Agent 검토 보고서 (배치)</h3><span className="tag ai">2건 승인 권장 · 1건 검토 필요</span></div>
        <div className="card-body stack">
          <div><div className="text-meta" style={{ marginBottom: 4 }}>배치 요약</div><div>{SIM_REPORT.summary}</div></div>
          <div>
            <div className="text-meta" style={{ marginBottom: 4 }}>{vizMode === 'tree' ? '트리 충돌 분석' : '그래프 충돌 분석'}</div>
            <div>{vizMode === 'tree' ? SIM_REPORT.conflictTree : SIM_REPORT.conflictGraph}</div>
          </div>
          <div><div className="text-meta" style={{ marginBottom: 4 }}>권고 의견</div><div>{SIM_REPORT.recommendation}</div></div>
        </div>
      </div>

      <div className="row" style={{ gap: 8, marginTop: 16, justifyContent: 'flex-end' }}>
        <button className="btn reject">전체 반려 (재작성 요청)</button>
        <button className="btn return">R-103만 제외하고 진행</button>
        <button className="btn approve">선택 {selectedCount}건 일괄 승인대기로 전환 →</button>
      </div>
    </>
  )
}

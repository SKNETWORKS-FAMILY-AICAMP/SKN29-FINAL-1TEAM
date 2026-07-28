// Tab2 — 시뮬레이션 검토 (Figma v9 · 다중 Rule 배치 · 트리 구조 · Agent 검토 보고서)
import { useState } from 'react'
import { ChevronDown, ChevronUp, RefreshCw } from 'lucide-react'
import { won } from '../../lib/format'
import { BATCH_CANDIDATES, SIM_KPI, SIM_RUN_META, type BatchCandidate } from './data/ruleConsoleMock'
import { RuleTreeMini, RuleTreeExplorer } from './RuleTreeView'

// Figma v9 Agent 검토 보고서 mock 데이터
const AGENT_REPORT_AUTO = [
  { merchant: '아근식당', amount: 320000, rule: 'R-102', note: '30만원 초과 기준에 정확히 부합하고, 과거 유사 식대 승인 건과 판단이 일치합니다. 사람 확인 없이 자동 승인대기 전환이 적절합니다.', autoApprove: true },
  { merchant: '거래처 접대', amount: 412000, rule: 'R-105', note: '접대비 3만원 초과 기준은 충족하지만, 참석자 4인 중 2인 내부 2인은 실제 목적이 맞는지 애매합니다. 참석자 구성원을 확인해주세요.', autoApprove: false },
  { merchant: '조카 결혼식', amount: 250000, rule: 'R-103', note: '경조사비 20만원 초과 기준은 충족하지만, 사급 경조사비 지급대상 및 한적 범위에 "조카"가 포함되는지 명확하지 않습니다. 인사규정 확인이 필요합니다.', autoApprove: false },
]

const AGENT_REPORT_DIFF = [
  { merchant: '송년회 회식비', amount: 450000, rule: 'R-105 적용', prevRule: 'R-102 적용', note: '이전에는 "접대"로 분류됐으나, 이번 건은 외부 가맹점에서 참석자가 집합되어 "접대"로 재분류됐습니다. 최근 규정 "외부인 접대 시 접대비 적용" 기준 변경이지, 그리고 과거 유사 건 검토도 소급 재검토가 필요합니다.', flagRed: true },
]

const DIFF_ROWS = [
  { merchant: '아근식당 · 320,000원', rule: 'R-102', prevAction: '회계담당자 직접 검토', nextAction: '자동으로 승인 대기 처리', highlight: false },
  { merchant: '거래처 접대 · 412,000원', rule: 'R-105', prevAction: '회계담당자 직접 검토', nextAction: '자동으로 승인 대기 처리', highlight: false },
  { merchant: '조카 결혼식 · 250,000원', rule: 'R-103', prevAction: '회계담당자 직접 검토', nextAction: '자동으로 승인 대기 처리', highlight: false },
  { merchant: '부서 회식 · 340,000원', rule: 'R-102', prevAction: '회계담당자 직접 검토', nextAction: '변화 없음 (그대로 검토)', highlight: true },
]

export function SimulationTab() {
  const [candidates, setCandidates] = useState<BatchCandidate[]>(BATCH_CANDIDATES)
  const [explorerOpen, setExplorerOpen] = useState(false)
  const [showDiff, setShowDiff] = useState(false)

  const toggle = (id: string) => setCandidates((prev) => prev.map((c) => (c.id === id ? { ...c, checked: !c.checked } : c)))
  const selectedCount = candidates.filter((c) => c.checked).length
  const autoApproveCount = AGENT_REPORT_AUTO.filter((r) => r.autoApprove).length

  return (
    <>
      <div className="note" style={{ marginBottom: 16, fontSize: 12 }}>
        💡 v9 반영사항: Agent 검토 보고서를 단순 수치가 아닌, 건별 판단 근거와 요약으로 제공합니다.
      </div>

      {/* Rule 선택 (배치 온보딩) */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-head">
          <h3>검토 대상 Rule 선택 (배치 온보딩)</h3>
          <span className="text-meta">선택 {selectedCount}건 · 미선택 {candidates.length - selectedCount}건</span>
        </div>
        <div className="card-body" style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 10 }}>
          {candidates.map((c) => (
            <label
              key={c.id}
              style={{
                display: 'flex', gap: 8, alignItems: 'flex-start', padding: '10px 12px',
                border: `1px solid ${c.checked ? 'var(--primary)' : 'var(--border)'}`,
                borderRadius: 'var(--radius-control)',
                background: c.checked ? 'var(--primary-soft)' : undefined,
                cursor: 'pointer',
              }}
            >
              <input type="checkbox" checked={c.checked} onChange={() => toggle(c.id)} style={{ marginTop: 2 }} />
              <div>
                <b style={{ fontSize: 12.5, color: c.checked ? 'var(--primary)' : 'var(--text)' }}>{c.id}</b>
                <div className="text-meta" style={{ fontSize: 11, marginTop: 2 }}>{c.label}</div>
              </div>
            </label>
          ))}
        </div>
      </div>

      {/* Rule 실행 흐름도 (트리) */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-head">
          <h3>Rule 실행 흐름도</h3>
          <span className="text-meta">신규 {selectedCount}건 · 충돌 확인 필요 2건</span>
          <button className="btn sm" style={{ marginLeft: 'auto' }} onClick={() => setExplorerOpen(true)}>심지 펼쳐서 보드라요 🌳</button>
        </div>
        <div className="card-body" style={{ padding: 12 }}>
          <RuleTreeMini onExpand={() => setExplorerOpen(true)} />
        </div>
      </div>
      {explorerOpen && <RuleTreeExplorer onClose={() => setExplorerOpen(false)} />}

      {/* 시뮬레이션 메타 + 재실행 */}
      <div className="row" style={{ justifyContent: 'space-between', marginBottom: 10 }}>
        <span className="text-meta">과거 이력 샘플 {SIM_RUN_META.sampleSize.toLocaleString('ko-KR')}건으로 {selectedCount}개 Rule 배치 시뮬레이션 실행됨 ({SIM_RUN_META.ranAt})</span>
        <button className="btn sm"><RefreshCw size={12} /> 다시 실행</button>
      </div>

      {/* KPI */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 16 }}>
        <div className="kpi"><div className="label">배치 전체 적중 건수</div><div className="value">{SIM_KPI.matched}건</div></div>
        <div className="kpi"><div className="label">평균 오탐율 (FP)</div><div className="value">{(SIM_KPI.falsePositiveRate * 100).toFixed(1)}%</div></div>
        <div className="kpi" style={{ borderTop: '3px solid var(--tone-green)' }}><div className="label">예상 검토 감소량</div><div className="value" style={{ color: 'var(--tone-green)' }}>-{(SIM_KPI.reviewReduction * 100).toFixed(0)}%</div></div>
      </div>

      {/* Agent 검토 보고서 */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-head">
          <h3>🤖 Agent 검토 보고서 — 판단이 달라진 건 검토</h3>
          <span className="text-meta" style={{ cursor: 'pointer' }}>사람 확인 필요 {AGENT_REPORT_AUTO.filter(r => !r.autoApprove).length}건</span>
        </div>
        <div className="card-body stack-lg">
          {/* 섹션 1: 직접검토 → 승인대기 전환 */}
          <div>
            <div style={{ fontWeight: 700, marginBottom: 4, fontSize: 13 }}>① 직접검토→ 승인대기로 전환된 건 ({AGENT_REPORT_AUTO.length}건)</div>
            <div className="text-meta" style={{ marginBottom: 10 }}>Rule이 이미 도착했는지 기준으로 판단하고, 사람 확인이 필요한 건은 아래를 보드라요.</div>
            <div className="stack">
              {AGENT_REPORT_AUTO.map((r, i) => (
                <div key={i} style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius-control)', padding: '12px 14px', background: 'var(--surface)' }}>
                  <div className="row" style={{ justifyContent: 'space-between', marginBottom: 6 }}>
                    <span style={{ fontWeight: 600, fontSize: 13 }}>{r.merchant} · {won(r.amount)}</span>
                    <div className="row" style={{ gap: 6 }}>
                      <span className="tag ai" style={{ fontSize: 11 }}>{r.rule}</span>
                      {r.autoApprove
                        ? <span className="tag ok" style={{ fontSize: 11 }}>✓ Rule 정상 적용</span>
                        : <span className="tag warn" style={{ fontSize: 11 }}>🙋 사람 확인 필요</span>}
                    </div>
                  </div>
                  <div className="text-meta" style={{ fontSize: 12 }}>{r.note}</div>
                </div>
              ))}
            </div>
          </div>

          {/* 섹션 2: 이전 판단과 다르게 분류 */}
          <div>
            <div style={{ fontWeight: 700, marginBottom: 4, fontSize: 13 }}>② 이전 판단과 다르게 분류된 건 ({AGENT_REPORT_DIFF.length}건)</div>
            <div className="text-meta" style={{ marginBottom: 10 }}>판단이 달라진 건을 변경하고, 소급 재검토가 필요합니다.</div>
            <div className="stack">
              {AGENT_REPORT_DIFF.map((r, i) => (
                <div key={i} style={{ border: `1px solid ${r.flagRed ? 'var(--tone-orange)' : 'var(--border)'}`, borderRadius: 'var(--radius-control)', padding: '12px 14px', background: r.flagRed ? 'var(--tone-orange-bg)' : 'var(--surface)' }}>
                  <div className="row" style={{ justifyContent: 'space-between', marginBottom: 6 }}>
                    <span style={{ fontWeight: 600, fontSize: 13 }}>{r.merchant} · {won(r.amount)}</span>
                    <div className="row" style={{ gap: 6 }}>
                      <span style={{ fontSize: 11, color: 'var(--muted)', textDecoration: 'line-through' }}>{r.prevRule}</span>
                      <span style={{ color: 'var(--muted)' }}>→</span>
                      <span className="tag ai" style={{ fontSize: 11 }}>{r.rule}</span>
                      {r.flagRed && <span className="tag warn" style={{ fontSize: 11 }}>🚩 특이 필요</span>}
                    </div>
                  </div>
                  <div className="text-meta" style={{ fontSize: 12 }}>{r.note}</div>
                </div>
              ))}
            </div>
          </div>

          <div style={{ padding: '10px 14px', background: 'var(--surface-2)', borderRadius: 'var(--radius-control)', fontSize: 12 }}>
            <span style={{ fontWeight: 600 }}>종합 권고:</span> {autoApproveCount}건 1(아근식당)만 즉시 승인대기 전환이 적절합니다. 나머지 {AGENT_REPORT_AUTO.length - autoApproveCount}건은 위 확인 사항을 검토한 후 개별적으로 처리해주세요.
          </div>
        </div>
      </div>

      {/* 무엇이 달라지나요 (diff) */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div
          className="card-head"
          style={{ cursor: 'pointer' }}
          role="button"
          tabIndex={0}
          onClick={() => setShowDiff((v) => !v)}
        >
          <h3>· 무엇이 달라지나요? (상세 변경 내역) {DIFF_ROWS.length}건</h3>
          <span className="text-meta row" style={{ gap: 4 }}>접기 {showDiff ? <ChevronUp size={13} /> : <ChevronDown size={13} />}</span>
        </div>
        {showDiff && (
          <table className="table">
            <thead>
              <tr>
                <th>가맹점 · 금액</th>
                <th>적용 Rule</th>
                <th>지금까지는</th>
                <th style={{ color: 'var(--primary)' }}>앞으로는</th>
              </tr>
            </thead>
            <tbody>
              {DIFF_ROWS.map((r, i) => (
                <tr key={i}>
                  <td style={{ fontWeight: 500, fontSize: 12 }}>{r.merchant}</td>
                  <td><span className="tag ai" style={{ fontSize: 11 }}>{r.rule}</span></td>
                  <td>
                    <span style={{ fontSize: 12, color: 'var(--muted)' }}>
                      🧑 {r.prevAction}
                    </span>
                  </td>
                  <td>
                    <span style={{ fontSize: 12, color: r.highlight ? 'var(--muted)' : 'var(--primary)', fontWeight: r.highlight ? 400 : 600 }}>
                      {r.highlight ? '🧑' : '⚡'} {r.nextAction}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* 하단 액션 버튼 */}
      <div className="row" style={{ gap: 8, justifyContent: 'space-between' }}>
        <button className="btn reject">전체 반려 (재작성 요청)</button>
        <button className="btn primary" style={{ padding: '8px 20px' }}>
          선택 {selectedCount}건 일괄 승인대기로 전환 →
        </button>
      </div>
    </>
  )
}

// S-04 Rule 콘솔 — 회계/운영(관리자). FR-UI-04, FR-RB-01~03, FR-RV-01~04
import { useState, type CSSProperties } from 'react'
import { Paperclip } from 'lucide-react'
import { rules } from '../data/mock'
import type { Rule } from '../types/domain'
import { pct } from '../lib/format'
import { activateOnEnterOrSpace } from '../lib/a11y'

type Tab = 'DRAFT' | 'SIMULATED' | 'ACTIVE'
const TAB_LABEL: Record<Tab, string> = { DRAFT: '초안 대기', SIMULATED: '시뮬레이션', ACTIVE: 'Active' }

export function RuleConsole() {
  const [tab, setTab] = useState<Tab>('DRAFT')
  const list = rules.filter((r) => r.status === tab)
  const [sel, setSel] = useState<Rule | null>(list[0] ?? null)

  const pick = (t: Tab) => {
    setTab(t)
    setSel(rules.find((r) => r.status === t) ?? null)
  }

  return (
    <>
      <div className="page-head">
        <span className="screen-id">S-04</span>
        <h1>Rule 콘솔</h1>
        <div className="sub">RAG로 추출된 조항 기반 Rule 초안을 시뮬레이션 검토 후 승인/수정/폐기/롤백합니다. (자동 승인 금지)</div>
      </div>

      <div className="filter-bar">
        {(['DRAFT', 'SIMULATED', 'ACTIVE'] as Tab[]).map((t) => (
          <button key={t} className={'btn' + (tab === t ? ' primary' : '')} onClick={() => pick(t)}>
            {TAB_LABEL[t]} ({rules.filter((r) => r.status === t).length})
          </button>
        ))}
        <div className="spacer" />
        <button className="btn">＋ 규정 문서 업로드</button>
      </div>

      <div className="split">
        <div className="card">
          <div className="card-head"><h3>{TAB_LABEL[tab]} 목록</h3></div>
          <table className="table">
            <thead><tr><th>Rule</th><th>출처 조항</th></tr></thead>
            <tbody>
              {list.map((r) => (
                <tr
                  key={r.id}
                  tabIndex={0}
                  className={sel?.id === r.id ? 'selected' : undefined}
                  onClick={() => setSel(r)}
                  onKeyDown={activateOnEnterOrSpace(() => setSel(r))}
                >
                  <td>{r.name}{r.version && <span className="tag" style={{ marginLeft: 8 }}>v{r.version}</span>}</td>
                  <td className="text-meta">{r.sourceClause}</td>
                </tr>
              ))}
              {list.length === 0 && <tr><td colSpan={2} className="muted">해당 상태의 Rule이 없습니다.</td></tr>}
            </tbody>
          </table>
        </div>

        {sel && (
          <div className="stack-lg">
            <div className="card">
              <div className="card-head"><h3>{sel.name}</h3></div>
              <div className="card-body stack">
                <div><span className="text-meta">condition</span><pre style={pre}>{sel.condition}</pre></div>
                <div><span className="text-meta">action</span><pre style={pre}>{sel.action}</pre></div>
                <div className="text-meta row" style={{ gap: 4 }}><Paperclip size={12} />{sel.sourceClause}</div>
              </div>
            </div>

            {/* 시뮬레이션 지표 3종 (FR-RV-01~02) */}
            {sel.sim && (
              <div className="grid-3">
                <div className="kpi"><div className="label">매칭 건수</div><div className="value">{sel.sim.matched}</div></div>
                <div className="kpi"><div className="label">오탐율</div><div className="value">{pct(sel.sim.falsePositiveRate)}</div></div>
                <div className="kpi"><div className="label">예상 검토 감소</div><div className="value">{pct(sel.sim.reviewReduction)}</div></div>
              </div>
            )}

            <div className="card">
              <div className="card-body row">
                {sel.status !== 'ACTIVE'
                  ? <button className="btn approve">승인 (ACTIVE 전환)</button>
                  : <button className="btn">롤백 (이전 버전 복원)</button>}
                <button className="btn">수정</button>
                <button className="btn reject">폐기</button>
                <div className="spacer" />
                <span className="text-meta">모든 변경은 audit_logs에 기록</span>
              </div>
            </div>
          </div>
        )}
      </div>
    </>
  )
}

const pre: CSSProperties = {
  margin: '4px 0 0', padding: '8px 12px', background: 'var(--surface-2)',
  border: '1px solid var(--border)', borderRadius: 'var(--radius-control)', fontSize: 'var(--text-meta)', whiteSpace: 'pre-wrap',
}

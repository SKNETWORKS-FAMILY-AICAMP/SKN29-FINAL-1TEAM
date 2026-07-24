// S-02 팀 취합·제출 — 팀장. FR-UI-02, FR-DA-07~08, FR-DB-03
import { useMemo, useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { anomalyTags, teamBudget } from '../data/mock'
import { CARD_TYPE_LABEL, type Settlement } from '../types/domain'
import { pct, won } from '../lib/format'
import { KpiCard } from '../components/ui/KpiCard'
import { SettlementDetailModal } from '../components/settlement/SettlementDetailModal'
import { reviewSettlement, submitSettlements } from '../api/settlementService'
import { useSettlements } from '../context/SettlementsContext'
import { activateOnEnterOrSpace } from '../lib/a11y'

export function TeamAggregation() {
  const { teamMembers, updateStatus } = useSettlements()
  const [onlyAnomaly, setOnlyAnomaly] = useState(false)
  const [selected, setSelected] = useState<Settlement | null>(null)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)

  const all = teamMembers.flatMap((m) => m.items)
  const stats = useMemo(() => {
    const anomalous = all.filter((i) => anomalyTags(i).length > 0).length
    return {
      members: teamMembers.length,
      total: all.reduce((s, i) => s + i.amount, 0),
      anomalous,
      normal: all.length - anomalous,
    }
  }, [all, teamMembers.length])

  const toggleMember = (name: string) => {
    const next = new Set(expanded)
    next.has(name) ? next.delete(name) : next.add(name)
    setExpanded(next)
  }

  const handleRowDecision = async (id: string, decision: 'RETURN' | 'REJECT') => {
    setBusy(true)
    const status = await reviewSettlement(id, decision)
    updateStatus(id, status)
    setBusy(false)
  }

  const submitIds = async (ids: string[]) => {
    if (ids.length === 0) return
    setBusy(true)
    const status = await submitSettlements(ids)
    ids.forEach((id) => updateStatus(id, status))
    setBusy(false)
  }

  const submitNormalOnly = () => submitIds(all.filter((i) => anomalyTags(i).length === 0 && i.status === 'DRAFT').map((i) => i.id))
  const confirmSubmitAll = () => submitIds(all.filter((i) => i.status === 'DRAFT').map((i) => i.id))

  const hasVisibleMember = teamMembers.some((m) =>
    (onlyAnomaly ? m.items.filter((i) => anomalyTags(i).length > 0) : m.items).length > 0
  )

  return (
    <>
      <div className="page-head row" style={{ justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <span className="screen-id">S-02</span>
          <h1>팀 취합·제출</h1>
          <div className="sub">정상 건은 접히고 이상 건만 강조됩니다. 이상 건은 개별 처리하고 나머지는 일괄 제출합니다.</div>
        </div>
        <span className="tag warn">마감 D-2</span>
      </div>

      <div className="kpi-grid">
        <KpiCard label="팀원 수" value={stats.members} unit="명" />
        <KpiCard label="총 취합액" value={won(stats.total)} />
        <KpiCard label="이상 건" value={stats.anomalous} unit="건" warn={stats.anomalous > 0} />
        <KpiCard label="정상 건" value={stats.normal} unit="건" />
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-head">
          <h3>팀 예산 현황 · 2026년 7월</h3>
          <span className="tag ok">잔여 {pct(1 - teamBudget.used / teamBudget.total)}</span>
        </div>
        <div className="card-body">
          <div className="row" style={{ justifyContent: 'space-between', marginBottom: 4 }}>
            <span className="text-meta">잔여 예산</span>
            <span className="text-meta">총 {won(teamBudget.total)}원 중 {won(teamBudget.used)}원 사용</span>
          </div>
          <div style={{ fontSize: 22, fontWeight: 700, color: 'var(--tone-green)', marginBottom: 8 }}>
            {won(teamBudget.total - teamBudget.used)}
          </div>
          <div style={{ height: 8, background: 'var(--surface-2)', borderRadius: 'var(--radius-pill)', overflow: 'hidden', marginBottom: 20 }}>
            <div style={{ width: pct(teamBudget.used / teamBudget.total), height: '100%', background: 'var(--tone-green)' }} />
          </div>

          <div className="text-meta" style={{ marginBottom: 12, fontWeight: 600 }}>항목별 잔여 예산</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12 }}>
            {teamBudget.categories.map((c) => {
              const rate = c.used / c.limit
              const remaining = c.limit - c.used
              const warn = rate >= 0.7
              const barColor = rate >= 0.9 ? 'var(--tone-red)' : rate >= 0.7 ? 'var(--tone-orange)' : 'var(--tone-green)'
              return (
                <div key={c.label} style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '12px 14px', background: warn ? 'var(--tone-red-bg)' : 'var(--surface)' }}>
                  <div className="row" style={{ justifyContent: 'space-between', marginBottom: 6 }}>
                    <span style={{ fontSize: 12, fontWeight: 600 }}>{c.label}</span>
                    <span style={{ fontSize: 11, fontWeight: 800, padding: '1px 6px', borderRadius: 999, background: barColor + '22', color: barColor }}>{pct(rate)}</span>
                  </div>
                  <div style={{ fontSize: 15, fontWeight: 700, color: warn ? 'var(--tone-red)' : 'var(--tone-green)', marginBottom: 6 }}>
                    잔여 {won(remaining)}
                  </div>
                  <div style={{ height: 5, background: 'var(--surface-2)', borderRadius: 'var(--radius-pill)', overflow: 'hidden', marginBottom: 4 }}>
                    <div style={{ width: pct(Math.min(rate, 1)), height: '100%', background: barColor, transition: 'width 0.3s' }} />
                  </div>
                  <div className="text-meta" style={{ fontSize: 10 }}>예산 {won(c.limit)}</div>
                </div>
              )
            })}
          </div>
        </div>
      </div>

      <div className="filter-bar">
        <label className="row" style={{ gap: 6 }}>
          <input type="checkbox" checked={onlyAnomaly} onChange={(e) => setOnlyAnomaly(e.target.checked)} />
          이상건만 보기
        </label>
        <div className="spacer" />
        <button className="btn" disabled={busy} onClick={confirmSubmitAll}>제출 확정</button>
        <button className="btn primary" disabled={busy || stats.normal === 0} onClick={submitNormalOnly}>
          이상건 제외 일괄제출 ({stats.normal}건)
        </button>
      </div>

      {!hasVisibleMember && (
        <div className="card">
          <div className="card-body text-meta">이상 건이 없습니다.</div>
        </div>
      )}

      <div className="stack" style={{ gap: 12 }}>
        {teamMembers.map((m) => {
          const visibleItems = onlyAnomaly ? m.items.filter((i) => anomalyTags(i).length > 0) : m.items
          if (visibleItems.length === 0) return null
          const isOpen = expanded.has(m.name) || onlyAnomaly
          const memberAnomaly = m.items.filter((i) => anomalyTags(i).length > 0).length
          return (
            <div className={'card' + (memberAnomaly > 0 ? ' anomaly' : '')} key={m.name}>
              <div
                className="card-head"
                role="button"
                tabIndex={0}
                aria-expanded={isOpen}
                style={{ cursor: 'pointer' }}
                onClick={() => toggleMember(m.name)}
                onKeyDown={activateOnEnterOrSpace(() => toggleMember(m.name))}
              >
                <h3 className="row" style={{ gap: 6 }}>
                  {isOpen ? <ChevronDown size={16} className="muted" /> : <ChevronRight size={16} className="muted" />}
                  {m.name}
                  <span className="text-meta" style={{ fontWeight: 500, marginLeft: 8 }}>
                    {m.items.length}건 · 이상 {memberAnomaly}건
                  </span>
                </h3>
                <span className="tag">{won(m.items.reduce((s, i) => s + i.amount, 0))}</span>
              </div>
              {isOpen && (
                <table className="table">
                  <thead>
                    <tr><th>거래일자</th><th>가맹점</th><th className="num">금액</th><th>카드구분</th><th>이상 사유</th><th>처리</th></tr>
                  </thead>
                  <tbody>
                    {visibleItems.map((i) => {
                      const tags = anomalyTags(i)
                      return (
                        <tr
                          key={i.id}
                          tabIndex={0}
                          onClick={() => setSelected(i)}
                          onKeyDown={activateOnEnterOrSpace(() => setSelected(i))}
                        >
                          <td>{i.date}</td>
                          <td>{i.merchant}</td>
                          <td className="num">{won(i.amount)}</td>
                          <td>{CARD_TYPE_LABEL[i.cardType]}</td>
                          <td>
                            {tags.length === 0
                              ? <span className="tag ok">정상</span>
                              : tags.map((t) => <span key={t} className="tag warn" style={{ marginRight: 4 }}>{t}</span>)}
                          </td>
                          <td onClick={(ev) => ev.stopPropagation()}>
                            {tags.length === 0 ? (
                              <span className="text-meta">일괄 대상</span>
                            ) : i.status !== 'DRAFT' ? (
                              <span className="text-meta">처리됨 · {i.status}</span>
                            ) : (
                              <div className="row">
                                <button className="btn sm return" disabled={busy} onClick={() => handleRowDecision(i.id, 'RETURN')}>보완요청</button>
                                <button className="btn sm reject" disabled={busy} onClick={() => handleRowDecision(i.id, 'REJECT')}>반려</button>
                              </div>
                            )}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              )}
            </div>
          )
        })}
      </div>

      {selected && (
        <SettlementDetailModal
          item={selected}
          onClose={() => setSelected(null)}
          onStatusChange={updateStatus}
        />
      )}
    </>
  )
}

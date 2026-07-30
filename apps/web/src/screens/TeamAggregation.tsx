// S-02 팀 취합·제출 — 팀장. FR-UI-02, FR-DA-07~08, FR-DB-03
import { useMemo, useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { anomalyTags, teamBudget } from '../data/mock'
import { CARD_TYPE_LABEL, type Settlement } from '../types/domain'
import { pct, won } from '../lib/format'
import { KpiCard } from '../components/ui/KpiCard'
import { SettlementDetailModal } from '../components/settlement/SettlementDetailModal'
import { decideTeamSettlement, submitSettlements } from '../api/settlementService'
import { useSettlements } from '../context/SettlementsContext'
import { useAuth } from '../context/AuthContext'
import { useCan } from '../lib/capabilities'
import { activateOnEnterOrSpace } from '../lib/a11y'

export function TeamAggregation() {
  const { teamMembers, updateStatus } = useSettlements()
  const { user } = useAuth()
  const teamName = user?.dept ?? '내 팀' // 로그인 사용자의 소속 팀(재무회계팀 / AI·개발팀 등)
  const canManage = useCan()('team_aggregate') // 팀 취합 권한 보유자만 개별 건 조회·처리
  const [onlyAnomaly, setOnlyAnomaly] = useState(false)
  const [memberFilter, setMemberFilter] = useState<Set<string>>(new Set())
  const [selected, setSelected] = useState<Settlement | null>(null)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)

  const all = teamMembers.flatMap((m) => m.items)
  const filteredMembers = memberFilter.size === 0 ? teamMembers : teamMembers.filter((m) => memberFilter.has(m.name))
  const visibleAll = filteredMembers.flatMap((m) => m.items)
  const budget = useMemo(() => {
    const categories = teamBudget.categories.map((category) => ({
      ...category,
      used: all.filter((item) => item.aiCategory === category.label).reduce((sum, item) => sum + item.amount, 0),
    }))
    return { categories, total: categories.reduce((sum, c) => sum + c.limit, 0), used: categories.reduce((sum, c) => sum + c.used, 0) }
  }, [all])
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
    const status = await decideTeamSettlement(id, decision)
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

  const submitNormalOnly = () => submitIds(visibleAll.filter((i) => anomalyTags(i).length === 0 && i.status === 'TEAM_COLLECTING').map((i) => i.id))
  const requestAnomalyCorrections = async () => {
    const targets = visibleAll.filter((i) => anomalyTags(i).length > 0 && i.status === 'TEAM_COLLECTING')
    if (targets.length === 0) return
    setBusy(true)
    const results = await Promise.all(targets.map(async (item) => ({ id: item.id, status: await decideTeamSettlement(item.id, 'RETURN', `자동 보완요청: ${anomalyTags(item).join(', ')}`) })))
    results.forEach(({ id, status }) => updateStatus(id, status))
    setBusy(false)
  }

  const hasVisibleMember = filteredMembers.some((m) =>
    (onlyAnomaly ? m.items.filter((i) => anomalyTags(i).length > 0) : m.items).length > 0
  )
  const budgetRemaining = budget.total - budget.used
  const budgetRemainingRate = budgetRemaining / budget.total
  const budgetTone = budgetRemainingRate <= 0.2 ? 'var(--tone-red)' : budgetRemainingRate <= 0.5 ? 'var(--tone-amber)' : 'var(--tone-green)'
  const budgetRateLabel = budgetRemainingRate < 0 ? `초과 ${pct(budgetRemainingRate)}` : `잔여 ${pct(budgetRemainingRate)}`

  return (
    <>
      <div className="page-head row" style={{ justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <span className="screen-id">S-02</span>
          <h1>팀 취합·제출 · {teamName}</h1>
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
          <span className="tag" style={{ color: budgetTone, borderColor: budgetTone }}>{budgetRateLabel}</span>
        </div>
        <div className="card-body">
          <div className="row" style={{ justifyContent: 'space-between', marginBottom: 4 }}>
            <span className="text-meta">잔여 예산</span>
            <span className="text-meta">총 {won(budget.total)}원 중 {won(budget.used)}원 사용</span>
          </div>
          <div style={{ fontSize: 22, fontWeight: 700, color: budgetTone, marginBottom: 8 }}>
            {budgetRemaining < 0 ? `초과 ${won(Math.abs(budgetRemaining))}` : won(budgetRemaining)}
          </div>
          <div style={{ height: 8, background: 'var(--surface-2)', borderRadius: 'var(--radius-pill)', overflow: 'hidden', marginBottom: 20 }}>
            <div style={{ width: pct(Math.max(0, Math.min(budgetRemainingRate, 1))), height: '100%', background: budgetTone }} />
          </div>

          <div className="text-meta" style={{ marginBottom: 12, fontWeight: 600 }}>항목별 잔여 예산</div>
          <div className="team-budget-grid">
            {budget.categories.slice(0, 10).map((c) => {
              const remaining = c.limit - c.used
              const remainingRate = remaining / c.limit
              const tone = remainingRate <= 0.2 ? 'danger' : remainingRate <= 0.5 ? 'caution' : 'safe'
              const barColor = tone === 'danger' ? 'var(--tone-red)' : tone === 'caution' ? 'var(--tone-amber)' : 'var(--tone-green)'
              return (
                <div key={c.label} className={`team-budget-item ${tone}`}>
                  <div className="row" style={{ justifyContent: 'space-between', marginBottom: 6 }}>
                    <span style={{ fontSize: 12, fontWeight: 600 }}>{c.label}</span>
                    <span style={{ fontSize: 11, fontWeight: 800, padding: '1px 6px', borderRadius: 999, background: barColor + '22', color: barColor }}>
                      {remainingRate < 0 ? `초과 ${pct(remainingRate)}` : `잔여 ${pct(remainingRate)}`}
                    </span>
                  </div>
                  <div style={{ fontSize: 15, fontWeight: 700, color: barColor, marginBottom: 6 }}>
                    {remaining < 0 ? `초과 ${won(Math.abs(remaining))}` : `잔여 ${won(remaining)}`}
                  </div>
                  <div style={{ height: 5, background: 'var(--surface-2)', borderRadius: 'var(--radius-pill)', overflow: 'hidden', marginBottom: 4 }}>
                    <div style={{ width: pct(Math.max(0, Math.min(remainingRate, 1))), height: '100%', background: barColor, transition: 'width 0.3s' }} />
                  </div>
                  <div className="text-meta" style={{ fontSize: 10 }}>예산 {won(c.limit)}</div>
                </div>
              )
            })}
          </div>
        </div>
      </div>

      {!canManage && (
        <div className="card">
          <div className="card-body text-meta">
            개별 지출 건은 <b>팀장</b>만 조회·처리할 수 있습니다. 임직원은 팀 예산 현황만 확인할 수 있어요.
          </div>
        </div>
      )}

      {canManage && (<>
      <div className="filter-bar">
        <details className="multi-select">
          <summary>사람별 보기 {memberFilter.size > 0 ? `(${memberFilter.size}명)` : '(전체)'}</summary>
          <div className="multi-select-menu">
            {teamMembers.map((member) => <label key={member.name}><input type="checkbox" checked={memberFilter.has(member.name)} onChange={() => setMemberFilter((current) => { const next = new Set(current); next.has(member.name) ? next.delete(member.name) : next.add(member.name); return next })} />{member.name}</label>)}
            {memberFilter.size > 0 && <button className="btn sm" onClick={() => setMemberFilter(new Set())}>전체 보기</button>}
          </div>
        </details>
        <label className="row" style={{ gap: 6 }}>
          <input type="checkbox" checked={onlyAnomaly} onChange={(e) => setOnlyAnomaly(e.target.checked)} />
          이상건만 보기
        </label>
        <div className="spacer" />
        <button className="btn return" disabled={busy || stats.anomalous === 0} onClick={requestAnomalyCorrections}>이상건 자동 보완요청</button>
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
        {filteredMembers.map((m) => {
          const visibleItems = onlyAnomaly ? m.items.filter((i) => anomalyTags(i).length > 0) : m.items
          if (visibleItems.length === 0) return null
          const isOpen = expanded.has(m.name) || onlyAnomaly
          const memberAnomaly = m.items.filter((i) => anomalyTags(i).length > 0).length
          return (
            <div className="card" key={m.name}>
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
                    {m.items.length}건 · 이상{' '}
                    <span style={memberAnomaly > 0 ? { color: 'var(--tone-red)', fontWeight: 700 } : undefined}>{memberAnomaly}건</span>
                  </span>
                </h3>
                <span className="tag">{won(m.items.reduce((s, i) => s + i.amount, 0))}</span>
              </div>
              {isOpen && (
                <table className="table team-settlement-table">
                  <colgroup>
                    <col style={{ width: 112 }} />
                    <col />
                    <col style={{ width: 112 }} />
                    <col style={{ width: 108 }} />
                    <col style={{ width: 190 }} />
                    <col style={{ width: 176 }} />
                  </colgroup>
                  <thead>
                    <tr><th>거래일자</th><th>가맹점</th><th className="num">금액</th><th>카드구분</th><th>이상 사유</th><th>처리</th></tr>
                  </thead>
                  <tbody>
                    {visibleItems.map((i) => {
                      const tags = anomalyTags(i)
                      return (
                        <tr
                          key={i.id}
                          className={tags.length > 0 ? 'anomaly-row' : undefined}
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
                          <td className="team-actions" onClick={(ev) => ev.stopPropagation()}>
                            {tags.length === 0 ? (
                              <span className="text-meta">일괄 대상</span>
                            ) : i.status !== 'TEAM_COLLECTING' ? (
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
      </>)}

      {selected && (
        <SettlementDetailModal
          item={selected}
          onClose={() => setSelected(null)}
          onStatusChange={updateStatus}
          context="team"
        />
      )}
    </>
  )
}

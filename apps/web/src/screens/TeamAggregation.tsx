// S-02 팀 취합·제출 — 팀장. FR-UI-02, FR-DA-07~08, FR-DB-03
import { useMemo, useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { anomalyTags, teamMembers } from '../data/mock'
import { CARD_TYPE_LABEL, type Settlement } from '../types/domain'
import { won } from '../lib/format'
import { KpiCard } from '../components/ui/KpiCard'
import { SettlementDetailModal } from '../components/settlement/SettlementDetailModal'
import { activateOnEnterOrSpace } from '../lib/a11y'

export function TeamAggregation() {
  const [onlyAnomaly, setOnlyAnomaly] = useState(false)
  const [selected, setSelected] = useState<Settlement | null>(null)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const all = teamMembers.flatMap((m) => m.items)
  const stats = useMemo(() => {
    const anomalous = all.filter((i) => anomalyTags(i).length > 0).length
    return {
      members: teamMembers.length,
      total: all.reduce((s, i) => s + i.amount, 0),
      anomalous,
      normal: all.length - anomalous,
    }
  }, [all])

  const toggleMember = (name: string) => {
    const next = new Set(expanded)
    next.has(name) ? next.delete(name) : next.add(name)
    setExpanded(next)
  }

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

      <div className="filter-bar">
        <label className="row" style={{ gap: 6 }}>
          <input type="checkbox" checked={onlyAnomaly} onChange={(e) => setOnlyAnomaly(e.target.checked)} />
          이상건만 보기
        </label>
        <div className="spacer" />
        <button className="btn">제출 확정</button>
        <button className="btn primary">이상건 제외 일괄제출 ({stats.normal}건)</button>
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
                            {tags.length > 0 ? (
                              <div className="row">
                                <button className="btn sm return">보완요청</button>
                                <button className="btn sm reject">반려</button>
                              </div>
                            ) : (
                              <span className="text-meta">일괄 대상</span>
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

      {selected && <SettlementDetailModal item={selected} onClose={() => setSelected(null)} />}
    </>
  )
}

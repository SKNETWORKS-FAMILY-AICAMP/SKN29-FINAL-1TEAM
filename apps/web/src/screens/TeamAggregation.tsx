// S-02 팀 취합·제출 — 팀장. FR-UI-02, FR-DA-07~08, FR-DB-03
import { useEffect, useMemo, useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { teamBudget } from '../data/mock'
import { judgementTags, needsAttention, notJudged } from '../lib/judgement'
import { CARD_TYPE_LABEL, type Settlement } from '../types/domain'
import { pct, won } from '../lib/format'
import { KpiCard } from '../components/ui/KpiCard'
import { SettlementDetailModal } from '../components/settlement/SettlementDetailModal'
import { decideTeamSettlement, submitSettlements } from '../api/settlementService'
import { endpoints } from '../api/client'
import { USE_MOCK } from '../api/config'
import { useSettlements } from '../context/SettlementsContext'
import { useAuth } from '../context/AuthContext'
import { useCan } from '../lib/capabilities'
import { activateOnEnterOrSpace } from '../lib/a11y'
import { currentMonth, isInMonth, monthLabel } from '../lib/period'

// 이 화면의 두 스코프 — 섞이면 숫자가 어긋난다.
//  ① 팀 통계 대시보드(KPI·예산): 해당 팀 · 해당 월 · 최종반려(REJECT) 제외 **모든 상태**
//  ② 취합 목록: 해당 팀 팀원들의 이번 달 **팀 단계(TEAM_*)** 건만
const inTeamStage = (item: Settlement) => item.status.startsWith('TEAM_')
// 사용액은 진행 상태와 무관하게 "이미 쓴 돈"으로 잡는다(카드는 이미 결제됨). 최종 반려만 뺀다.
//  백엔드 TeamBudgetView._BUDGET_EXCLUDE와 같은 규칙.
const countsTowardStats = (item: Settlement) => item.status !== 'REJECT'
// mock 데이터에는 dept가 없다 — 그 경우 팀 필터를 건너뛴다(실 모드에선 항상 채워진다).
const inTeam = (item: Settlement, teamName: string) => !item.dept || item.dept === teamName

/** GET /api/team-budget/ 응답. `unbudgetedUsed`는 예산 행이 없는 과목의 지출(항목 합과 총액의 차이). */
interface TeamBudgetView {
  total: number
  used: number
  categories: { label: string; limit: number; used: number }[]
  unbudgetedUsed?: number
}

export function TeamAggregation() {
  const { all, teamMembers, updateStatus } = useSettlements()
  const { user } = useAuth()
  const teamName = user?.dept ?? '내 팀' // 로그인 사용자의 소속 팀(재무회계팀 / AI·개발팀 등)
  const canManage = useCan()('team_aggregate') // 팀 취합 권한 보유자만 개별 건 조회·처리
  const month = currentMonth()
  const [onlyAnomaly, setOnlyAnomaly] = useState(false)
  const [memberFilter, setMemberFilter] = useState<Set<string>>(new Set())
  const [selected, setSelected] = useState<Settlement | null>(null)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)

  // ② 취합 목록 — 우리 팀 · 이번 달 · 팀 단계(TEAM_*)만. 제출(SUBMITTED)하면 즉시 사라진다.
  const members = useMemo(
    () => teamMembers
      .map((m) => ({
        ...m,
        items: m.items.filter((i) => inTeamStage(i) && inTeam(i, teamName) && isInMonth(i.date, month)),
      }))
      .filter((m) => m.items.length > 0),
    [teamMembers, teamName, month],
  )
  const listedAll = members.flatMap((m) => m.items)
  const filteredMembers = memberFilter.size === 0 ? members : members.filter((m) => memberFilter.has(m.name))
  const visibleAll = filteredMembers.flatMap((m) => m.items)
  const collecting = listedAll.filter((i) => i.status === 'TEAM_COLLECTING')

  // ① 팀 통계 대시보드 — 우리 팀 · 이번 달 · 최종반려 제외 전체 내역(상태 무관).
  const teamMonthly = useMemo(
    () => all.filter((i) => inTeam(i, teamName) && isInMonth(i.date, month) && countsTowardStats(i)),
    [all, teamName, month],
  )

  // 팀 예산 — 한도는 DB(TeamBudget), 사용액은 서버 집계(상태 무관·최종반려만 제외).
  //  서버 집계 규칙은 위 ①(countsTowardStats)과 같아야 KPI 총 사용액과 예산 카드가 맞아떨어진다.
  const [budget, setBudget] = useState<TeamBudgetView>(teamBudget)
  const [budgetLive, setBudgetLive] = useState(USE_MOCK) // 실 모드에서 서버 응답을 받았는지
  useEffect(() => {
    if (USE_MOCK || !user?.teamId) return
    let cancelled = false
    endpoints.teamBudget(user.teamId, month)
      .then(({ data }) => {
        if (cancelled || !data?.categories?.length) return
        setBudget(data)
        setBudgetLive(true)
      })
      .catch(() => undefined)
    return () => { cancelled = true }
  }, [user?.teamId, month, teamMembers])

  // ① 대시보드 지표 — teamMonthly(팀·월·최종반려 제외 전체) 기준.
  const stats = useMemo(() => {
    const anomalous = teamMonthly.filter((i) => needsAttention(i)).length
    return {
      members: new Set(teamMonthly.map((i) => i.user)).size,
      total: teamMonthly.reduce((s, i) => s + i.amount, 0),
      count: teamMonthly.length,
      anomalous,
      normal: teamMonthly.length - anomalous,
    }
  }, [teamMonthly])

  // ② 취합 처리 버튼용 — 지금 취합 대기(TEAM_COLLECTING) 중인 건만.
  //  이상 건 = 보완요청·반려 판정. 검토(REVIEW)로 갈 건은 정상 건과 함께 그대로 제출된다.
  const collectingStats = useMemo(() => {
    const anomalous = collecting.filter((i) => needsAttention(i)).length
    return { anomalous, normal: collecting.length - anomalous }
  }, [collecting])

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

  // 제출 직후 룰 엔진 1차판정이 이어 돌아 건마다 도착 상태가 다르다
  //  (통과→승인대기 / 보완·위반→보완요청 / 검토필요→검토중). 일괄 제출이라도 한 상태로 뭉치면 안 된다.
  const submitIds = async (ids: string[]) => {
    if (ids.length === 0) return
    setBusy(true)
    const outcome = await submitSettlements(ids)
    ids.forEach((id) => updateStatus(id, outcome.status[id] ?? 'SUBMITTED'))
    setBusy(false)
  }

  const submitNormalOnly = () => submitIds(
    visibleAll.filter((i) => !needsAttention(i) && i.status === 'TEAM_COLLECTING').map((i) => i.id),
  )
  const requestAnomalyCorrections = async () => {
    const targets = visibleAll.filter((i) => needsAttention(i) && i.status === 'TEAM_COLLECTING')
    if (targets.length === 0) return
    setBusy(true)
    const results = await Promise.all(targets.map(async (item) => ({ id: item.id, status: await decideTeamSettlement(item.id, 'RETURN', `자동 보완요청: ${judgementTags(item).join(', ')}`) })))
    results.forEach(({ id, status }) => updateStatus(id, status))
    setBusy(false)
  }

  const hasVisibleMember = filteredMembers.some((m) =>
    (onlyAnomaly ? m.items.filter((i) => needsAttention(i)) : m.items).length > 0
  )
  const budgetRemaining = budget.total - budget.used
  // 한도가 0이면 나눗셈이 Infinity/NaN이 되어 막대·퍼센트가 깨진다 — 0으로 떨어뜨린다.
  const budgetRemainingRate = budget.total > 0 ? budgetRemaining / budget.total : 0
  const budgetTone = budgetRemainingRate <= 0.2 ? 'var(--tone-red)' : budgetRemainingRate <= 0.5 ? 'var(--tone-amber)' : 'var(--tone-green)'
  const budgetRateLabel = budget.total <= 0 ? '한도 미설정'
    : budgetRemainingRate < 0 ? `초과 ${pct(budgetRemainingRate)}` : `잔여 ${pct(budgetRemainingRate)}`
  // 예산 행이 없는 과목의 지출 — 있으면 "항목 합 ≠ 총 사용액"이므로 숨기지 않고 알린다.
  const unbudgetedUsed = budget.unbudgetedUsed ?? 0

  return (
    <>
      <div className="hero-band">
        <div className="page-head row" style={{ justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            <h1>팀 취합·제출 · {teamName}</h1>
            <div className="sub">정상 건은 접히고 이상 건만 강조됩니다. 이상 건(보완요청·반려)은 개별 처리하고 나머지는 일괄 제출합니다.</div>
          </div>
          <span className="badge" style={{ color: 'var(--tone-red)', background: 'var(--tone-red-bg)', padding: '6px 14px', fontSize: 13 }}>마감 D-2</span>
        </div>

        <div className="scope-chip-row">
          <span className="scope-chip"><span className="sw" />이번 달 ({monthLabel(month)})</span>
          <span className="scope-chip"><span className="sw" style={{ background: 'var(--tone-purple)' }} />{teamName}</span>
        </div>

        {/* ① 팀 통계 대시보드 — 취합 목록과 스코프가 다르다(전 상태 집계). */}
        <div className="kpi-grid">
          <KpiCard flat={false} accent="var(--accent-purple)" label="지출 증빙 인원" value={stats.members} unit="명" />
          <KpiCard accent="var(--accent-amber)" label="총 사용액" value={won(stats.total)} />
          <KpiCard accent="var(--accent-red)" warn label="이상 건" value={stats.anomalous} unit="건" />
          <KpiCard accent="var(--accent-green)" label="정상 건" value={stats.normal} unit="건" />
        </div>
        <div className="text-meta" style={{ margin: '10px 0 0', color: 'var(--sidebar-text-muted)' }}>
          팀 통계 · {monthLabel(month)} · {teamName} — 최종반려를 제외한 이번 달 전체 내역 {stats.count}건 기준
        </div>

      <div className="card" style={{ marginTop: 16, marginBottom: 0 }}>
        <div className="card-head">
          <h3>팀 예산 현황 · {monthLabel(month)}</h3>
          <span className="tag" style={{ color: budgetTone, borderColor: budgetTone }}>{budgetRateLabel}</span>
        </div>
        <div className="card-body">
          {!budgetLive && (
            <div className="note" style={{ marginBottom: 12 }}>
              ⚠ 팀 예산을 서버에서 불러오지 못했습니다. 아래 숫자는 <b>샘플 값</b>이며 실제 사용액이 아닙니다.
            </div>
          )}
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

          <div className="row" style={{ justifyContent: 'space-between', marginBottom: 12 }}>
            <span className="text-meta" style={{ fontWeight: 600 }}>항목별 잔여 예산</span>
            {/* 항목 합이 총 사용액과 어긋나면 그 차이를 숨기지 않고 밝힌다. */}
            {unbudgetedUsed > 0 && (
              <span className="text-meta" title="예산 항목이 배정되지 않은 계정과목의 지출입니다">
                ⚠ 예산 미배정 항목 사용 {won(unbudgetedUsed)}
              </span>
            )}
          </div>
          <div className="team-budget-grid">
            {budget.categories.slice(0, 10).map((c) => {
              const remaining = c.limit - c.used
              const remainingRate = c.limit > 0 ? remaining / c.limit : 0
              const tone = remainingRate <= 0.2 ? 'danger' : remainingRate <= 0.5 ? 'caution' : 'safe'
              // 항목별 미니카드는 배지·바·금액 모두 채도 높은 accent 색(시안 실측) — 카드 배경 틴트는 무채색 계열 tone 유지
              const barColor = tone === 'danger' ? 'var(--accent-red)' : tone === 'caution' ? 'var(--accent-amber)' : 'var(--accent-green)'
              return (
                <div key={c.label} className={`team-budget-item ${tone}`}>
                  <div className="row" style={{ justifyContent: 'space-between', marginBottom: 6 }}>
                    <span style={{ fontSize: 12, fontWeight: 600 }}>{c.label}</span>
                    <span style={{ fontSize: 11, fontWeight: 800, padding: '2px 8px', borderRadius: 999, background: barColor, color: '#fff' }}>
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
      </div>

      <div className="page-inner">
      {!canManage && (
        <div className="card">
          <div className="card-body text-meta">
            개별 지출 건은 <b>팀장</b>만 조회·처리할 수 있습니다. 임직원은 팀 예산 현황만 확인할 수 있어요.
          </div>
        </div>
      )}

      {canManage && (<>
      {/* ② 취합 목록 — 대시보드와 달리 팀 단계(TEAM_*) 건만 보인다. */}
      <div className="text-meta" style={{ margin: '0 0 8px' }}>
        취합 대상 · {monthLabel(month)} — 팀원이 팀에 올린 건({listedAll.length}건)만 표시합니다. 회계로 제출하면 목록에서 사라집니다.
      </div>
      <div className="filter-bar">
        <details className="multi-select">
          <summary>사람별 보기 {memberFilter.size > 0 ? `(${memberFilter.size}명)` : '(전체)'}</summary>
          <div className="multi-select-menu">
            {members.map((member) => <label key={member.name}><input type="checkbox" checked={memberFilter.has(member.name)} onChange={() => setMemberFilter((current) => { const next = new Set(current); next.has(member.name) ? next.delete(member.name) : next.add(member.name); return next })} />{member.name}</label>)}
            {memberFilter.size > 0 && <button className="btn sm" onClick={() => setMemberFilter(new Set())}>전체 보기</button>}
          </div>
        </details>
        <label className="row" style={{ gap: 6 }}>
          <input type="checkbox" checked={onlyAnomaly} onChange={(e) => setOnlyAnomaly(e.target.checked)} />
          이상건만 보기
        </label>
        <div className="spacer" />
        <button className="btn return" disabled={busy || collectingStats.anomalous === 0} onClick={requestAnomalyCorrections}>
          이상건 자동 보완요청 ({collectingStats.anomalous}건)
        </button>
        <button className="btn primary" disabled={busy || collectingStats.normal === 0} onClick={submitNormalOnly}>
          이상건 제외 일괄제출 ({collectingStats.normal}건)
        </button>
      </div>

      {!hasVisibleMember && (
        <div className="card">
          <div className="card-body text-meta">
            {listedAll.length === 0
              ? `${monthLabel(month)}에 취합할 팀 내역이 없습니다.`
              : '이상 건이 없습니다.'}
          </div>
        </div>
      )}

      <div className="stack" style={{ gap: 12 }}>
        {filteredMembers.map((m) => {
          const visibleItems = onlyAnomaly ? m.items.filter((i) => needsAttention(i)) : m.items
          if (visibleItems.length === 0) return null
          const isOpen = expanded.has(m.name) || onlyAnomaly
          const memberAnomaly = m.items.filter((i) => needsAttention(i)).length
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
                    <tr><th>거래일자</th><th>가맹점</th><th className="num">금액</th><th>카드구분</th><th>판정 사유</th><th>처리</th></tr>
                  </thead>
                  <tbody>
                    {visibleItems.map((i) => {
                      const tags = judgementTags(i)
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
                            {/* 판정 전 ≠ 정상. 검사하지 않은 것과 통과한 것을 같은 배지로 쓰면
                                판정이 실패한 건이 조용히 일괄제출에 섞인다. */}
                            {notJudged(i)
                              ? <span className="tag">판정 전</span>
                              : tags.length === 0
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
      </div>

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

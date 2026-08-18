// S-01 내 지출 — 사용자(임직원). FR-UI-01, FR-DA-01~09, FR-DB-02
import { useMemo, useState } from 'react'
import { AlertTriangle, Check, Download, Loader2, Plus, UserPlus } from 'lucide-react'
import { CARD_TYPE_LABEL, type Settlement, type SettlementStatus } from '../types/domain'
import { won } from '../lib/format'
import { KpiCard } from '../components/ui/KpiCard'
import { StatusBadge } from '../components/ui/StatusBadge'
import { SettlementDetailModal } from '../components/settlement/SettlementDetailModal'
import { claimSettlement, importSettlements, raiseSettlements } from '../api/settlementService'
import { useSettlements } from '../context/SettlementsContext'
import { activateOnEnterOrSpace } from '../lib/a11y'
import { currentMonth, isInMonth, monthLabel } from '../lib/period'

const DONE: SettlementStatus[] = ['CONFIRMED', 'ERP_VOUCHER_DRAFTED']
const PROCESSING: SettlementStatus[] = ['SUBMITTED', 'RPA_JUDGED', 'PENDING_CONFIRM', 'IN_REVIEW', 'TEAM_COLLECTING', 'TEAM_RETURNED', 'TEAM_REJECTED']
const SUBMITTABLE: SettlementStatus[] = ['DRAFT'] // 올림 가능 = 작성중(개인 → 팀 취합)

// 메인 화면 우선순위: 보완요청 → 반려 → 작성중 → 처리중 → (완료는 기본 숨김)
function priorityOf(s: SettlementStatus): number {
  if (s === 'RETURNED') return 0
  if (s === 'REJECT') return 1
  if (s === 'DRAFT') return 2
  if (DONE.includes(s)) return 9
  return 3
}

type ViewFilter = 'ACTIVE' | 'RETURNED' | 'REJECT' | 'DRAFT' | 'PROCESSING' | 'DONE' | 'ALL'

export function MyExpenses() {
  const { myExpenses: expenses, updateStatus, addExpense, removeExpense, refresh } = useSettlements()
  const [selected, setSelected] = useState<Settlement | null>(null)
  const [creating, setCreating] = useState(false)
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [submitting, setSubmitting] = useState(false)
  const [period, setPeriod] = useState<'MONTH' | 'ALL'>('MONTH')
  const [importing, setImporting] = useState(false)
  const [importNote, setImportNote] = useState('')
  const [view, setView] = useState<ViewFilter>('ACTIVE')
  // "이번 달" = 오늘이 속한 달(단순 월 기준). 일자는 보지 않으므로 같은 달이면 미래 일자도 포함된다.
  const month = currentMonth()

  // 이번 달 지표(KPI)
  const stats = useMemo(() => {
    const m = expenses.filter((e) => isInMonth(e.date, month))
    return {
      total: m.reduce((s, e) => s + e.amount, 0),
      draft: m.filter((e) => e.status === 'DRAFT').length,
      returned: m.filter((e) => e.status === 'RETURNED').length,
      rejected: m.filter((e) => e.status === 'REJECT').length,
    }
  }, [expenses, month])

  // 기간 + 상태 필터 → 우선순위 정렬
  const list = useMemo(() => {
    let l = expenses.filter((e) => period === 'ALL' || isInMonth(e.date, month))
    l = l.filter((e) => {
      switch (view) {
        case 'ACTIVE': return !DONE.includes(e.status) // 진행중(완료 제외)
        case 'DONE': return DONE.includes(e.status)
        case 'PROCESSING': return PROCESSING.includes(e.status)
        case 'ALL': return true
        default: return e.status === view // RETURNED / REJECT / DRAFT
      }
    })
    return [...l].sort((a, b) => priorityOf(a.status) - priorityOf(b.status) || b.date.localeCompare(a.date))
  }, [expenses, period, view, month])

  const runImport = async () => {
    setImporting(true)
    setImportNote('')
    try {
      const result = await importSettlements()
      await refresh()
      setImportNote(
        result.exhausted && result.created === 0
          ? `준비된 표본 ${result.totalBatches}회분을 모두 불러왔습니다.`
          : `${result.batch}/${result.totalBatches}회차 · ${result.created}건을 불러왔습니다`
            + (result.claimPending > 0 ? ` (실사용자 등록 대기 ${result.claimPending}건)` : '')
            + (result.exhausted ? ' — 마지막 회차입니다.' : ''),
      )
    } catch {
      setImportNote('결제내역을 불러오지 못했습니다. 로그인 상태와 연결을 확인해주세요.')
    } finally {
      setImporting(false)
    }
  }

  /** 팀·공용 카드 결제의 실사용자 본인 등록. 등록과 동시에 내 지출로 귀속된다. */
  const claim = async (id: string) => {
    await claimSettlement(id)
    await refresh()
  }

  const toggle = (id: string) => {
    const next = new Set(checked)
    next.has(id) ? next.delete(id) : next.add(id)
    setChecked(next)
  }

  const raiseChecked = async () => {
    const ids = [...checked]
    setSubmitting(true)
    const status = await raiseSettlements(ids) // DRAFT → TEAM_COLLECTING (팀에 올림)
    ids.forEach((id) => updateStatus(id, status))
    setChecked(new Set())
    setSubmitting(false)
  }

  return (
    <>
      <div className="page-head row" style={{ justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <span className="screen-id">S-01</span>
          <h1>내 지출</h1>
          <div className="sub">이번 달 처리 중인 내역을 <b>보완요청 → 반려 → 작성중</b> 순으로 보여줍니다. 필터로 완료·이전 달 내역도 조회할 수 있어요.</div>
        </div>
        <div className="row" style={{ gap: 8 }}>
          {/* ERP/카드사 결제기록 수집. 개인카드 건은 바로 내 것이 되고, 팀·공용 카드 건은
              주인 없이 들어와 팀원 전원에게 '실사용자 등록 대기'로 보인다. */}
          <button className="btn" disabled={importing} onClick={() => void runImport()}>
            {importing ? <Loader2 size={14} className="spin" /> : <Download size={14} />}
            {importing ? ' 카드사 결제내역 조회 중…' : ' 내역 불러오기'}
          </button>
          <button className="btn primary" onClick={() => setCreating(true)}>
            <Plus size={14} /> 신규 지출 등록
          </button>
        </div>
      </div>

      <div className="kpi-grid">
        <KpiCard label={`${monthLabel(month)} 사용액`} value={won(stats.total)} />
        <KpiCard label="작성중(올림 가능)" value={stats.draft} unit="건" />
        <KpiCard label="보완요청" value={stats.returned} unit="건" warn={stats.returned > 0} />
        <KpiCard label="반려" value={stats.rejected} unit="건" warn={stats.rejected > 0} />
      </div>

      {importNote && (
        <div className="note" style={{ marginBottom: 12 }}>{importNote}</div>
      )}

      <div className="filter-bar">
        <select value={period} onChange={(e) => setPeriod(e.target.value as 'MONTH' | 'ALL')}>
          <option value="MONTH">이번 달</option>
          <option value="ALL">전체 기간</option>
        </select>
        <select value={view} onChange={(e) => setView(e.target.value as ViewFilter)}>
          <option value="ACTIVE">진행중 (기본)</option>
          <option value="RETURNED">보완요청</option>
          <option value="REJECT">반려</option>
          <option value="DRAFT">작성중</option>
          <option value="PROCESSING">처리중</option>
          <option value="DONE">완료(확정·전표)</option>
          <option value="ALL">전체</option>
        </select>
        <div className="spacer" />
        <button className="btn primary" disabled={checked.size === 0 || submitting} onClick={raiseChecked}>
          {submitting ? '올리는 중…' : `선택 ${checked.size}건 팀에 올림`}
        </button>
      </div>

      <div className="card">
        <table className="table">
          <thead>
            <tr>
              <th></th>
              <th>거래일자</th><th>가맹점</th><th className="num">금액</th>
              <th>카드구분</th><th>비용분류</th><th>증빙</th><th>정산상태</th>
            </tr>
          </thead>
          <tbody>
            {list.map((e) => {
              // 실사용자 미등록 건은 아직 '내 것'이 아니다 — 선택·올림 대상에서 빼고
              // 등록 버튼만 준다. 남의 결제를 내가 제출해 버리는 걸 막는다.
              const pending = Boolean(e.claimPending)
              const submittable = SUBMITTABLE.includes(e.status) && !pending
              return (
                <tr
                  key={e.id}
                  tabIndex={0}
                  className={pending ? 'row-pending' : undefined}
                  onClick={() => { if (!pending) setSelected(e) }}
                  onKeyDown={activateOnEnterOrSpace(() => { if (!pending) setSelected(e) })}
                >
                  <td className="checkbox-cell" onClick={(ev) => { ev.stopPropagation(); if (submittable) toggle(e.id) }}>
                    <input
                      type="checkbox"
                      disabled={!submittable}
                      checked={checked.has(e.id)}
                      onChange={() => toggle(e.id)}
                      onClick={(ev) => ev.stopPropagation()}
                    />
                  </td>
                  <td>{e.date}</td>
                  <td>{e.merchant}</td>
                  <td className="num">{won(e.amount)}</td>
                  <td>{CARD_TYPE_LABEL[e.cardType]}</td>
                  <td><span className="tag">{e.aiCategory}</span></td>
                  <td>
                    {e.evidence === 'MISSING'
                      ? <span className="tag warn"><AlertTriangle size={11} /> 누락</span>
                      : <span className="tag ok"><Check size={11} /> 완료</span>}
                  </td>
                  <td>
                    {pending
                      ? (
                        <button
                          className="btn sm primary"
                          onClick={(ev) => { ev.stopPropagation(); void claim(e.id) }}
                          title="이 팀카드 결제를 내가 사용했다면 등록하세요"
                        >
                          <UserPlus size={11} /> 내가 사용했어요
                        </button>
                      )
                      : <StatusBadge status={e.status} />}
                  </td>
                </tr>
              )
            })}
            {list.length === 0 && (
              <tr><td colSpan={8} className="text-meta" style={{ textAlign: 'center', padding: 24 }}>해당 조건의 내역이 없습니다.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="text-meta" style={{ marginTop: 12 }}>
        표시 {list.length}건 · 선택 {checked.size}건 (제출 가능한 건만 선택할 수 있어요)
      </div>

      {selected && (
        <SettlementDetailModal
          item={selected}
          onClose={() => setSelected(null)}
          onStatusChange={updateStatus}
          onDeleted={removeExpense}
          context="mine"
        />
      )}
      {creating && (
        <SettlementDetailModal
          item={null}
          onClose={() => setCreating(false)}
          onCreated={addExpense}
        />
      )}
    </>
  )
}

// S-01 내 지출 — 사용자(임직원). FR-UI-01, FR-DA-01~09, FR-DB-02
import { useMemo, useState } from 'react'
import { AlertTriangle, Check, Plus } from 'lucide-react'
import { CARD_TYPE_LABEL, type Settlement, type SettlementStatus } from '../types/domain'
import { won } from '../lib/format'
import { KpiCard } from '../components/ui/KpiCard'
import { StatusBadge } from '../components/ui/StatusBadge'
import { SettlementDetailModal } from '../components/settlement/SettlementDetailModal'
import { submitSettlements } from '../api/settlementService'
import { useSettlements } from '../context/SettlementsContext'
import { activateOnEnterOrSpace } from '../lib/a11y'

const THIS_MONTH = '2026-07' // 데모 기준 '이번 달'
const DONE: SettlementStatus[] = ['CONFIRMED', 'ERP_VOUCHER_DRAFTED']
const PROCESSING: SettlementStatus[] = ['SUBMITTED', 'RPA_JUDGED', 'PENDING_CONFIRM', 'IN_REVIEW', 'TEAM_COLLECTING', 'TEAM_RETURNED', 'TEAM_REJECTED']
const SUBMITTABLE: SettlementStatus[] = ['DRAFT'] // 제출 가능 = 작성중

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
  const { myExpenses: expenses, updateStatus, addExpense } = useSettlements()
  const [selected, setSelected] = useState<Settlement | null>(null)
  const [creating, setCreating] = useState(false)
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [submitting, setSubmitting] = useState(false)
  const [period, setPeriod] = useState<'MONTH' | 'ALL'>('MONTH')
  const [view, setView] = useState<ViewFilter>('ACTIVE')

  // 이번 달 지표(KPI)
  const stats = useMemo(() => {
    const m = expenses.filter((e) => e.date.startsWith(THIS_MONTH))
    return {
      total: m.reduce((s, e) => s + e.amount, 0),
      draft: m.filter((e) => e.status === 'DRAFT').length,
      returned: m.filter((e) => e.status === 'RETURNED').length,
      rejected: m.filter((e) => e.status === 'REJECT').length,
    }
  }, [expenses])

  // 기간 + 상태 필터 → 우선순위 정렬
  const list = useMemo(() => {
    let l = expenses.filter((e) => period === 'ALL' || e.date.startsWith(THIS_MONTH))
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
  }, [expenses, period, view])

  const toggle = (id: string) => {
    const next = new Set(checked)
    next.has(id) ? next.delete(id) : next.add(id)
    setChecked(next)
  }

  const submitChecked = async () => {
    const ids = [...checked]
    setSubmitting(true)
    const status = await submitSettlements(ids)
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
        <button className="btn primary" onClick={() => setCreating(true)}>
          <Plus size={14} /> 신규 지출 등록
        </button>
      </div>

      <div className="kpi-grid">
        <KpiCard label="이번달 사용액" value={won(stats.total)} />
        <KpiCard label="작성중(제출 가능)" value={stats.draft} unit="건" />
        <KpiCard label="보완요청" value={stats.returned} unit="건" warn={stats.returned > 0} />
        <KpiCard label="반려" value={stats.rejected} unit="건" warn={stats.rejected > 0} />
      </div>

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
        <button className="btn primary" disabled={checked.size === 0 || submitting} onClick={submitChecked}>
          {submitting ? '제출 중…' : `선택 ${checked.size}건 일괄 제출`}
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
              const submittable = SUBMITTABLE.includes(e.status)
              return (
                <tr
                  key={e.id}
                  tabIndex={0}
                  onClick={() => setSelected(e)}
                  onKeyDown={activateOnEnterOrSpace(() => setSelected(e))}
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
                  <td><StatusBadge status={e.status} /></td>
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

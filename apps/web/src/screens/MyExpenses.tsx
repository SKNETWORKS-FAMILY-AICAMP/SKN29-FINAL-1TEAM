// S-01 내 지출 — 사용자(임직원). FR-UI-01, FR-DA-01~09, FR-DB-02
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertTriangle, Check, Plus } from 'lucide-react'
import { myExpenses } from '../data/mock'
import { CARD_TYPE_LABEL, type Settlement } from '../types/domain'
import { won } from '../lib/format'
import { KpiCard } from '../components/ui/KpiCard'
import { StatusBadge } from '../components/ui/StatusBadge'
import { SettlementDetailModal } from '../components/settlement/SettlementDetailModal'
import { activateOnEnterOrSpace } from '../lib/a11y'

export function MyExpenses() {
  const nav = useNavigate()
  const [selected, setSelected] = useState<Settlement | null>(null)
  const [checked, setChecked] = useState<Set<string>>(new Set())

  const stats = useMemo(() => {
    const total = myExpenses.reduce((s, e) => s + e.amount, 0)
    const unsubmitted = myExpenses.filter((e) => e.status === 'DRAFT').length
    const returned = myExpenses.filter((e) => e.status === 'RETURNED').length
    return { total, unsubmitted, returned }
  }, [])

  const toggle = (id: string) => {
    const next = new Set(checked)
    next.has(id) ? next.delete(id) : next.add(id)
    setChecked(next)
  }

  return (
    <>
      <div className="page-head row" style={{ justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <span className="screen-id">S-01</span>
          <h1>내 지출</h1>
          <div className="sub">AI 정산 초안을 확인·수정하고 제출합니다. AI 제안값은 노란 태그로 표시됩니다.</div>
        </div>
        <button className="btn primary" onClick={() => nav('/my-expenses/new')}>
          <Plus size={14} /> 신규 지출 등록
        </button>
      </div>

      <div className="kpi-grid">
        <KpiCard label="이번달 사용액" value={won(stats.total)} />
        <KpiCard label="미제출 건수" value={stats.unsubmitted} unit="건" />
        <KpiCard label="보완요청 건수" value={stats.returned} unit="건" warn={stats.returned > 0} />
        <KpiCard label="평균 승인 소요" value={2.4} unit="일" />
      </div>

      <div className="filter-bar">
        <select><option>전체 기간</option><option>이번 주</option><option>이번 달</option></select>
        <select><option>전체 상태</option><option>초안</option><option>제출됨</option><option>보완요청</option></select>
        <select><option>전체 카드구분</option><option>개인 배정</option><option>팀 카드</option><option>공용</option></select>
        <div className="spacer" />
        <button className="btn primary" disabled={checked.size === 0}>
          선택 {checked.size}건 일괄 제출
        </button>
      </div>

      <div className="card">
        <table className="table">
          <thead>
            <tr>
              <th></th>
              <th>거래일자</th><th>가맹점</th><th className="num">금액</th>
              <th>카드구분</th><th>AI분류</th><th>증빙</th><th>정산상태</th>
            </tr>
          </thead>
          <tbody>
            {myExpenses.map((e) => (
              <tr
                key={e.id}
                tabIndex={0}
                onClick={() => setSelected(e)}
                onKeyDown={activateOnEnterOrSpace(() => setSelected(e))}
              >
                <td className="checkbox-cell" onClick={(ev) => { ev.stopPropagation(); toggle(e.id) }}>
                  <input
                    type="checkbox"
                    disabled={e.status !== 'DRAFT'}
                    checked={checked.has(e.id)}
                    onChange={() => toggle(e.id)}
                    onClick={(ev) => ev.stopPropagation()}
                  />
                </td>
                <td>{e.date}</td>
                <td>{e.merchant}</td>
                <td className="num">{won(e.amount)}</td>
                <td>{CARD_TYPE_LABEL[e.cardType]}</td>
                <td>
                  <span className={'tag' + (e.aiSuggested ? ' ai' : '')}>
                    {e.aiCategory}{e.aiSuggested ? ' (제안)' : ''}
                  </span>
                </td>
                <td>
                  {e.evidence === 'MISSING'
                    ? <span className="tag warn"><AlertTriangle size={11} /> 누락</span>
                    : <span className="tag ok"><Check size={11} /> 완료</span>}
                </td>
                <td><StatusBadge status={e.status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="text-meta" style={{ marginTop: 12 }}>
        총 {myExpenses.length}건 중 {checked.size}건 선택됨
      </div>

      {selected && <SettlementDetailModal item={selected} onClose={() => setSelected(null)} />}
    </>
  )
}

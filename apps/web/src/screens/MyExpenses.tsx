// S-01 내 지출 — 사용자(임직원). FR-UI-01, FR-DA-01~09, FR-DB-02
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertTriangle, Check, ChevronDown, Lightbulb, Plus, Search } from 'lucide-react'
import { CARD_TYPE_LABEL, type Settlement } from '../types/domain'
import { won } from '../lib/format'
import { KpiCard } from '../components/ui/KpiCard'
import { StatusBadge } from '../components/ui/StatusBadge'
import { SettlementDetailModal } from '../components/settlement/SettlementDetailModal'
import { submitSettlements } from '../api/settlementService'
import { useSettlements } from '../context/SettlementsContext'
import { activateOnEnterOrSpace } from '../lib/a11y'

// 필터 pill 컴포넌트 — Figma S-01 필터 바 스펙
function FilterPill({ label, options, value, onChange }: { label: string; options: string[]; value: string; onChange: (v: string) => void }) {
  const [open, setOpen] = useState(false)
  const active = value !== options[0]
  return (
    <div style={{ position: 'relative' }}>
      <button
        className={'btn sm' + (active ? ' primary' : '')}
        onClick={() => setOpen((o) => !o)}
        style={{ gap: 4 }}
      >
        {active ? value : label} <ChevronDown size={11} />
      </button>
      {open && (
        <>
          <div style={{ position: 'fixed', inset: 0, zIndex: 10 }} onClick={() => setOpen(false)} />
          <div style={{ position: 'absolute', top: '100%', left: 0, marginTop: 4, background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', boxShadow: '0 8px 24px rgba(0,0,0,0.1)', zIndex: 11, minWidth: 140 }}>
            {options.map((o) => (
              <div
                key={o}
                onClick={() => { onChange(o); setOpen(false) }}
                style={{ padding: '8px 12px', fontSize: 13, cursor: 'pointer', fontWeight: o === value ? 600 : 400, color: o === value ? 'var(--primary)' : 'var(--text)', background: o === value ? 'var(--primary-soft)' : undefined }}
                onMouseEnter={(e) => { if (o !== value) (e.target as HTMLElement).style.background = 'var(--surface-2)' }}
                onMouseLeave={(e) => { if (o !== value) (e.target as HTMLElement).style.background = '' }}
              >
                {o}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

export function MyExpenses() {
  const nav = useNavigate()
  const { myExpenses: expenses, updateStatus } = useSettlements()
  const [selected, setSelected] = useState<Settlement | null>(null)
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [submitting, setSubmitting] = useState(false)

  // 필터 상태
  const [periodFilter, setPeriodFilter] = useState('전체 기간')
  const [cardFilter, setCardFilter] = useState('전체 카드구분')
  const [categoryFilter, setCategoryFilter] = useState('전체 분류')
  const [evidenceFilter, setEvidenceFilter] = useState('전체 증빙')
  const [statusFilter, setStatusFilter] = useState('전체 상태')
  const [searchQ, setSearchQ] = useState('')

  const stats = useMemo(() => {
    const total = expenses.reduce((s, e) => s + e.amount, 0)
    const unsubmitted = expenses.filter((e) => e.status === 'DRAFT').length
    const returned = expenses.filter((e) => e.status === 'RETURNED').length
    return { total, unsubmitted, returned }
  }, [expenses])

  const filtered = useMemo(() => {
    return expenses.filter((e) => {
      if (cardFilter !== '전체 카드구분' && CARD_TYPE_LABEL[e.cardType] !== cardFilter) return false
      if (categoryFilter !== '전체 분류' && e.aiCategory !== categoryFilter) return false
      if (evidenceFilter === '완료' && e.evidence !== 'OK') return false
      if (evidenceFilter === '누락' && e.evidence !== 'MISSING') return false
      if (statusFilter !== '전체 상태' && e.status !== statusFilter) return false
      if (searchQ && !e.merchant.includes(searchQ)) return false
      return true
    })
  }, [expenses, cardFilter, categoryFilter, evidenceFilter, statusFilter, searchQ])

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

  const aiHint = '거래처 회식, 참석 4인, 집대성 가맹점 업종코드 일치 — 3만원 초과 시 적격증빙 필수 · 30만원 이하로 사전승인 대상 아님'

  return (
    <>
      <div className="page-head row" style={{ justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <span className="screen-id">S-01</span>
          <h1>내 지출</h1>
          <div className="sub">이번 달 지출 내역을 확인하고 제출하세요.</div>
        </div>
        <button className="btn primary" onClick={() => nav('/my-expenses/new')}>
          <Plus size={14} /> 신규 지출 등록
        </button>
      </div>

      <div className="kpi-grid">
        <KpiCard label="이번달 사용액" value={won(stats.total)} />
        <KpiCard label="미제출" value={stats.unsubmitted} unit="건" />
        <KpiCard label="보완요청" value={stats.returned} unit="건" warn={stats.returned > 0} />
        <KpiCard label="평균 승인 소요" value={1.8} unit="일" />
      </div>

      {/* 필터 바 — Figma S-01 pill 스타일 */}
      <div className="filter-bar">
        <FilterPill label="거래 일자" value={periodFilter} onChange={setPeriodFilter}
          options={['전체 기간', '이번 주', '이번 달', '지난 달']} />
        <FilterPill label="카드 구분" value={cardFilter} onChange={setCardFilter}
          options={['전체 카드구분', '개인 배정', '팀 카드', '공용', '후정산']} />
        <FilterPill label="비용 분류" value={categoryFilter} onChange={setCategoryFilter}
          options={['전체 분류', '식대', '출장', '접대', '회의', '비품', '업무활성']} />
        <FilterPill label="증빙" value={evidenceFilter} onChange={setEvidenceFilter}
          options={['전체 증빙', '완료', '누락']} />
        <FilterPill label="검토 상태" value={statusFilter} onChange={setStatusFilter}
          options={['전체 상태', '초안', '제출됨', '보완요청', '승인대기', '확정']} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '5px 10px', border: '1px solid var(--border-strong)', borderRadius: 'var(--radius-control)', background: 'var(--surface)' }}>
          <Search size={12} color="var(--muted)" />
          <input
            placeholder="검색"
            value={searchQ}
            onChange={(e) => setSearchQ(e.target.value)}
            style={{ border: 'none', outline: 'none', background: 'none', fontSize: 12, width: 80, padding: 0 }}
          />
        </div>
      </div>

      <div className="card">
        <table className="table">
          <thead>
            <tr>
              <th></th>
              <th>거래일자</th><th>가맹점</th><th className="num">금액</th>
              <th>카드구분</th><th>비용 분류</th><th>증빙</th><th>검토 상태</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((e) => (
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
                <td className="text-meta">{e.date}</td>
                <td style={{ fontWeight: 500 }}>{e.merchant}</td>
                <td className="num" style={{ fontWeight: 600 }}>{won(e.amount)}</td>
                <td className="text-meta">{CARD_TYPE_LABEL[e.cardType]}</td>
                <td>
                  <span className={'tag' + (e.aiSuggested ? ' ai' : '')}>
                    {e.aiCategory}{e.aiSuggested ? ' ●AI' : ''}
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
            {filtered.length === 0 && (
              <tr><td colSpan={8} className="text-meta" style={{ textAlign: 'center', padding: 24 }}>조건에 맞는 지출 내역이 없습니다.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {/* AI 분류 근거·규정 힌트 배너 — Figma S-01 하단 노란 배너 */}
      <div style={{ marginTop: 12, padding: '10px 14px', background: '#fffbeb', border: '1px solid #f0e0a0', borderRadius: 'var(--radius-control)', display: 'flex', gap: 8, alignItems: 'flex-start' }}>
        <Lightbulb size={14} color="#a3701a" style={{ flexShrink: 0, marginTop: 1 }} />
        <div>
          <span style={{ fontSize: 12, fontWeight: 700, color: '#a3701a' }}>AI 분류 근거·규정 힌트</span>
          <span style={{ fontSize: 12, color: '#92400e', marginLeft: 8 }}>"{aiHint}"</span>
        </div>
      </div>

      <div className="row" style={{ marginTop: 10, justifyContent: 'space-between' }}>
        <span className="text-meta">총 {filtered.length}건 중 {checked.size}건 선택됨</span>
        <button className="btn primary" disabled={checked.size === 0 || submitting} onClick={submitChecked}>
          {submitting ? '제출 중…' : `선택 건 일괄 제출`}
        </button>
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

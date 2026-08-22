// S-01 내 지출("지출 증빙") — 사용자(임직원). FR-UI-01, FR-DA-01~09, FR-DB-02
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertTriangle, Check, Download, FileText, Loader2, Plus, Search, UserPlus } from 'lucide-react'
import {
  CARD_TYPE_LABEL, categoryTone,
  type CardType, type Category, type Settlement, type SettlementStatus,
} from '../types/domain'
import { useCategories } from '../lib/categories'
import { won } from '../lib/format'
import { KpiCard } from '../components/ui/KpiCard'
import { StatusText } from '../components/ui/StatusText'
import { SettlementDetailModal } from '../components/settlement/SettlementDetailModal'
import { claimSettlement, importSettlements, raiseSettlements } from '../api/settlementService'
import { useSettlements } from '../context/SettlementsContext'
import { useAuth } from '../context/AuthContext'
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

/** S-01 "검토 상태" 컬럼 전용 라벨(시안 실측) — 다른 화면의 STATUS_META 라벨은 그대로 둔다. */
const S01_STATUS_LABEL: Partial<Record<SettlementStatus, string>> = {
  DRAFT: '제출이전',
  CONFIRMED: '승인완료',
}

type ViewFilter = 'ACTIVE' | 'RETURNED' | 'REJECT' | 'DRAFT' | 'PROCESSING' | 'DONE' | 'ALL'

export function MyExpenses() {
  const { myExpenses: expenses, updateStatus, addExpense, removeExpense, refresh } = useSettlements()
  const { user } = useAuth()
  const nav = useNavigate()
  const [selected, setSelected] = useState<Settlement | null>(null)
  const [creating, setCreating] = useState(false)
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [submitting, setSubmitting] = useState(false)
  const [period, setPeriod] = useState<'MONTH' | 'ALL'>('MONTH')
  const [importing, setImporting] = useState(false)
  const [importNote, setImportNote] = useState('')
  const [view, setView] = useState<ViewFilter>('ACTIVE')
  const [cardTypeFilter, setCardTypeFilter] = useState<CardType | 'ALL'>('ALL')
  const [categoryFilter, setCategoryFilter] = useState<Category | 'ALL'>('ALL')
  const { categories } = useCategories()   // 목록 정본은 서버(`/api/meta/categories/`)
  const [evidenceFilter, setEvidenceFilter] = useState<'ALL' | 'OK' | 'MISSING'>('ALL')
  const [search, setSearch] = useState('')
  // "이번 달" = 오늘이 속한 달(단순 월 기준). 일자는 보지 않으므로 같은 달이면 미래 일자도 포함된다.
  const month = currentMonth()

  // 이번 달 지표(KPI)
  const stats = useMemo(() => {
    const m = expenses.filter((e) => isInMonth(e.date, month))
    return {
      total: m.reduce((s, e) => s + e.amount, 0),
      draft: m.filter((e) => e.status === 'DRAFT').length,
      processing: m.filter((e) => PROCESSING.includes(e.status)).length,
      returned: m.filter((e) => e.status === 'RETURNED').length,
      rejected: m.filter((e) => e.status === 'REJECT').length,
    }
  }, [expenses, month])

  // 기간 + 상태 + 카드구분·비용분류·증빙·검색 필터 → 우선순위 정렬
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
    if (cardTypeFilter !== 'ALL') l = l.filter((e) => e.cardType === cardTypeFilter)
    //  배지가 보여주는 값(확정 우선)과 **같은 기준**으로 거른다 — 예전엔 필터만
    //  `aiCategory`를 봐서, 사람이 분류를 고쳐 확정한 건이 화면에 보이는 분류로는 안 걸렸다.
    if (categoryFilter !== 'ALL') l = l.filter((e) => (e.category || e.aiCategory) === categoryFilter)
    if (evidenceFilter !== 'ALL') l = l.filter((e) => e.evidence === evidenceFilter)
    const q = search.trim()
    if (q) l = l.filter((e) => e.merchant.includes(q))
    return [...l].sort((a, b) => priorityOf(a.status) - priorityOf(b.status) || b.date.localeCompare(a.date))
  }, [expenses, period, view, month, cardTypeFilter, categoryFilter, evidenceFilter, search])

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
      <div className="hero-band">
        <div className="page-head row" style={{ justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            <span className="screen-id">S-01</span>
            <h1>지출 증빙</h1>
            <div className="sub">지출 내역을 확인하고 증빙 내역을 제출하세요.</div>
          </div>
          <div className="row" style={{ gap: 8 }}>
            {/* ERP/카드사 결제기록 수집. 개인카드 건은 바로 내 것이 되고, 팀·공용 카드 건은
                주인 없이 들어와 팀원 전원에게 '실사용자 등록 대기'로 보인다. */}
            <button className="btn" disabled={importing} onClick={() => void runImport()}>
              {importing ? <Loader2 size={14} className="spin" /> : <Download size={14} />}
              {importing ? ' 카드사 결제내역 조회 중…' : ' 내역 불러오기'}
            </button>
            <button className="btn" onClick={() => setCreating(true)}>
              <Plus size={14} /> 신규 지출 등록
            </button>
          </div>
        </div>

        <div className="scope-chip-row">
          <span className="scope-chip"><span className="sw" />이번 달 ({monthLabel(month)})</span>
          {user?.dept && <span className="scope-chip"><span className="sw" style={{ background: 'var(--tone-purple)' }} />{user.dept}</span>}
        </div>

        <div className="kpi-grid" style={{ gridTemplateColumns: 'repeat(5, 1fr)' }}>
          <KpiCard flat label={`${monthLabel(month)} 사용액`} value={won(stats.total)} />
          <KpiCard flat label="미제출" value={stats.draft} unit="건" />
          <KpiCard flat label="검토중" value={stats.processing} unit="건" />
          <KpiCard flat warn label="보완 요청" value={stats.returned} unit="건" />
          <KpiCard flat labelWarn label="반려" value={stats.rejected} unit="건" />
        </div>
      </div>

      <div className="page-inner">
        {importNote && (
          <div className="note" style={{ marginBottom: 12 }}>{importNote}</div>
        )}

        <div className="filter-bar">
          <select value={period} onChange={(e) => setPeriod(e.target.value as 'MONTH' | 'ALL')}>
            <option value="MONTH">이번 달</option>
            <option value="ALL">전체 기간</option>
          </select>
          <select value={cardTypeFilter} onChange={(e) => setCardTypeFilter(e.target.value as CardType | 'ALL')}>
            <option value="ALL">카드 구분</option>
            {Object.entries(CARD_TYPE_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
          <select value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value as Category | 'ALL')}>
            <option value="ALL">비용 분류</option>
            {categories.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
          </select>
          <select value={evidenceFilter} onChange={(e) => setEvidenceFilter(e.target.value as 'ALL' | 'OK' | 'MISSING')}>
            <option value="ALL">증빙</option>
            <option value="OK">증빙 완료</option>
            <option value="MISSING">증빙 누락</option>
          </select>
          <select value={view} onChange={(e) => setView(e.target.value as ViewFilter)}>
            <option value="ACTIVE">검토 상태(진행중)</option>
            <option value="RETURNED">보완요청</option>
            <option value="REJECT">반려</option>
            <option value="DRAFT">작성중</option>
            <option value="PROCESSING">처리중</option>
            <option value="DONE">완료(확정·전표)</option>
            <option value="ALL">전체</option>
          </select>
          <label className="search-box">
            <Search size={13} />
            <input type="text" placeholder="검색" value={search} onChange={(e) => setSearch(e.target.value)} />
          </label>
        </div>

        <div className="card">
          <table className="table">
            <thead>
              <tr>
                <th></th>
                <th>거래일자</th><th>가맹점</th><th className="num">금액</th>
                <th>카드구분</th><th>비용분류</th><th>증빙</th><th>검토상태</th><th></th>
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
                    <td>
                      <span className="tag" style={{ color: `var(--tone-${categoryTone(e.category || e.aiCategory)})`, background: `var(--tone-${categoryTone(e.category || e.aiCategory)}-bg)`, borderColor: 'transparent' }}>
                        {(e.category || e.aiCategory) || '선택 필요'}
                        {e.aiSuggested && (e.category || e.aiCategory) ? ' · AI' : ''}
                      </span>
                    </td>
                    <td>
                      {e.evidence === 'MISSING'
                        ? <span className="tag caution"><AlertTriangle size={11} /> 누락</span>
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
                        : <StatusText status={e.status} label={S01_STATUS_LABEL[e.status]} />}
                    </td>
                    <td>
                      {/* 확정된 건은 ERP 전표(안)를 다시 볼 수 있어야 한다 — 예전엔 검토 모달의
                          승인 직후 자동 이동 한 번뿐이라 그 순간을 놓치면 접근할 길이 없었다. */}
                      {DONE.includes(e.status) && (
                        <button
                          className="btn sm"
                          onClick={(ev) => { ev.stopPropagation(); nav(`/erp/${e.id}`) }}
                        >
                          <FileText size={11} /> 전표 보기
                        </button>
                      )}
                    </td>
                  </tr>
                )
              })}
              {list.length === 0 && (
                <tr><td colSpan={9} className="text-meta" style={{ textAlign: 'center', padding: 24 }}>해당 조건의 내역이 없습니다.</td></tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center', marginTop: 12 }}>
          <div className="text-meta">
            표시 {list.length}건 · 선택 {checked.size}건 (제출 가능한 건만 선택할 수 있어요)
          </div>
          <button className="btn primary" disabled={checked.size === 0 || submitting} onClick={raiseChecked}>
            {submitting ? '올리는 중…' : `선택 ${checked.size}건 팀에 제출`}
          </button>
        </div>
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
          //  신규 등록도 **저장된 뒤에는 일반 건과 같다** — 모달 안에서 올림·삭제가
          //  일어나므로 목록이 그 결과를 받아야 한다(예전엔 저장하면 바로 닫혀서 필요 없었다).
          onStatusChange={updateStatus}
          onDeleted={removeExpense}
        />
      )}
    </>
  )
}
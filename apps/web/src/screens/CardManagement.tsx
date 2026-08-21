// S-09 법인카드 관리 — 회계. 팀/개인 배정 카드 현황 + 배정 변경·회수/정지,
// 회수 필요 카드 별도 조치 큐.
//
// 실 API 연동(`/api/cards/`). **화면은 판정을 하지 않는다** — 사용액도, "회수가 필요한가"도
// 서버가 계산해 내려준 값을 그대로 쓴다. 여기서 다시 계산하면 임계값 사본이 두 벌 생기고
// 곧 서로 다른 말을 한다(이전 목데이터 시절엔 그 판정이 아예 화면 상수였다).
import { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertTriangle, ArrowLeft, ArrowRight, CreditCard, RefreshCw, Search } from 'lucide-react'
import { won } from '../lib/format'
import { AssignCardModal } from '../components/cards/AssignCardModal'
import { RecallCardModal } from '../components/cards/RecallCardModal'
import {
  assignCard, fetchCardAttention, fetchCards, stopCard,
  type AttentionGroupData, type CardOption, type CorpCard,
} from '../api/cardService'

export function CardManagement() {
  const [view, setView] = useState<'list' | 'attention'>('list')
  const [cards, setCards] = useState<CorpCard[]>([])
  const [teams, setTeams] = useState<CardOption[]>([])
  const [people, setPeople] = useState<CardOption[]>([])
  const [month, setMonth] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [pending, setPending] = useState(false)

  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState<string>('ALL')
  const [teamFilter, setTeamFilter] = useState<string>('ALL')
  const [statusFilter, setStatusFilter] = useState<string>('ALL')
  const [assigning, setAssigning] = useState<CorpCard | null>(null)
  const [recalling, setRecalling] = useState<CorpCard | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await fetchCards()
      setCards(res.cards)
      setTeams(res.teams)
      setPeople(res.people)
      setMonth(res.month)
    } catch (e) {
      // 조용히 빈 목록을 그리지 않는다 — "카드가 없다"와 "못 불러왔다"는 다른 상황이다.
      setError(e instanceof Error ? e.message : '카드 목록을 불러오지 못했습니다.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const teamNames = useMemo(
    () => [...new Set(cards.map((c) => c.teamName).filter(Boolean))] as string[],
    [cards],
  )

  const list = useMemo(() => {
    const q = search.trim()
    return cards.filter((c) => {
      if (typeFilter !== 'ALL' && c.type !== typeFilter) return false
      if (teamFilter !== 'ALL' && c.teamName !== teamFilter) return false
      if (statusFilter !== 'ALL' && c.status !== statusFilter) return false
      if (q && !((c.number ?? '').includes(q) || c.assignee.includes(q) || (c.teamName ?? '').includes(q) || c.name.includes(q))) return false
      return true
    })
  }, [cards, search, typeFilter, teamFilter, statusFilter])

  const attentionCount = useMemo(() => cards.filter((c) => c.attention).length, [cards])

  const confirmAssign = async (target: { mode: 'TEAM' | 'PERSONAL'; teamId?: number; userId?: number; reason: string }) => {
    if (!assigning) return
    setPending(true)
    try {
      const updated = await assignCard(assigning.id, target)
      setCards((prev) => prev.map((c) => (c.id === updated.id ? updated : c)))
      setAssigning(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : '배정 변경에 실패했습니다.')
    } finally {
      setPending(false)
    }
  }

  const confirmRecall = async (reason: string, detail: string) => {
    if (!recalling) return
    setPending(true)
    try {
      const updated = await stopCard(recalling.id, detail.trim() ? `${reason} — ${detail.trim()}` : reason)
      setCards((prev) => prev.map((c) => (c.id === updated.id ? updated : c)))
      setRecalling(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : '회수 처리에 실패했습니다.')
    } finally {
      setPending(false)
    }
  }

  if (view === 'attention') {
    return (
      <AttentionView
        onBack={() => setView('list')}
        onRecall={setRecalling}
        recalling={recalling}
        onConfirmRecall={confirmRecall}
        onCloseRecall={() => setRecalling(null)}
        pending={pending}
      />
    )
  }

  return (
    <>
      <div className="hero-band" style={{ paddingBottom: 24 }}>
        <div className="page-head row" style={{ justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 0 }}>
          <div>
            <h1>법인카드 관리</h1>
            <div className="sub">팀별·개인별로 배정된 법인카드 현황을 확인하고 관리하세요{month ? ` · ${month} 사용액 기준` : ''}</div>
          </div>
          <button
            className="btn"
            style={{ background: 'var(--tone-red-bg)', color: 'var(--tone-red)', borderColor: 'transparent' }}
            onClick={() => setView('attention')}
          >
            회수/중지 필요 카드{attentionCount > 0 ? ` (${attentionCount})` : ''} <ArrowRight size={14} />
          </button>
        </div>
      </div>

      <div className="page-inner">
        {error && (
          <div className="note" style={{ background: 'var(--tone-red-bg)', border: '1px solid #e8c0c0', marginBottom: 16 }}>
            {error} <button className="btn sm" style={{ marginLeft: 8 }} onClick={() => void load()}><RefreshCw size={12} /> 다시 시도</button>
          </div>
        )}

        <div className="card" style={{ padding: 16, marginBottom: 16 }}>
          <label className="search-box" style={{ width: '100%', marginBottom: 20 }}>
            <Search size={14} />
            <input
              style={{ width: '100%' }}
              placeholder="카드번호, 배정자, 팀 검색"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </label>
          <div className="filter-bar" style={{ padding: 0, border: 'none', gap: 14 }}>
            <span className="text-meta">카드분류</span>
            <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
              <option value="ALL">전체</option>
              <option value="TEAM">팀카드</option>
              <option value="PERSONAL">개인카드</option>
              <option value="SHARED">공용</option>
              <option value="POST_PAID">후정산</option>
              <option value="PREPAID">선결제</option>
            </select>
            <span className="text-meta">팀</span>
            <select value={teamFilter} onChange={(e) => setTeamFilter(e.target.value)}>
              <option value="ALL">전체 팀</option>
              {teamNames.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
            <span className="text-meta">상태</span>
            <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
              <option value="ALL">전체</option>
              <option value="ACTIVE">정상</option>
              <option value="STOPPED">정지·회수</option>
            </select>
          </div>
        </div>

        <div className="card">
          <div className="card-head"><h3>카드 목록</h3></div>
          <table className="table">
            <thead>
              <tr>
                <th>카드</th><th>카드 종류</th><th>배정 대상</th>
                <th className="num">이번달 사용액</th><th className="num">한도</th><th>상태</th><th></th>
              </tr>
            </thead>
            <tbody>
              {list.map((c) => (
                <tr key={c.id}>
                  <td>
                    <span className="row" style={{ gap: 8 }}>
                      <span style={{
                        display: 'flex', alignItems: 'center', justifyContent: 'center', width: 24, height: 18,
                        borderRadius: 4, background: c.type === 'PERSONAL' ? 'var(--sidebar-bg)' : 'var(--primary)', flexShrink: 0,
                      }}>
                        <CreditCard size={11} color="#fff" />
                      </span>
                      <span>
                        {c.number || c.name}
                        {c.number && c.name && <span className="text-meta" style={{ marginLeft: 6 }}>{c.name}</span>}
                      </span>
                    </span>
                  </td>
                  <td>
                    <span className="tag" style={c.type !== 'PERSONAL' ? { background: 'var(--primary-soft)', color: 'var(--primary)', borderColor: 'transparent' } : undefined}>
                      {c.typeLabel}
                    </span>
                  </td>
                  <td>
                    {c.assignee}
                    {c.attention && (
                      <div className="text-meta" style={{ color: 'var(--tone-amber)' }}>⚠ {c.attention.label}</div>
                    )}
                  </td>
                  <td className="num">{won(c.usage)}</td>
                  {/* 한도 0 = 미설정. 0원을 한도로 그리면 전 카드가 초과로 보인다. */}
                  <td className="num text-meta">{c.limit > 0 ? won(c.limit) : '미설정'}</td>
                  <td>
                    <span className="badge" style={c.status === 'ACTIVE'
                      ? { color: 'var(--tone-green)', background: 'var(--tone-green-bg)' }
                      : { color: 'var(--tone-red)', background: 'var(--tone-red-bg)' }}>
                      {c.statusLabel}
                    </span>
                  </td>
                  <td>
                    <div className="row" style={{ justifyContent: 'flex-end' }}>
                      <button className="btn sm" onClick={() => setAssigning(c)} disabled={pending}>배정 변경</button>
                      <button
                        className="btn sm"
                        style={{ borderColor: 'var(--tone-red)', color: 'var(--tone-red)' }}
                        onClick={() => setRecalling(c)}
                        disabled={pending || c.status === 'STOPPED'}
                      >
                        회수/정지
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {list.length === 0 && (
                <tr><td colSpan={7} className="text-meta" style={{ textAlign: 'center', padding: 24 }}>
                  {loading ? '불러오는 중…' : '해당 조건의 카드가 없습니다.'}
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="text-meta" style={{ marginTop: 12 }}>총 {list.length}건</div>
      </div>

      {assigning && (
        <AssignCardModal
          number={assigning.number || assigning.name}
          currentLabel={`${assigning.assignee} (${assigning.typeLabel})`}
          teams={teams}
          people={people}
          onClose={() => setAssigning(null)}
          onConfirm={confirmAssign}
        />
      )}
      {recalling && (
        <RecallCardModal
          number={recalling.number || recalling.name}
          assignee={recalling.assignee}
          statusLabel={recalling.statusLabel}
          defaultReason={recalling.attention?.label}
          onClose={() => setRecalling(null)}
          onConfirm={confirmRecall}
        />
      )}
    </>
  )
}

/** 회수/중지 필요 카드 — 서버가 사유별로 묶어 내려준 그대로 보여준다. */
function AttentionView({
  onBack, onRecall, recalling, onConfirmRecall, onCloseRecall, pending,
}: {
  onBack: () => void
  onRecall: (card: CorpCard) => void
  recalling: CorpCard | null
  onConfirmRecall: (reason: string, detail: string) => void
  onCloseRecall: () => void
  pending: boolean
}) {
  const [groups, setGroups] = useState<AttentionGroupData[]>([])
  const [total, setTotal] = useState(0)
  const [rule, setRule] = useState<{ windowDays: number; minCount: number } | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    void (async () => {
      try {
        const res = await fetchCardAttention()
        setGroups(res.groups)
        setTotal(res.total)
        setRule(res.anomalyRule)
      } finally {
        setLoading(false)
      }
    })()
  }, [recalling])

  return (
    <div className="page-inner">
      <button className="btn sm" style={{ marginBottom: 16 }} onClick={onBack}>
        <ArrowLeft size={13} /> 카드 관리로 돌아가기
      </button>
      <div className="page-head">
        <h1>회수/중지 필요 카드</h1>
        <div className="sub">퇴사자 또는 반복 이상사용이 감지된 카드입니다. 확인 후 조치해주세요.</div>
      </div>

      <div className="note" style={{
        display: 'flex', gap: 10, alignItems: 'flex-start', marginBottom: 24,
        background: total > 0 ? 'var(--tone-amber-bg)' : 'var(--surface-2)',
        border: total > 0 ? '1px solid #ead9ad' : '1px solid var(--border)',
      }}>
        <AlertTriangle size={18} color={total > 0 ? 'var(--tone-amber)' : 'var(--muted)'} style={{ flexShrink: 0, marginTop: 1 }} />
        <div>
          <div style={{ fontWeight: 700 }}>
            {loading ? '확인 중…' : total > 0 ? `현재 ${total}건의 카드가 조치가 필요합니다` : '조치가 필요한 카드가 없습니다'}
          </div>
          {/* 판정 기준을 화면에 그대로 적는다 — 근거를 숨기면 회수 결정을 내리는 사람이 판단할 수 없다. */}
          {rule && (
            <div className="text-meta">
              퇴사 처리된 사용자의 개인카드 · 최근 {rule.windowDays}일 내 동일 가맹점 {rule.minCount}회 이상 결제
            </div>
          )}
        </div>
      </div>

      {groups.map((g) => (
        <div key={g.reason} className="card" style={{ marginBottom: 16 }}>
          <div className="card-head"><h3>{g.label}</h3><span className="text-meta">{g.cards.length}건</span></div>
          <table className="table">
            <thead>
              <tr><th>카드</th><th>배정 대상</th><th>확인 사항</th><th></th></tr>
            </thead>
            <tbody>
              {g.cards.map((c) => (
                <tr key={c.id}>
                  <td>{c.number || c.name}</td>
                  <td>{c.assignee}</td>
                  <td>
                    {c.attention?.note}
                    <div className="text-meta">
                      {c.attention?.dateLabel}: {c.attention?.date || '-'}
                    </div>
                  </td>
                  <td>
                    <div className="row" style={{ justifyContent: 'flex-end' }}>
                      <button
                        className="btn sm"
                        style={{ borderColor: 'var(--tone-red)', color: 'var(--tone-red)' }}
                        onClick={() => onRecall(c)}
                        disabled={pending}
                      >
                        회수/정지
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}

      <div className="text-meta" style={{ marginTop: 8 }}>회수 확정 시 카드가 즉시 사용 정지되고 사유가 함께 기록됩니다.</div>

      {recalling && (
        <RecallCardModal
          number={recalling.number || recalling.name}
          assignee={recalling.assignee}
          statusLabel={recalling.statusLabel}
          defaultReason={recalling.attention?.label}
          onClose={onCloseRecall}
          onConfirm={onConfirmRecall}
        />
      )}
    </div>
  )
}

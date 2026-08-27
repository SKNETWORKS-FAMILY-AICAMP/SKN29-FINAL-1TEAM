// S-09 법인카드 관리 — 회계. 팀/개인 배정 카드 현황 + 배정 변경·회수/정지,
// 회수 필요 카드 별도 조치 큐.
//
// 카드 목록은 실 API 연동(`/api/cards/`). **화면은 판정을 하지 않는다** — 사용액도, "회수가
// 필요한가"도 서버가 계산해 내려준 값을 그대로 쓴다. 여기서 다시 계산하면 임계값 사본이 두 벌
// 생기고 곧 서로 다른 말을 한다(이전 목데이터 시절엔 그 판정이 아예 화면 상수였다).
//
// ⚠️ 예외 하나: **「회수/중지 필요」 조치 큐(`AttentionView`)는 시연용 목업이다.** 분실신고·
// 휴직·장기미사용은 그 사실을 담는 자리가 도메인에 없어 서버가 낼 수 없다. 화면에 그렇다고
// 밝히고, 거기서 누른 회수는 서버로 나가지 않는다. 자세한 건 아래 AttentionView 주석.
import type { CSSProperties } from 'react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle, ArrowLeft, ArrowRight, CalendarClock, CircleCheckBig, FlaskConical,
  Moon, RefreshCw, Repeat, Search, ShieldAlert, UserMinus,
} from 'lucide-react'
import { won } from '../lib/format'
import { AssignCardModal } from '../components/cards/AssignCardModal'
import { RecallCardModal } from '../components/cards/RecallCardModal'
import { KpiCard } from '../components/ui/KpiCard'
import { SkeletonRows } from '../components/ui/Skeleton'
import {
  assignCard, fetchCards, stopCard,
  type CardOption, type CorpCard,
} from '../api/cardService'
import {
  ATTENTION_MOCK, ATTENTION_MOCK_TOTAL, REASON_META, REASON_ORDER, SEVERITY_META,
  type AttentionMockCard, type AttentionReason,
} from '../data/cardAttentionMock'

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

  //  「회수/중지 필요」 화면은 지금 **시연용 목업**이다(→ `data/cardAttentionMock.ts` 서두).
  //  그래서 배지 숫자도 그 목업 건수를 쓴다 — 실 API 건수를 띄우고 목업 목록을 열면
  //  버튼과 화면이 다른 수를 말한다.
  const attentionCount = ATTENTION_MOCK_TOTAL

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

  if (view === 'attention') return <AttentionView onBack={() => setView('list')} />

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
          <div className="load-error" style={{ marginBottom: 16 }}>
            {error} <button className="btn sm" onClick={() => void load()}><RefreshCw size={12} /> 다시 시도</button>
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
          <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th>카드번호</th><th>카드 종류</th><th>배정 대상</th>
                <th className="num">이번달 사용액</th><th className="num">한도</th><th>상태</th><th></th>
              </tr>
            </thead>
            <tbody>
              {list.map((c) => (
                <tr key={c.id}>
                  <td>
                    <span className="row" style={{ gap: 8 }}>
                      <span className="card-chip" />
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
                        className="btn sm outline-danger"
                        onClick={() => setRecalling(c)}
                        disabled={pending || c.status === 'STOPPED'}
                      >
                        회수/정지
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {list.length === 0 && (loading
                ? <SkeletonRows rows={5} cols={7} />
                : <tr><td colSpan={7} className="text-meta" style={{ textAlign: 'center', padding: 24 }}>
                    해당 조건의 카드가 없습니다.
                  </td></tr>
              )}
            </tbody>
          </table>
          </div>
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


/* ── 회수/중지 필요 카드 ──────────────────────────────────────────────
 *
 *  ⚠️ **시연용 목업이다.** 여기 뜨는 9건은 `data/cardAttentionMock.ts`의 상수이고 서버에
 *  묻지 않는다 — 분실신고·휴직·장기미사용은 그 사실을 담는 자리가 도메인에 아직 없어서
 *  실 API가 낼 수 없는 사유다(내는 건 퇴사·반복 이상사용 둘뿐).
 *
 *  그래서 두 가지를 지킨다:
 *   ① 화면 상단에 「시연용 예시 데이터」라고 밝힌다. 회수는 되돌릴 수 없는 결정이라
 *      근거가 가짜인 줄 모르고 누르는 상황을 만들면 안 된다.
 *   ② 회수 확정이 서버로 나가지 않는다. 화면 안에서만 '조치 완료'로 바뀐다
 *      (실제로 `POST /api/cards/{id}/stop/`을 부르면 존재하지 않는 id로 404가 난다).
 *  실 사실이 도메인에 들어오면 목업 파일째 걷어내고 서버 응답을 그대로 그린다.
 */
const REASON_ICON: Record<AttentionReason, typeof UserMinus> = {
  RETIRED_OWNER: UserMinus,
  LOST_REPORTED: ShieldAlert,
  REPEAT_ANOMALY: Repeat,
  LEAVE_OF_ABSENCE: CalendarClock,
  DORMANT: Moon,
}

/** 사유 색을 CSS로 넘기는 통로 — `.attn-*`는 이 두 변수만 읽는다(색 정본은 REASON_META). */
const toneVars = (reason: AttentionReason): CSSProperties =>
  ({ '--attn-tone': REASON_META[reason].tone, '--attn-bg': REASON_META[reason].bg } as CSSProperties)

function AttentionView({ onBack }: { onBack: () => void }) {
  const [filter, setFilter] = useState<AttentionReason | 'ALL'>('ALL')
  //  조치한 건은 목록에서 지우지 않고 사유를 들고 남긴다 — 방금 무엇을 처리했는지가
  //  보여야 하고, 시연 중 되돌아와도 흐름이 이어진다.
  const [done, setDone] = useState<Record<number, string>>({})
  const [recalling, setRecalling] = useState<AttentionMockCard | null>(null)

  const counts = useMemo(() => {
    const map = {} as Record<AttentionReason, number>
    for (const r of REASON_ORDER) map[r] = 0
    for (const c of ATTENTION_MOCK) if (!done[c.id]) map[c.reason] += 1
    return map
  }, [done])

  const remaining = ATTENTION_MOCK.filter((c) => !done[c.id])
  const urgent = remaining.filter((c) => c.severity === 'URGENT').length
  const watch = remaining.filter((c) => c.severity === 'WATCH').length
  const list = filter === 'ALL' ? ATTENTION_MOCK : ATTENTION_MOCK.filter((c) => c.reason === filter)

  const confirmRecall = (reason: string, detail: string) => {
    if (!recalling) return
    setDone((prev) => ({ ...prev, [recalling.id]: detail.trim() ? `${reason} — ${detail.trim()}` : reason }))
    setRecalling(null)
  }

  return (
    <>
      <div className="hero-band" style={{ paddingBottom: 24 }}>
        <button className="btn sm" style={{ marginBottom: 14 }} onClick={onBack}>
          <ArrowLeft size={13} /> 카드 관리로 돌아가기
        </button>
        <div className="page-head" style={{ marginBottom: 0 }}>
          <h1 className="row" style={{ gap: 10, alignItems: 'center' }}>
            회수/중지 필요 카드
            <span className="tag" style={{ background: 'var(--tone-purple-bg)', color: 'var(--tone-purple)', borderColor: 'transparent', fontWeight: 700 }}>
              <FlaskConical size={12} /> 시연용 예시 데이터
            </span>
          </h1>
          <div className="sub">
            퇴사·분실신고·반복 이상사용 등 카드를 계속 두면 안 되는 사유가 잡힌 건입니다.
            사유와 근거를 확인한 뒤 회수 여부를 결정하세요.
          </div>
        </div>
        <div className="kpi-grid">
          <KpiCard flat label="조치 필요" value={remaining.length} unit="건" />
          <KpiCard flat warn={urgent > 0} label="즉시 조치" value={urgent} unit="건" />
          <KpiCard flat label="확인 필요" value={watch} unit="건" />
          <KpiCard flat label="조치 완료" value={Object.keys(done).length} unit="건" />
        </div>
      </div>

      <div className="page-inner">
        <div className="note" style={{
          display: 'flex', gap: 10, alignItems: 'flex-start', marginBottom: 20,
          background: 'var(--tone-purple-bg)', border: '1px dashed var(--tone-purple)', color: 'var(--text)',
        }}>
          <FlaskConical size={16} color="var(--tone-purple)" style={{ flexShrink: 0, marginTop: 1 }} />
          <div>
            <div style={{ fontWeight: 700, marginBottom: 2 }}>화면 시연용 예시 데이터입니다</div>
            {/* 무엇이 가짜인지 정확히 적는다 — "일부 목업"으로 뭉개면 어느 줄이 진짜인지 아무도 모른다. */}
            <div className="text-meta">
              분실신고·휴직·장기미사용은 아직 시스템이 수집하지 않는 사실이라, 조치 흐름을 보여주기 위한
              예시로 채워 두었습니다. 여기서 누른 회수/정지는 실제 카드에 반영되지 않습니다.
            </div>
          </div>
        </div>

        {/* 사유별 필터 — 큐가 길어지면 "지금 볼 것"부터 좁힌다. */}
        <div className="attn-filters">
          <button
            className={`attn-filter${filter === 'ALL' ? ' active' : ''}`}
            style={{ '--attn-tone': 'var(--primary)', '--attn-bg': 'var(--primary-soft)' } as CSSProperties}
            onClick={() => setFilter('ALL')}
          >
            <span className="ico"><AlertTriangle size={16} /></span>
            <span className="txt">
              <div className="n">{remaining.length}</div>
              <div className="l">전체</div>
            </span>
          </button>
          {REASON_ORDER.map((r) => {
            const Icon = REASON_ICON[r]
            return (
              <button
                key={r}
                className={`attn-filter${filter === r ? ' active' : ''}`}
                style={toneVars(r)}
                onClick={() => setFilter(filter === r ? 'ALL' : r)}
                title={REASON_META[r].desc}
              >
                <span className="ico"><Icon size={16} /></span>
                <span className="txt">
                  <div className="n">{counts[r]}</div>
                  <div className="l">{REASON_META[r].label}</div>
                </span>
              </button>
            )
          })}
        </div>

        {filter !== 'ALL' && (
          <div className="text-meta" style={{ marginBottom: 12 }}>{REASON_META[filter].desc}</div>
        )}

        <div className="attn-list">
          {list.map((c) => {
            const Icon = REASON_ICON[c.reason]
            const sev = SEVERITY_META[c.severity]
            const doneReason = done[c.id]
            return (
              <div key={c.id} className={`attn-row${doneReason ? ' done' : ''}`} style={toneVars(c.reason)}>
                <span className="ico"><Icon size={19} /></span>
                <div className="attn-body">
                  <div className="attn-title">
                    {/* 카드 미니어처 — 목록 어디서나 같은 모양으로 '카드'를 가리킨다. */}
                    <span className="card-chip" />
                    <span className="attn-no">{c.number}</span>
                    <span className="tag">{c.typeLabel}</span>
                    <span className="badge" style={{ color: REASON_META[c.reason].tone, background: REASON_META[c.reason].bg }}>
                      {REASON_META[c.reason].label}
                    </span>
                    {doneReason
                      ? <span className="badge" style={{ color: 'var(--tone-green)', background: 'var(--tone-green-bg)' }}><CircleCheckBig size={11} /> 조치 완료</span>
                      : <span className="badge" style={{ color: sev.tone, background: sev.bg }}>{sev.label}</span>}
                  </div>
                  <div className="attn-sub">{c.name} · {c.assignee} · {c.team}</div>
                  <div className="attn-note">{c.note}</div>
                  <div className="attn-facts">
                    <span>{c.dateLabel}<b>{c.date}</b></span>
                    <span>경과<b>{c.elapsedDays}일</b></span>
                    <span>최근 사용<b>{c.lastUsedAt} · {won(c.lastUsedAmount)}</b></span>
                    <span>이번 달 사용액<b>{won(c.monthUsage)}</b></span>
                    <span>한도<b>{won(c.limit)}</b></span>
                  </div>
                  {doneReason ? (
                    <div className="attn-reco" style={{ borderStyle: 'solid', borderColor: '#bfe6d1', background: 'var(--tone-green-bg)' }}>
                      처리 사유 <b>{doneReason}</b>
                    </div>
                  ) : (
                    <div className="attn-reco">권장 조치 <b>{c.recommend}</b></div>
                  )}
                </div>
                <div className="attn-actions">
                  <button
                    className={'btn sm' + (doneReason ? '' : ' outline-danger')}
                    onClick={() => setRecalling(c)}
                    disabled={!!doneReason}
                  >
                    {doneReason ? '처리됨' : '회수/정지'}
                  </button>
                </div>
              </div>
            )
          })}
          {list.length === 0 && (
            <div className="card" style={{ padding: 32, textAlign: 'center' }} >
              <div style={{ fontWeight: 700, marginBottom: 4 }}>이 사유로 조치할 카드가 없습니다</div>
              <div className="text-meta">다른 사유를 선택하거나 전체를 확인하세요.</div>
            </div>
          )}
        </div>

        <div className="text-meta" style={{ marginTop: 14 }}>
          실제 운영에서는 회수 확정 시 카드가 즉시 사용 정지되고 사유가 함께 기록됩니다.
        </div>
      </div>

      {recalling && (
        <RecallCardModal
          number={`${recalling.number} · ${recalling.name}`}
          assignee={recalling.assignee}
          statusLabel={SEVERITY_META[recalling.severity].label}
          defaultReason={RECALL_REASON_OF[recalling.reason]}
          onClose={() => setRecalling(null)}
          onConfirm={confirmRecall}
        />
      )}
    </>
  )
}

/** 모달 사유 선택지(`RecallCardModal`의 REASONS)와 **같은 문자열**이어야 기본 선택이 먹는다. */
const RECALL_REASON_OF: Record<AttentionReason, string> = {
  RETIRED_OWNER: '퇴사 처리',
  LOST_REPORTED: '분실·도난 신고',
  REPEAT_ANOMALY: '반복 이상사용 감지',
  LEAVE_OF_ABSENCE: '휴직·장기 파견',
  DORMANT: '장기 미사용',
}

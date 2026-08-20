// S-09 법인카드 관리 — 회계. 팀/개인 배정 카드 현황 조회 + 배정 변경/회수·정지, 회수 필요 카드 별도 조치 큐.
import { useMemo, useState } from 'react'
import { AlertTriangle, ArrowLeft, ArrowRight, CreditCard, Search } from 'lucide-react'
import { won } from '../lib/format'
import { AssignCardModal } from '../components/cards/AssignCardModal'
import { RecallCardModal } from '../components/cards/RecallCardModal'

type CardType = 'TEAM' | 'PERSONAL'
type CardStatus = 'NORMAL' | 'STOP_NEEDED'

interface CorpCard {
  id: string
  number: string
  type: CardType
  assignee: string
  team: string
  usage: number
  limit: number
  status: CardStatus
}

interface AttentionCard {
  id: string
  number: string
  owner: string
  team: string
  dateLabel: string
  date: string
  note: string
  reason: string
}

// 백엔드 카드 관리 API가 아직 없어 화면 시연용 목데이터로 구성했다(FastAPI/Django 연동은 별도 작업 필요).
const SEED_CARDS: CorpCard[] = [
  { id: 'c1', number: '1234-56**-****-7890', type: 'TEAM', assignee: '개발팀', team: '개발팀', usage: 3240000, limit: 5000000, status: 'NORMAL' },
  { id: 'c2', number: '5521-88**-****-1123', type: 'TEAM', assignee: '마케팅팀', team: '마케팅팀', usage: 2180000, limit: 4000000, status: 'NORMAL' },
  { id: 'c3', number: '9012-34**-****-5567', type: 'PERSONAL', assignee: '박서연 (영업팀)', team: '영업팀', usage: 890000, limit: 1500000, status: 'NORMAL' },
  { id: 'c4', number: '4432-11**-****-9981', type: 'PERSONAL', assignee: '김도현 (디자인팀)', team: '디자인팀', usage: 1120000, limit: 1500000, status: 'NORMAL' },
  { id: 'c5', number: '7789-22**-****-3345', type: 'TEAM', assignee: '경영지원팀', team: '경영지원팀', usage: 5430000, limit: 6000000, status: 'NORMAL' },
  { id: 'c6', number: '2210-77**-****-6612', type: 'PERSONAL', assignee: '최민준 (개발팀)', team: '개발팀', usage: 210000, limit: 1000000, status: 'STOP_NEEDED' },
  { id: 'c7', number: '8890-45**-****-2234', type: 'PERSONAL', assignee: '정하윤 (마케팅팀, 2026-07-31 퇴사)', team: '마케팅팀', usage: 0, limit: 1000000, status: 'STOP_NEEDED' },
  { id: 'c8', number: '3345-90**-****-4478', type: 'TEAM', assignee: '디자인팀', team: '디자인팀', usage: 1980000, limit: 3000000, status: 'NORMAL' },
]

const RETIRED: AttentionCard[] = [
  { id: 'a1', number: '8890-45**-****-2234', owner: '정하윤', team: '마케팅팀', dateLabel: '퇴사일', date: '2026-07-31', note: '퇴사 처리 완료 - 카드 회수 필요', reason: '퇴사 처리' },
  { id: 'a2', number: '6671-23**-****-8890', owner: '이준서', team: '영업팀', dateLabel: '퇴사일', date: '2026-08-05', note: '퇴사 처리 완료 - 카드 회수 필요', reason: '퇴사 처리' },
]
const ANOMALY: AttentionCard[] = [
  { id: 'a3', number: '5521-90**-****-3312', owner: '최민준', team: '개발팀', dateLabel: '감지일', date: '2026-08-10', note: '최근 30일 내 동일 가맹점 12회 결제 감지', reason: '반복 이상사용 감지' },
]

const TEAMS = ['개발팀', '마케팅팀', '영업팀', '디자인팀', '경영지원팀']
const PEOPLE = ['박서연 (영업팀)', '김도현 (디자인팀)', '최민준 (개발팀)', '이준서 (영업팀)']

export function CardManagement() {
  const [view, setView] = useState<'list' | 'attention'>('list')
  const [cards, setCards] = useState(SEED_CARDS)
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState<CardType | 'ALL'>('ALL')
  const [teamFilter, setTeamFilter] = useState<string>('ALL')
  const [statusFilter, setStatusFilter] = useState<CardStatus | 'ALL'>('ALL')
  const [assigning, setAssigning] = useState<CorpCard | null>(null)
  const [recalling, setRecalling] = useState<{ number: string; assignee: string; statusLabel: string; reason?: string } | null>(null)

  const teams = useMemo(() => [...new Set(cards.map((c) => c.team))], [cards])

  const list = useMemo(() => {
    const q = search.trim()
    return cards.filter((c) => {
      if (typeFilter !== 'ALL' && c.type !== typeFilter) return false
      if (teamFilter !== 'ALL' && c.team !== teamFilter) return false
      if (statusFilter !== 'ALL' && c.status !== statusFilter) return false
      if (q && !(c.number.includes(q) || c.assignee.includes(q) || c.team.includes(q))) return false
      return true
    })
  }, [cards, search, typeFilter, teamFilter, statusFilter])

  const confirmAssign = (target: { mode: 'TEAM' | 'PERSONAL'; value: string; reason: string }) => {
    if (!assigning) return
    setCards((prev) => prev.map((c) => (c.id === assigning.id
      ? { ...c, type: target.mode, assignee: target.value, team: target.mode === 'TEAM' ? target.value : c.team }
      : c)))
    setAssigning(null)
  }

  const confirmRecall = () => {
    if (!recalling) return
    setCards((prev) => prev.map((c) => (c.number === recalling.number ? { ...c, status: 'STOP_NEEDED' } : c)))
    setRecalling(null)
  }

  if (view === 'attention') {
    const total = RETIRED.length + ANOMALY.length
    return (
      <div className="page-inner">
        <button className="btn sm" style={{ marginBottom: 16 }} onClick={() => setView('list')}>
          <ArrowLeft size={13} /> 카드 관리로 돌아가기
        </button>
        <div className="page-head">
          <h1>회수/중지 필요 카드</h1>
          <div className="sub">퇴사자 또는 반복 이상사용이 감지된 카드입니다. 확인 후 조치해주세요.</div>
        </div>

        <div className="note" style={{
          display: 'flex', gap: 10, alignItems: 'flex-start', marginBottom: 24,
          background: 'var(--tone-amber-bg)', border: '1px solid #ead9ad',
        }}>
          <AlertTriangle size={18} color="var(--tone-amber)" style={{ flexShrink: 0, marginTop: 1 }} />
          <div>
            <div style={{ fontWeight: 700 }}>현재 {total}건의 카드가 조치가 필요합니다</div>
            <div className="text-meta">퇴사자 카드 {RETIRED.length}건 · 반복 이상사용 카드 {ANOMALY.length}건</div>
          </div>
        </div>

        <AttentionGroup title="퇴사자 카드" items={RETIRED} onRecall={setRecalling} />
        <AttentionGroup title="반복 이상사용 감지 카드" items={ANOMALY} onRecall={setRecalling} />

        <div className="text-meta" style={{ marginTop: 8 }}>조치가 필요한 카드는 회수 확인 후 자동으로 사용 정지 처리됩니다.</div>

        {recalling && (
          <RecallCardModal
            number={recalling.number}
            assignee={recalling.assignee}
            statusLabel={recalling.statusLabel}
            defaultReason={recalling.reason}
            onClose={() => setRecalling(null)}
            onConfirm={confirmRecall}
          />
        )}
      </div>
    )
  }

  return (
    <>
      <div className="hero-band" style={{ paddingBottom: 24 }}>
        <div className="page-head row" style={{ justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 0 }}>
          <div>
            <h1>법인카드 관리</h1>
            <div className="sub">팀별·개인별로 배정된 법인카드 현황을 확인하고 관리하세요</div>
          </div>
          <button
            className="btn"
            style={{ background: 'var(--tone-red-bg)', color: 'var(--tone-red)', borderColor: 'transparent' }}
            onClick={() => setView('attention')}
          >
            회수/중지 필요 카드 <ArrowRight size={14} />
          </button>
        </div>
      </div>

      <div className="page-inner">
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
            <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value as CardType | 'ALL')}>
              <option value="ALL">전체 팀</option>
              <option value="TEAM">팀카드</option>
              <option value="PERSONAL">개인카드</option>
            </select>
            <span className="text-meta">팀</span>
            <select value={teamFilter} onChange={(e) => setTeamFilter(e.target.value)}>
              <option value="ALL">전체 팀</option>
              {teams.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
            <span className="text-meta">상태</span>
            <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as CardStatus | 'ALL')}>
              <option value="ALL">전체 팀</option>
              <option value="NORMAL">정상</option>
              <option value="STOP_NEEDED">중지 필요</option>
            </select>
          </div>
        </div>

        <div className="card">
          <div className="card-head"><h3>카드 목록</h3></div>
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
                      <span style={{
                        display: 'flex', alignItems: 'center', justifyContent: 'center', width: 24, height: 18,
                        borderRadius: 4, background: c.type === 'TEAM' ? 'var(--primary)' : 'var(--sidebar-bg)', flexShrink: 0,
                      }}>
                        <CreditCard size={11} color="#fff" />
                      </span>
                      {c.number}
                    </span>
                  </td>
                  <td>
                    <span className="tag" style={c.type === 'TEAM' ? { background: 'var(--primary-soft)', color: 'var(--primary)', borderColor: 'transparent' } : undefined}>
                      {c.type === 'TEAM' ? '팀카드' : '개인카드'}
                    </span>
                  </td>
                  <td>{c.assignee}</td>
                  <td className="num">{won(c.usage)}</td>
                  <td className="num text-meta">{won(c.limit)}</td>
                  <td>
                    <span className="badge" style={c.status === 'NORMAL'
                      ? { color: 'var(--tone-green)', background: 'var(--tone-green-bg)' }
                      : { color: 'var(--tone-amber)', background: 'var(--tone-amber-bg)' }}>
                      {c.status === 'NORMAL' ? '정상' : '중지 필요'}
                    </span>
                  </td>
                  <td>
                    <div className="row" style={{ justifyContent: 'flex-end' }}>
                      <button className="btn sm" onClick={() => setAssigning(c)}>배정 변경</button>
                      <button
                        className="btn sm"
                        style={{ borderColor: 'var(--tone-red)', color: 'var(--tone-red)' }}
                        onClick={() => setRecalling({
                          number: c.number, assignee: c.assignee,
                          statusLabel: c.status === 'NORMAL' ? '정상' : '중지 필요',
                        })}
                      >
                        회수/정지
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {list.length === 0 && (
                <tr><td colSpan={7} className="text-meta" style={{ textAlign: 'center', padding: 24 }}>해당 조건의 카드가 없습니다.</td></tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="text-meta" style={{ marginTop: 12 }}>총 {list.length}건</div>
      </div>

      {assigning && (
        <AssignCardModal
          number={assigning.number}
          currentLabel={`${assigning.assignee} (${assigning.type === 'TEAM' ? '팀카드' : '개인카드'})`}
          teams={TEAMS}
          people={PEOPLE}
          onClose={() => setAssigning(null)}
          onConfirm={confirmAssign}
        />
      )}
      {recalling && (
        <RecallCardModal
          number={recalling.number}
          assignee={recalling.assignee}
          statusLabel={recalling.statusLabel}
          onClose={() => setRecalling(null)}
          onConfirm={confirmRecall}
        />
      )}
    </>
  )
}

function AttentionGroup({
  title, items, onRecall,
}: {
  title: string
  items: AttentionCard[]
  onRecall: (target: { number: string; assignee: string; statusLabel: string; reason: string }) => void
}) {
  if (items.length === 0) return null
  return (
    <div style={{ marginBottom: 24 }}>
      <div className="row" style={{ gap: 8, marginBottom: 10 }}>
        <h3 style={{ fontSize: 15 }}>{title}</h3>
        <span className="text-meta">{items.length}건</span>
      </div>
      <div className="stack" style={{ gap: 10 }}>
        {items.map((a) => (
          <div key={a.id} className="card row" style={{
            borderLeft: '3px solid var(--tone-amber)', padding: '14px 16px', justifyContent: 'space-between', alignItems: 'center',
          }}>
            <div className="row" style={{ gap: 12 }}>
              <span style={{
                display: 'flex', alignItems: 'center', justifyContent: 'center', width: 40, height: 28,
                borderRadius: 6, background: 'var(--sidebar-bg)', flexShrink: 0,
              }}>
                <CreditCard size={14} color="#fff" />
              </span>
              <div>
                <span className="row" style={{ gap: 8 }}>
                  <b style={{ fontSize: 13.5 }}>카드 {a.number}</b>
                  <span className="text-meta">{a.owner} · {a.team}</span>
                  <span className="tag">{a.dateLabel}: {a.date}</span>
                </span>
                <div className="text-meta" style={{ marginTop: 3 }}>{a.note}</div>
              </div>
            </div>
            <div className="row">
              <button
                className="btn sm"
                style={{ background: 'var(--tone-red-bg)', color: 'var(--tone-red)', borderColor: 'transparent' }}
                onClick={() => onRecall({ number: a.number, assignee: `${a.owner} (${a.team})`, statusLabel: '중지 필요', reason: a.reason })}
              >
                즉시 회수
              </button>
              <button className="btn sm">검토 후 처리</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
// S-08 예산 관리 — 회계/임원진. 전사 팀별 비용분류 예산 조회(전 팀 탭 전환).
//
// 실 API 연동(`/api/team-budget/overview/`). **한도만 DB, 사용액은 실 내역 집계**라는
// 서버 규약을 그대로 받는다 — 화면이 합계를 다시 만들지 않는다(`TeamBudget` 불변식:
// 팀 총한도 = 과목 한도 합 / 과목 사용 합 = 총 사용액).
//
// 수정(Frame 22)은 여전히 범위 밖이다 — 예산 쓰기 API가 없고, 예산은 통제가 아니라
// 지표라는 원칙상 누가 고칠 수 있는지가 먼저 정해져야 한다.
import { useEffect, useMemo, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { won, pct } from '../lib/format'
import { endpoints } from '../api/client'

interface BudgetCategory { label: string; limit: number; used: number }
interface TeamBudgetRow {
  id: number
  name: string
  total: number
  used: number
  categories: BudgetCategory[]
  unbudgeted: Record<string, number>
  unbudgetedUsed: number
}

type Tone = 'NORMAL' | 'CAUTION' | 'OVER'
const toneOf = (rate: number): Tone => (rate >= 100 ? 'OVER' : rate >= 75 ? 'CAUTION' : 'NORMAL')
const TONE_LABEL: Record<Tone, string> = { NORMAL: '정상', CAUTION: '주의', OVER: '초과' }
const TONE_COLOR: Record<Tone, string> = { NORMAL: 'var(--tone-green)', CAUTION: 'var(--tone-amber)', OVER: 'var(--tone-red)' }
const TONE_BG: Record<Tone, string> = { NORMAL: 'var(--tone-green-bg)', CAUTION: 'var(--tone-amber-bg)', OVER: 'var(--tone-red-bg)' }

export function BudgetManagement() {
  const [teams, setTeams] = useState<TeamBudgetRow[]>([])
  const [month, setMonth] = useState('')
  const [selected, setSelected] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const { data } = await endpoints.budgetOverview()
      setTeams(data.teams ?? [])
      setMonth(data.month ?? '')
      setSelected((prev) => prev ?? data.teams?.[0]?.id ?? null)
    } catch (e) {
      setError(e instanceof Error ? e.message : '예산 현황을 불러오지 못했습니다.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [])

  const team = useMemo(() => teams.find((t) => t.id === selected) ?? teams[0], [teams, selected])

  //  총액은 **서버가 준 값**을 쓴다. 화면에서 과목 합으로 다시 만들면 예산 행이 없는
  //  과목의 지출(unbudgeted)이 빠져서 "항목 합 ≠ 총 사용액"이 조용히 생긴다.
  const totals = useMemo(() => {
    if (!team) return { allocated: 0, used: 0, remaining: 0, rate: 0 }
    const allocated = team.total || team.categories.reduce((s, r) => s + r.limit, 0)
    return {
      allocated, used: team.used, remaining: allocated - team.used,
      rate: allocated > 0 ? team.used / allocated : 0,
    }
  }, [team])

  return (
    <>
      <div className="hero-band" style={{ paddingBottom: 24 }}>
        <div className="page-head">
          <h1>예산 관리</h1>
          <div className="sub">각 팀의 비용 분류별 예산을 확인하세요{month ? ` · ${month}` : ''}</div>
        </div>
      </div>

      <div className="page-inner">
        {error && (
          <div className="note" style={{ background: 'var(--tone-red-bg)', border: '1px solid #e8c0c0', marginBottom: 16 }}>
            {error} <button className="btn sm" style={{ marginLeft: 8 }} onClick={() => void load()}><RefreshCw size={12} /> 다시 시도</button>
          </div>
        )}

        <div className="row" style={{ gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
          {teams.map((t) => (
            <button
              key={t.id}
              type="button"
              className="btn"
              style={team?.id === t.id ? { background: 'var(--primary-soft)', borderColor: 'var(--primary)', color: 'var(--primary)', fontWeight: 700 } : undefined}
              onClick={() => setSelected(t.id)}
            >
              {t.name}
            </button>
          ))}
          {teams.length === 0 && !loading && <span className="text-meta">등록된 팀이 없습니다.</span>}
        </div>

        <div className="kpi-grid" style={{ gridTemplateColumns: 'repeat(4, 1fr)' }}>
          <div className="kpi"><div className="label">총 예산</div><div className="value">{won(totals.allocated)}</div></div>
          <div className="kpi"><div className="label">사용 금액</div><div className="value">{won(totals.used)}</div></div>
          <div className="kpi"><div className="label">잔여 예산</div><div className="value">{won(totals.remaining)}</div></div>
          <div className="kpi">
            <div className="label">집행률</div>
            <div className="value">{Math.round(totals.rate * 100)}<small>%</small></div>
            <div style={{ height: 6, background: 'var(--surface-2)', borderRadius: 'var(--radius-pill)', overflow: 'hidden', marginTop: 8 }}>
              <div style={{ width: pct(Math.min(totals.rate, 1)), height: '100%', background: 'var(--primary)' }} />
            </div>
          </div>
        </div>

        {/* 예산 행이 없는 과목의 지출 — 숨기면 "항목 합 ≠ 총 사용액"이 원인 없이 어긋나 보인다. */}
        {team && team.unbudgetedUsed > 0 && (
          <div className="note" style={{ background: 'var(--tone-amber-bg)', border: '1px solid #ead9ad', marginBottom: 16 }}>
            예산 행이 없는 과목의 지출 {won(team.unbudgetedUsed)} — 아래 항목 합계에는 포함되지 않습니다
            ({Object.entries(team.unbudgeted).map(([k, v]) => `${k || '분류 미지정'} ${won(v)}`).join(' · ')}).
          </div>
        )}

        <div className="note" style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12,
          background: 'var(--tone-amber-bg)', border: '1px solid #ead9ad', marginBottom: 16,
        }}>
          <span>예산 수정 권한이 없습니다. 관리자에게 권한을 요청하세요.</span>
          <button className="btn sm" disabled>권한 요청</button>
        </div>

        <div className="card">
          <table className="table">
            <thead>
              <tr>
                <th>카테고리명</th><th className="num">배정 예산</th><th className="num">사용 금액</th>
                <th className="num">잔여</th><th>진행률</th><th>상태</th><th></th>
              </tr>
            </thead>
            <tbody>
              {(team?.categories ?? []).map((r) => {
                const remaining = r.limit - r.used
                const rate = r.limit > 0 ? r.used / r.limit : 0
                const tone = toneOf(rate * 100)
                return (
                  <tr key={r.label}>
                    <td><b>{r.label}</b></td>
                    <td className="num">{won(r.limit)}</td>
                    <td className="num">{won(r.used)}</td>
                    <td className="num" style={remaining < 0 ? { color: 'var(--tone-red)' } : undefined}>{won(remaining)}</td>
                    <td>
                      <div className="row" style={{ gap: 8, alignItems: 'center' }}>
                        <div style={{ width: 90, height: 6, background: 'var(--surface-2)', borderRadius: 'var(--radius-pill)', overflow: 'hidden' }}>
                          <div style={{ width: pct(Math.min(rate, 1)), height: '100%', background: TONE_COLOR[tone] }} />
                        </div>
                        <span className="text-meta">{Math.round(rate * 100)}%</span>
                      </div>
                    </td>
                    <td><span className="badge" style={{ color: TONE_COLOR[tone], background: TONE_BG[tone] }}>{TONE_LABEL[tone]}</span></td>
                    <td><button className="btn sm" disabled>수정</button></td>
                  </tr>
                )
              })}
              {(team?.categories.length ?? 0) === 0 && (
                <tr><td colSpan={7} className="text-meta" style={{ textAlign: 'center', padding: 24 }}>
                  {loading ? '불러오는 중…' : '이 팀·이번 달에 배정된 예산이 없습니다.'}
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </>
  )
}

// S-08 예산 관리 — 회계/임원진. 전사 팀별 비용분류 예산 조회(전체/팀별 탭 전환) +
// 계정과목 지출 추세·예산 산정 지표(구 거버넌스 대시보드 흡수, 거버넌스 메뉴는 팀 결정으로 폐지).
//
// 실 API 연동(`/api/team-budget/overview/`). **한도만 DB, 사용액은 실 내역 집계**라는
// 서버 규약을 그대로 받는다 — 화면이 합계를 다시 만들지 않는다(`TeamBudget` 불변식:
// 팀 총한도 = 과목 한도 합 / 과목 사용 합 = 총 사용액). "전체" 탭은 이 팀별 응답을
// 화면에서 합산한 것이지 서버가 별도로 계산해 주지 않는다.
//
// 계정과목별 지출 추세·과부족 패턴도 **실 API**다(`/api/team-budget/trend/`).
// 목업이던 시절의 전제("과거 달 데이터가 seed에 없다")는 `seed_adopted`가 직전 3개월을
// 실제 전이로 만들면서 깨졌다.
//
// **「0원」과 「데이터 없음」을 구분한다** — 서버가 정산이 한 건도 없는 달을 `null`로 준다.
// 0으로 채우면 이력이 3개월뿐인데도 13개월 그래프가 그려지고, 사람은 앞의 0을 "지출이
// 없었다"로, 그 다음을 "급증"으로 읽는다. 팀 탭을 누르면 그 팀의 추세를 다시 받는다.
import { useEffect, useMemo, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { won, pct } from '../lib/format'
import { endpoints } from '../api/client'
import { Sparkline, DeltaText } from '../components/ui/GovCharts'

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

/** 과부족 패턴 한 줄. `months/windowMonths` = 같은 방향으로 치우친 개월 / 한도가 있던 개월. */
interface PatternRow {
  category: string
  months: number
  windowMonths: number
  avgGapPct: number
  amount: number
}
interface TrendData {
  months: string[]
  categories: string[]
  /** 정산이 한 건도 없는 달은 `null` — 0원과 다른 뜻이다. */
  spend: Record<string, (number | null)[]>
  totals: (number | null)[]
  dataMonths: string[]
  window: number
  pattern: { surplus: PatternRow[]; short: PatternRow[] }
}

type Tone = 'NORMAL' | 'CAUTION' | 'OVER'
const toneOf = (rate: number): Tone => (rate >= 100 ? 'OVER' : rate >= 75 ? 'CAUTION' : 'NORMAL')
const TONE_LABEL: Record<Tone, string> = { NORMAL: '정상', CAUTION: '주의', OVER: '초과' }
const TONE_COLOR: Record<Tone, string> = { NORMAL: 'var(--tone-green)', CAUTION: 'var(--tone-amber)', OVER: 'var(--tone-red)' }
const TONE_BG: Record<Tone, string> = { NORMAL: 'var(--tone-green-bg)', CAUTION: 'var(--tone-amber-bg)', OVER: 'var(--tone-red-bg)' }

const manwon = (value: number) => `${Math.round(value).toLocaleString()}만원`
const trendNote = (diff: number, rate: number) =>
  rate >= 30 ? `${manwon(diff)} 늘었습니다 — 한도 재산정 대상`
    : rate >= 10 ? `${manwon(diff)} 증가 — 추이 관찰 필요`
    : rate <= -10 ? `${manwon(Math.abs(diff))} 감소 — 한도 여유`
    : '변동 폭이 작습니다'

/** "전체" 탭 — 서버가 팀별로 내려준 걸 화면에서 합산한다(서버 계산 아님). */
const ALL = -1

function mergeTeams(teams: TeamBudgetRow[]): TeamBudgetRow {
  const byLabel = new Map<string, BudgetCategory>()
  const unbudgeted: Record<string, number> = {}
  for (const t of teams) {
    for (const c of t.categories) {
      const row = byLabel.get(c.label) ?? { label: c.label, limit: 0, used: 0 }
      row.limit += c.limit
      row.used += c.used
      byLabel.set(c.label, row)
    }
    for (const [cat, amt] of Object.entries(t.unbudgeted)) unbudgeted[cat] = (unbudgeted[cat] ?? 0) + amt
  }
  return {
    id: ALL, name: '전체',
    total: teams.reduce((s, t) => s + t.total, 0),
    used: teams.reduce((s, t) => s + t.used, 0),
    categories: [...byLabel.values()],
    unbudgeted,
    unbudgetedUsed: teams.reduce((s, t) => s + t.unbudgetedUsed, 0),
  }
}

export function BudgetManagement() {
  const [teams, setTeams] = useState<TeamBudgetRow[]>([])
  const [month, setMonth] = useState('')
  const [selected, setSelected] = useState<number>(ALL)
  const [trend, setTrend] = useState<TrendData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const { data } = await endpoints.budgetOverview()
      setTeams(data.teams ?? [])
      setMonth(data.month ?? '')
    } catch (e) {
      setError(e instanceof Error ? e.message : '예산 현황을 불러오지 못했습니다.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [])

  //  추세는 탭(전체/팀)이 바뀌면 다시 받는다 — 팀별로 쪼갤 데이터가 없어 "전체"에 고정
  //  했던 건 목업 시절의 제약이다. **추세를 못 받아도 예산 표는 그대로 보여준다**(따로
  //  잡는 이유): 부가 섹션 하나가 실패해서 화면 전체가 비면 담당자가 할 일을 못 한다.
  useEffect(() => {
    let alive = true
    const params = selected === ALL ? undefined : selected
    void (async () => {
      try {
        const { data } = await endpoints.budgetTrend(params)
        if (alive) setTrend(data)
      } catch {
        if (alive) setTrend(null)
      }
    })()
    return () => { alive = false }
  }, [selected])

  const allScope = useMemo(() => mergeTeams(teams), [teams])
  const team = selected === ALL ? allScope : (teams.find((t) => t.id === selected) ?? allScope)

  //  총액은 **서버가 준 값**을 쓴다. 화면에서 과목 합으로 다시 만들면 예산 행이 없는
  //  과목의 지출(unbudgeted)이 빠져서 "항목 합 ≠ 총 사용액"이 조용히 생긴다.
  const totals = useMemo(() => {
    const allocated = team.total || team.categories.reduce((s, r) => s + r.limit, 0)
    return {
      allocated, used: team.used, remaining: allocated - team.used,
      rate: allocated > 0 ? team.used / allocated : 0,
    }
  }, [team])

  // 이번달 팀별 예산 소진율 — 실 데이터(팀 배열은 이미 응답에 있다, 추가 호출 없음).
  const teamBurnRates = useMemo(
    () => teams.map((t) => ({ id: t.id, name: t.name, rate: t.total > 0 ? (t.used / t.total) * 100 : null, used: t.used })),
    [teams],
  )
  const maxBurnRate = Math.max(100, ...teamBurnRates.map((t) => t.rate ?? 0))

  //  계정과목별 지출 추세 — 전월 대비(시안에 YOY 토글 없음). 금액은 서버가 **원** 단위로
  //  주고 표시만 만원으로 접는다(화면에서 단위를 바꿔 저장하면 합계가 어긋난다).
  //
  //  비교 기준은 「배열의 끝에서 두 번째」가 아니라 **데이터가 있는 마지막 두 달**이다.
  //  이력이 3개월이면 앞 10칸이 `null`인데, 인덱스로 잡으면 전월이 null이 되어 증감이
  //  전부 0%로 나온다.
  const trendRows = useMemo(() => {
    if (!trend) return []
    const withData = trend.months
      .map((m, i) => ({ m, i }))
      .filter(({ m }) => trend.dataMonths.includes(m))
    if (!withData.length) return []
    const nowIdx = withData[withData.length - 1].i
    //  이력이 한 달뿐이면 **비교할 전월이 없다**. 자기 자신을 기준으로 두면 "전월에도 같은
    //  금액을 썼다"로 보이고 증감률이 0%로 찍힌다 — 없는 것을 0으로 채우지 않는다.
    const baseIdx = withData.length > 1 ? withData[withData.length - 2].i : null
    return trend.categories.map((cat) => {
      const series = trend.spend[cat] ?? []
      const now = series[nowIdx] ?? 0
      const base = baseIdx === null ? null : (series[baseIdx] ?? 0)
      const diff = base === null ? null : now - base
      return {
        category: cat,
        //  Sparkline은 숫자만 받는다 — 데이터 없는 달은 그리지 않고 잘라낸다.
        series: withData.map(({ i }) => series[i] ?? 0),
        now, base, diff,
        rate: base ? ((now - base) / base) * 100 : null,
      }
    })
  }, [trend])

  const totalSeries = useMemo(() => {
    if (!trend) return [] as number[]
    return trend.months
      .map((m, i) => ({ m, v: trend.totals[i] }))
      .filter(({ m }) => trend.dataMonths.includes(m))
      .map(({ v }) => v ?? 0)
  }, [trend])

  const totalNow = totalSeries.length ? totalSeries[totalSeries.length - 1] : 0
  const totalBase = totalSeries.length > 1 ? totalSeries[totalSeries.length - 2] : null
  const totalDiff = totalBase === null ? null : totalNow - totalBase
  const totalRate = totalBase ? ((totalNow - totalBase) / totalBase) * 100 : null
  const topMover = [...trendRows]
    .filter((r) => r.diff !== null)
    .sort((a, b) => Math.abs(b.diff!) - Math.abs(a.diff!))[0]
  //  이력이 몇 달인지 화면에 적는다 — 13개월 틀에 3개월만 차 있으면 사람은 그 사실을
  //  모르고 "예년보다 늘었다"를 읽는다.
  const historyMonths = trend?.dataMonths.length ?? 0

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
          <button
            type="button" className="btn"
            style={selected === ALL ? { background: 'var(--primary-soft)', borderColor: 'var(--primary)', color: 'var(--primary)', fontWeight: 700 } : undefined}
            onClick={() => setSelected(ALL)}
          >
            전체
          </button>
          {teams.map((t) => (
            <button
              key={t.id}
              type="button"
              className="btn"
              style={selected === t.id ? { background: 'var(--primary-soft)', borderColor: 'var(--primary)', color: 'var(--primary)', fontWeight: 700 } : undefined}
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

        {/* 팀별 소진율은 "전체" 탭 전용(팀 하나로는 비교가 의미 없다). 과부족 패턴은 실
            데이터가 생겨 팀별로도 뜻이 있지만, 소진율 비교와 한 카드에 묶여 있어 같이 둔다. */}
        {selected === ALL && (
          <div className="budget-pattern-grid" style={{ marginTop: 16 }}>
            <div className="card">
              <div className="card-head"><h3>이번달 팀별 예산 소진율</h3></div>
              <div className="card-body">
                {teamBurnRates.length === 0 ? (
                  <div className="text-meta">{loading ? '불러오는 중…' : '팀이 없습니다.'}</div>
                ) : (
                  <div className="team-burn-bars">
                    {teamBurnRates.map((t) => {
                      const rate = t.rate ?? 0
                      const tone = toneOf(rate)
                      return (
                        <div key={t.id} className="team-burn-bar-col">
                          <div className="team-burn-bar-value" style={{ color: TONE_COLOR[tone] }}>
                            {t.rate != null ? `${Math.round(t.rate)}%` : won(t.used)}
                          </div>
                          <div
                            className="team-burn-bar"
                            style={{ height: `${Math.max((rate / maxBurnRate) * 100, 2)}%`, background: TONE_COLOR[tone] }}
                          />
                          <div className="team-burn-bar-label">{t.name}</div>
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            </div>

            <div className="card">
              <div className="card-head">
                <div>
                  <h3>예산 산정 지표</h3>
                  <div className="text-meta">
                    같은 항목이 매달 남거나 모자라면 집행이 아니라 <b>한도 산정</b>의 문제입니다
                    {trend ? ` · 최근 ${trend.window}개월 중 이력 ${historyMonths}개월` : ''}
                  </div>
                </div>
              </div>
              <div className="card-body">
                <div className="budget-pattern-subgrid">
                  <div>
                    <div className="gov-sub-title">자주 남는 항목</div>
                    <table className="table gov-pattern-table">
                      <thead><tr><th>항목</th><th className="num">해당 개월</th><th className="num">평균 잔여</th><th className="num">누적</th></tr></thead>
                      <tbody>
                        {(trend?.pattern.surplus ?? []).map((row) => (
                          <tr key={row.category}>
                            <td><b>{row.category}</b></td>
                            {/* 분모는 6이 아니라 **한도가 있던 개월**이다 — 예산 행이 없는
                                달을 세면 "6개월 중 2개월"이 실제보다 낮게 보인다. */}
                            <td className="num">{row.months}/{row.windowMonths}</td>
                            <td className="num" style={{ color: 'var(--tone-green)', fontWeight: 700 }}>+{row.avgGapPct}%</td>
                            <td className="num text-meta">{manwon(row.amount / 10000)}</td>
                          </tr>
                        ))}
                        {trend && trend.pattern.surplus.length === 0 && (
                          <tr><td colSpan={4} className="text-meta">한도가 남는 항목이 없습니다</td></tr>
                        )}
                      </tbody>
                    </table>
                  </div>

                  <div>
                    <div className="gov-sub-title">자주 부족한 항목</div>
                    <table className="table gov-pattern-table">
                      <thead><tr><th>항목</th><th className="num">해당 개월</th><th className="num">평균 초과</th><th className="num">누적</th></tr></thead>
                      <tbody>
                        {(trend?.pattern.short ?? []).map((row) => (
                          <tr key={row.category}>
                            <td><b>{row.category}</b></td>
                            <td className="num">{row.months}/{row.windowMonths}</td>
                            <td className="num" style={{ color: 'var(--tone-red)', fontWeight: 700 }}>{row.avgGapPct}%</td>
                            <td className="num text-meta">{manwon(Math.abs(row.amount) / 10000)}</td>
                          </tr>
                        ))}
                        {trend && trend.pattern.short.length === 0 && (
                          <tr><td colSpan={4} className="text-meta">한도를 넘긴 항목이 없습니다</td></tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* 예산 행이 없는 과목의 지출 — 숨기면 "항목 합 ≠ 총 사용액"이 원인 없이 어긋나 보인다. */}
        {team.unbudgetedUsed > 0 && (
          <div className="note" style={{ background: 'var(--tone-amber-bg)', border: '1px solid #ead9ad', margin: '16px 0' }}>
            예산 행이 없는 과목의 지출 {won(team.unbudgetedUsed)} — 아래 항목 합계에는 포함되지 않습니다
            ({Object.entries(team.unbudgeted).map(([k, v]) => `${k || '분류 미지정'} ${won(v)}`).join(' · ')}).
          </div>
        )}

        <div className="note" style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12,
          background: 'var(--tone-amber-bg)', border: '1px solid #ead9ad', margin: '16px 0',
        }}>
          <span>예산 수정 권한이 없습니다. 관리자에게 권한을 요청하세요.</span>
          <button className="btn sm" disabled>권한 요청</button>
        </div>

        <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 4 }}>계정과목별 예산 현황</div>
        <div className="text-meta" style={{ marginBottom: 8 }}>{team.name} 예산</div>
        <div className="card" style={{ marginBottom: 24 }}>
          <table className="table">
            <thead>
              <tr>
                <th>카테고리명</th><th className="num">배정 예산</th><th className="num">사용 금액</th>
                <th className="num">잔여</th><th>사용률</th><th>상태</th><th></th>
              </tr>
            </thead>
            <tbody>
              {team.categories.map((r) => {
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
              {team.categories.length === 0 && (
                <tr><td colSpan={7} className="text-meta" style={{ textAlign: 'center', padding: 24 }}>
                  {loading ? '불러오는 중…' : '이 팀·이번 달에 배정된 예산이 없습니다.'}
                </td></tr>
              )}
            </tbody>
          </table>
        </div>

        {/* 계정과목별 지출 추세 — 실 데이터. 팀 탭을 따라간다(`selected`가 바뀌면 다시 받는다). */}
        <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 4 }}>
          계정과목별 지출 추세{selected !== ALL ? ` · ${team.name}` : ''}
        </div>
        <div className="text-meta" style={{ marginBottom: 8 }}>
          {/* 「13개월」이라 적어두고 3개월만 차 있으면 사람은 그걸 모른다 — 실제 이력을 적는다. */}
          이력 {historyMonths}개월 · 전월 대비 증감 (단위 만원)
        </div>
        <div className="card">
          <table className="table gov-trend-table">
            <thead>
              <tr>
                <th style={{ width: 88 }}>계정과목</th>
                {/* 「13개월」로 고정해 두면 이력이 3개월이어도 그렇게 읽힌다 — 실제 값을 쓴다. */}
                <th style={{ width: 110 }}>{historyMonths || ''}개월 추이</th>
                <th className="num" style={{ width: 92 }}>이번 달</th>
                <th className="num" style={{ width: 92 }}>전월</th>
                <th style={{ width: 120 }}>전월대비 증감률</th>
                <th>메모</th>
              </tr>
            </thead>
            <tbody>
              {trendRows.length === 0 && (
                <tr><td colSpan={6} className="text-meta">
                  {trend ? '집계할 지출 이력이 없습니다' : '지출 추세를 불러오지 못했습니다'}
                </td></tr>
              )}
              {trendRows.map((row) => (
                <tr key={row.category}>
                  <td><b>{row.category}</b></td>
                  <td><Sparkline data={row.series} color="var(--primary)" width={100} height={26} /></td>
                  <td className="num">{Math.round(row.now / 10000).toLocaleString()}</td>
                  <td className="num text-meta">
                    {row.base === null ? '—' : Math.round(row.base / 10000).toLocaleString()}
                  </td>
                  <td>{row.rate === null ? <span className="text-meta">—</span>
                       : <DeltaText value={row.rate} higherIsBetter={false} />}</td>
                  {/* trendNote는 **만원** 단위를 받는다 — 원 단위를 그대로 넘기면
                      "4,720,000만원 늘었습니다"가 된다. */}
                  <td className="text-meta">
                    {row.diff === null || row.rate === null
                      ? '비교할 전월 이력이 없습니다'
                      : trendNote(row.diff / 10000, row.rate)}
                  </td>
                </tr>
              ))}
              <tr className="gov-total-row">
                <td><b>합계</b></td>
                <td><Sparkline data={totalSeries} color="var(--text)" width={100} height={26} /></td>
                <td className="num"><b>{Math.round(totalNow / 10000).toLocaleString()}</b></td>
                <td className="num text-meta">
                  {totalBase === null ? '—' : Math.round(totalBase / 10000).toLocaleString()}
                </td>
                <td>{totalRate === null ? <span className="text-meta">—</span>
                     : <DeltaText value={totalRate} higherIsBetter={false} />}</td>
                <td className="text-meta">
                  {/* 이력이 한 달뿐이거나 추세 조회가 실패하면 topMover가 없다 — 문장을
                      지어내지 않고 비운다. */}
                  {topMover && totalBase && totalDiff !== null
                    ? <>{totalDiff >= 0 ? '증가분' : '감소분'}의 대부분이 <b>{topMover.category}</b>({manwon(Math.abs(topMover.diff!) / 10000)})에서 나왔습니다.</>
                    : '비교할 전월 이력이 없습니다'}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </>
  )
}

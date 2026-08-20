// 예산 관리 — 회계/임원진. 전사 팀별 비용분류 예산 조회(전 팀 탭 전환). 조회 전용(Frame 21) —
// 수정 권한(Frame 22)은 권한 모델이 아직 정리되지 않아 이번 작업 범위에서 제외했다(관리자에게 권한 요청 버튼만 노출).
import { useMemo, useState } from 'react'
import { won, pct } from '../lib/format'

interface BudgetRow {
  category: string
  allocated: number
  used: number
}

// 백엔드 API가 아직 없어 화면 시연용 목데이터로 구성했다.
const TEAM_BUDGETS: Record<string, BudgetRow[]> = {
  개발팀: [
    { category: '식비', allocated: 2000000, used: 1450000 },
    { category: '교통비', allocated: 800000, used: 620000 },
    { category: '기업업무추진비', allocated: 3500000, used: 3680000 },
    { category: '소모품비', allocated: 1200000, used: 540000 },
    { category: '출장비', allocated: 4500000, used: 1550000 },
  ],
  마케팅팀: [
    { category: '식비', allocated: 1500000, used: 1120000 },
    { category: '교통비', allocated: 600000, used: 410000 },
    { category: '기업업무추진비', allocated: 2800000, used: 1950000 },
    { category: '소모품비', allocated: 900000, used: 380000 },
    { category: '출장비', allocated: 2000000, used: 1780000 },
  ],
  영업팀: [
    { category: '식비', allocated: 1800000, used: 1690000 },
    { category: '교통비', allocated: 1200000, used: 1340000 },
    { category: '기업업무추진비', allocated: 4000000, used: 4480000 },
    { category: '소모품비', allocated: 500000, used: 190000 },
    { category: '출장비', allocated: 3200000, used: 2010000 },
  ],
  디자인팀: [
    { category: '식비', allocated: 1200000, used: 780000 },
    { category: '교통비', allocated: 500000, used: 260000 },
    { category: '기업업무추진비', allocated: 1500000, used: 640000 },
    { category: '소모품비', allocated: 1800000, used: 1210000 },
    { category: '출장비', allocated: 1000000, used: 320000 },
  ],
  경영지원팀: [
    { category: '식비', allocated: 1000000, used: 590000 },
    { category: '교통비', allocated: 400000, used: 180000 },
    { category: '기업업무추진비', allocated: 1200000, used: 650000 },
    { category: '소모품비', allocated: 2000000, used: 1340000 },
    { category: '출장비', allocated: 800000, used: 210000 },
  ],
}

const TEAMS = Object.keys(TEAM_BUDGETS)

type Tone = 'NORMAL' | 'CAUTION' | 'OVER'
const toneOf = (rate: number): Tone => (rate >= 100 ? 'OVER' : rate >= 75 ? 'CAUTION' : 'NORMAL')
const TONE_LABEL: Record<Tone, string> = { NORMAL: '정상', CAUTION: '주의', OVER: '초과' }
const TONE_COLOR: Record<Tone, string> = { NORMAL: 'var(--tone-green)', CAUTION: 'var(--tone-amber)', OVER: 'var(--tone-red)' }
const TONE_BG: Record<Tone, string> = { NORMAL: 'var(--tone-green-bg)', CAUTION: 'var(--tone-amber-bg)', OVER: 'var(--tone-red-bg)' }

export function BudgetManagement() {
  const [team, setTeam] = useState(TEAMS[0])
  const rows = TEAM_BUDGETS[team]

  const totals = useMemo(() => {
    const allocated = rows.reduce((s, r) => s + r.allocated, 0)
    const used = rows.reduce((s, r) => s + r.used, 0)
    return { allocated, used, remaining: allocated - used, rate: allocated > 0 ? used / allocated : 0 }
  }, [rows])

  return (
    <>
      <div className="hero-band" style={{ paddingBottom: 24 }}>
        <div className="page-head">
          <h1>예산 관리</h1>
          <div className="sub">각 팀의 비용 분류별 예산을 확인하세요</div>
        </div>
      </div>

      <div className="page-inner">
        <div className="row" style={{ gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
          {TEAMS.map((t) => (
            <button
              key={t}
              type="button"
              className="btn"
              style={team === t ? { background: 'var(--primary-soft)', borderColor: 'var(--primary)', color: 'var(--primary)', fontWeight: 700 } : undefined}
              onClick={() => setTeam(t)}
            >
              {t}
            </button>
          ))}
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
              {rows.map((r) => {
                const remaining = r.allocated - r.used
                const rate = r.allocated > 0 ? r.used / r.allocated : 0
                const tone = toneOf(rate * 100)
                return (
                  <tr key={r.category}>
                    <td><b>{r.category}</b></td>
                    <td className="num">{won(r.allocated)}</td>
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
            </tbody>
          </table>
        </div>
      </div>
    </>
  )
}
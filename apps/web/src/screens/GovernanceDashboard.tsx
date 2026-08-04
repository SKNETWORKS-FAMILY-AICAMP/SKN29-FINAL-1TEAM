// S-05 거버넌스 대시보드 — 회계/운영 상부. FR-UI-05, FR-DB-05~08
// 예산·정책은 통제(차단)가 아니라 지표·추천으로만 반영한다(CLAUDE §2).
//
// 화면 구성(임원 읽는 순서):
//  ① 핵심 KPI  ② 계정과목별 지출 추세(전월/전년 동월 선택)  ③ 예산 산정 지표
//  ④ 팀 단위 예산 ↔ 퇴사율 ↔ 생산성 동행  ⑤ 정책 인사이트 · 리스크 패턴
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowRight, Table2 } from 'lucide-react'
import {
  BurnMeter, DeltaBar, DeltaText, LinePanel, SERIES, Sparkline,
  burnStatus, BURN_META, correlationLabel, pearson,
} from '../components/ui/GovCharts'
import {
  CATEGORY_ORDER, CATEGORY_SPEND, COMPARE_LABEL, GOV_KPIS, GOV_MONTHS,
  IDX_NOW, INSIGHT_META, OFTEN_SHORT, OFTEN_SURPLUS, POLICY_INSIGHTS,
  REALLOCATION, REJECT_REASONS, RISK_PATTERNS, SEVERITY_META, TEAM_SERIES,
  compareIndex, monthTotal, type CompareMode,
} from '../data/governanceMock'

const CONFIDENCE_LABEL = { HIGH: '신뢰도 높음', MEDIUM: '신뢰도 보통', LOW: '신뢰도 낮음' } as const
const manwon = (value: number) => `${Math.round(value).toLocaleString()}만원`

export function GovernanceDashboard() {
  const nav = useNavigate()
  const [compare, setCompare] = useState<CompareMode>('MOM')
  const [teamName, setTeamName] = useState(TEAM_SERIES[0].team)
  const [showTable, setShowTable] = useState(false)

  const baseIndex = compareIndex(compare)

  // ② 계정과목별: 이번 달 금액 + 선택한 비교 기준 대비 증감
  const categoryRows = useMemo(() => {
    const rows = CATEGORY_ORDER.map((category) => {
      const series = CATEGORY_SPEND[category]
      const now = series[IDX_NOW]
      const base = series[baseIndex]
      const diff = now - base
      return { category, series, now, base, diff, rate: base ? (diff / base) * 100 : 0 }
    })
    return rows.sort((a, b) => b.rate - a.rate) // 증가율 큰 것부터 — 임원이 볼 순서
  }, [baseIndex])
  const maxAbsRate = Math.max(...categoryRows.map((r) => Math.abs(r.rate)), 1)
  const totalNow = monthTotal(IDX_NOW)
  const totalBase = monthTotal(baseIndex)
  const totalRate = ((totalNow - totalBase) / totalBase) * 100

  // ④ 선택 팀의 세 지표 — 스케일이 달라 한 축에 겹치지 않고 패널로 나눈다
  const team = TEAM_SERIES.find((t) => t.team === teamName) ?? TEAM_SERIES[0]
  const rBurnAttrition = pearson(team.burnRate, team.attrition)
  const rBurnPerformance = pearson(team.burnRate, team.performance)

  return (
    <>
      <div className="page-head row" style={{ justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <span className="screen-id">S-05</span>
          <h1>거버넌스 대시보드</h1>
          <div className="sub">
            법인카드 지출·정산 운영 현황과 예산 산정 근거를 제공합니다. 예산은 <b>경고성 지표</b>이며 자동 차단하지 않습니다.
          </div>
        </div>
        <span className="text-meta">기준 {GOV_MONTHS[IDX_NOW]} · 전사</span>
      </div>

      {/* ── ① 핵심 KPI ─────────────────────────────────────── */}
      <div className="gov-kpi-grid">
        {GOV_KPIS.map((kpi) => {
          const up = kpi.delta.trim().startsWith('+')
          const good = up === kpi.higherIsBetter
          const color = good ? SERIES.performance : SERIES.attrition
          return (
            <div key={kpi.key} className="gov-kpi" title={kpi.hint}>
              <div className="gov-kpi-label">{kpi.label}</div>
              <div className="gov-kpi-value">
                {kpi.value}{kpi.unit && <small>{kpi.unit}</small>}
              </div>
              <div className="gov-kpi-foot">
                <span style={{ color, fontWeight: 700, fontSize: 12, whiteSpace: 'nowrap' }}>
                  {up ? '▲' : '▼'} {kpi.delta.replace(/^[+-]/, '')}
                </span>
                <Sparkline data={kpi.spark} color={color} width={72} height={24} />
              </div>
              <div className="gov-kpi-hint">{kpi.hint}</div>
            </div>
          )
        })}
      </div>

      {/* ── ② 계정과목별 지출 추세 ────────────────────────────── */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-head">
          <div>
            <h3>계정과목별 지출 추세</h3>
            <div className="text-meta">13개월 추이 · {COMPARE_LABEL[compare]} 증감 (단위 만원)</div>
          </div>
          <div className="seg-toggle">
            <button type="button" className={compare === 'MOM' ? 'active' : ''} onClick={() => setCompare('MOM')}>전월 대비</button>
            <button type="button" className={compare === 'YOY' ? 'active' : ''} onClick={() => setCompare('YOY')}>전년 동월 대비</button>
          </div>
        </div>
        <div className="card-body" style={{ paddingTop: 8 }}>
          <table className="table gov-trend-table">
            <thead>
              <tr>
                <th style={{ width: 88 }}>계정과목</th>
                <th style={{ width: 110 }}>13개월 추이</th>
                <th className="num" style={{ width: 92 }}>이번 달</th>
                <th className="num" style={{ width: 92 }}>{COMPARE_LABEL[compare]}</th>
                <th style={{ width: 150 }}>증감률</th>
                <th>해석</th>
              </tr>
            </thead>
            <tbody>
              {categoryRows.map((row) => (
                <tr key={row.category}>
                  <td><b>{row.category}</b></td>
                  <td><Sparkline data={row.series} color="var(--primary)" width={100} height={26} /></td>
                  <td className="num">{row.now.toLocaleString()}</td>
                  <td className="num text-meta">{row.base.toLocaleString()}</td>
                  <td>
                    <div className="row" style={{ gap: 8, alignItems: 'center' }}>
                      <DeltaBar value={row.rate} max={maxAbsRate} width={110} />
                      <DeltaText value={row.rate} higherIsBetter={false} />
                    </div>
                  </td>
                  <td className="text-meta">
                    {row.rate >= 30 ? `${manwon(row.diff)} 늘었습니다 — 한도 재산정 대상`
                      : row.rate >= 10 ? `${manwon(row.diff)} 증가 — 추이 관찰 필요`
                      : row.rate <= -10 ? `${manwon(Math.abs(row.diff))} 감소 — 한도 여유`
                      : '변동 폭이 작습니다'}
                  </td>
                </tr>
              ))}
              <tr className="gov-total-row">
                <td><b>합계</b></td>
                <td><Sparkline data={GOV_MONTHS.map((_, i) => monthTotal(i))} color="var(--text)" width={100} height={26} /></td>
                <td className="num"><b>{totalNow.toLocaleString()}</b></td>
                <td className="num text-meta">{totalBase.toLocaleString()}</td>
                <td><DeltaText value={totalRate} higherIsBetter={false} /></td>
                <td className="text-meta">
                  증가분의 대부분이 <b>{categoryRows[0].category}</b>({manwon(categoryRows[0].diff)})에서 나왔습니다.
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      {/* ── ③ 예산 산정 지표 ──────────────────────────────────── */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-head">
          <div>
            <h3>예산 산정 지표</h3>
            <div className="text-meta">같은 항목이 매달 남거나 모자라면 집행이 아니라 <b>한도 산정</b>의 문제입니다 (최근 6개월)</div>
          </div>
        </div>
        <div className="card-body">
          <div className="gov-budget-grid">
            <div>
              <div className="gov-sub-title">팀별 예산 소진율</div>
              <div className="stack" style={{ gap: 6 }}>
                {TEAM_SERIES.map((t) => (
                  <BurnMeter
                    key={t.team} label={t.team} rate={t.burnRate[IDX_NOW]}
                    sub={`${t.bu} · ${t.headcount}명`}
                    selected={t.team === teamName}
                    onClick={() => setTeamName(t.team)}
                  />
                ))}
              </div>
              <div className="text-meta" style={{ marginTop: 8 }}>
                팀을 누르면 아래 ④ 동행 지표가 그 팀으로 바뀝니다.
              </div>
            </div>

            <div>
              <div className="gov-sub-title">자주 남는 항목</div>
              <table className="table gov-pattern-table">
                <thead><tr><th>항목</th><th className="num">해당 개월</th><th className="num">평균 잔여</th><th className="num">누적</th></tr></thead>
                <tbody>
                  {OFTEN_SURPLUS.map((row) => (
                    <tr key={row.category}>
                      <td><b>{row.category}</b></td>
                      <td className="num">{row.months}/6</td>
                      <td className="num" style={{ color: SERIES.budget, fontWeight: 700 }}>+{row.avgGap}%</td>
                      <td className="num text-meta">{manwon(row.amount)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <div className="gov-sub-title" style={{ marginTop: 16 }}>자주 부족한 항목</div>
              <table className="table gov-pattern-table">
                <thead><tr><th>항목</th><th className="num">해당 개월</th><th className="num">평균 초과</th><th className="num">누적</th></tr></thead>
                <tbody>
                  {OFTEN_SHORT.map((row) => (
                    <tr key={row.category}>
                      <td><b>{row.category}</b></td>
                      <td className="num">{row.months}/6</td>
                      <td className="num" style={{ color: SERIES.attrition, fontWeight: 700 }}>{row.avgGap}%</td>
                      <td className="num text-meta">{manwon(Math.abs(row.amount))}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div>
              <div className="gov-sub-title">재배분 제안</div>
              <div className="stack" style={{ gap: 10 }}>
                {REALLOCATION.map((r) => (
                  <div key={`${r.from}-${r.to}`} className="gov-realloc">
                    <div className="row" style={{ gap: 8, alignItems: 'center', marginBottom: 4 }}>
                      <span className="tag">{r.from}</span>
                      <ArrowRight size={13} className="muted" />
                      <span className="tag ai">{r.to}</span>
                      <b style={{ marginLeft: 'auto', fontVariantNumeric: 'tabular-nums' }}>{manwon(r.amount)}</b>
                    </div>
                    <div className="text-meta">{r.note}</div>
                  </div>
                ))}
                <div className="note">
                  총 한도를 늘리지 않고 <b>{manwon(REALLOCATION.reduce((s, r) => s + r.amount, 0))}</b>을 옮기는 안입니다.
                  확정은 상부 결재로만 이뤄집니다.
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ── ④ 팀 단위 동행 지표 ───────────────────────────────── */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-head">
          <div>
            <h3>예산 소진 ↔ 퇴사율 ↔ 생산성 동행 지표</h3>
            <div className="text-meta">{team.team} · {team.bu} · {team.headcount}명 · 최근 13개월</div>
          </div>
          <div className="row" style={{ gap: 8 }}>
            <select value={teamName} onChange={(e) => setTeamName(e.target.value)} aria-label="팀 선택">
              {TEAM_SERIES.map((t) => <option key={t.team}>{t.team}</option>)}
            </select>
            <button className={'btn sm' + (showTable ? ' primary' : '')} onClick={() => setShowTable((v) => !v)}>
              <Table2 size={13} /> 표로 보기
            </button>
          </div>
        </div>
        <div className="card-body">
          {/* 스케일이 다른 세 지표 — 이중축 대신 축을 공유하는 세 패널로 나눠 그린다 */}
          <div className="gov-panel-grid">
            <LinePanel title="예산 소진율" unit="%" data={team.burnRate} labels={GOV_MONTHS}
              color={SERIES.budget} reference={{ value: 100, label: '한도' }} />
            <LinePanel title="퇴사율" unit="%" data={team.attrition} labels={GOV_MONTHS}
              color={SERIES.attrition} />
            <LinePanel title="생산성 지수" unit="" data={team.performance} labels={GOV_MONTHS}
              color={SERIES.performance} reference={{ value: 100, label: '기준' }} />
          </div>

          <div className="gov-corr-row">
            <div className="gov-corr">
              <span className="gov-swatch" style={{ background: SERIES.budget }} aria-hidden="true" />
              <span className="gov-swatch" style={{ background: SERIES.attrition }} aria-hidden="true" />
              <span>예산 소진율 ↔ 퇴사율</span>
              <b style={{ color: Math.abs(rBurnAttrition) >= 0.6 ? SERIES.attrition : 'var(--text)' }}>
                r = {rBurnAttrition.toFixed(2)}
              </b>
              <span className="text-meta">{correlationLabel(rBurnAttrition)}</span>
            </div>
            <div className="gov-corr">
              <span className="gov-swatch" style={{ background: SERIES.budget }} aria-hidden="true" />
              <span className="gov-swatch" style={{ background: SERIES.performance }} aria-hidden="true" />
              <span>예산 소진율 ↔ 생산성</span>
              <b style={{ color: Math.abs(rBurnPerformance) >= 0.6 ? SERIES.performance : 'var(--text)' }}>
                r = {rBurnPerformance.toFixed(2)}
              </b>
              <span className="text-meta">{correlationLabel(rBurnPerformance)}</span>
            </div>
          </div>

          <div className="note" style={{ marginTop: 12 }}>
            <b>읽는 법 —</b> {team.readout}
            <br />
            ※ 상관계수는 화면에 그려진 13개월 값으로 계산한 <b>동행 정도</b>이며 인과관계가 아닙니다.
            원인 판단에는 인사·업무량 데이터가 함께 필요합니다.
          </div>

          {showTable && (
            <div style={{ overflowX: 'auto', marginTop: 12 }}>
              <table className="table gov-data-table">
                <thead>
                  <tr>
                    <th>지표</th>
                    {GOV_MONTHS.map((m) => <th key={m} className="num">{m}</th>)}
                  </tr>
                </thead>
                <tbody>
                  <tr><td>예산 소진율 (%)</td>{team.burnRate.map((v, i) => <td key={i} className="num">{v}</td>)}</tr>
                  <tr><td>퇴사율 (%)</td>{team.attrition.map((v, i) => <td key={i} className="num">{v}</td>)}</tr>
                  <tr><td>생산성 지수</td>{team.performance.map((v, i) => <td key={i} className="num">{v}</td>)}</tr>
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* ── ⑤ 정책 인사이트 · 리스크 패턴 ──────────────────────── */}
      <div className="grid-2" style={{ marginBottom: 16 }}>
        <div className="card">
          <div className="card-head">
            <h3>정책 인사이트 추천</h3>
            <span className="text-meta">근거 · 예상 효과 · 신뢰도</span>
          </div>
          <div className="card-body stack" style={{ gap: 10 }}>
            {POLICY_INSIGHTS.map((insight) => {
              const meta = INSIGHT_META[insight.kind]
              return (
                <div key={insight.title} className="gov-insight">
                  <div className="row" style={{ gap: 6, marginBottom: 6, flexWrap: 'wrap' }}>
                    <span className={'tag ' + meta.tone}>{meta.label}</span>
                    <b style={{ flex: 1, minWidth: 160 }}>{insight.title}</b>
                    <span className="text-meta">{CONFIDENCE_LABEL[insight.confidence]}</span>
                  </div>
                  <div className="gov-insight-line"><span className="gov-insight-key">근거</span>{insight.evidence}</div>
                  <div className="gov-insight-line"><span className="gov-insight-key">예상 효과</span>{insight.expected}</div>
                  <div className="row" style={{ justifyContent: 'flex-end', marginTop: 8 }}>
                    <button className="btn sm" onClick={() => nav(insight.action.to)}>
                      {insight.action.label} <ArrowRight size={12} />
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        <div className="stack-lg">
          <div className="card">
            <div className="card-head">
              <h3>리스크 패턴 알림</h3>
              <span className="text-meta">심각도 · 영향 범위 · 추세</span>
            </div>
            <div className="card-body stack" style={{ gap: 10 }}>
              {RISK_PATTERNS.map((risk) => {
                const meta = SEVERITY_META[risk.severity]
                return (
                  <div key={risk.title} className="gov-risk" style={{ borderLeftColor: meta.color }}>
                    <div className="row" style={{ gap: 6, marginBottom: 4, flexWrap: 'wrap' }}>
                      {/* 심각도는 색 + 기호 + 라벨을 함께 쓴다 */}
                      <span style={{ color: meta.color, fontWeight: 700, fontSize: 12 }}>
                        {meta.icon} {meta.label}
                      </span>
                      <span className="tag">{risk.pattern}</span>
                      <b style={{ flex: 1, minWidth: 140 }}>{risk.title}</b>
                      <Sparkline data={risk.spark} color={meta.color} width={64} height={22} />
                    </div>
                    <div className="text-meta">{risk.scope}</div>
                    <div className="text-meta" style={{ color: meta.color, fontWeight: 600 }}>{risk.trend}</div>
                    <div className="row" style={{ justifyContent: 'flex-end', marginTop: 6 }}>
                      <button className="btn sm" onClick={() => nav(risk.to)}>해당 건 보기 <ArrowRight size={12} /></button>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>

          <div className="card">
            <div className="card-head">
              <h3>반려 사유 Top 5</h3>
              <span className="text-meta">전월 대비</span>
            </div>
            <table className="table">
              <tbody>
                {REJECT_REASONS.map((r, i) => (
                  <tr key={r.reason}>
                    <td style={{ width: 24 }} className="muted">{i + 1}</td>
                    <td>{r.reason}</td>
                    <td className="num" style={{ width: 52 }}><b>{r.count}</b></td>
                    <td className="num" style={{ width: 72 }}>
                      <DeltaText value={((r.count - r.prev) / r.prev) * 100} higherIsBetter={false} bold={false} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div className="text-meta" style={{ fontSize: 11 }}>
        ※ 예산 지표는 경고성 모니터링이며 초과 시에도 자동 차단하지 않습니다. 정책 인사이트·재배분 제안은 <b>추천</b>이고 최종 결정은 상부가 수행합니다.
        {' '}소진율 구간: {(['OVER', 'TIGHT', 'HEALTHY', 'SLACK'] as const).map((s) => (
          <span key={s} style={{ marginLeft: 8, color: BURN_META[s].color, fontWeight: 600 }}>
            {BURN_META[s].icon} {BURN_META[s].label}
          </span>
        ))}
        {' '}(현재 전사 {burnStatus(84) === 'HEALTHY' ? '적정' : BURN_META[burnStatus(84)].label} 구간)
      </div>
    </>
  )
}

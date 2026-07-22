// S-05 거버넌스 대시보드 — 회계/운영 상부. FR-UI-05, FR-DB-05~08
// 예산·정책은 통제(차단)가 아니라 지표·추천으로만 반영한다.
import { useNavigate } from 'react-router-dom'
import { AlertTriangle } from 'lucide-react'
import { budgetByBU, policyInsights, rejectReasonsTop5, riskAlerts, spendTrend } from '../data/mock'
import { KpiCard } from '../components/ui/KpiCard'
import { LabeledBars, StackedTrend } from '../components/ui/MiniChart'

export function GovernanceDashboard() {
  const nav = useNavigate()
  return (
    <>
      <div className="page-head">
        <span className="screen-id">S-05</span>
        <h1>거버넌스 대시보드</h1>
        <div className="sub">지출 추세·예산 소진율·정책 인사이트를 제공합니다. 예산은 경고성 지표이며 자동 차단하지 않습니다.</div>
      </div>

      <div className="filter-bar">
        <select><option>최근 6개월</option><option>이번 분기</option></select>
        <select><option>전체 본부</option><option>AI사업본부</option><option>영업본부</option></select>
      </div>

      <div className="kpi-grid">
        <KpiCard label="총 지출액" value="₩4.2억" />
        <KpiCard label="예산 소진율" value={78} unit="%" />
        <KpiCard label="자동처리율" value={68} unit="%" />
        <KpiCard label="정책위반 의심" value={7} unit="건" warn />
      </div>

      <div className="grid-2" style={{ marginBottom: 16 }}>
        <div className="card">
          <div className="card-head"><h3>분류별 지출 추세</h3><span className="text-meta">식대·출장·접대</span></div>
          <div className="card-body">
            <StackedTrend
              data={spendTrend}
              keys={[
                { key: '식대', color: 'var(--tone-blue)' },
                { key: '출장', color: 'var(--tone-teal)' },
                { key: '접대', color: 'var(--tone-amber)' },
              ]}
            />
            <div className="row" style={{ gap: 16, marginTop: 8, fontSize: 12 }}>
              <span><b style={{ color: 'var(--tone-blue)' }}>■</b> 식대</span>
              <span><b style={{ color: 'var(--tone-teal)' }}>■</b> 출장</span>
              <span><b style={{ color: 'var(--tone-amber)' }}>■</b> 접대</span>
            </div>
          </div>
        </div>

        <div className="card">
          <div className="card-head"><h3>본부별 예산 소진율</h3><span className="text-meta">경고성 모니터링</span></div>
          <div className="card-body"><LabeledBars data={budgetByBU.map((b) => ({ label: b.bu, rate: b.rate }))} /></div>
        </div>
      </div>

      <div className="grid-2">
        <div className="card">
          <div className="card-head"><h3>반려 사유 Top 5</h3></div>
          <table className="table">
            <tbody>
              {rejectReasonsTop5.map((r, i) => (
                <tr key={r.reason}>
                  <td style={{ width: 28 }} className="muted">{i + 1}</td>
                  <td>{r.reason}</td>
                  <td className="num"><b>{r.count}</b></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="stack-lg">
          {/* 정책 인사이트 추천 (FR-DB-07) — 최종 결정은 사람 */}
          <div className="card">
            <div className="card-head"><h3>정책 인사이트 추천</h3></div>
            <div className="card-body stack">
              {policyInsights.map((p, i) => (
                <div key={i} className="note" style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                  <span className="tag ai">{p.kind}</span>
                  <span style={{ flex: 1 }}>{p.text}</span>
                  <button className="btn sm" onClick={() => p.action === 'S-04' && nav('/rules')}>검토하기</button>
                </div>
              ))}
            </div>
          </div>

          {/* 리스크 패턴 알림 (FR-DB-08) */}
          <div className="card">
            <div className="card-head"><h3>리스크 패턴 알림</h3><span className="tag warn">분할결제 등</span></div>
            <div className="card-body stack">
              {riskAlerts.map((a, i) => (
                <div key={i} className="row" style={{ justifyContent: 'space-between' }}>
                  <div>
                    <div className="row" style={{ gap: 6, fontWeight: 600 }}>
                      <AlertTriangle size={14} color="var(--tone-red)" />{a.title}
                    </div>
                    <div className="text-meta">{a.detail}</div>
                  </div>
                  <button className="btn sm" onClick={() => nav('/review')}>상세보기</button>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </>
  )
}

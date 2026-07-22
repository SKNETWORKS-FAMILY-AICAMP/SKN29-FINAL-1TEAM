// S-03 검토 워크스페이스 — 회계 담당자.
// FR-UI-03, FR-RR-01~08, FR-RL-01~02, FR-DB-04
// MVP 2단계: ① 비지도 이상탐지 → ② RAG 내규검증. 지도학습(review_prob)은 post-MVP.
import { useState } from 'react'
import { reviewItems } from '../data/mock'
import type { ReviewItem } from '../types/domain'
import { won, pct } from '../lib/format'
import { KpiCard } from '../components/ui/KpiCard'

const RECO_LABEL: Record<ReviewItem['aiRecommendation'], { text: string; cls: string }> = {
  APPROVE: { text: '승인 권장', cls: 'ok' },
  RETURN: { text: '보완요청 권장', cls: 'warn' },
  REJECT: { text: '반려 권장', cls: 'warn' },
}

export function ReviewWorkspace() {
  // anomaly_score 내림차순 정렬 (FR-RL-01, FR-RR-04)
  const sorted = [...reviewItems].sort((a, b) => b.anomalyScore - a.anomalyScore)
  const [sel, setSel] = useState<ReviewItem>(sorted[0])

  return (
    <>
      <div className="page-head">
        <span className="screen-id">S-03</span>
        <h1>검토 워크스페이스</h1>
        <div className="sub">Rule 미매칭·불확실 건만 위험도순으로 정렬합니다. 최종 결정은 사람이 수행합니다.</div>
      </div>

      <div className="kpi-grid">
        <KpiCard label="자동처리율" value={68} unit="%" />
        <KpiCard label="검토 대기" value={sorted.length} unit="건" />
        <KpiCard label="평균 검토 시간" value={3.1} unit="분" />
        <KpiCard label="이상 후보(고위험)" value={sorted.filter((i) => i.anomalyScore >= 0.7).length} unit="건" warn />
      </div>

      {/* 2단계 파이프라인 안내 (FR-RR-02) */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-body row" style={{ justifyContent: 'space-between' }}>
          <div className="pipeline">
            <span className="step s1">① 단순 이상탐지 (비지도)</span>
            <span className="arrow">→</span>
            <span className="step s2">② RAG 내규 검증 (이상 후보 한정)</span>
          </div>
          <span className="note" style={{ margin: 0 }}>콜드스타트 대응 · 지도학습(review_probability)은 post-MVP</span>
        </div>
      </div>

      <div className="split">
        {/* Review List */}
        <div className="card">
          <div className="card-head"><h3>Review List</h3><span className="muted" style={{ fontSize: 12 }}>anomaly_score 내림차순</span></div>
          <table className="table">
            <thead>
              <tr><th>위험도</th><th>가맹점</th><th className="num">금액</th><th>AI 권장</th></tr>
            </thead>
            <tbody>
              {sorted.map((i) => (
                <tr key={i.id} onClick={() => setSel(i)} style={sel.id === i.id ? { background: 'var(--primary-soft)' } : undefined}>
                  <td style={{ width: 120 }}>
                    <div className="row" style={{ gap: 6 }}>
                      <b style={{ color: 'var(--tone-red)' }}>{Math.round(i.anomalyScore * 100)}</b>
                      <div className="anomaly-meter" style={{ flex: 1 }}><span style={{ width: pct(i.anomalyScore) }} /></div>
                    </div>
                  </td>
                  <td>{i.merchant}<div className="muted" style={{ fontSize: 11 }}>{i.user} · {i.date}</div></td>
                  <td className="num">{won(i.amount)}</td>
                  <td><span className={'tag ' + RECO_LABEL[i.aiRecommendation].cls}>{RECO_LABEL[i.aiRecommendation].text}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* 상세 패널: ①이상탐지 + ②RAG검증 */}
        <div className="stack" style={{ gap: 16 }}>
          <div className="card">
            <div className="card-head"><h3>① 이상탐지 결과</h3><span className="tag" style={{ color: 'var(--tone-purple)', background: 'var(--tone-purple-bg)' }}>anomaly {sel.anomalyScore.toFixed(2)}</span></div>
            <div className="card-body">
              <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>Feature 기여도 (어느 feature가 이상 신호를 유발했는가)</div>
              <div className="stack">
                {sel.featureContribs.map((f) => (
                  <div key={f.feature} className="row" style={{ gap: 10 }}>
                    <div style={{ width: 160, fontSize: 12 }}>{f.feature}</div>
                    <div style={{ flex: 1, height: 8, background: 'var(--surface-2)', borderRadius: 999, overflow: 'hidden' }}>
                      <div style={{ width: pct(f.weight), height: '100%', background: 'var(--tone-purple)' }} />
                    </div>
                    <div style={{ width: 40, fontSize: 12 }} className="right">{pct(f.weight)}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="card">
            <div className="card-head"><h3>② RAG 내규 검증</h3><span className="tag" style={{ color: 'var(--tone-teal)', background: 'var(--tone-teal-bg)' }}>근거 {sel.ragRefs.length}건</span></div>
            <div className="card-body">
              <ul className="evidence-list">
                {sel.ragRefs.map((r) => (
                  <li key={r.source}>
                    <div>{r.title}</div>
                    <div className="src">📎 {r.source}</div>
                  </li>
                ))}
              </ul>
              <div className="note" style={{ marginTop: 12 }}>
                <strong className={'tag ' + RECO_LABEL[sel.aiRecommendation].cls}>AI 권장: {RECO_LABEL[sel.aiRecommendation].text}</strong>
                <span style={{ marginLeft: 8 }}>신뢰도 {pct(sel.aiConfidence)}</span>
                <div style={{ marginTop: 6 }}>사유: {sel.anomalyReasons.join(', ')}</div>
              </div>
            </div>
          </div>

          {/* 원클릭 처리 3종 (FR-UI-03) */}
          <div className="card">
            <div className="card-body row">
              <button className="btn approve">승인</button>
              <button className="btn return">보완요청(RETURNED)</button>
              <button className="btn reject">반려(REJECT)</button>
              <div className="spacer" />
              <span className="muted" style={{ fontSize: 12 }}>결정은 decision_labels로 적재(향후 지도학습용)</span>
            </div>
          </div>
        </div>
      </div>
    </>
  )
}

// S-03 검토 워크스페이스 — 회계 담당자.
// FR-UI-03, FR-RR-01~08, FR-RL-01~02, FR-DB-04
// MVP 2단계: ① 비지도 이상탐지 → ② RAG 내규검증. 지도학습(review_prob)은 post-MVP.
import { useState } from 'react'
import { Paperclip } from 'lucide-react'
import type { ReviewItem } from '../types/domain'
import { won, pct } from '../lib/format'
import { KpiCard } from '../components/ui/KpiCard'
import { LabeledBar } from '../components/ui/MiniChart'
import { reviewSettlement } from '../api/settlementService'
import { useSettlements } from '../context/SettlementsContext'
import { activateOnEnterOrSpace } from '../lib/a11y'

const RECO_LABEL: Record<ReviewItem['aiRecommendation'], { text: string; cls: string }> = {
  APPROVE: { text: '승인 권장', cls: 'ok' },
  RETURN: { text: '보완요청 권장', cls: 'warn' },
  REJECT: { text: '반려 권장', cls: 'warn' },
}

export function ReviewWorkspace() {
  const { reviewItems: items, updateStatus } = useSettlements()
  const [selId, setSelId] = useState(items[0]?.id)
  const [busy, setBusy] = useState(false)

  // 검토 대기 = 아직 사람이 결정하지 않은 IN_REVIEW 건만. anomaly_score 내림차순 (FR-RL-01, FR-RR-04)
  const pending = [...items].filter((i) => i.status === 'IN_REVIEW').sort((a, b) => b.anomalyScore - a.anomalyScore)
  const sel = pending.find((i) => i.id === selId) ?? pending[0]

  const decide = async (decision: 'APPROVE' | 'RETURN' | 'REJECT') => {
    if (!sel) return
    setBusy(true)
    const status = await reviewSettlement(sel.id, decision)
    updateStatus(sel.id, status)
    const next = pending.find((i) => i.id !== sel.id)
    if (next) setSelId(next.id)
    setBusy(false)
  }

  if (!sel) {
    return (
      <>
        <div className="page-head">
          <span className="screen-id">S-03</span>
          <h1>검토 워크스페이스</h1>
          <div className="sub">Rule 미매칭·불확실 건만 위험도순으로 정렬합니다. 최종 결정은 사람이 수행합니다.</div>
        </div>
        <div className="card"><div className="card-body text-meta">검토 대기 중인 건이 없습니다.</div></div>
      </>
    )
  }

  return (
    <>
      <div className="page-head">
        <span className="screen-id">S-03</span>
        <h1>검토 워크스페이스</h1>
        <div className="sub">Rule 미매칭·불확실 건만 위험도순으로 정렬합니다. 최종 결정은 사람이 수행합니다.</div>
      </div>

      <div className="kpi-grid">
        <KpiCard label="자동처리율" value={68} unit="%" />
        <KpiCard label="검토 대기" value={pending.length} unit="건" />
        <KpiCard label="평균 검토 시간" value={3.1} unit="분" />
        <KpiCard label="이상 후보(고위험)" value={pending.filter((i) => i.anomalyScore >= 0.7).length} unit="건" warn />
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
          <div className="card-head"><h3>Review List</h3><span className="text-meta">anomaly_score 내림차순</span></div>
          <table className="table">
            <thead>
              <tr><th>위험도</th><th>가맹점</th><th className="num">금액</th><th>AI 권장</th></tr>
            </thead>
            <tbody>
              {pending.map((i) => (
                <tr
                  key={i.id}
                  tabIndex={0}
                  className={sel.id === i.id ? 'selected' : undefined}
                  onClick={() => setSelId(i.id)}
                  onKeyDown={activateOnEnterOrSpace(() => setSelId(i.id))}
                >
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
        <div className="stack-lg">
          <div className="card">
            <div className="card-head"><h3>① 이상탐지 결과</h3><span className="tag" style={{ color: 'var(--tone-purple)', background: 'var(--tone-purple-bg)' }}>anomaly {sel.anomalyScore.toFixed(2)}</span></div>
            <div className="card-body">
              <div className="text-meta" style={{ marginBottom: 8 }}>Feature 기여도 (어느 feature가 이상 신호를 유발했는가)</div>
              <div className="stack">
                {sel.featureContribs.map((f) => (
                  <LabeledBar key={f.feature} label={f.feature} value={f.weight} labelWidth={160} color="var(--tone-purple)" />
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
                    <div className="src row" style={{ gap: 4 }}><Paperclip size={11} />{r.source}</div>
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
              <button className="btn approve" disabled={busy} onClick={() => decide('APPROVE')}>승인</button>
              <button className="btn return" disabled={busy} onClick={() => decide('RETURN')}>보완요청(RETURNED)</button>
              <button className="btn reject" disabled={busy} onClick={() => decide('REJECT')}>반려(REJECT)</button>
              <div className="spacer" />
              <span className="text-meta">결정은 decision_labels로 적재(향후 지도학습용)</span>
            </div>
          </div>
        </div>
      </div>
    </>
  )
}

// S-03 검토 워크스페이스 — 회계 담당자.
// FR-UI-03, FR-RR-01~08, FR-RL-01~02, FR-DB-04
// MVP 2단계: ① 비지도 이상탐지 → ② RAG 내규검증. 지도학습(review_prob)은 post-MVP.
import { useState } from 'react'
import { Paperclip, ExternalLink, History } from 'lucide-react'
import type { ReviewItem } from '../types/domain'
import { CARD_TYPE_LABEL, CATEGORIES } from '../types/domain'
import { won, pct } from '../lib/format'
import { KpiCard } from '../components/ui/KpiCard'
import { LabeledBar } from '../components/ui/MiniChart'
import { DecisionReasonModal } from '../components/settlement/DecisionReasonModal'
import { reviewSettlement } from '../api/settlementService'
import { useSettlements } from '../context/SettlementsContext'
import { activateOnEnterOrSpace } from '../lib/a11y'

type Reco = ReviewItem['aiRecommendation']
const RECO_LABEL: Record<Reco, { text: string; cls: string; mark: string }> = {
  APPROVE: { text: '승인', cls: 'ok', mark: '✓' },
  RETURN: { text: '보완요청', cls: 'warn', mark: '✎' },
  REJECT: { text: '반려', cls: 'warn', mark: '✕' },
}
type Filter = 'ALL' | Reco

export function ReviewWorkspace() {
  const { reviewItems: items, updateStatus } = useSettlements()
  const [selId, setSelId] = useState(items[0]?.id)
  const [filter, setFilter] = useState<Filter>('ALL')
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [showHistory, setShowHistory] = useState(false)
  const [modal, setModal] = useState<{ decision: 'RETURN' | 'REJECT'; ids: string[] } | null>(null)
  const [busy, setBusy] = useState(false)

  // 검토 대기 = 아직 사람이 결정하지 않은 IN_REVIEW 건만. anomaly_score 내림차순 (FR-RL-01, FR-RR-04)
  const pending = [...items].filter((i) => i.status === 'IN_REVIEW').sort((a, b) => b.anomalyScore - a.anomalyScore)
  const counts: Record<Filter, number> = {
    ALL: pending.length,
    APPROVE: pending.filter((i) => i.aiRecommendation === 'APPROVE').length,
    RETURN: pending.filter((i) => i.aiRecommendation === 'RETURN').length,
    REJECT: pending.filter((i) => i.aiRecommendation === 'REJECT').length,
  }
  const listed = filter === 'ALL' ? pending : pending.filter((i) => i.aiRecommendation === filter)
  const sel = pending.find((i) => i.id === selId) ?? listed[0] ?? pending[0]

  const pickFilter = (f: Filter) => {
    setFilter(f)
    // 추천 필터 선택 시 해당 건 전체 자동 선택 (S-03 Review 목업)
    setChecked(f === 'ALL' ? new Set() : new Set(pending.filter((i) => i.aiRecommendation === f).map((i) => i.id)))
  }

  const toggleCheck = (id: string) => {
    const next = new Set(checked)
    next.has(id) ? next.delete(id) : next.add(id)
    setChecked(next)
  }

  const applyDecision = async (decision: Reco, ids: string[], reason = '') => {
    setBusy(true)
    for (const id of ids) {
      const status = await reviewSettlement(id, decision, reason)
      updateStatus(id, status)
    }
    setChecked(new Set())
    setModal(null)
    setShowHistory(false)
    const next = pending.find((i) => !ids.includes(i.id))
    if (next) setSelId(next.id)
    setBusy(false)
  }

  // 상세 패널 단건 처리
  const decideOne = (decision: Reco) => {
    if (!sel) return
    if (decision === 'APPROVE') applyDecision('APPROVE', [sel.id])
    else setModal({ decision, ids: [sel.id] })
  }
  // 필터 칩 기준 일괄 처리
  const decideBulk = () => {
    if (filter === 'ALL' || checked.size === 0) return
    const ids = [...checked]
    if (filter === 'APPROVE') applyDecision('APPROVE', ids)
    else setModal({ decision: filter, ids })
  }

  const modalItem = modal ? pending.find((i) => i.id === modal.ids[0]) : undefined

  return (
    <>
      <div className="page-head">
        <span className="screen-id">S-03</span>
        <h1>검토 워크스페이스</h1>
        <div className="sub">Rule 미매칭·불확실 건만 위험도순으로 정렬합니다. 최종 결정은 사람이 수행합니다.</div>
      </div>

      <div className="kpi-grid">
        <KpiCard label="자동처리율" value={82} unit="%" />
        <KpiCard label="검토 대기" value={pending.length} unit="건" />
        <KpiCard label="평균 검토 시간" value={6.2} unit="분" />
        <KpiCard label="이상 후보(고위험)" value={pending.filter((i) => i.anomalyScore >= 0.7).length} unit="건" warn />
      </div>

      {/* 2단계 파이프라인 안내 (FR-RR-02) */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-body row" style={{ justifyContent: 'space-between' }}>
          <div className="pipeline">
            <span className="step s1">① 이상탐지 (비지도, anomaly_score)</span>
            <span className="arrow">→</span>
            <span className="step s2">② RAG 내규검증 (①의 이상 후보 건에 한정)</span>
          </div>
          <span className="note" style={{ margin: 0 }}>콜드스타트 대응 · 지도학습(review_probability)은 post-MVP</span>
        </div>
      </div>

      {pending.length === 0 ? (
        <div className="card"><div className="card-body text-meta">검토 대기 중인 건이 없습니다.</div></div>
      ) : (
        <div className="split">
          {/* Review List */}
          <div className="card">
            <div className="card-head">
              <h3>Review List</h3>
              <span className="text-meta">① 이상탐지 anomaly_score 순 정렬</span>
            </div>
            {/* AI 권장 기준 필터 칩 */}
            <div className="row" style={{ gap: 6, padding: '10px 16px 0', flexWrap: 'wrap' }}>
              {(['ALL', 'APPROVE', 'RETURN', 'REJECT'] as Filter[]).map((f) => (
                <button key={f} className={'tag' + (filter === f ? ' ai' : '')} style={{ cursor: 'pointer' }} onClick={() => pickFilter(f)}>
                  {f === 'ALL' ? '전체' : `${RECO_LABEL[f].mark} ${RECO_LABEL[f].text}`} {counts[f]}
                </button>
              ))}
            </div>
            {/* 일괄 처리 바 (추천 필터 선택 시) */}
            {filter !== 'ALL' && checked.size > 0 && (
              <div className="row" style={{ justifyContent: 'space-between', padding: '10px 16px 0' }}>
                <span className="text-meta">추천: {RECO_LABEL[filter].text} {checked.size}건 선택됨</span>
                <button className={'btn sm ' + (filter === 'APPROVE' ? 'approve' : filter === 'RETURN' ? 'return' : 'reject')} disabled={busy} onClick={decideBulk}>
                  선택 {checked.size}건 일괄 {RECO_LABEL[filter].text}
                </button>
              </div>
            )}
            <table className="table">
              <thead>
                <tr><th style={{ width: 32 }}></th><th>위험도</th><th>대상</th><th className="num">금액</th><th>AI 권장</th></tr>
              </thead>
              <tbody>
                {listed.map((i) => (
                  <tr
                    key={i.id}
                    tabIndex={0}
                    className={sel?.id === i.id ? 'selected' : undefined}
                    onClick={() => { setSelId(i.id); setShowHistory(false) }}
                    onKeyDown={activateOnEnterOrSpace(() => { setSelId(i.id); setShowHistory(false) })}
                  >
                    <td className="checkbox-cell" onClick={(e) => { e.stopPropagation(); toggleCheck(i.id) }}>
                      <input type="checkbox" checked={checked.has(i.id)} onChange={() => toggleCheck(i.id)} onClick={(e) => e.stopPropagation()} />
                    </td>
                    <td style={{ width: 110 }}>
                      <div className="row" style={{ gap: 6 }}>
                        <b style={{ color: 'var(--tone-red)', width: 26 }}>{Math.round(i.anomalyScore * 100)}</b>
                        <div className="anomaly-meter" style={{ flex: 1 }}><span style={{ width: pct(i.anomalyScore) }} /></div>
                      </div>
                    </td>
                    <td>
                      <div style={{ fontWeight: 600 }}>{i.user} <span className="text-meta">{i.dept}</span></div>
                      <div className="muted" style={{ fontSize: 11 }}>{i.anomalyReasons[0]}</div>
                    </td>
                    <td className="num">{won(i.amount)}</td>
                    <td><span className={'tag ' + RECO_LABEL[i.aiRecommendation].cls}>{RECO_LABEL[i.aiRecommendation].mark} {RECO_LABEL[i.aiRecommendation].text}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* 상세 패널 */}
          {sel && (
            <div className="stack-lg">
              {/* 헤더 + 영수증·추출필드 */}
              <div className="card">
                <div className="card-head">
                  <h3>선택 건 상세 — {sel.user}</h3>
                  <span className="text-meta">{sel.dept} · {won(sel.amount)} · {sel.aiCategory}</span>
                </div>
                <div className="card-body">
                  <div className="grid-2" style={{ gap: 16 }}>
                    <div>
                      <div className="text-meta" style={{ marginBottom: 6 }}>영수증 이미지</div>
                      <div style={{ height: 150, border: '1px dashed var(--border-strong)', borderRadius: 'var(--radius-control)', background: 'var(--surface-2)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--muted)', fontSize: 13 }}>
                        {sel.evidence === 'MISSING' ? '⚠ 영수증 미지정' : '🧾 미리보기'}
                      </div>
                    </div>
                    <div>
                      <div className="field" style={{ marginBottom: 10 }}>
                        <label>가맹점 <span className="tag ai">AI 판독 ✓</span></label>
                        <input defaultValue={sel.merchant} readOnly />
                      </div>
                      <div className="row" style={{ gap: 10 }}>
                        <div className="field" style={{ flex: 1, marginBottom: 10 }}>
                          <label>일시</label>
                          <input defaultValue={`${sel.date} ${sel.time ?? ''}`} readOnly />
                        </div>
                        <div className="field" style={{ flex: 1, marginBottom: 10 }}>
                          <label>금액</label>
                          <input defaultValue={won(sel.amount)} readOnly />
                        </div>
                      </div>
                      <div className="field" style={{ marginBottom: 10 }}>
                        <label>카드구분</label>
                        <input defaultValue={CARD_TYPE_LABEL[sel.cardType] + (sel.cardType === 'SHARED' ? ' → 실사용자 입력 필요' : '')} readOnly />
                      </div>
                      <div className="field" style={{ marginBottom: 0 }}>
                        <label>비용분류 <span className="tag ai">● AI 제안</span></label>
                        <select defaultValue={sel.aiCategory}>
                          {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
                        </select>
                      </div>
                    </div>
                  </div>
                  {sel.purpose && (
                    <div className="field" style={{ margin: '12px 0 0' }}>
                      <label>지출 목적 / 사유</label>
                      <input defaultValue={sel.purpose} readOnly />
                    </div>
                  )}
                  <div className="row" style={{ marginTop: 12 }}>
                    <button className="btn sm" onClick={() => setShowHistory((v) => !v)}>
                      <History size={13} /> 상태 변경 이력
                    </button>
                  </div>
                  {showHistory && (
                    <ul className="timeline" style={{ marginTop: 12 }}>
                      <li><div>DRAFT → SUBMITTED</div><div className="t-meta">{sel.user} · {sel.date}</div></li>
                      <li><div>SUBMITTED → RPA_JUDGED (Rule 미매칭)</div><div className="t-meta">Rule Agent</div></li>
                      <li><div>RPA_JUDGED → IN_REVIEW (Risk Review 이관)</div><div className="t-meta">①이상탐지 → ②RAG검증</div></li>
                    </ul>
                  )}
                </div>
              </div>

              {/* ① 이상탐지 결과 */}
              <div className="card">
                <div className="card-head">
                  <h3>① 이상탐지 결과</h3>
                  <span className="tag" style={{ color: 'var(--tone-purple)', background: 'var(--tone-purple-bg)' }}>anomaly {sel.anomalyScore.toFixed(2)}</span>
                </div>
                <div className="card-body">
                  <div className="text-meta" style={{ marginBottom: 8 }}>Feature 기여도 (이상 신호 유발 요인)</div>
                  <div className="stack">
                    {sel.featureContribs.map((f) => (
                      <LabeledBar key={f.feature} label={f.feature} value={f.weight} labelWidth={160} color="var(--tone-purple)" />
                    ))}
                  </div>
                </div>
              </div>

              {/* ② RAG 내규 검증 — 간단 설명 + 근거 링크 */}
              <div className="card">
                <div className="card-head">
                  <h3>② RAG 내규 검증</h3>
                  <span className={'tag ' + RECO_LABEL[sel.aiRecommendation].cls}>AI 권장: {RECO_LABEL[sel.aiRecommendation].text} · {pct(sel.aiConfidence)}</span>
                </div>
                <div className="card-body">
                  <p style={{ margin: '0 0 12px' }}>
                    {sel.ragRefs.length === 0
                      ? '이상 신호가 낮아 내규 위반 소지가 크지 않습니다. 관련 근거 없이 승인 권장합니다.'
                      : `이상탐지로 선별된 건으로, 관련 내규·유사사례를 대조한 결과 "${sel.anomalyReasons.join(', ')}" 사유로 ${RECO_LABEL[sel.aiRecommendation].text}을(를) 권장합니다.`}
                  </p>
                  {sel.ragRefs.length > 0 && (
                    <div className="stack">
                      {sel.ragRefs.map((r) => (
                        <a key={r.source} className="row" href="#" onClick={(e) => e.preventDefault()}
                           style={{ justifyContent: 'space-between', padding: '8px 12px', border: '1px solid var(--border)', borderRadius: 'var(--radius-control)', background: 'var(--surface-2)' }}>
                          <span className="row" style={{ gap: 6 }}>
                            <span className="tag">{r.kind === 'case' ? '사례' : '내규'}</span>
                            <span className="text-meta">{r.source}</span>
                          </span>
                          <span className="row" style={{ gap: 4, color: 'var(--primary)', fontSize: 12, fontWeight: 600 }}>
                            {r.kind === 'case' ? <Paperclip size={12} /> : <ExternalLink size={12} />}
                            {r.kind === 'case' ? '사례 보기' : '원문 보기'}
                          </span>
                        </a>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              {/* 원클릭 처리 3종 (FR-UI-03) */}
              <div className="card">
                <div className="card-body row">
                  <button className="btn approve" disabled={busy} onClick={() => decideOne('APPROVE')}>✓ 승인</button>
                  <button className="btn return" disabled={busy} onClick={() => decideOne('RETURN')}>✎ 보완요청</button>
                  <button className="btn reject" disabled={busy} onClick={() => decideOne('REJECT')}>✕ 반려(최종)</button>
                  <div className="spacer" />
                  <span className="text-meta">결정 → decision_labels 적재 (MVP 재학습 미적용)</span>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {modal && modalItem && (
        <DecisionReasonModal
          item={modalItem}
          decision={modal.decision}
          onClose={() => setModal(null)}
          onConfirm={(reason, detail) => applyDecision(modal.decision, modal.ids, [reason, detail].filter(Boolean).join(' — '))}
        />
      )}
    </>
  )
}

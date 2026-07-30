// S-03 검토 워크스페이스 — 회계 담당자.
// FR-UI-03, FR-RR-01~08, FR-RL-01~02, FR-DB-04
// MVP 2단계: ① 비지도 이상탐지 → ② RAG 내규검증. 지도학습(review_prob)은 post-MVP.
import { useState } from 'react'
import { Paperclip, ExternalLink, History, ChevronDown, ChevronRight } from 'lucide-react'
import type { ReviewItem } from '../types/domain'
import { CARD_TYPE_LABEL, CATEGORIES, type Category } from '../types/domain'
import { won, pct } from '../lib/format'
import { LabeledBar } from '../components/ui/MiniChart'
import { DecisionReasonModal } from '../components/settlement/DecisionReasonModal'
import { StatusBadge } from '../components/ui/StatusBadge'
import { reviewSettlement } from '../api/settlementService'
import { useSettlements } from '../context/SettlementsContext'
import { useCan } from '../lib/capabilities'
import { activateOnEnterOrSpace } from '../lib/a11y'

type Reco = ReviewItem['aiRecommendation']
const RECO_LABEL: Record<Reco, { text: string; abbr: string; cls: string }> = {
  APPROVE: { text: '승인', abbr: '승인', cls: 'ok' },
  RETURN: { text: '보완요청', abbr: '보완', cls: 'warn' },
  REJECT: { text: '반려', abbr: '반려', cls: 'warn' },
}
type Filter = 'ALL' | Reco

// 위험도(anomaly_score×100) 색 구간: ~30 정상(초록) / 30~60 주의(주황) / 60~ 고위험(빨강)
const riskColor = (score: number) => (score >= 60 ? 'var(--tone-red)' : score >= 30 ? 'var(--tone-amber)' : 'var(--tone-green)')

// 비용분류 2글자 약어(표시용). Category는 고정 enum이라 프론트 매핑으로 충분 — 미지값은 앞 2글자 폴백.
const CAT_ABBR: Partial<Record<Category, string>> = { 업무활성: '업무' }
const catAbbr = (c: string) => CAT_ABBR[c as Category] ?? c.slice(0, 2)

export function ReviewWorkspace() {
  const { reviewItems: items, updateStatus } = useSettlements()
  const canReview = useCan()('accounting_review') // 회계 검토·확정 권한(없으면 처리 버튼 비활성)
  const [selId, setSelId] = useState<string | undefined>(items[0]?.id)
  const [filter, setFilter] = useState<Filter>('ALL')
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [showHistory, setShowHistory] = useState(false)
  const [showFact, setShowFact] = useState(false)
  const [modal, setModal] = useState<{ decision: 'RETURN' | 'REJECT'; ids: string[] } | null>(null)
  const [busy, setBusy] = useState(false)
  const [view, setView] = useState<'PENDING' | 'HISTORY'>('PENDING')
  const isHistory = view === 'HISTORY'

  // 검토 대기 = 아직 사람이 결정하지 않은 IN_REVIEW 건. 이전 처리 = 그 외(이미 결정된) 건. anomaly_score 내림차순 (FR-RL-01, FR-RR-04)
  const pending = [...items].filter((i) => i.status === 'IN_REVIEW').sort((a, b) => b.anomalyScore - a.anomalyScore)
  const processed = [...items].filter((i) => i.status !== 'IN_REVIEW').sort((a, b) => b.anomalyScore - a.anomalyScore)
  const source = isHistory ? processed : pending
  const counts: Record<Filter, number> = {
    ALL: source.length,
    APPROVE: source.filter((i) => i.aiRecommendation === 'APPROVE').length,
    RETURN: source.filter((i) => i.aiRecommendation === 'RETURN').length,
    REJECT: source.filter((i) => i.aiRecommendation === 'REJECT').length,
  }
  const listed = filter === 'ALL' ? source : source.filter((i) => i.aiRecommendation === filter)
  const sel = source.find((i) => i.id === selId) ?? listed[0] ?? source[0]
  // fact.json — 정산 상세 모달과 동일한 "규정 판정 입력값" 스냅샷(읽기 전용 요약)
  const fact = sel && {
    merchant: sel.merchant,
    amount: sel.amount,
    date: `${sel.date}${sel.time ? ` ${sel.time}` : ''}`,
    cardType: sel.cardType,
    category: sel.aiCategory,
    evidence: sel.evidence === 'OK' ? 'attached' : 'missing',
    purpose: sel.purpose ?? null,
    anomalyScore: sel.anomalyScore,
    aiRecommendation: sel.aiRecommendation,
    aiConfidence: sel.aiConfidence,
  }

  const pickFilter = (f: Filter) => {
    setFilter(f)
    // 추천 필터 선택 시 해당 건 전체 자동 선택 (S-03 Review 목업) — 이전 처리 뷰에선 일괄처리 없음
    setChecked(f === 'ALL' || isHistory ? new Set() : new Set(source.filter((i) => i.aiRecommendation === f).map((i) => i.id)))
  }

  // 검토 대기 ↔ 이전 처리 내역 전환 — 선택·필터 초기화(같은 UI, 이전 처리 뷰는 처리 버튼 비활성)
  const switchView = (v: 'PENDING' | 'HISTORY') => {
    setView(v)
    setFilter('ALL')
    setChecked(new Set())
    setSelId(undefined)
    setShowHistory(false)
    setShowFact(false)
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
    setShowFact(false)
    const next = source.find((i) => !ids.includes(i.id))
    if (next) setSelId(next.id)
    setBusy(false)
  }

  // 상세 패널 단건 처리
  const decideOne = (decision: Reco) => {
    if (!sel) return
    if (decision === 'APPROVE') applyDecision('APPROVE', [sel.id])
    else setModal({ decision, ids: [sel.id] })
  }
  // 리스트의 권장 처리 배지 클릭 → 해당 건에 곧바로 권장 결정 적용(승인은 즉시, 보완/반려는 사유 모달)
  const decideItem = (item: ReviewItem, decision: Reco) => {
    if (decision === 'APPROVE') applyDecision('APPROVE', [item.id])
    else setModal({ decision, ids: [item.id] })
  }
  // 필터 칩 기준 일괄 처리
  const decideBulk = () => {
    if (filter === 'ALL' || checked.size === 0) return
    const ids = [...checked]
    if (filter === 'APPROVE') applyDecision('APPROVE', ids)
    else setModal({ decision: filter, ids })
  }

  const modalItem = modal ? source.find((i) => i.id === modal.ids[0]) : undefined

  return (
    <div className="review-ws">
      <div className="page-head row" style={{ justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <span className="screen-id">S-03</span>
          <h1>검토 워크스페이스</h1>
          <div className="sub">Rule 미매칭·불확실 건만 위험도순으로 정렬합니다. 최종 결정은 사람이 수행합니다.</div>
        </div>
        {/* 요약 지표 — 제목 우측 상단에 작게 */}
        <div className="head-stats">
          <div className="head-stat"><span className="v">82%</span><span className="l">자동처리율</span></div>
          <div className="head-stat"><span className="v">{pending.length}건</span><span className="l">검토 대기</span></div>
          <div className="head-stat"><span className="v">6.2분</span><span className="l">평균 검토 시간</span></div>
        </div>
      </div>

      {source.length === 0 ? (
        <div className="card review-empty">
          <div className="card-head">
            <h3>Review List</h3>
            <div className="seg-toggle">
              <button type="button" className={!isHistory ? 'active' : ''} onClick={() => switchView('PENDING')}>검토 대기</button>
              <button type="button" className={isHistory ? 'active' : ''} onClick={() => switchView('HISTORY')}>이전 처리</button>
            </div>
          </div>
          <div className="card-body text-meta">{isHistory ? '이전 처리 내역이 없습니다.' : '검토 대기 중인 건이 없습니다.'}</div>
        </div>
      ) : (
        <div className="split">
          {/* Review List */}
          <div className="card">
            <div className="card-head">
              <h3>Review List</h3>
              {/* 검토 대기 ↔ 이전 처리 내역 전환 */}
              <div className="seg-toggle">
                <button type="button" className={!isHistory ? 'active' : ''} onClick={() => switchView('PENDING')}>검토 대기</button>
                <button type="button" className={isHistory ? 'active' : ''} onClick={() => switchView('HISTORY')}>이전 처리</button>
              </div>
            </div>
            <div className="text-meta" style={{ padding: '8px 16px 0' }}>
              {isHistory
                ? `처리 완료 ${source.length}건 · 조회 전용`
                : `고위험 ${source.filter((i) => i.anomalyScore >= 0.7).length}건 · anomaly_score 순`}
            </div>
            {/* AI 권장 기준 필터 칩 */}
            <div className="row" style={{ gap: 6, padding: '10px 16px 0', flexWrap: 'wrap' }}>
              {(['ALL', 'APPROVE', 'RETURN', 'REJECT'] as Filter[]).map((f) => (
                <button key={f} className={'tag' + (filter === f ? ' ai' : '')} style={{ cursor: 'pointer' }} onClick={() => pickFilter(f)}>
                  {f === 'ALL' ? '전체' : RECO_LABEL[f].text} {counts[f]}
                </button>
              ))}
            </div>
            {/* 일괄 처리 바 (추천 필터 선택 시) — 이전 처리 뷰에선 숨김 */}
            {!isHistory && filter !== 'ALL' && checked.size > 0 && (
              <div className="row" style={{ justifyContent: 'space-between', padding: '10px 16px 0' }}>
                <span className="text-meta">추천: {RECO_LABEL[filter].text} {checked.size}건 선택됨</span>
                <button className={'btn sm ' + (filter === 'APPROVE' ? 'approve' : filter === 'RETURN' ? 'return' : 'reject')} disabled={busy || !canReview} onClick={decideBulk}>
                  선택 {checked.size}건 일괄 {RECO_LABEL[filter].text}
                </button>
              </div>
            )}
            <ul className="review-list">
              {listed.map((i) => {
                const score = Math.round(i.anomalyScore * 100)
                const reco = RECO_LABEL[i.aiRecommendation]
                return (
                  <li
                    key={i.id}
                    className={'review-item' + (sel?.id === i.id ? ' selected' : '')}
                    tabIndex={0}
                    onClick={() => { setSelId(i.id); setShowHistory(false); setShowFact(false) }}
                    onKeyDown={activateOnEnterOrSpace(() => { setSelId(i.id); setShowHistory(false); setShowFact(false) })}
                  >
                    <input
                      type="checkbox"
                      className="review-item-check"
                      checked={checked.has(i.id)}
                      onChange={() => toggleCheck(i.id)}
                      onClick={(e) => e.stopPropagation()}
                      disabled={isHistory}
                      aria-label={`${i.user} 선택`}
                    />
                    {/* 위험도: 색 + 숫자만 (~30 정상 / 30~60 주의 / 60~ 고위험) */}
                    <span className="risk-score" style={{ color: riskColor(score) }}>{score}</span>
                    <div className="review-item-body">
                      <div className="review-item-top">
                        <div className="target">
                          <span className="team">{i.dept}</span>
                          <span className="name">{i.user}</span>
                        </div>
                        <span className="tag cat" title={i.aiCategory}>{catAbbr(i.aiCategory)}</span>
                        <button
                          type="button"
                          className={'tag reco-btn ' + reco.cls}
                          disabled={busy || isHistory || !canReview}
                          title={isHistory ? '이미 처리된 건입니다' : `클릭하여 ${reco.text} 처리`}
                          onClick={(e) => { e.stopPropagation(); decideItem(i, i.aiRecommendation) }}
                        >
                          {reco.abbr}
                        </button>
                      </div>
                      <div className="review-item-reason">{i.anomalyReasons.join(', ')}</div>
                    </div>
                  </li>
                )
              })}
            </ul>
          </div>

          {/* 상세 패널 — 정산 상세 모달 레이아웃 참고(좌: 영수증·기본내역·이력/facts, 우: 이상탐지·RAG·액션) */}
          {sel && fact && (
            <div className="review-detail grid-2">
              {/* ───────── 좌: 영수증 + 기본내역 + facts/이력 접이식 ───────── */}
              <div className="stack">
                <div className="card">
                  <div className="card-head">
                    <h3>선택 건 상세 — {sel.user}</h3>
                    <span className="text-meta">{sel.dept} · {sel.aiCategory}</span>
                  </div>
                  <div className="card-body">
                    <div className="text-meta" style={{ marginBottom: 6 }}>영수증 이미지</div>
                    <div style={{ height: 160, border: '1px dashed var(--border-strong)', borderRadius: 'var(--radius-control)', background: 'var(--surface-2)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--muted)', fontSize: 13 }}>
                      {sel.evidence === 'MISSING' ? '⚠ 영수증 미지정' : '🧾 미리보기'}
                    </div>
                  </div>
                </div>

                {/* 기본 내역 (조회 전용) */}
                <div className="card">
                  <div className="card-head"><h3>기본 내역</h3></div>
                  <div className="card-body">
                    <div className="field">
                      <label>가맹점 <span className="tag ai">AI 판독 ✓</span></label>
                      <input defaultValue={sel.merchant} readOnly />
                    </div>
                    <div className="grid-2" style={{ gap: 10 }}>
                      <div className="field"><label>일시</label>
                        <input defaultValue={`${sel.date} ${sel.time ?? ''}`} readOnly />
                      </div>
                      <div className="field"><label>금액</label>
                        <input defaultValue={won(sel.amount)} readOnly />
                      </div>
                    </div>
                    <div className="grid-2" style={{ gap: 10 }}>
                      <div className="field"><label>카드구분</label>
                        <input defaultValue={CARD_TYPE_LABEL[sel.cardType] + (sel.cardType === 'SHARED' ? ' → 실사용자 입력 필요' : '')} readOnly />
                      </div>
                      <div className="field">
                        <label>비용분류 <span className="tag ai">● AI 제안</span></label>
                        <select defaultValue={sel.aiCategory}>
                          {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
                        </select>
                      </div>
                    </div>
                    {sel.purpose && (
                      <div className="field" style={{ marginBottom: 0 }}>
                        <label>지출 목적 / 사유</label>
                        <input defaultValue={sel.purpose} readOnly />
                      </div>
                    )}
                  </div>
                </div>

                {/* fact.json — 접이식(상태 이력 토글과 동일 패턴) */}
                <div className="card">
                  <button className="card-head" style={{ width: '100%', background: 'none', border: 'none', cursor: 'pointer' }} onClick={() => setShowFact((v) => !v)}>
                    <h3 style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      {showFact ? <ChevronDown size={15} /> : <ChevronRight size={15} />} fact.json
                    </h3>
                    <span className="text-meta">규정 판정 입력값</span>
                  </button>
                  {showFact && (
                    <div className="card-body">
                      <pre style={{ margin: 0, fontSize: 12, lineHeight: 1.5, background: 'var(--surface-2)', borderRadius: 'var(--radius-control)', padding: 12, overflowX: 'auto' }}>{JSON.stringify(fact, null, 2)}</pre>
                    </div>
                  )}
                </div>

                {/* 상태 변경 이력 — 접이식 */}
                <div className="card">
                  <button className="card-head" style={{ width: '100%', background: 'none', border: 'none', cursor: 'pointer' }} onClick={() => setShowHistory((v) => !v)}>
                    <h3 style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      {showHistory ? <ChevronDown size={15} /> : <ChevronRight size={15} />} 상태 변경 이력
                    </h3>
                    <History size={14} className="muted" />
                  </button>
                  {showHistory && (
                    <div className="card-body">
                      <ul className="timeline">
                        <li><div>DRAFT → SUBMITTED</div><div className="t-meta">{sel.user} · {sel.date}</div></li>
                        <li><div>SUBMITTED → RPA_JUDGED (Rule 미매칭)</div><div className="t-meta">Rule Agent</div></li>
                        <li><div>RPA_JUDGED → IN_REVIEW (Risk Review 이관)</div><div className="t-meta">①이상탐지 → ②RAG검증</div></li>
                      </ul>
                    </div>
                  )}
                </div>
              </div>

              {/* ───────── 우: ①이상탐지 + ②RAG검증 + 액션 ───────── */}
              <div className="stack">
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

                {/* 원클릭 처리 3종 (FR-UI-03) — 3버튼 균등 정렬. 이전 처리 뷰는 조회 전용(비활성) */}
                <div className="card">
                  <div className="card-body">
                    {isHistory && (
                      <div className="row" style={{ justifyContent: 'space-between', marginBottom: 10 }}>
                        <span className="text-meta">이미 처리된 건 — 조회 전용</span>
                        <StatusBadge status={sel.status} />
                      </div>
                    )}
                    <div className="row review-actions">
                      <button className="btn approve" disabled={busy || isHistory || !canReview} onClick={() => decideOne('APPROVE')}>승인</button>
                      <button className="btn return" disabled={busy || isHistory || !canReview} onClick={() => decideOne('RETURN')}>보완요청</button>
                      <button className="btn reject" disabled={busy || isHistory || !canReview} onClick={() => decideOne('REJECT')}>반려(최종)</button>
                    </div>
                    <div className="text-meta" style={{ marginTop: 10, textAlign: 'right' }}>결정 → decision_labels 적재 (MVP 재학습 미적용)</div>
                  </div>
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
    </div>
  )
}

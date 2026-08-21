// S-03 검토 워크스페이스 — 회계 담당자.
// FR-UI-03, FR-RR-01~08, FR-RL-01~02, FR-DB-04
// MVP 2단계: ① 비지도 이상탐지 → ② RAG 내규검증. 지도학습(review_prob)은 post-MVP.
import { useState } from 'react'
import { Paperclip, ExternalLink, History, ChevronDown, ChevronRight } from 'lucide-react'
import type { ReviewItem } from '../types/domain'
import { CARD_TYPE_LABEL, CATEGORIES, type Category } from '../types/domain'
import { won, pct } from '../lib/format'
import { LabeledBar } from '../components/ui/MiniChart'
import { RulePassedNotice } from '../components/settlement/RulePassedNotice'
import { ReviewDetailEmpty } from '../components/settlement/ReviewDetailEmpty'
import { Markdown } from '../components/ui/Markdown'
import { DecisionReasonModal } from '../components/settlement/DecisionReasonModal'
import { StatusBadge } from '../components/ui/StatusBadge'
import { confirmSettlement, reviewSettlement } from '../api/settlementService'
import { AWAITING_CONFIRM_STATUSES, REVIEW_HISTORY_STATUSES } from '../api/settlements'
import { useSettlements } from '../context/SettlementsContext'
import { useCan } from '../lib/capabilities'
import { activateOnEnterOrSpace } from '../lib/a11y'
import { currentMonth, isInMonth, monthLabel } from '../lib/period'

// AI 권고 — Risk Review Agent(2차 RAG 검증)가 낸 **권장 처리**다. 룰 엔진 판정이 아니고,
// 사람의 결정도 아니다. 세 축이 전부 "승인"이라는 같은 단어를 쓰기 때문에 화면에서
// 반드시 갈라 놓아야 한다: AI **권장** 승인 / 사람이 승인해 **확정 대기**(PENDING_CONFIRM) /
// **확정 완료**(CONFIRMED).
type Reco = 'APPROVE' | 'RETURN' | 'REJECT'
type RecoOrNone = ReviewItem['aiRecommendation']
const RECO_LABEL: Record<Reco, { text: string; abbr: string; cls: string }> = {
  APPROVE: { text: '승인', abbr: '승인', cls: 'ok' },
  RETURN: { text: '보완요청', abbr: '보완', cls: 'warn' },
  REJECT: { text: '반려', abbr: '반려', cls: 'warn' },
}
// Risk Review가 아직 안 돈 건. 예전엔 이 자리에 'APPROVE'가 기본값으로 채워져 있어서
// **돌지도 않은 건이 "AI 권장: 승인"으로 표시**됐다 — 없는 판단을 지어낸 것이다.
const RECO_NONE = { text: 'AI 미실행', abbr: '미실행', cls: '' }
const recoLabel = (r: RecoOrNone) => (r ? RECO_LABEL[r] : RECO_NONE)
// 2차 RAG 검증의 판정. 권고(RECO_LABEL)와 **다른 축**이라 따로 보여준다 —
// "규정 위반인가"와 "그래서 어떻게 하라는 건가"를 같이 봐야 담당자가 판단할 수 있다.
type Verdict = 'VIOLATION' | 'NO_VIOLATION' | 'INSUFFICIENT_INFO'
const VERDICT_LABEL: Record<Verdict, string> = {
  VIOLATION: '내규 위반',
  NO_VIOLATION: '위반 없음',
  INSUFFICIENT_INFO: '판단 보류',
}
const VERDICT_STYLE: Record<Verdict, { color: string; background: string }> = {
  VIOLATION: { color: 'var(--tone-red)', background: 'var(--tone-red-bg)' },
  NO_VIOLATION: { color: 'var(--tone-green)', background: 'var(--tone-green-bg)' },
  INSUFFICIENT_INFO: { color: 'var(--tone-amber)', background: 'var(--tone-amber-bg)' },
}

type Filter = 'ALL' | Reco
/** 검토 워크스페이스의 세 작업함. 확정 대기를 이력에 묻어 두면 아무도 확정하지 않는다. */
type View = 'PENDING' | 'CONFIRM' | 'HISTORY'

// 위험도(anomaly_score×100) 색 구간: ~30 정상(초록) / 30~60 주의(주황) / 60~ 고위험(빨강)
const riskColor = (score: number) => (score >= 60 ? 'var(--tone-red)' : score >= 30 ? 'var(--tone-amber)' : 'var(--tone-green)')

// 비용분류 2글자 약어(표시용). Category는 고정 enum이라 프론트 매핑으로 충분 — 미지값은 앞 2글자 폴백.
// (2026-08-14: '업무활성'→'회식' 카테고리 교체로 특수 약어가 필요 없어짐 — '회식'은 이미 2글자라
// 폴백만으로 충분하다. 새로 특수 약어가 필요한 카테고리가 생기면 여기 추가할 것.)
const CAT_ABBR: Partial<Record<Category, string>> = {}
const catAbbr = (c: string) => CAT_ABBR[c as Category] ?? c.slice(0, 2)

// 이미 처리된 건의 "실제 결과" — 이전 처리 탭은 AI 권장이 아니라 이 값으로 세고·거르고·표시한다.
//  **`PENDING_CONFIRM`은 여기 없다.** 그건 처리 결과가 아니라 **확정 대기**다 — 룰 판정
//  PASS로 자동 도착한 건(아무도 안 봤다)까지 "승인 처리됨"으로 세고 있었다.
const OUTCOME_BY_STATUS: Partial<Record<ReviewItem['status'], Reco>> = {
  CONFIRMED: 'APPROVE', ERP_VOUCHER_DRAFTED: 'APPROVE',
  RETURNED: 'RETURN', REJECT: 'REJECT',
}
const outcomeOf = (item: ReviewItem): RecoOrNone => OUTCOME_BY_STATUS[item.status] ?? item.aiRecommendation

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
  const [view, setView] = useState<View>('PENDING')
  const isHistory = view === 'HISTORY'
  const isConfirm = view === 'CONFIRM'
  const month = currentMonth()

  // 검토 대기 = 아직 사람이 결정하지 않은 IN_REVIEW 건. anomaly_score 내림차순 (FR-RL-01, FR-RR-04)
  const pending = [...items].filter((i) => i.status === 'IN_REVIEW').sort((a, b) => b.anomalyScore - a.anomalyScore)
  // 확정 대기 = PENDING_CONFIRM. **처리가 끝난 게 아니라 남은 일이다** — 룰 판정 PASS로
  //  자동 도착한 건(아무도 안 봤다)과 담당자가 승인한 건이 함께 모이고, 둘 다 사람이
  //  확정해야 CONFIRMED가 된다(FR-ST-03). 달로 자르지 않는다: 밀린 확정은 지난달 것도 해야 한다.
  const awaiting = [...items]
    .filter((i) => AWAITING_CONFIRM_STATUSES.includes(i.status))
    .sort((a, b) => b.date.localeCompare(a.date))
  // 이전 처리 = 이번 달에 확정·보완요청·반려로 **끝난** 건. 최근 거래일순.
  const processed = [...items]
    .filter((i) => REVIEW_HISTORY_STATUSES.includes(i.status) && isInMonth(i.date, month))
    .sort((a, b) => (a.date === b.date ? b.anomalyScore - a.anomalyScore : b.date.localeCompare(a.date)))
  const source = isHistory ? processed : isConfirm ? awaiting : pending
  // 검토 대기는 AI 권장 기준, 이전 처리는 실제 처리 결과 기준으로 세고 거른다.
  const bucketOf = (item: ReviewItem): RecoOrNone => (isHistory ? outcomeOf(item) : item.aiRecommendation)
  const counts: Record<Filter, number> = {
    ALL: source.length,
    APPROVE: source.filter((i) => bucketOf(i) === 'APPROVE').length,
    RETURN: source.filter((i) => bucketOf(i) === 'RETURN').length,
    REJECT: source.filter((i) => bucketOf(i) === 'REJECT').length,
  }
  const listed = filter === 'ALL' ? source : source.filter((i) => bucketOf(i) === filter)
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
    setChecked(f === 'ALL' || isHistory ? new Set() : new Set(source.filter((i) => bucketOf(i) === f).map((i) => i.id)))
  }

  // 작업함 전환 — 선택·필터 초기화(같은 UI, 이전 처리 뷰는 처리 버튼 비활성)
  const switchView = (v: View) => {
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

  // 사람 최종 확정 (FR-ST-03) — PENDING_CONFIRM → CONFIRMED.
  //  이 경로가 화면에 아예 없어서 확정 대기 건이 어디로도 못 가고 쌓이고 있었다.
  const confirmIds = async (ids: string[]) => {
    if (ids.length === 0) return
    setBusy(true)
    for (const id of ids) {
      const status = await confirmSettlement(id)
      if (status) updateStatus(id, status)
    }
    setChecked(new Set())
    setSelId(undefined)
    setBusy(false)
  }

  // 상세 패널 단건 처리
  const decideOne = (decision: Reco) => {
    if (!sel) return
    if (decision === 'APPROVE') applyDecision('APPROVE', [sel.id])
    else setModal({ decision, ids: [sel.id] })
  }
  // 리스트의 권장 처리 배지 클릭 → 해당 건에 곧바로 권장 결정 적용(승인은 즉시, 보완/반려는 사유 모달)
  const decideItem = (item: ReviewItem, decision: RecoOrNone) => {
    if (!decision) return   // AI가 안 돈 건 — 권고가 없으니 원클릭 처리도 없다
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

  //  빈 상태 문구는 한 곳에서 만든다 — 목록·상세·액션이 서로 다른 말을 하면 사용자가
  //  "목록이 빈 건가, 선택을 안 한 건가"를 화면마다 다시 판단해야 한다.
  const emptyMessage = source.length === 0
    ? (isHistory ? `${monthLabel(month)}에 확정·보완요청·반려된 내역이 없습니다.`
      : isConfirm ? '확정 대기 중인 건이 없습니다.' : '검토 대기 중인 건이 없습니다.')
    : listed.length === 0 ? '이 필터에 해당하는 건이 없습니다.'
      : '왼쪽 목록에서 건을 선택하세요.'

  return (
    <div className="review-ws">
      <div className="hero-band">
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
            <div className="head-stat"><span className="v">{awaiting.length}건</span><span className="l">확정 대기</span></div>
            <div className="head-stat"><span className="v">6.2분</span><span className="l">평균 검토 시간</span></div>
          </div>
        </div>
      </div>

      <div className="split" style={{ padding: 'var(--space-6)' }}>
          {/* Review List */}
          <div className="card">
            <div className="card-head">
              <h3>Review List</h3>
              {/* 검토 대기 ↔ 이전 처리 내역 전환 */}
              <div className="seg-toggle">
                <button type="button" className={view === 'PENDING' ? 'active' : ''} onClick={() => switchView('PENDING')}>검토 대기 {pending.length}</button>
                <button type="button" className={view === 'CONFIRM' ? 'active' : ''} onClick={() => switchView('CONFIRM')}>확정 대기 {awaiting.length}</button>
                <button type="button" className={view === 'HISTORY' ? 'active' : ''} onClick={() => switchView('HISTORY')}>이전 처리</button>
              </div>
            </div>
            {/* 요약 줄 — 비었을 땐 아래 빈 상태 문구가 같은 말을 하므로 겹쳐 쓰지 않는다. */}
            {source.length > 0 && (
            <div className="text-meta" style={{ padding: '8px 16px 0' }}>
              {isHistory
                ? `${monthLabel(month)} 처리 완료 ${source.length}건 · 조회 전용`
                : isConfirm
                  ? `사람 확정을 기다리는 ${source.length}건 · 룰 자동통과분 포함`
                  : `고위험 ${source.filter((i) => i.anomalyScore >= 0.7).length}건 · anomaly_score 순`}
            </div>
            )}
            {/* AI 권장 기준 필터 칩 — 확정 대기함에선 의미가 없다(권장이 아니라 확정만 남았다). */}
            {!isConfirm && (
            <div className="row" style={{ gap: 6, padding: '10px 16px 0', flexWrap: 'wrap' }}>
              {(['ALL', 'APPROVE', 'RETURN', 'REJECT'] as Filter[]).map((f) => (
                <button key={f} className={'tag' + (filter === f ? ' ai' : '')} style={{ cursor: 'pointer' }}
                  title={f === 'ALL' ? undefined : isHistory ? `${RECO_LABEL[f].text}으로 처리된 건` : `AI 권장이 ${RECO_LABEL[f].text}인 건`}
                  onClick={() => pickFilter(f)}>
                  {f === 'ALL' ? '전체' : RECO_LABEL[f].text} {counts[f]}
                </button>
              ))}
            </div>
            )}
            {/* 확정 대기 일괄 처리 — FR-ST-03의 '사람 확정'을 여기서 수행한다. */}
            {isConfirm && checked.size > 0 && (
              <div className="row" style={{ justifyContent: 'space-between', padding: '10px 16px 0' }}>
                <span className="text-meta">{checked.size}건 선택됨</span>
                <button className="btn sm approve" disabled={busy || !canReview} onClick={() => confirmIds([...checked])}>
                  선택 {checked.size}건 확정(CONFIRMED)
                </button>
              </div>
            )}
            {/* 일괄 처리 바 (추천 필터 선택 시) — 이전 처리 뷰에선 숨김 */}
            {view === 'PENDING' && filter !== 'ALL' && checked.size > 0 && (
              <div className="row" style={{ justifyContent: 'space-between', padding: '10px 16px 0' }}>
                <span className="text-meta">추천: {RECO_LABEL[filter].text} {checked.size}건 선택됨</span>
                <button className={'btn sm ' + (filter === 'APPROVE' ? 'approve' : filter === 'RETURN' ? 'return' : 'reject')} disabled={busy || !canReview} onClick={decideBulk}>
                  선택 {checked.size}건 일괄 {RECO_LABEL[filter].text}
                </button>
              </div>
            )}
            {listed.length === 0 && (
              <div className="card-body text-meta">{emptyMessage}</div>
            )}
            <ul className="review-list">
              {listed.map((i) => {
                // Risk Review를 거치지 않은 건(룰 PASS로 승인 대기 직행)은 **점수가 없다**.
                // 0으로 그리면 "이상 없음"으로 읽혀, 아무도 안 본 건이 검토된 것처럼 보인다.
                const score = i.riskReviewed ? Math.round(i.anomalyScore * 100) : null
                const reco = recoLabel(i.aiRecommendation)
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
                    <span
                      className="risk-score"
                      style={{ color: score === null ? 'var(--muted)' : riskColor(score) }}
                      title={score === null ? '이상탐지를 거치지 않은 건입니다(룰 판정 통과)' : undefined}
                    >
                      {score ?? '-'}
                    </span>
                    <div className="review-item-body">
                      <div className="review-item-top">
                        <div className="target">
                          <span className="team">{i.dept}</span>
                          <span className="name">{i.user}</span>
                        </div>
                        <span className="tag cat" title={i.aiCategory}>{catAbbr(i.aiCategory)}</span>
                        {/* 이전 처리·확정 대기 뷰는 AI 권장이 아니라 실제 상태를 보여준다.
                            확정 대기에서 AI 권장 배지를 띄우면 "권장 승인"과 "승인되어 확정 대기"가
                            같은 칩으로 보여 담당자가 둘을 구별할 수 없다. */}
                        {isHistory || isConfirm ? (
                          <StatusBadge status={i.status} />
                        ) : reco === RECO_NONE ? (
                          <span className="tag" title="Risk Review Agent가 아직 돌지 않았습니다">{reco.abbr}</span>
                        ) : (
                          <button
                            type="button"
                            className={'tag reco-btn ' + reco.cls}
                            disabled={busy || !canReview}
                            title={`클릭하여 ${reco.text} 처리`}
                            onClick={(e) => { e.stopPropagation(); decideItem(i, i.aiRecommendation) }}
                          >
                            {reco.abbr}
                          </button>
                        )}
                      </div>
                      <div className="review-item-reason">
                        {isHistory || isConfirm
                          ? `${i.date} · ${won(i.amount)} · ${i.merchant}`
                          : i.anomalyReasons.join(', ')}
                      </div>
                    </div>
                  </li>
                )
              })}
            </ul>
          </div>

          {/* 상세 패널 — 정산 상세 모달 레이아웃 참고(좌: 영수증·기본내역·이력/facts, 우: 이상탐지·RAG·액션) */}
          {/* 선택이 없어도 **같은 골격**을 유지한다 — 오른쪽 절반이 사라졌다 나타나면
              레이아웃이 두 벌이 되어, 건이 생길 때마다 눌러야 할 자리가 바뀐다. */}
          {!(sel && fact) && <ReviewDetailEmpty message={emptyMessage} />}
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
                      <input value={sel.merchant} readOnly />
                    </div>
                    <div className="grid-2" style={{ gap: 10 }}>
                      <div className="field"><label>일시</label>
                        <input value={`${sel.date} ${sel.time ?? ''}`} readOnly />
                      </div>
                      <div className="field"><label>금액</label>
                        <input value={won(sel.amount)} readOnly />
                      </div>
                    </div>
                    <div className="grid-2" style={{ gap: 10 }}>
                      <div className="field"><label>카드구분</label>
                        <input value={CARD_TYPE_LABEL[sel.cardType] + (sel.cardType === 'SHARED' ? ' → 실사용자 입력 필요' : '')} readOnly />
                      </div>
                      <div className="field">
                        <label>비용분류 <span className="tag ai">● AI 제안</span></label>
                        {/* key: 선택 건이 바뀌면 remount해 AI 제안값으로 되돌린다(비제어 select) */}
                        <select key={sel.id} defaultValue={sel.aiCategory}>
                          {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
                        </select>
                      </div>
                    </div>
                    {sel.purpose && (
                      <div className="field" style={{ marginBottom: 0 }}>
                        <label>지출 목적 / 사유</label>
                        <input value={sel.purpose} readOnly />
                      </div>
                    )}
                  </div>
                </div>

                {/* fact.json — 접이식. 판정 시점 EvalContext 스냅샷이 있으면 그 원본을 보여준다 */}
                <div className="card">
                  <button className="card-head" style={{ width: '100%', background: 'none', border: 'none', cursor: 'pointer' }} onClick={() => setShowFact((v) => !v)}>
                    <h3 style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      {showFact ? <ChevronDown size={15} /> : <ChevronRight size={15} />} fact.json
                    </h3>
                    <span className="text-meta">{sel.evalContext ? 'EvalContext 스냅샷 (판정 시점 원본)' : '규정 판정 입력값'}</span>
                  </button>
                  {showFact && (
                    <div className="card-body">
                      {sel.evalContext && (
                        <div className="note" style={{ marginBottom: 10 }}>
                          룰 엔진이 판정에 사용한 <b>EvalContext</b> 전체 스냅샷입니다. 이 값만으로 판정을 그대로 재현할 수 있어
                          사후 감사·이의 제기 대응이 가능합니다. (schema v{String(sel.evalContext.meta?.schema_version ?? '-')} ·
                          builder {String(sel.evalContext.meta?.builder_version ?? '-')})
                        </div>
                      )}
                      <pre style={{ margin: 0, fontSize: 12, lineHeight: 1.5, background: 'var(--surface-2)', borderRadius: 'var(--radius-control)', padding: 12, maxHeight: 420, overflow: 'auto' }}>
                        {JSON.stringify(sel.evalContext ?? fact, null, 2)}
                      </pre>
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
                {/* ① 이상탐지 결과 — Risk Review를 거친 건에만 값이 있다. */}
                <div className="card">
                  <div className="card-head">
                    <h3>① 이상탐지 결과</h3>
                    <span className="tag" style={sel.riskReviewed
                      ? { color: 'var(--tone-purple)', background: 'var(--tone-purple-bg)' }
                      : { color: 'var(--muted)' }}>
                      anomaly {sel.riskReviewed ? sel.anomalyScore.toFixed(2) : '-'}
                    </span>
                  </div>
                  <div className="card-body">
                    {sel.riskReviewed ? (
                      <>
                        <div className="text-meta" style={{ marginBottom: 8 }}>Feature 기여도 (이상 신호 유발 요인)</div>
                        <div className="stack">
                          {sel.featureContribs.map((f) => (
                            <LabeledBar key={f.feature} label={f.feature} value={f.weight} labelWidth={160} color="var(--tone-purple)" />
                          ))}
                        </div>
                      </>
                    ) : (
                      <RulePassedNotice item={sel} />
                    )}
                  </div>
                </div>

                {/* ② RAG 내규 검증 — 간단 설명 + 근거 링크 */}
                <div className="card">
                  <div className="card-head">
                    <h3>② RAG 내규 검증</h3>
                    <span className="row" style={{ gap: 6 }}>
                      {/* 판정과 권고는 다른 축이다 — 판단 보류(INSUFFICIENT_INFO)를 권고만 보면 놓친다. */}
                      {sel.violationVerdict && (
                        <span className="tag" style={VERDICT_STYLE[sel.violationVerdict]}>
                          {VERDICT_LABEL[sel.violationVerdict]}
                        </span>
                      )}
                      <span className={'tag ' + recoLabel(sel.aiRecommendation).cls}>
                        {sel.aiRecommendation
                          ? `AI 권장: ${recoLabel(sel.aiRecommendation).text} · ${pct(sel.aiConfidence)}`
                          : 'AI 권장 없음 (미실행)'}
                      </span>
                    </span>
                  </div>
                  <div className="card-body">
                    {sel.violationVerdict === 'INSUFFICIENT_INFO' && (
                      // 이 상태를 조용히 넘기면 담당자가 "검증했는데 문제없음"으로 오해한다.
                      <p className="note" style={{ margin: '0 0 12px', color: 'var(--tone-amber)' }}>
                        근거가 부족해 <b>판단을 보류</b>한 건입니다. 아래 내용은 참고용이며, 증빙·사유를 직접 확인해주세요.
                      </p>
                    )}
                    {sel.ragReport
                      ? <Markdown source={sel.ragReport} />
                      : (
                        <p style={{ margin: '0 0 12px' }}>
                          {!sel.aiRecommendation
                            ? 'Risk Review Agent가 아직 실행되지 않았습니다. 아래 근거 없이 판단하지 마세요.'
                            : sel.ragRefs.length === 0
                              ? '이상 신호가 낮아 내규 위반 소지가 크지 않습니다. 관련 근거 없이 승인 권장합니다.'
                              : `이상탐지로 선별된 건으로, 관련 내규·유사사례를 대조한 결과 "${sel.anomalyReasons.join(', ')}" 사유로 ${recoLabel(sel.aiRecommendation).text}을(를) 권장합니다.`}
                        </p>
                      )}
                    {sel.ragRefs.length > 0 && (
                      <div className="stack" style={{ marginTop: sel.ragReport ? 14 : 0 }}>
                        <div className="text-meta" style={{ fontWeight: 700 }}>참조 근거 {sel.ragRefs.length}건</div>
                        {sel.ragRefs.map((r) => (
                          <a key={r.source} href="#" onClick={(e) => e.preventDefault()}
                             style={{ display: 'block', padding: '8px 12px', border: '1px solid var(--border)', borderRadius: 'var(--radius-control)', background: 'var(--surface-2)', textDecoration: 'none', color: 'inherit' }}>
                            <span className="row" style={{ justifyContent: 'space-between', gap: 8 }}>
                              <span className="row" style={{ gap: 6, minWidth: 0 }}>
                                <span className="tag">{r.kind === 'case' ? '사례' : '내규'}</span>
                                <span className="text-meta">{r.source}</span>
                                {r.relevance !== undefined && <span className="tag ai">적합도 {Math.round(r.relevance * 100)}%</span>}
                              </span>
                              <span className="row" style={{ gap: 4, color: 'var(--primary)', fontSize: 12, fontWeight: 600, flexShrink: 0 }}>
                                {r.kind === 'case' ? <Paperclip size={12} /> : <ExternalLink size={12} />}
                                {r.kind === 'case' ? '사례 보기' : '원문 보기'}
                              </span>
                            </span>
                            <div style={{ fontSize: 12.5, marginTop: 4 }}>{r.title}</div>
                            {r.excerpt && (
                              <div className="text-meta" style={{ marginTop: 4, paddingLeft: 8, borderLeft: '2px solid var(--border-strong)', lineHeight: 1.6 }}>
                                “{r.excerpt}”
                              </div>
                            )}
                          </a>
                        ))}
                      </div>
                    )}
                  </div>
                </div>

                {/* 원클릭 처리 3종 (FR-UI-03) — 3버튼 균등 정렬. 이전 처리 뷰는 조회 전용(비활성) */}
                <div className="card">
                  <div className="card-body">
                    {(isHistory || isConfirm) && (
                      <div className="row" style={{ justifyContent: 'space-between', marginBottom: 10 }}>
                        <span className="text-meta">
                          {isHistory ? '이미 처리된 건 — 조회 전용' : '검토를 마친 건 — 사람 확정만 남았습니다'}
                        </span>
                        <StatusBadge status={sel.status} />
                      </div>
                    )}
                    {/* 확정 대기는 '검토 결정'이 아니라 '확정'만 남은 단계다. 여기에 승인·보완·반려를
                        그대로 두면 이미 내려진 결정을 다시 내리는 것처럼 보인다(전이도 불가). */}
                    {isConfirm ? (
                      <div className="row review-actions">
                        <button className="btn approve" disabled={busy || !canReview} onClick={() => confirmIds([sel.id])}>
                          확정(CONFIRMED)
                        </button>
                      </div>
                    ) : (
                      <div className="row review-actions">
                        <button className="btn approve" disabled={busy || isHistory || !canReview} onClick={() => decideOne('APPROVE')}>승인</button>
                        <button className="btn return" disabled={busy || isHistory || !canReview} onClick={() => decideOne('RETURN')}>보완요청</button>
                        <button className="btn reject" disabled={busy || isHistory || !canReview} onClick={() => decideOne('REJECT')}>반려(최종)</button>
                      </div>
                    )}
                    <div className="text-meta" style={{ marginTop: 10, textAlign: 'right' }}>
                      {isConfirm ? '확정 시 ERP 전표(안)가 생성됩니다 (FR-ST-03)' : '결정 → decision_labels 적재 (MVP 재학습 미적용)'}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}
      </div>

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

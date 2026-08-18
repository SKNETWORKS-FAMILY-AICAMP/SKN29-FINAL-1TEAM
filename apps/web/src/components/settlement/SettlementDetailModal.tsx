// S-06 정산 상세 · 수정 · 신규등록 통합 모달 — FR-DA-02~06, FR-ST-01~04, FR-AUD-01
//  item=null → 신규등록(빈 모달, 영수증 업로드 또는 직접 기입으로 생성)
//  item=Settlement → 상세보기 및 수정 (내 건이 아니면 조회 전용)
//  context='team' → 팀 취합 뷰: 팀장이 팀원 건을 팀 보완요청/팀 반려 처리
//  좌: 영수증/추가증빙 업로드 + 상태변경이력 / 우: 기본내역·분류·사유 + fact.json(자동생성) + AI 코멘트
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  AlertTriangle, Check, ChevronDown, ChevronRight, FileText, Lock, Paperclip,
  Receipt, Sparkles, Trash2, Upload, X,
} from 'lucide-react'
import {
  CARD_TYPE_LABEL, CATEGORIES,
  type CardType, type Category, type ReviewItem, type Settlement, type SettlementStatus,
} from '../../types/domain'
import { needsAttention } from '../../lib/judgement'
import { Modal } from '../ui/Modal'
import { StatusBadge } from '../ui/StatusBadge'
import { useCan } from '../../lib/capabilities'
import { todayISO } from '../../lib/period'
import { useAuth } from '../../context/AuthContext'
import {
  createSettlement, decideTeamSettlement, deleteSettlement, raiseSettlements, reviewSettlement,
  reviseDraft, submitSettlements, suggestDraft, type DraftSuggestion, type PolicyHint,
} from '../../api/settlementService'
import { ReturnReasonModal } from './ReturnReasonModal'

// 신규등록 시 영수증 Vision 판독을 흉내내는 mock 추출값 (백엔드 연동 전까지의 데모용)
const MOCK_OCR = { merchant: '강남 한식당', amount: '452,000', category: '접대' as Category }

interface AiComment { icon: 'ocr' | 'doc' | 'ai'; text: string }
interface ExtraFile { id: string; name: string }

const numOnly = (s: string) => Number(s.replace(/[^0-9]/g, '') || '0')

export function SettlementDetailModal({
  item,
  onClose,
  onStatusChange,
  onCreated,
  onDeleted,
  context = 'default',
}: {
  /** null이면 신규 지출 등록(빈 모달). Settlement이면 상세보기·수정. */
  item: Settlement | null
  onClose: () => void
  /** 정산 상태가 실제로 바뀌었을 때 — 부모가 목록의 해당 건 상태를 갱신 */
  onStatusChange?: (id: string, status: SettlementStatus) => void
  /** 신규 생성이 완료됐을 때 — 부모가 목록에 새 건을 추가 */
  onCreated?: (item: Settlement) => void
  /** 삭제 완료 시 — 부모가 목록에서 제거 */
  onDeleted?: (id: string) => void
  /** 'team'=팀 취합 뷰(팀장이 팀원 건 처리) / 'mine'='내 지출'(본인 건 — 삭제·제출만) */
  context?: 'default' | 'team' | 'mine'
}) {
  const can = useCan()
  const { user } = useAuth()
  const nav = useNavigate()
  const isCreate = item === null
  // 회계 검토·확정 권한. 단 '내 지출' 화면에서는 본인 건이므로 검토 버튼을 노출하지 않는다.
  const canReview = can('accounting_review') && context !== 'mine'

  // ── 권한/모드 ──
  const isTeamView = context === 'team'
  const isMineView = context === 'mine'   // '내 지출' — 회계 권한이 있어도 검토 버튼을 띄우지 않는다
  // 개인/검토 화면(default)에선 편집 주체로 보고, 팀 취합 뷰에서만 소유자(이름 일치)로 한정.
  //  (mock 로그인 이름이 데이터 소유자와 달라도 '내 지출' 편집/제출이 막히지 않도록)
  const isOwner = isCreate || !isTeamView || item?.user === user?.name
  // 팀 취합 뷰에서 팀장급이 '남의' 취합중(TEAM_COLLECTING) 건을 처리
  const canTeamDecide = isTeamView && !isOwner && can('team_aggregate') && item?.status === 'TEAM_COLLECTING'
  const readOnly = !isCreate && !isOwner // 팀 취합 뷰에서 내 건이 아니면 보기만 가능

  // ── 편집 상태(우측 폼) ──
  const [merchant, setMerchant] = useState(item?.merchant ?? '')
  // 신규 등록의 기본 날짜는 **오늘**이다. 예전엔 목업 시절 상수('2026-07-28')가 박혀 있어서,
  // 사용자가 날짜를 안 고치면 지난달 건으로 저장됐다 — 등록은 성공(201)하는데 '내 지출'이
  // 기본으로 이번 달만 보여주므로 **목록에서 사라진 것처럼 보였다**.
  const [dateStr, setDateStr] = useState(item?.date ?? todayISO())
  const [amountText, setAmountText] = useState(item ? String(item.amount) : '')
  const [cardType, setCardType] = useState<CardType>(item?.cardType ?? 'PERSONAL')
  const [category, setCategory] = useState<Category>(item?.aiCategory ?? '접대')
  const [purpose, setPurpose] = useState(item?.purpose ?? '')
  const [aiSuggested, setAiSuggested] = useState(item?.aiSuggested ?? false)

  // ── 좌측 업로드 상태 ──
  const [receiptUp, setReceiptUp] = useState(item?.evidence === 'OK')
  const [extraFiles, setExtraFiles] = useState<ExtraFile[]>([])

  // ── AI 코멘트 로그 / 규정 힌트 / 지시 입력 / fact.json 접힘 ──
  const [comments, setComments] = useState<AiComment[]>([])
  const [hints, setHints] = useState<PolicyHint[]>([])
  const [instruction, setInstruction] = useState('')
  const [factOpen, setFactOpen] = useState(false)

  const [pending, setPending] = useState(false)
  const [showReturnModal, setShowReturnModal] = useState(false)

  const evidence: 'OK' | 'MISSING' = receiptUp || extraFiles.length > 0 ? 'OK' : 'MISSING'
  const needsResubmit = isOwner && !canReview && !isCreate && item?.status === 'RETURNED'
  const isDraft = !isCreate && item?.status === 'DRAFT' // 개인 보유 → 팀 취합으로 '올림' 대상
  // 삭제는 아직 팀·회계 단계로 넘어가지 않은 건만 (백엔드도 같은 기준으로 막는다)
  const canDelete = !isCreate && ['DRAFT', 'TEAM_RETURNED', 'TEAM_REJECTED'].includes(item?.status ?? '')
  // 이상 건(건당한도초과·실사용자미지정 등)은 팀 취합 뷰에서 제출 불가 — 보완요청·반려로만 처리
  const isAnomaly = !isCreate && item ? needsAttention(item) : false

  // fact.json — 현재 입력값으로 자동 생성(자동생성/자동갱신)
  const fact = useMemo(() => ({
    merchant: merchant || null,
    amount: numOnly(amountText),
    date: dateStr,
    cardType,
    category,
    evidence: evidence === 'OK' ? 'attached' : 'missing',
    extraDocs: extraFiles.length,
    purpose: purpose || null,
    source: receiptUp ? 'vision_ocr' : 'manual',
    aiSuggested,
  }), [merchant, amountText, dateStr, cardType, category, evidence, extraFiles.length, purpose, receiptUp, aiSuggested])

  const pushComment = (c: AiComment) => setComments((prev) => [...prev, c])

  // 영수증 업로드 → 초안 작성 Agent 호출(생성 모드). 실패 시 로컬 mock으로 폴백.
  const uploadReceipt = async () => {
    setReceiptUp(true)
    setPending(true)
    const result = await suggestDraft({
      merchant, amount: numOnly(amountText), date: dateStr, cardType, evidence: 'OK',
    })
    setPending(false)
    if (!result) {
      if (!merchant) setMerchant(MOCK_OCR.merchant)
      if (!amountText) setAmountText(MOCK_OCR.amount)
      pushComment({ icon: 'ocr', text: '영수증을 판독했습니다. (오프라인 폴백 — Core API 연결을 확인해주세요)' })
      return
    }
    applyDraft(result)
  }

  /** Draft Agent 응답을 폼·코멘트·규정 힌트에 반영 */
  const applyDraft = (result: DraftSuggestion) => {
    const d = result.draft
    if (d.merchant) setMerchant(String(d.merchant))
    if (d.amount) setAmountText(String(d.amount))
    if (d.category) { setCategory(d.category as Category); setAiSuggested(true) }
    if (d.purpose) setPurpose(String(d.purpose))
    if (d.evidence) setReceiptUp(d.evidence === 'OK')
    setHints(result.policyHints ?? [])
    result.comments?.forEach((c) => pushComment({ icon: c.icon as AiComment['icon'], text: c.text }))
  }

  // 자연어 지시로 초안 수정(수정 모드)
  const askAgent = async () => {
    const text = instruction.trim()
    setPending(true)
    const result = text
      ? await reviseDraft(text, {
          merchant, amount: numOnly(amountText), category, aiCategory: category,
          purpose, evidence, headcount: 0,
        })
      : await suggestDraft({ merchant, amount: numOnly(amountText), date: dateStr, cardType, evidence })
    setPending(false)
    if (!result) { pushComment({ icon: 'ai', text: 'AI 초안 생성에 실패했습니다. Core API 연결을 확인해주세요.' }); return }
    applyDraft(result)
    setInstruction('')
  }

  // 추가 증빙 업로드(미리보기 없음) → 파일 칩 추가 + 코멘트
  const uploadExtra = () => {
    const n = extraFiles.length + 1
    const name = `추가증빙_${n}.pdf`
    setExtraFiles((prev) => [...prev, { id: `x${prev.length}-${name}`, name }])
    pushComment({ icon: 'doc', text: `증빙 문서 "${name}" 인식 — ${category} 목적 보강 근거로 첨부했습니다.` })
  }
  const removeExtra = (id: string) => setExtraFiles((prev) => prev.filter((f) => f.id !== id))


  const draft = (): Omit<Settlement, 'id' | 'status'> => ({
    date: dateStr,
    merchant: merchant || '미상 가맹점',
    amount: numOnly(amountText),
    cardType,
    aiCategory: category,
    aiSuggested,
    evidence,
    user: user?.name ?? '나',
    purpose: purpose || undefined,
  })

  // 신규 저장 → createSettlement → 목록에 추가
  const save = async () => {
    setPending(true)
    const created = await createSettlement(draft())
    onCreated?.(created)
    setPending(false)
    onClose()
  }

  // '내 지출' 삭제 — 아직 팀·회계로 넘어가지 않은 건만.
  const remove = async () => {
    if (!item) return
    if (!window.confirm(`“${item.merchant}” 지출 건을 삭제합니다. 되돌릴 수 없습니다. 계속할까요?`)) return
    setPending(true)
    const ok = await deleteSettlement(item.id)
    setPending(false)
    if (!ok) { window.alert('이미 팀·회계로 넘어간 건은 삭제할 수 없습니다.'); return }
    onDeleted?.(item.id)
    onClose()
  }

  // 개인 '올림' (DRAFT → TEAM_COLLECTING). 1인 팀도 팀 취합 단계를 거친다.
  const raise = async () => {
    if (!item) return
    setPending(true)
    const status = await raiseSettlements([item.id])
    onStatusChange?.(item.id, status)
    setPending(false)
    onClose()
  }

  // 팀 제출 (TEAM_COLLECTING → SUBMITTED) · 회계 보완요청 재제출 (RETURNED → SUBMITTED)
  //  제출 직후 룰 엔진 1차판정이 이어 돌아 실제 도착 상태는 건마다 다르다 — 그 값을 그대로 반영한다.
  const submit = async () => {
    if (!item) return
    setPending(true)
    const outcome = await submitSettlements([item.id])
    onStatusChange?.(item.id, outcome.status[item.id] ?? 'SUBMITTED')
    setPending(false)
    onClose()
  }

  const approve = async () => {
    if (!item) return
    setPending(true)
    const status = await reviewSettlement(item.id, 'APPROVE')
    onStatusChange?.(item.id, status)
    setPending(false)
    nav(`/erp/${item.id}`)
  }

  const reject = async () => {
    if (!item) return
    setPending(true)
    const status = await reviewSettlement(item.id, 'REJECT')
    onStatusChange?.(item.id, status)
    setPending(false)
    onClose()
  }

  // 팀 반려 — 팀 취합 단계 반려(회계 반려와 별개 상태)
  const teamReject = async () => {
    if (!item) return
    setPending(true)
    const status = await decideTeamSettlement(item.id, 'REJECT')
    onStatusChange?.(item.id, status)
    setPending(false)
    onClose()
  }

  // 보완요청 사유 확정 — 팀 뷰면 팀 보완요청(TEAM_RETURNED), 아니면 회계 보완요청(RETURNED)
  const returnWithReason = async (reason: string, detail: string) => {
    if (!item) return
    const msg = detail ? `${reason} — ${detail}` : reason
    const status = canTeamDecide
      ? await decideTeamSettlement(item.id, 'RETURN', msg)
      : await reviewSettlement(item.id, 'RETURN', msg)
    onStatusChange?.(item.id, status)
    setShowReturnModal(false)
    onClose()
  }

  // F-2: 보완요청 사유는 별도 모달에서 (상세 모달은 잠시 숨김)
  if (showReturnModal && item) {
    return <ReturnReasonModal item={item} onClose={() => setShowReturnModal(false)} onSubmit={returnWithReason} />
  }

  const canSave = merchant.trim() !== '' && numOnly(amountText) > 0

  const footer = (
    <>
      {/* 팀 취합 뷰에선 취소 버튼을 두지 않는다(닫기는 우상단 X·Esc). 그 외 화면은 기존대로 취소/닫기 노출 */}
      {!isTeamView && (
        <button className="btn" onClick={onClose} disabled={pending}>{readOnly ? '닫기' : '취소'}</button>
      )}
      {isCreate ? (
        <button className="btn primary" onClick={save} disabled={pending || !canSave}>
          {pending ? '저장 중…' : '저장(등록)'}
        </button>
      ) : canTeamDecide ? (
        <>
          <button className="btn return" onClick={() => setShowReturnModal(true)} disabled={pending}>팀 보완요청</button>
          <button className="btn reject" onClick={teamReject} disabled={pending}>팀 반려</button>
          {/* 이상 건은 제출 불가 — 보완요청·반려로 처리 유도 */}
          <button
            className="btn primary"
            onClick={submit}
            disabled={pending || isAnomaly}
            title={isAnomaly ? '이상 건은 제출할 수 없습니다. 팀 보완요청·팀 반려로 처리하세요.' : undefined}
          >
            {isAnomaly ? '제출 불가 (이상 건)' : '제출(SUBMITTED)'}
          </button>
        </>
      ) : canReview ? (
        <>
          <button className="btn return" onClick={() => setShowReturnModal(true)} disabled={pending}>보완요청(RETURNED)</button>
          <button className="btn reject" onClick={reject} disabled={pending}>반려(REJECT)</button>
          {/* FR-ST-03: 확신 통과 건이라도 사람 확정 필수 */}
          <button className="btn approve" onClick={approve} disabled={pending}>승인 · 확정(CONFIRMED)</button>
        </>
      ) : isOwner ? (
        isDraft ? (
          <>
            {isMineView && (
              <button className="btn reject" onClick={remove} disabled={pending}>
                <Trash2 size={13} /> 삭제
              </button>
            )}
            <button className="btn primary" onClick={raise} disabled={pending}>팀에 올림</button>
          </>
        ) : (
          <>
            {isMineView && canDelete && (
              <button className="btn reject" onClick={remove} disabled={pending}>
                <Trash2 size={13} /> 삭제
              </button>
            )}
            <button
              className="btn primary"
              onClick={submit}
              disabled={pending || (isTeamView && isAnomaly)}
              title={isTeamView && isAnomaly ? '이상 건은 제출할 수 없습니다.' : undefined}
            >
              {isTeamView && isAnomaly ? '제출 불가 (이상 건)' : needsResubmit ? '보완 후 재제출' : '제출(SUBMITTED)'}
            </button>
          </>
        )
      ) : (
        <span className="text-meta row" style={{ gap: 6 }}><Lock size={12} /> 본인 건이 아니어 조회만 가능합니다.</span>
      )}
    </>
  )

  const auditTrail = item ? (item as ReviewItem).auditTrail : undefined
  const title = isCreate
    ? '신규 지출 등록'
    : `정산 상세${readOnly ? '' : ' · 수정'} · ${item!.id}`

  return (
    <Modal title={title} onClose={onClose} footer={footer} maxWidth={1040}>
      <div className="row" style={{ justifyContent: 'space-between', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 16, fontWeight: 700 }}>{merchant || (isCreate ? '신규 지출' : '—')}</div>
          <div className="text-meta">
            {dateStr} · {CARD_TYPE_LABEL[cardType]} 카드
            {!isCreate && item!.user ? ` · ${item!.user}` : ''}
            {readOnly ? ' · 조회 전용' : ''}
          </div>
        </div>
        {isCreate
          ? <span className="tag">신규 작성</span>
          : <StatusBadge status={item!.status} />}
      </div>

      <div className="grid-2">
        {/* ───────── 좌측: 영수증 + 추가증빙 + 상태변경이력 ───────── */}
        <div className="stack">
          {/* 영수증 (미리보기) */}
          <div className="card">
            <div className="card-head">
              <h3>영수증</h3>
              {receiptUp && <span className="tag ai"><Check size={11} /> Vision 판독</span>}
            </div>
            <div className="card-body">
              <div style={{
                height: 168, background: 'var(--surface-2)', borderRadius: 'var(--radius-control)',
                display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
                gap: 6, color: 'var(--muted)', border: '1px dashed var(--border-strong)',
              }}>
                {receiptUp
                  ? <><Receipt size={18} /> 영수증 미리보기</>
                  : <><AlertTriangle size={16} /> {readOnly ? '첨부된 영수증 없음' : '증빙 없음 — 업로드하거나 직접 기입'}</>}
              </div>
              {!readOnly && (
                <button className="btn primary" style={{ width: '100%', justifyContent: 'center', marginTop: 12 }} onClick={uploadReceipt} disabled={pending}>
                  <Upload size={14} /> {receiptUp ? '영수증 다시 업로드' : '영수증 업로드 (자동 분석)'}
                </button>
              )}
            </div>
          </div>

          {/* 추가 증빙 (미리보기 없음) */}
          <div className="card">
            <div className="card-head"><h3>추가 증빙 자료</h3><span className="text-meta">미리보기 없음</span></div>
            <div className="card-body">
              {!readOnly && (
                <button className="btn" style={{ width: '100%', justifyContent: 'center' }} onClick={uploadExtra} disabled={pending}>
                  <Paperclip size={14} /> 계약서·이체확인증 등 첨부
                </button>
              )}
              {extraFiles.length > 0 ? (
                <div className="stack" style={{ marginTop: readOnly ? 0 : 10 }}>
                  {extraFiles.map((f) => (
                    <div key={f.id} className="row" style={{ justifyContent: 'space-between', background: 'var(--surface-2)', borderRadius: 'var(--radius-control)', padding: '8px 10px' }}>
                      <div className="row" style={{ gap: 8 }}>
                        <FileText size={16} color="var(--tone-red)" />
                        <span style={{ fontSize: 12.5 }}>{f.name}</span>
                      </div>
                      {!readOnly && (
                        <button className="x-btn" style={{ width: 24, height: 24 }} aria-label="삭제" onClick={() => removeExtra(f.id)}>
                          <X size={13} />
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              ) : readOnly && <div className="text-meta">첨부된 추가 증빙이 없습니다.</div>}
            </div>
          </div>

          {/* 상태 변경 이력 (Audit Trail) */}
          <div className="card">
            <div className="card-head"><h3>상태 변경 이력</h3></div>
            <div className="card-body">
              {isCreate ? (
                <div className="text-meta">저장 후 이력이 기록됩니다.</div>
              ) : (
                <ul className="timeline">
                  {auditTrail?.map((ev, i) => (
                    <li key={i}>
                      <div style={{ fontSize: 13 }}>{ev.status}{ev.note ? ` — ${ev.note}` : ''}</div>
                      <div className="t-meta">{ev.actor} · {ev.timestamp}</div>
                    </li>
                  )) ?? (
                    <>
                      <li><div>DRAFT — 초안 자동생성</div><div className="t-meta">Draft Agent · {item!.date} 09:12</div></li>
                      <li><div>SUBMITTED — 제출</div><div className="t-meta">{item!.user} · 09:40</div></li>
                      <li><div>RPA_JUDGED — Rule Agent 판정</div><div className="t-meta">Rule Agent · 09:41</div></li>
                    </>
                  )}
                </ul>
              )}
            </div>
          </div>
        </div>

        {/* ───────── 우측: 기본내역 + 분류·사유 + fact.json + AI 코멘트 ───────── */}
        <div className="stack">
          <div className="card">
            <div className="card-head">
              <h3>기본 내역</h3>
              {!readOnly && <span className="tag ai"><Sparkles size={11} /> Draft Agent</span>}
            </div>
            <div className="card-body">
              {!readOnly && (
                <div className="row" style={{ gap: 6, marginBottom: 12 }}>
                  <input
                    value={instruction}
                    onChange={(e) => setInstruction(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') void askAgent() }}
                    placeholder="AI에게 지시 — 예) 분류는 접대로, 참석 6명, 사유 더 자세히"
                    style={{ flex: 1 }}
                    disabled={pending}
                  />
                  <button className="btn primary" onClick={() => void askAgent()} disabled={pending}>
                    <Sparkles size={13} /> {instruction.trim() ? 'AI로 수정' : 'AI로 생성'}
                  </button>
                </div>
              )}
              <div className="field"><label>가맹점</label>
                <input value={merchant} onChange={(e) => setMerchant(e.target.value)} placeholder="가맹점명" disabled={readOnly} />
              </div>
              <div className="grid-2" style={{ gap: 10 }}>
                <div className="field"><label>거래일자</label>
                  <input type="date" value={dateStr} onChange={(e) => setDateStr(e.target.value)} disabled={readOnly} />
                </div>
                <div className="field"><label>금액 (원)</label>
                  <input value={amountText} onChange={(e) => setAmountText(e.target.value)} placeholder="0" inputMode="numeric" disabled={readOnly} />
                </div>
              </div>
              <div className="grid-2" style={{ gap: 10 }}>
                <div className="field"><label>카드 구분</label>
                  <select value={cardType} onChange={(e) => setCardType(e.target.value as CardType)} disabled={readOnly}>
                    {Object.entries(CARD_TYPE_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </select>
                </div>
                <div className="field">
                  <label>비용 분류 {aiSuggested && <span className="tag ai">AI 제안</span>}</label>
                  <select value={category} onChange={(e) => setCategory(e.target.value as Category)} disabled={readOnly}>
                    {CATEGORIES.map((c) => <option key={c}>{c}</option>)}
                  </select>
                </div>
              </div>
              <div className="field" style={{ marginBottom: hints.length ? undefined : 0 }}><label>지출 목적 · 사유</label>
                <textarea rows={2} value={purpose} onChange={(e) => setPurpose(e.target.value)} placeholder="실사용자·목적·거래처 등 (AI 버튼으로 자동 보정 가능)" disabled={readOnly} />
              </div>
              {/* 제출 전 규정 안내 — 반려를 미리 막는다 */}
              {hints.length > 0 && (
                <div className="field" style={{ marginBottom: 0 }}>
                  <label>제출 전 규정 안내 {hints.filter((h) => h.level === 'warn').length > 0
                    && <span className="tag warn">확인 {hints.filter((h) => h.level === 'warn').length}건</span>}</label>
                  <div className="stack" style={{ gap: 6 }}>
                    {hints.map((hint, index) => (
                      <div key={index} style={{
                        padding: '8px 10px', borderRadius: 'var(--radius-control)', fontSize: 12.5, lineHeight: 1.6,
                        background: hint.level === 'warn' ? 'var(--tone-amber-bg)' : 'var(--surface-2)',
                        borderLeft: `3px solid ${hint.level === 'warn' ? 'var(--tone-amber)' : 'var(--border-strong)'}`,
                      }}>
                        <div className="row" style={{ gap: 6 }}>
                          <span className="tag">{hint.clause}</span>
                          <b style={{ fontSize: 12 }}>{hint.status}</b>
                        </div>
                        <div className="text-meta" style={{ marginTop: 3 }}>{hint.text}</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* fact.json — 자동생성, 접어두기 */}
          <div className="card">
            <button
              className="card-head"
              style={{ width: '100%', background: 'none', border: 'none', cursor: 'pointer' }}
              onClick={() => setFactOpen((v) => !v)}
            >
              <h3 style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                {factOpen ? <ChevronDown size={15} /> : <ChevronRight size={15} />} fact.json (자동 생성)
              </h3>
              <span className="text-meta">규정 판정 입력값</span>
            </button>
            {factOpen && (
              <div className="card-body">
                <pre style={{
                  margin: 0, fontSize: 12, lineHeight: 1.5, background: 'var(--surface-2)',
                  borderRadius: 'var(--radius-control)', padding: 12, overflowX: 'auto',
                }}>{JSON.stringify(fact, null, 2)}</pre>
              </div>
            )}
          </div>

          {/* AI 코멘트 로그 */}
          <div className="card">
            <div className="card-head"><h3>AI 코멘트</h3></div>
            <div className="card-body">
              {readOnly ? (
                <div className="text-meta">조회 전용 화면입니다. {canTeamDecide ? '팀 보완요청·팀 반려로 처리하세요.' : ''}</div>
              ) : comments.length === 0 ? (
                <div className="text-meta">영수증·증빙을 업로드하거나 AI 버튼을 누르면 무엇을 반영해 어디를 수정했는지 안내합니다.</div>
              ) : (
                <ul className="stack" style={{ gap: 8, listStyle: 'none', padding: 0, margin: 0 }}>
                  {comments.map((c, i) => (
                    <li key={i} className="row" style={{ gap: 8, alignItems: 'flex-start' }}>
                      <span className="tag ai" style={{ flexShrink: 0 }}>
                        {c.icon === 'ocr' ? <Receipt size={11} /> : c.icon === 'doc' ? <FileText size={11} /> : <Sparkles size={11} />}
                      </span>
                      <span style={{ fontSize: 12.5, lineHeight: 1.5 }}>{c.text}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </div>
      </div>
    </Modal>
  )
}

// S-06 정산 상세 · 수정 · 신규등록 통합 모달 — FR-DA-02~06, FR-ST-01~04, FR-AUD-01
//  item=null → 신규등록(빈 모달, 영수증 업로드 또는 직접 기입으로 생성)
//  item=Settlement → 상세보기 및 수정 (내 건이 아니면 조회 전용)
//  context='team' → 팀 취합 뷰: 팀장이 팀원 건을 팀 보완요청/팀 반려 처리
//  좌: 영수증/추가증빙 업로드 + 상태변경이력 / 우: 기본내역·분류·사유 + fact.json(자동생성) + AI 코멘트
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  AlertTriangle, Check, ChevronDown, ChevronRight, FileText, Lock,
  Receipt, Sparkles, Trash2, Upload,
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
  reviseDraft, submitSettlements, suggestDraft, updateSettlement,
  type DraftSuggestion, type PolicyHint,
} from '../../api/settlementService'
import { DecisionReasonModal } from './DecisionReasonModal'
import { EvidenceAttachments } from './EvidenceAttachments'
import { RuleJudgementPanel } from './RuleJudgementPanel'
import type { Attachment } from '../../api/attachmentService'
import { fetchMyCards, type CorpCard } from '../../api/cardService'

// 신규등록 시 영수증 Vision 판독을 흉내내는 mock 추출값 (백엔드 연동 전까지의 데모용)
const MOCK_OCR = { merchant: '강남 한식당', amount: '452,000', category: '접대' as Category }

interface AiComment { icon: 'ocr' | 'doc' | 'ai'; text: string }
interface ExtraFile { id: string; name: string }

const numOnly = (s: string) => Number(s.replace(/[^0-9]/g, '') || '0')
// 상태 변경 이력 타임라인 점 색 — 상태값을 매핑하지 않고 진행 단계를 순환색으로 표현(시안 실측: 회색→파랑→amber→빨강)
const TIMELINE_TONES = ['gray', 'blue', 'amber', 'red']

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
  //  카드는 **구분이 아니라 실물**을 고른다. 예전엔 구분(개인/팀/공용)만 골랐고 서버가
  //  그 구분의 아무 카드나 붙여서, 남의 개인카드가 내 지출에 붙을 수 있었다.
  const [cardId, setCardId] = useState<number | null>(item?.cardId ?? null)
  const [myCards, setMyCards] = useState<CorpCard[]>([])
  const [cardsLoaded, setCardsLoaded] = useState(false)
  //  카드 구분은 이제 **선택한 카드에서 따라온다**(초안 요청·표시에 쓰인다).
  const selectedCard = myCards.find((c) => c.id === cardId)
  const cardType = (selectedCard?.type ?? item?.cardType ?? 'PERSONAL') as CardType
  // 사람이 확정한 분류(`category`)가 있으면 그게 먼저다. 없으면 AI 제안을 미리 채워
  //  두고, 사용자가 그대로 제출하면 그 순간 확정값이 된다(`persistEdits`).
  const [category, setCategory] = useState<Category>(item?.category ?? item?.aiCategory ?? '접대')
  const [purpose, setPurpose] = useState(item?.purpose ?? '')
  const [aiSuggested, setAiSuggested] = useState(item?.aiSuggested ?? false)
  // 가맹점 업종 — 사람이 고르는 값이 아니라 **서버가 조회해 준 사실**이라 입력칸이 없다.
  //  화면이 들고 있다가 저장 때 같이 올린다(안 올리면 판정이 쓸 업종이 통째로 비어 버린다).
  const [industry, setIndustry] = useState(item?.merchantIndustry ?? '')
  const [industryCode, setIndustryCode] = useState(item?.merchantIndustryCode ?? '')

  // ── 좌측 업로드 상태 ──
  const [receiptUp, setReceiptUp] = useState(item?.evidence === 'OK')
  const [extraFiles, setExtraFiles] = useState<ExtraFile[]>([])

  // ── AI 코멘트 로그 / 규정 힌트 / 지시 입력 / fact.json 접힘 ──
  const [comments, setComments] = useState<AiComment[]>([])
  const [hints, setHints] = useState<PolicyHint[]>([])
  const [instruction, setInstruction] = useState('')
  // 신규 등록(F-1) 시안은 방금 생성된 fact.json을 펼쳐서 보여준다 — 기존 건 조회는 접어둔 채 시작.
  const [factOpen, setFactOpen] = useState(isCreate)

  const [pending, setPending] = useState(false)
  //  결정은 **항상 사유 모달을 거친다** — 팀 반려가 확인 없이 바로 나가던 것도 여기로 합쳤다.
  const [decisionTarget, setDecisionTarget] = useState<'RETURN' | 'REJECT' | null>(null)

  const evidence: 'OK' | 'MISSING' = receiptUp || extraFiles.length > 0 ? 'OK' : 'MISSING'
  const needsResubmit = isOwner && !canReview && !isCreate && item?.status === 'RETURNED'
  const isDraft = !isCreate && item?.status === 'DRAFT' // 개인 보유 → 팀 취합으로 '올림' 대상
  // 삭제는 아직 팀·회계 단계로 넘어가지 않은 건만 (백엔드도 같은 기준으로 막는다)
  const canDelete = !isCreate && ['DRAFT', 'TEAM_RETURNED', 'TEAM_REJECTED'].includes(item?.status ?? '')
  // 이상 건(보완요청·반려 판정)은 팀 취합 뷰에서 제출 불가 — 보완요청·반려로만 처리한다.
  //  검토(REVIEW)로 갈 건은 이상 건이 아니다(회계가 볼 일이라 팀은 그대로 올려보낸다).
  const isAnomaly = !isCreate && item ? needsAttention(item) : false

  // fact.json — 현재 입력값으로 자동 생성(자동생성/자동갱신)
  const fact = useMemo(() => ({
    merchant: merchant || null,
    amount: numOnly(amountText),
    date: dateStr,
    cardType,
    category,
    merchantIndustry: industry || null,
    evidence: evidence === 'OK' ? 'attached' : 'missing',
    extraDocs: extraFiles.length,
    purpose: purpose || null,
    source: receiptUp ? 'vision_ocr' : 'manual',
    aiSuggested,
  }), [merchant, amountText, dateStr, cardType, category, industry, evidence, extraFiles.length, purpose, receiptUp, aiSuggested])

  //  카드 목록은 모달이 열릴 때 한 번. 조회 전용(남의 건)이면 고칠 일이 없어 부르지 않는다.
  useEffect(() => {
    if (readOnly) { setCardsLoaded(true); return }
    let alive = true
    void (async () => {
      try {
        const cards = await fetchMyCards()
        if (!alive) return
        setMyCards(cards)
        //  이미 붙은 카드가 목록에 없으면(배정이 바뀌었거나 정지됨) 비워 둔다 —
        //  임의로 다른 카드를 고르면 판정 사실이 조용히 바뀐다.
        setCardId((prev) => (prev && cards.some((c) => c.id === prev) ? prev : cards[0]?.id ?? null))
      } catch { /* 목록을 못 받아도 나머지 입력은 계속 쓸 수 있어야 한다 */ }
      finally { if (alive) setCardsLoaded(true) }
    })()
    return () => { alive = false }
  }, [readOnly])

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
    if (d.merchantIndustry !== undefined) setIndustry(String(d.merchantIndustry ?? ''))
    if (d.merchantIndustryCode !== undefined) setIndustryCode(String(d.merchantIndustryCode ?? ''))
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
          merchantIndustry: industry, merchantIndustryCode: industryCode,
          purpose, evidence, headcount: 0,
        })
      : await suggestDraft({ merchant, amount: numOnly(amountText), date: dateStr, cardType, evidence })
    setPending(false)
    if (!result) { pushComment({ icon: 'ai', text: 'AI 초안 생성에 실패했습니다. Core API 연결을 확인해주세요.' }); return }
    applyDraft(result)
    setInstruction('')
  }

  // 첨부 판독이 끝나면 AI 코멘트로 알린다. **문구를 지어내지 않는다** — 서버가 실제로
  // 읽어낸 사실 개수만 말한다(예전엔 업로드하는 순간 "인식했습니다"를 찍어 놓고
  // 아무것도 읽지 않았다).
  const onFactsExtracted = useCallback((a: Attachment) => {
    const n = Object.keys(a.extracted ?? {}).length
    setExtraFiles((prev) => (prev.some((f) => f.id === String(a.id)) ? prev : [...prev, { id: String(a.id), name: a.originalName }]))
    setComments((prev) => [...prev, {
      icon: 'doc',
      text: n > 0
        ? `증빙 문서 "${a.originalName}" 판독 완료 — 판정 사실 ${n}건을 확인했습니다.`
        : `증빙 문서 "${a.originalName}"을 판독했지만 확인된 판정 사실이 없습니다.`,
    }])
  }, [])


  const draft = (): Omit<Settlement, 'id' | 'status'> => ({
    date: dateStr,
    merchant: merchant || '미상 가맹점',
    amount: numOnly(amountText),
    cardType,
    cardId,
    // 화면 드롭다운 값은 **사람이 확정한 분류**다. `aiCategory`는 AI가 원래 뭐라고 했는지를
    // 남기는 자리라 여기서 덮어쓰지 않는다 — 서버가 확정값이 없으면 제안을 받아 채운다.
    category,
    aiCategory: item?.aiCategory ?? category,
    aiSuggested,
    evidence,
    user: user?.name ?? '나',
    purpose: purpose || undefined,
    merchantIndustry: industry || undefined,
    merchantIndustryCode: industryCode || undefined,
  })

  /**
   * 상태 전이 **전에** 화면 값을 저장한다.
   *
   * 이게 없던 동안 "수정하고 제출"이 통째로 유실됐다 — 모달 제목은 '수정'인데 저장 경로가
   * 없어서, 분류를 고르고 목적을 적어 제출해도 서버는 옛 값 그대로였고 판정이
   * 「분류 미기재」로 걸었다. 사람이 확인하고 올린 값이 판정에 닿지 않으면 확인이 무의미하다.
   *
   * 조회 전용(남의 건)일 땐 건너뛴다 — 팀장이 팀원 건을 제출할 때 남의 입력을 덮어쓰면 안 된다.
   */
  const persistEdits = async (): Promise<boolean> => {
    if (!item || readOnly) return true
    try {
      await updateSettlement(item.id, {
        category,
        purpose: purpose || '',
        merchantIndustry: industry || '',
        merchantIndustryCode: industryCode || '',
        merchant: merchant || undefined,
        amount: numOnly(amountText) || undefined,
        date: dateStr,
        cardId: cardId ?? undefined,
      })
      return true
    } catch (e: unknown) {
      // 저장 실패를 삼키면 "제출했는데 옛 값으로 판정된" 상황이 조용히 재현된다.
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      pushComment({ icon: 'ai', text: `수정 사항을 저장하지 못해 제출을 멈췄습니다 — ${detail ?? '서버 오류'}` })
      return false
    }
  }

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
    if (!await persistEdits()) { setPending(false); return }
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
    if (!await persistEdits()) { setPending(false); return }
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

  /**
   * 보완요청·반려 사유 확정. **팀 취합 뷰면 팀 결정**(TEAM_RETURNED/TEAM_REJECTED),
   * 그 외(회계 검토)면 회계 결정(RETURNED/REJECT)이다.
   *
   * 예전엔 실패가 통째로 삼켜져 **버튼이 죽은 것처럼** 보였다 — 팀 뷰에서 본인 건을 열면
   * `canTeamDecide`가 false가 되어 회계 API(`reviewSettlement`)로 나갔고, 권한이 없어
   * 403이 나도 화면엔 아무 일도 일어나지 않았다. 이제 사유를 그대로 보여준다.
   */
  const decideWithReason = async (reason: string, detail: string) => {
    if (!item || !decisionTarget) return
    const msg = [reason, detail].filter(Boolean).join(' — ')
    setPending(true)
    try {
      const status = isTeamView
        ? await decideTeamSettlement(item.id, decisionTarget, msg)
        : await reviewSettlement(item.id, decisionTarget, msg)
      onStatusChange?.(item.id, status)
      setDecisionTarget(null)
      onClose()
    } catch (e: unknown) {
      const detailMsg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      window.alert(detailMsg ?? '처리에 실패했습니다.')
    } finally {
      setPending(false)
    }
  }

  // F-2: 사유는 별도 모달에서 (상세 모달은 잠시 숨김)
  if (decisionTarget && item) {
    return (
      <DecisionReasonModal
        item={item}
        decision={decisionTarget}
        busy={pending}
        onClose={() => setDecisionTarget(null)}
        onConfirm={decideWithReason}
      />
    )
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
        /* 팀 취합 — 목록 행과 **같은 버튼 세트**다(화면마다 눌러야 할 자리가 다르면 안 된다).
           제출은 사유 없이 바로 회계로 올리고, 보완·반려는 사유 모달을 거친다. */
        <>
          <button className="btn return" onClick={() => setDecisionTarget('RETURN')} disabled={pending}>보완요청</button>
          <button className="btn reject" onClick={() => setDecisionTarget('REJECT')} disabled={pending}>반려</button>
          <button
            className="btn primary"
            onClick={submit}
            disabled={pending || isAnomaly}
            title={isAnomaly ? '이상 건은 제출할 수 없습니다. 보완요청·반려로 처리하세요.' : undefined}
          >
            {isAnomaly ? '제출 불가 (이상 건)' : '제출'}
          </button>
        </>
      ) : canReview && !isTeamView ? (
        /* 회계 검토 — 여기의 「승인」은 회계 담당자 본인의 결정(→ 승인대기)이다.
           팀 취합 뷰에서는 이 세트를 절대 띄우지 않는다(팀장이 회계 결정을 내리게 된다). */
        <>
          <button className="btn return" onClick={() => setDecisionTarget('RETURN')} disabled={pending}>보완요청(RETURNED)</button>
          <button className="btn reject" onClick={() => setDecisionTarget('REJECT')} disabled={pending}>반려(REJECT)</button>
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
    <Modal title={title} onClose={onClose} footer={footer} maxWidth={1040} dark>
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
              {receiptUp && <span className="tag ok"><Check size={11} /> Vision 판독</span>}
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

          {/* 증빙 첨부 + 판독 — 업로드가 곧 판독 트리거다(서버가 비전 판독을 돌린다). */}
          <EvidenceAttachments
            settlementId={item?.id ?? null}
            readOnly={readOnly}
            onFactsExtracted={onFactsExtracted}
          />

          {/* 상태 변경 이력 (Audit Trail) */}
          <div className="card">
            <div className="card-head"><h3>상태 변경 이력</h3></div>
            <div className="card-body">
              {isCreate ? (
                <div className="text-meta">저장 후 이력이 기록됩니다.</div>
              ) : (
                <ul className="timeline">
                  {auditTrail?.map((ev, i) => (
                    <li key={i} className={TIMELINE_TONES[i % TIMELINE_TONES.length]}>
                      <div style={{ fontSize: 13 }}>{ev.status}{ev.note ? ` — ${ev.note}` : ''}</div>
                      <div className="t-meta">{ev.actor} · {ev.timestamp}</div>
                    </li>
                  )) ?? (
                    <>
                      <li className="gray"><div>DRAFT — 초안 자동생성</div><div className="t-meta">Draft Agent · {item!.date} 09:12</div></li>
                      <li className="blue"><div>SUBMITTED — 제출</div><div className="t-meta">{item!.user} · 09:40</div></li>
                      <li className="amber"><div>RPA_JUDGED — Rule Agent 판정</div><div className="t-meta">Rule Agent · 09:41</div></li>
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
                <div className="field"><label>사용 카드</label>
                  {readOnly ? (
                    <input value={item?.cardName ?? CARD_TYPE_LABEL[cardType]} readOnly disabled />
                  ) : (
                    <select
                      value={cardId ?? ''}
                      onChange={(e) => setCardId(e.target.value ? Number(e.target.value) : null)}
                      disabled={!cardsLoaded || myCards.length === 0}
                    >
                      {/* 배정된 카드가 없으면 목록을 비워 두고 사유를 말한다 — 빈 드롭다운만
                          남으면 사용자는 "왜 못 고르지"를 알 수 없다. */}
                      {myCards.length === 0 && (
                        <option value="">{cardsLoaded ? '배정된 카드가 없습니다' : '불러오는 중…'}</option>
                      )}
                      {myCards.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.typeLabel} · {c.name || c.number || `카드 ${c.id}`}
                          {c.number && c.name ? ` (${c.number})` : ''}
                        </option>
                      ))}
                    </select>
                  )}
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
                        background: hint.level === 'warn' ? 'var(--tone-amber-bg)' : 'var(--primary-soft)',
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

          {/* 룰 엔진 판정 — fact.json이 "무엇을 입력했나"라면 여기는 "그래서 어떻게 판정됐나"다.
              신규 등록 중에는 판정 대상 자체가 없으므로 저장 후부터 보인다. */}
          {!isCreate && item && <RuleJudgementPanel item={item} />}

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

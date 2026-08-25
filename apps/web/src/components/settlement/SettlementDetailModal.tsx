// S-06 정산 상세 · 수정 · 신규등록 통합 모달 — FR-DA-02~06, FR-ST-01~04, FR-AUD-01
//  item=null → 신규등록(빈 모달, 영수증 업로드 또는 직접 기입으로 생성)
//  item=Settlement → 상세보기 및 수정 (내 건이 아니면 조회 전용)
//  context='team' → 팀 취합 뷰: 팀장이 팀원 건을 팀 보완요청/팀 반려 처리
//  좌: 영수증/추가증빙 업로드 + 상태변경이력 / 우: 기본내역·분류·사유 + fact.json(자동생성) + AI 코멘트
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  AlertTriangle, Check, ChevronDown, ChevronRight, Lock,
  Loader2, Receipt, Trash2, Upload, Wand2,
} from 'lucide-react'
import {
  CARD_TYPE_LABEL, CATEGORY_UNSET, DONE_STATUSES, EDITABLE_STATUSES, STATUS_META,
  SUBMITTABLE_STATUSES,
  type CardType, type Category, type Settlement, type SettlementStatus,
} from '../../types/domain'
import { useCategories } from '../../lib/categories'
import { needsAttention } from '../../lib/judgement'
import { Modal } from '../ui/Modal'
import { StatusBadge } from '../ui/StatusBadge'
import { useCan } from '../../lib/capabilities'
import { todayISO } from '../../lib/period'
import { useAuth } from '../../context/AuthContext'
import {
  createSettlement, decideTeamSettlement, deleteSettlement, draftForSettlement,
  prepareSubmit, raiseSettlements, reviewSettlement, submitSettlements, updateSettlement,
  type DraftNotice, type JudgementPreview,
  type SubmitPreparation,
} from '../../api/settlementService'
import { AgentPanel } from './AgentPanel'
import { SubmitConfirmModal } from './SubmitConfirmModal'
import { DecisionReasonModal } from './DecisionReasonModal'
import { EvidenceAttachments } from './EvidenceAttachments'
import { RuleJudgementPanel } from './RuleJudgementPanel'
import type { Attachment } from '../../api/attachmentService'
import { fetchMyCards, type CorpCard } from '../../api/cardService'

interface AiComment { icon: 'ocr' | 'doc' | 'ai'; text: string }
interface ExtraFile { id: string; name: string }

const numOnly = (s: string) => Number(s.replace(/[^0-9]/g, '') || '0')
// 상태 변경 이력 타임라인 점 색 — 상태값을 매핑하지 않고 진행 단계를 순환색으로 표현(시안 실측: 회색→파랑→amber→빨강)
const TIMELINE_TONES = ['gray', 'blue', 'amber', 'red']

/** 이력 시각 — 오늘이면 시:분, 아니면 날짜까지. 잘못된 값은 원문을 그대로 보여준다. */
function fmtEventTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const today = new Date()
  const sameDay = d.toDateString() === today.toDateString()
  const hm = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  return sameDay ? hm : `${d.getMonth() + 1}/${d.getDate()} ${hm}`
}

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
  /**
   * 조회 전용 여부 — **소유권과 상태, 두 축이 모두 통과해야 고칠 수 있다.**
   *
   * 예전엔 소유권만 봤다. 그래서 내 지출에서 확정(`CONFIRMED`)·검토중(`IN_REVIEW`) 건을
   * 열면 입력칸이 전부 활성이고 「제출」 버튼까지 떴다 — 서버가 400으로 막으니 데이터는
   * 멀쩡했지만, **고칠 수 있는 것처럼 보여주고 눌러야 실패를 알려주는** 화면이었다.
   */
  const statusEditable = isCreate || EDITABLE_STATUSES.includes(item!.status)
  const readOnly = !isCreate && (!isOwner || !statusEditable)
  //  왜 잠겼는지는 서로 다르다 — 안내 문구도 달라야 한다.
  //  **종결된 건에 "보완요청을 받으면 고칠 수 있습니다"라고 쓰면 안 된다** — 그 일은
  //  일어나지 않는다(`REJECT`·`TEAM_REJECTED`는 재제출 불가 단말). 기다리면 풀리는
  //  잠금과 영영 안 풀리는 잠금을 같은 문장으로 덮으면 사용자는 계속 기다린다.
  const lockNote = !isOwner
    ? (canTeamDecide
        ? '조회 전용 화면입니다. 팀 보완요청·팀 반려로 처리하세요.'
        : '본인이 등록한 건이 아니어 조회만 가능합니다.')
    : item?.status === 'TEAM_COLLECTING'
      ? '팀에 올린 뒤라 수정할 수 없습니다. 팀장이 보완요청으로 돌려보내면 고칠 수 있습니다.'
      : item?.status === 'TEAM_REJECTED'
        ? '팀에서 반려된 건이라 종결되었습니다. 다시 올릴 수 없으니 필요하면 새로 등록해 주세요.'
        : item?.status === 'REJECT'
          ? '회계에서 최종 반려된 건이라 종결되었습니다. 재제출할 수 없습니다.'
          : DONE_STATUSES.includes(item!.status)
            ? '확정된 건이라 수정할 수 없습니다.'
            : '회계로 넘어간 뒤라 수정할 수 없습니다. 보완요청을 받으면 고칠 수 있습니다.'

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
  //  **둘 다 없으면 비워 둔다** — 예전엔 '접대'로 떨어뜨렸는데, 아무도 고르지 않은 건이
  //  화면에는 접대로 보이고 제출하면 그대로 접대로 확정됐다(판정은 「분류 미기재」로 걸고
  //  있었으니 화면과 판정이 서로 다른 사실을 말한 셈이다).
  const [category, setCategory] = useState<Category>(item?.category ?? item?.aiCategory ?? CATEGORY_UNSET)
  //  드롭다운 목록은 서버 어휘를 쓴다(`GET /api/meta/categories/`) — 화면 상수로 두면
  //  분류가 늘어도 여기서만 안 보인다.
  const { categories } = useCategories()
  //  **영수증을 요구할지는 유래가 정한다.** 화면 등록은 파일이 필수지만(서버가 400),
  //  카드사 원장에서 수집한 건은 애초에 파일이 없다 — 같은 자리에 「필수」를 띄우면
  //  사용자가 고칠 수 없는 것을 고치라고 요구하는 셈이다.
  const fromErp = item?.origin === 'ERP'
  //  **거래 내역은 원장이 정본이다** — 가맹점·금액·일자·카드는 카드사 결제기록이라
  //  우리가 정정할 대상이 아니다(서버도 400으로 막는다). 분류·목적처럼 사람이 채우는
  //  값은 그대로 고칠 수 있다. 화면만 막고 서버를 안 막으면 요청을 손댄 값이 들어간다.
  const txLocked = readOnly || fromErp
  const [purpose, setPurpose] = useState(item?.purpose ?? '')
  //  참석 인원 — **빈 문자열은 「모름」이고 0은 「확인했더니 없음」이다**(서버 계약).
  //  숫자 state로 두면 그 구분이 사라져 안 적은 건이 "인원 0명"으로 단정된다.
  //  이 값이 없으면 1인당 환산액(`tx.per_person_amount`)이 아예 만들어지지 않아
  //  1인당 한도 룰이 전건 미해소로 강등된다 — 입력칸이 없던 시절의 실제 증상이다.
  const [headcount, setHeadcount] = useState(
    item?.headcount === null || item?.headcount === undefined ? '' : String(item.headcount),
  )
  const [aiSuggested, setAiSuggested] = useState(item?.aiSuggested ?? false)
  // 가맹점 업종 — 사람이 고르는 값이 아니라 **서버가 조회해 준 사실**이라 입력칸이 없다.
  //  화면이 들고 있다가 저장 때 같이 올린다(안 올리면 판정이 쓸 업종이 통째로 비어 버린다).
  const [industry, setIndustry] = useState(item?.merchantIndustry ?? '')
  const [industryCode, setIndustryCode] = useState(item?.merchantIndustryCode ?? '')

  // ── 좌측 업로드 상태 ──
  const [receiptUp, setReceiptUp] = useState(item?.evidence === 'OK')
  //  신규 등록은 정산 id가 없어 첨부 API를 못 쓴다 — 저장 요청에 함께 보낼 파일을 들고 있는다.
  const [receiptFile, setReceiptFile] = useState<File | null>(null)
  const receiptRef = useRef<HTMLInputElement>(null)
  const [extraFiles, setExtraFiles] = useState<ExtraFile[]>([])

  // ── AI 코멘트 로그 / 규정 힌트 / 지시 입력 / fact.json 접힘 ──
  const [comments, setComments] = useState<AiComment[]>([])
  // 신규 등록(F-1) 시안은 방금 생성된 fact.json을 펼쳐서 보여준다 — 기존 건 조회는 접어둔 채 시작.
  const [factOpen, setFactOpen] = useState(isCreate)

  // ── 신규 등록: **저장 먼저 → 비전 판독 → 초안** ─────────────────────
  //  예전엔 저장 전에 폼 값으로 초안을 만들었다. 그러면 모델이 보는 건 사람이 타이핑한
  //  값뿐이라 「비전이 기본 내역을 채운다」가 성립하지 않는다. 지금은 파일을 고르는 순간
  //  DRAFT로 저장하고(첨부 판독이 그 자리에서 예약된다), 판독이 끝나면 그 사실로 초안을 쓴다.
  const [createdId, setCreatedId] = useState<string | null>(null)
  /** 저장 이후에는 이 id로 첨부·초안·제출이 돈다. */
  const workingId = item?.id ?? createdId
  //  Agent가 무엇을 하고 있는지 **단계로** 보여준다 — 스피너만 돌리면 수십 초 동안
  //  멈춘 것처럼 보인다(비전 판독은 실제로 오래 걸린다).
  const [agentPhase, setAgentPhase] = useState<'' | 'saving' | 'reading' | 'drafting'>('')
  const [agentError, setAgentError] = useState('')
  const [reasoning, setReasoning] = useState('')
  const [notices, setNotices] = useState<DraftNotice[]>([])
  const [judgement, setJudgement] = useState<JudgementPreview | null>(null)
  //  제출 전 확인 — 서버가 `shouldConfirm`을 준 경우에만 뜬다.
  const [submitPrep, setSubmitPrep] = useState<SubmitPreparation | null>(null)
  const submitAfterConfirm = useRef<null | (() => Promise<void>)>(null)

  const [pending, setPending] = useState(false)
  //  결정은 **항상 사유 모달을 거친다** — 팀 반려가 확인 없이 바로 나가던 것도 여기로 합쳤다.
  const [decisionTarget, setDecisionTarget] = useState<'RETURN' | 'REJECT' | null>(null)

  const evidence: 'OK' | 'MISSING' = receiptUp || extraFiles.length > 0 ? 'OK' : 'MISSING'
  const needsResubmit = isOwner && !canReview && !isCreate && item?.status === 'RETURNED'
  //  「팀에 올림」 대상 — 개인 보유와 **팀 보완요청**(고쳐서 다시 올린다).
  //  회계 보완요청(`RETURNED → SUBMITTED` 재제출)과 같은 모양이다.
  const canRaise = !isCreate && ['DRAFT', 'TEAM_RETURNED'].includes(item!.status)
  const isTeamReturned = !isCreate && item!.status === 'TEAM_RETURNED'
  //  「제출」은 **서버가 그 전이를 허용하는 상태에서만** 띄운다(`services.ALLOWED`의 거울).
  //  예전엔 DRAFT가 아닌 모든 소유 건에 떠서, 확정·반려된 건에도 제출 버튼이 있었다.
  const canSubmit = !isCreate && SUBMITTABLE_STATUSES.includes(item!.status)
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

  /**
   * 영수증 **파일**을 고르면 그 자리에서 저장한다(신규 등록).
   *
   * 여기가 이 화면의 핵심 변경점이다. 예전 순서는 「사람이 가맹점·금액을 친다 → 폼 값으로
   * 초안 → 저장」이었고, 그러면 모델이 보는 건 사람이 타이핑한 값뿐이라 **영수증은 초안에
   * 아무 영향도 주지 못했다**(판독은 저장 후에야 돌고, 저장하면 모달이 닫혔다).
   *
   * 지금은 「파일 → 저장(DRAFT) → 서버가 판독 → 판독한 사실로 초안」이다. 사용자는
   * 파일 하나만 고르면 되고, 가맹점·금액은 **비전이 채운다**(`evidence_extract`가 거래
   * 원장에 반영한다 — 사람이 직접 친 값은 덮지 않는다).
   *
   * 저장을 되돌리는 「취소」는 두지 않는다 — 파일을 고른 시점에 이미 건이 생겼으므로,
   * 없애려면 「삭제」가 맞다(그게 실제로 일어나는 일이다).
   */
  const pickReceipt = async (file: File | undefined) => {
    if (!file || createdId) return
    setReceiptFile(file)
    setReceiptUp(true)
    setAgentError('')
    setAgentPhase('saving')
    try {
      //  가맹점·금액을 **보내지 않는다**. 서버가 `basicsPending`으로 표시해 두고,
      //  영수증 판독이 읽은 값으로 채운다. 사람이 미리 친 값이 있으면 그건 그대로 존중된다.
      const created = await createSettlement(draft(), file)
      setCreatedId(created.id)
      onCreated?.(created)
      setAgentPhase('reading')
      pushComment({ icon: 'ocr', text: `영수증 "${file.name}"을 올렸습니다. 판독이 끝나면 초안을 작성합니다.` })
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setAgentPhase('')
      setAgentError(detail ?? '저장하지 못했습니다.')
      setReceiptFile(null)
      setReceiptUp(false)
    }
  }

  /**
   * 저장된 건의 사실로 초안을 만든다(분류·목적·설명·안내).
   *
   * **폴백을 두지 않는다.** 사실 조회가 실패했는데 폼 값으로 그럴듯한 초안을 만들면
   * 사용자는 그걸 성공으로 읽는다 — 이 흐름이 없애려던 상태로 되돌아간다.
   */
  const runSettlementDraft = useCallback(async (id: string, instruction = '') => {
    setAgentPhase('drafting')
    setAgentError('')
    //  **교체 대상은 시작할 때 비운다.** 실패하면 `catch`가 사유만 세우는데, 그때 옛
    //  안내가 남아 있으면 「이미 고친 문제」를 계속 지적하고 오류와 나란히 떠서 어느
    //  쪽이 지금 상태인지 알 수 없다. 누적 로그(`comments`)는 그대로 둔다 — 그건
    //  일어난 일이라 지우면 안 된다.
    setReasoning('')
    setNotices([])
    setJudgement(null)
    try {
      const result = await draftForSettlement(id, instruction)
      const d = result.draft
      if (d.merchant) setMerchant(String(d.merchant))
      if (d.amount) setAmountText(String(d.amount))
      if (d.date) setDateStr(String(d.date))
      if (d.industry !== undefined) setIndustry(String(d.industry ?? ''))
      if (d.industryCode !== undefined) setIndustryCode(String(d.industryCode ?? ''))
      //  분류를 비워 보내면(판단 불가) 덮지 않는다 — 「선택 필요」로 남아 사람이 고른다.
      if (d.category) { setCategory(String(d.category)); setAiSuggested(true) }
      if (d.purpose) setPurpose(String(d.purpose))
      setReasoning(result.reasoning ?? '')
      setNotices(result.notices ?? [])
      setJudgement(result.judgement ?? null)
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setAgentError(detail ?? '초안을 만들지 못했습니다 — 분류와 목적을 직접 입력해 주세요.')
    } finally {
      setAgentPhase('')
    }
  }, [])

  // 첨부 판독이 끝나면 AI 코멘트로 알린다. **문구를 지어내지 않는다** — 서버가 실제로
  // 읽어낸 사실 개수만 말한다(예전엔 업로드하는 순간 "인식했습니다"를 찍어 놓고
  // 아무것도 읽지 않았다).
  const onFactsExtracted = useCallback((a: Attachment) => {
    const n = Object.keys(a.extracted ?? {}).length
    setExtraFiles((prev) => (prev.some((f) => f.id === String(a.id)) ? prev : [...prev, { id: String(a.id), name: a.originalName }]))
    setComments((prev) => [...prev, {
      icon: 'doc',
      text: a.extractionStatus === 'FAILED'
        ? `증빙 문서 "${a.originalName}" 판독에 실패했습니다 — 사실 없이 초안을 씁니다.`
        : n > 0
          ? `증빙 문서 "${a.originalName}" 판독 완료 — 판정 사실 ${n}건을 확인했습니다.`
          : `증빙 문서 "${a.originalName}"을 판독했지만 확인된 판정 사실이 없습니다.`,
    }])

    //  **판독이 끝나면 초안을 (다시) 쓴다.** 추가 증빙이 붙으면 판정 사실이 늘어나므로
    //  분류·목적·안내가 달라질 수 있다 — 사람이 별도 버튼을 눌러야 하면 아무도 안 누른다.
    //  실패도 트리거다(무한정 기다리지 않는다). 진행 중이면 겹쳐 부르지 않는다.
    const id = itemIdRef.current
    if (!id || agentPhaseRef.current === 'drafting') return
    void runSettlementDraft(id)
  }, [runSettlementDraft])

  //  콜백이 매번 새로 만들어지면 `EvidenceAttachments`의 폴링 이펙트가 재시작된다 —
  //  최신 값은 ref로 읽고 콜백 자체는 고정한다.
  const itemIdRef = useRef<string | null>(null)
  const agentPhaseRef = useRef(agentPhase)
  useEffect(() => { itemIdRef.current = workingId ?? null }, [workingId])
  useEffect(() => { agentPhaseRef.current = agentPhase }, [agentPhase])


  const draft = (): Omit<Settlement, 'id' | 'status'> => ({
    date: dateStr,
    //  **빈 값을 그대로 보낸다.** 예전엔 여기서 '미상 가맹점'을 채워 보냈는데, 서버는
    //  그걸 「사람이 친 값」으로 보고 영수증 판독이 채워도 되는 자리인지 판단할 근거를
    //  잃는다(`basicsPending`). 플레이스홀더는 서버가 정한다.
    merchant,
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
    if (!workingId || readOnly) return true
    const payload: Record<string, unknown> = {
      category,
      purpose: purpose || '',
      merchantIndustry: industry || '',
      merchantIndustryCode: industryCode || '',
      //  비었으면 `null`(모름)을 명시적으로 보낸다 — 키를 빼면 서버가 옛 값을 유지하므로
      //  사용자가 지운 것이 반영되지 않는다.
      headcount: headcount.trim() === '' ? null : Number(headcount),
    }
    //  **잠근 필드는 보내지도 않는다.** 화면에서 입력칸만 잠그고 값은 그대로 실어 보낸
    //  탓에, 원장 수집 건은 아무것도 안 고쳤는데 서버가 400으로 거절했고 「팀에 올림」이
    //  통째로 막혔다(실측 2026-08-24). 서버는 `key in body`만 보므로, 안 고칠 것은
    //  키 자체를 빼는 것이 유일하게 맞는 표현이다.
    if (!fromErp) {
      payload.merchant = merchant || undefined
      payload.amount = numOnly(amountText) || undefined
      payload.date = dateStr
      payload.cardId = cardId ?? undefined
    }
    try {
      await updateSettlement(workingId, payload)
      return true
    } catch (e: unknown) {
      // 저장 실패를 삼키면 "제출했는데 옛 값으로 판정된" 상황이 조용히 재현된다.
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      pushComment({ icon: 'ai', text: `수정 사항을 저장하지 못해 제출을 멈췄습니다 — ${detail ?? '서버 오류'}` })
      return false
    }
  }

  // '내 지출' 삭제 — 아직 팀·회계로 넘어가지 않은 건만.
  //  신규 등록에서 「취소」를 대신하는 자리이기도 하다 — 영수증을 고른 시점에 이미
  //  건이 생겼으므로, 없애는 동작의 정확한 이름은 취소가 아니라 삭제다.
  const remove = async () => {
    if (!workingId) return
    const label = merchant || item?.merchant || '이'
    if (!window.confirm(`“${label}” 지출 건을 삭제합니다. 되돌릴 수 없습니다. 계속할까요?`)) return
    setPending(true)
    const ok = await deleteSettlement(workingId)
    setPending(false)
    if (!ok) { window.alert('이미 팀·회계로 넘어간 건은 삭제할 수 없습니다.'); return }
    onDeleted?.(workingId)
    onClose()
  }

  // 개인 '올림' (DRAFT → TEAM_COLLECTING). 1인 팀도 팀 취합 단계를 거친다.
  /**
   * 올림·제출 공통 전처리 — **저장 → 문체 다듬기 → 판정 미리보기**.
   *
   * 기본 동작은 「조용히 다듬어 그대로 진행」이다. 서버가 `shouldConfirm`을 참으로 준
   * 경우에만 팝업을 띄우고, 그 기준은 서버가 소유한다(화면이 갖고 있으면 곧 갈린다).
   *
   * 준비 호출이 실패해도 진행을 막지 않는다 — 다듬기는 편의 기능이다.
   *
   * @returns 계속 진행해도 되면 true, 팝업을 띄웠으면 false
   */
  const prepareThen = async (go: () => Promise<void>): Promise<boolean> => {
    if (!workingId) return true
    if (!await persistEdits()) return false

    //  **잠긴 건은 다듬지도 않는다.** 다듬기는 `purpose`를 저장하는 편집이라
    //  (`submit_prep.prepare`), 서버도 같은 `EDITABLE_STATUSES`로 거절한다. 거절을
    //  삼키고 넘어가면 "왜 어떤 건만 팝업이 뜨나"가 설명되지 않으므로 여기서 건너뛴다.
    //  팀 제출(`TEAM_COLLECTING`)의 다듬기·확인은 이미 '올림' 단계에서 끝났다.
    if (readOnly) { await go(); return true }

    const prep = await prepareSubmit(workingId)
    if (prep) {
      //  다듬기가 적용됐으면 서버가 이미 저장했다 — 화면 값도 맞춰 둔다
      //  (안 맞추면 다음 `persistEdits`가 옛 문장으로 되돌린다).
      if (prep.purpose && prep.purpose !== purpose) setPurpose(prep.purpose)
      if (prep.shouldConfirm) {
        submitAfterConfirm.current = go
        setSubmitPrep(prep)
        return false
      }
      setNotices(prep.notices ?? [])
      setJudgement(prep.judgement ?? null)
    }
    await go()
    return true
  }

  const doRaise = async () => {
    if (!workingId) return
    const outcome = await raiseSettlements([workingId])
    //  **거절을 성공으로 그리지 않는다.** 서버가 전이를 막으면 `skipped`로 돌아오는데,
    //  예전엔 응답을 보지 않고 「팀 취합중」으로 바꾸고 닫아 버렸다 — 새로고침하면
    //  원래 상태였다.
    if (!outcome.raised.includes(workingId)) {
      setAgentError('팀에 올리지 못했습니다 — 이 상태에서는 올릴 수 없는 건입니다. 목록을 새로고침해 주세요.')
      return
    }
    onStatusChange?.(workingId, 'TEAM_COLLECTING')
    onClose()
  }

  const raise = async () => {
    setPending(true)
    try { await prepareThen(doRaise) } finally { setPending(false) }
  }

  // 팀 제출 (TEAM_COLLECTING → SUBMITTED) · 회계 보완요청 재제출 (RETURNED → SUBMITTED)
  //  제출 직후 룰 엔진 1차판정이 이어 돌아 실제 도착 상태는 건마다 다르다 — 그 값을 그대로 반영한다.
  const doSubmit = async () => {
    if (!workingId) return
    const outcome = await submitSettlements([workingId])
    onStatusChange?.(workingId, outcome.status[workingId] ?? 'SUBMITTED')
    onClose()
  }

  const submit = async () => {
    setPending(true)
    try { await prepareThen(doSubmit) } finally { setPending(false) }
  }

  /** 확인 팝업에서 고른 문장으로 저장하고 이어서 진행한다. */
  const confirmAndGo = async (chosen: string) => {
    const go = submitAfterConfirm.current
    setPending(true)
    try {
      if (workingId && chosen !== purpose) {
        setPurpose(chosen)
        await updateSettlement(workingId, { purpose: chosen })
      }
      setSubmitPrep(null)
      submitAfterConfirm.current = null
      await go?.()
    } finally { setPending(false) }
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

  //  제출 전 확인 — **서버가 `shouldConfirm`을 준 경우에만** 여기 온다(기본은 조용히 진행).
  if (submitPrep) {
    return (
      <SubmitConfirmModal
        prep={submitPrep}
        busy={pending}
        onCancel={() => { setSubmitPrep(null); submitAfterConfirm.current = null }}
        onSubmit={(chosen) => void confirmAndGo(chosen)}
      />
    )
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

  //  **영수증은 필수다.** 증빙 없이 등록되면 판정이 곧바로 「증빙 누락」으로 잡고,
  //  담당자는 되돌려보낼 뿐이다 — 그 왕복을 등록 단계에서 없앤다.
  //  신규 등록에서 아직 파일을 안 골랐으면 할 수 있는 게 없다.
  const creatingBeforeUpload = isCreate && !createdId

  const footer = (
    <>
      {/*  「취소」를 두지 않는다 — 영수증을 고른 순간 이미 건이 저장돼 있어서, 취소라는
          이름이 실제로 일어나는 일과 어긋난다(없애려면 삭제다). 파일을 고르기 전이거나
          조회 전용일 때만 닫기를 남긴다. 팀 취합 뷰는 종전대로 우상단 X·Esc로 닫는다. */}
      {!isTeamView && (creatingBeforeUpload || readOnly) && (
        <button className="btn" onClick={onClose} disabled={pending}>닫기</button>
      )}
      {creatingBeforeUpload ? (
        <span className="text-meta">영수증 파일을 고르면 등록되고 초안 작성이 시작됩니다.</span>
      ) : isCreate ? (
        <>
          <button className="btn reject" onClick={remove} disabled={pending || agentPhase !== ''}>
            <Trash2 size={13} /> 삭제
          </button>
          <button
            className="btn primary"
            onClick={raise}
            disabled={pending || agentPhase !== ''}
            title={agentPhase !== '' ? 'AI가 초안을 작성하는 중입니다.' : undefined}
          >
            {agentPhase !== '' ? 'AI 작성 중…' : '팀에 올림'}
          </button>
        </>
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
        canRaise ? (
          <>
            {isMineView && (
              <button className="btn reject" onClick={remove} disabled={pending}>
                <Trash2 size={13} /> 삭제
              </button>
            )}
            <button className="btn primary" onClick={raise} disabled={pending}>
              {isTeamReturned ? '보완 후 다시 올림' : '팀에 올림'}
            </button>
          </>
        ) : (
          <>
            {isMineView && canDelete && (
              <button className="btn reject" onClick={remove} disabled={pending}>
                <Trash2 size={13} /> 삭제
              </button>
            )}
            {canSubmit ? (
              <button
                className="btn primary"
                onClick={submit}
                disabled={pending || (isTeamView && isAnomaly)}
                title={isTeamView && isAnomaly ? '이상 건은 제출할 수 없습니다.' : undefined}
              >
                {isTeamView && isAnomaly ? '제출 불가 (이상 건)' : needsResubmit ? '보완 후 재제출' : '제출(SUBMITTED)'}
              </button>
            ) : (
              //  갈 수 없는 전이에 버튼을 두지 않는다 — 누르면 서버가 거절할 뿐이고,
              //  사용자는 왜 안 되는지 대신 무엇이 잘못됐는지를 묻게 된다.
              <span className="text-meta row" style={{ gap: 6 }}>
                <Lock size={12} /> {statusEditable
                  ? '이 상태에서는 제출할 수 없습니다.'
                  : lockNote}
              </span>
            )}
          </>
        )
      ) : (
        <span className="text-meta row" style={{ gap: 6 }}><Lock size={12} /> 본인 건이 아니어 조회만 가능합니다.</span>
      )}
    </>
  )

  //  이력은 서버가 주는 `events`가 정본이다(`SettlementEvent`). `auditTrail`은 mock 전용이라
  //  실 모드에서는 항상 비어 있었고, 그 빈자리를 가짜 3줄이 채우고 있었다.
  const events = item?.events ?? []
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
              {receiptUp
                ? <span className="tag ok"><Check size={11} /> Vision 판독</span>
                : fromErp && <span className="tag">원장 수집</span>}
            </div>
            <div className={'card-body' + (fromErp && !receiptUp ? ' is-muted' : '')}>
              <div style={{
                height: 168, background: 'var(--surface-2)', borderRadius: 'var(--radius-control)',
                display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
                gap: 6, color: 'var(--muted)', border: '1px dashed var(--border-strong)',
                //  원장 수집 건은 **비활성**으로 보여준다 — 여기서 할 일이 없다는 뜻이다.
                opacity: fromErp && !receiptUp ? 0.55 : 1,
              }}>
                {receiptFile
                  ? <><Receipt size={18} /> {receiptFile.name}</>
                  : receiptUp
                    ? <><Receipt size={18} /> 첨부된 영수증</>
                    : fromErp
                      ? <><Receipt size={18} /> 원장 수집 건 — 영수증 파일 없음</>
                      : <><AlertTriangle size={16} /> {readOnly ? '첨부된 영수증 없음' : '영수증을 첨부해 주세요 (필수)'}</>}
              </div>

              {!readOnly && isCreate && (
                <>
                  <input
                    ref={receiptRef}
                    type="file"
                    accept=".pdf,.png,.jpg,.jpeg,.webp,.heic"
                    style={{ display: 'none' }}
                    onChange={(e) => void pickReceipt(e.target.files?.[0])}
                  />
                  {/*  **파일을 고르면 그 자리에서 등록된다.** 다시 고르기는 두지 않는다 —
                      이미 저장된 건의 영수증을 바꾸는 건 「다시 고르기」가 아니라 삭제 후
                      재등록이거나 추가 증빙 첨부다(아래 증빙 자료). */}
                  {!createdId && (
                    <button
                      className="btn primary"
                      style={{ width: '100%', justifyContent: 'center', marginTop: 12 }}
                      onClick={() => receiptRef.current?.click()}
                      disabled={pending || agentPhase !== ''}
                    >
                      <Upload size={14} /> 영수증 파일 선택
                    </button>
                  )}
                  <div className="text-meta" style={{ marginTop: 6 }}>
                    파일을 고르면 <b>바로 등록</b>되고, 서버가 영수증을 판독해 가맹점·금액과
                    품목·주류 포함 여부 같은 <b>판정 사실</b>을 읽습니다. 읽은 내용으로 분류와
                    지출 목적 초안이 채워집니다.
                  </div>
                </>
              )}
              {/*  **한 줄이면 된다.** 「원장 수집 건 — 영수증 파일 없음」은 위 자리표시자가
                  이미 말한다. 여기 남길 것은 "그럼 어디에 올리나"뿐이다. */}
              {!readOnly && !isCreate && (
                <div className="text-meta" style={{ marginTop: 10 }}>
                  {fromErp && !receiptUp ? '증빙' : '추가 증빙'}은 아래 <b>증빙 자료</b>에서 첨부합니다.
                </div>
              )}
            </div>
          </div>

          {/* 증빙 첨부 + 판독 — 업로드가 곧 판독 트리거다(서버가 비전 판독을 돌린다). */}
          <EvidenceAttachments
            settlementId={workingId ?? null}
            readOnly={readOnly}
            onFactsExtracted={onFactsExtracted}
          />

          {/* 상태 변경 이력 (Audit Trail) */}
          <div className="card">
            <div className="card-head"><h3>상태 변경 이력</h3></div>
            <div className="card-body">
              {/*  **실제 `SettlementEvent`를 그린다.** 예전엔 서버가 `events`를 내려주는데도
                   화면은 `auditTrail`(목업)을 봤고, 없으면 09:12/09:40/09:41이 박힌 가짜 3줄을
                   그렸다 — 처리자도 사유도 실제와 무관했다. 이력은 감사 기록이라 지어내면 안 된다. */}
              {isCreate ? (
                <div className="text-meta">저장 후 이력이 기록됩니다.</div>
              ) : events.length === 0 ? (
                <div className="text-meta">아직 기록된 상태 변경이 없습니다.</div>
              ) : (
                <ul className="timeline">
                  {events.map((ev, i) => (
                    <li key={ev.id ?? i} className={TIMELINE_TONES[i % TIMELINE_TONES.length]}>
                      <div style={{ fontSize: 13 }}>
                        {STATUS_META[ev.toState as SettlementStatus]?.label ?? ev.toState}
                        {ev.reason ? ` — ${ev.reason}` : ''}
                      </div>
                      <div className="t-meta">{ev.actor || '시스템'} · {fmtEventTime(ev.createdAt)}</div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </div>

        {/* ───────── 우측: Agent 진행·안내 + 기본내역 + 분류·사유 + fact.json ───────── */}
        <div className="stack">
          <div className="card">
            <div className="card-head">
              <h3>기본 내역</h3>
              {/*  **지시문 입력칸을 없앤 자리.** 「AI에게 지시」는 메인 흐름이 아니다 —
                  이 화면의 기본 경로는 영수증을 올리면 저장→판독→초안이 저절로 도는 것이고,
                  지시문은 그 위에 얹힌 옛 폼 기반 경로였다. 버튼 하나만 남겨
                  「방금 고친 값으로 다시 써 줘」에만 쓴다. */}
              {/*  남의 건이면 아예 안 보이고, **내 건이 잠긴 것뿐이면 비활성으로 보인다.**
                  버튼이 사라지면 "원래 없는 기능"으로 읽히지만, 흐려진 버튼과 사유 툴팁은
                  "지금은 못 쓴다"를 말한다 — 잠긴 이유는 사용자가 풀 수 있는 것이다. */}
              {isOwner && (
                <button
                  className="btn sm icon-only ai"
                  onClick={() => { if (workingId && !readOnly) void runSettlementDraft(workingId) }}
                  disabled={readOnly || !workingId || pending || agentPhase !== ''}
                  title={readOnly
                    ? lockNote
                    : workingId
                      ? 'AI로 다시 작성 — 저장된 사실과 증빙 판독 결과로 분류·목적을 채웁니다'
                      : '영수증을 올려 등록한 뒤 사용할 수 있습니다'}
                  aria-label="AI로 다시 작성"
                >
                  {/*  누르는 자리에서 바로 돌아야 한다 — AI 카드는 화면 아래라
                      스크롤 밖일 수 있다. */}
                  {agentPhase !== '' ? <Loader2 size={14} className="spin" /> : <Wand2 size={14} />}
                </button>
              )}
            </div>
            <div className="card-body">
              {fromErp && !readOnly && (
                <div className="text-meta" style={{ marginBottom: 10 }}>
                  카드사 결제기록에서 수집한 건이라 <b>거래 내역은 수정할 수 없습니다.</b>
                  분류·목적·참석 인원은 고칠 수 있습니다.
                </div>
              )}
              <div className="field"><label>가맹점</label>
                <input value={merchant} onChange={(e) => setMerchant(e.target.value)} placeholder="가맹점명" disabled={txLocked} />
              </div>
              <div className="grid-2" style={{ gap: 10 }}>
                <div className="field"><label>거래일자</label>
                  <input type="date" value={dateStr} onChange={(e) => setDateStr(e.target.value)} disabled={txLocked} />
                </div>
                <div className="field"><label>금액 (원)</label>
                  <input value={amountText} onChange={(e) => setAmountText(e.target.value)} placeholder="0" inputMode="numeric" disabled={txLocked} />
                </div>
              </div>
              <div className="grid-2" style={{ gap: 10 }}>
                <div className="field"><label>사용 카드</label>
                  {txLocked ? (
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
                  <label>
                    비용 분류 {aiSuggested && category && <span className="tag ai">AI 제안</span>}
                    {!category && <span className="tag warn">선택 필요</span>}
                  </label>
                  <select value={category} onChange={(e) => setCategory(e.target.value as Category)} disabled={readOnly}>
                    {/* 미분류를 고를 수 있는 자리를 남긴다 — 없으면 아무도 안 고른 건이
                        첫 항목으로 보이고, 그 값이 저장되면 「사람이 확정했다」는 기록이 된다. */}
                    <option value="">선택 필요 — 분류를 골라주세요</option>
                    {categories.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
                  </select>
                  {!category && !readOnly && (
                    <div className="text-meta" style={{ marginTop: 4 }}>
                      고르지 않고 제출하면 「분류 미기재」 사유가 붙어 회계 검토로 넘어갑니다.
                    </div>
                  )}
                </div>
              </div>
              <div className="field">
                {/*  안내문은 라벨 옆에 **더 연하게** 붙인다 — 입력칸 아래에 문단으로
                    두면 값보다 안내가 커 보인다. 짧게 남기는 이유는 신고값과 확인값이
                    **다른 축**이라서다: 안 적으면 "인원을 적었으니 됐다"고 믿고 명단을 안 올린다. */}
                <label style={{ display: 'flex', alignItems: 'baseline', gap: 6, flexWrap: 'wrap' }}>
                  <span>참석 인원 <span className="text-meta" style={{ fontWeight: 400 }}>(신고)</span></span>
                  <span className="text-meta" style={{ fontWeight: 400, opacity: 0.72 }}>
                    정확한 인원이 필요한 판정은 참석자 명단·회의록 첨부값을 씁니다
                  </span>
                </label>
                <input
                  type="number" min={0} inputMode="numeric" value={headcount} disabled={readOnly}
                  onChange={(e) => setHeadcount(e.target.value)}
                  placeholder="비워두면 「모름」 · 0은 「해당 없음」"
                />
                {headcount.trim() !== '' && Number(headcount) > 0 && numOnly(amountText) > 0 && (
                  <div className="text-meta" style={{ marginTop: 4 }}>
                    1인당 {Math.floor(numOnly(amountText) / Number(headcount)).toLocaleString()}원으로 판정됩니다
                  </div>
                )}
              </div>
              <div className="field" style={{ marginBottom: 0 }}><label>지출 목적 · 사유</label>
                <textarea rows={2} value={purpose} onChange={(e) => setPurpose(e.target.value)} placeholder="실사용자·목적·거래처 등 (AI 버튼으로 자동 보정 가능)" disabled={readOnly} />
              </div>
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

          {/*  **한 번의 AI 실행이 낸 것을 한 자리에서** 보여준다. 예전엔 진행·설명·안내가
               상단 패널에, 로그가 여기에 나뉘어 있어서 위아래를 오가며 맞춰 봐야 했다.
               누적(logs)과 교체(reasoning·notices·judgement)의 구분은 컴포넌트가 설명한다. */}
          <AgentPanel
            phase={agentPhase}
            error={agentError}
            reasoning={reasoning}
            notices={notices}
            judgement={judgement}
            logs={comments}
            readOnly={readOnly}
            readOnlyNote={lockNote}
          />
        </div>
      </div>
    </Modal>
  )
}

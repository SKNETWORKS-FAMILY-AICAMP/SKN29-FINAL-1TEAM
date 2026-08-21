// F-2 처리 사유 입력 모달 — 보완요청(RETURNED) / 반려(REJECT) 공용.
//
// **모든 화면이 이 모달 하나를 쓴다**(회계 검토·팀 취합 목록·정산 상세). 화면마다 다른
// 모달을 두면 사유 어휘도, 반려 재확인 절차도 곧 갈린다 — 실제로 상세 모달만 보완요청
// 전용 모달을 따로 쓰고 있었고 반려는 아예 확인 없이 바로 나갔다.
//
// 열릴 때 **Draft Agent가 사유 초안을 채운다**(`fetchDecisionReason`). 판정이 이미 사유
// 코드와 내역을 갖고 있으므로, 결정자는 처음부터 쓰지 않고 **지우고 고치기만** 하면 된다.
// 초안은 그대로 편집 가능하고, 저장되는 건 사람이 최종적으로 보낸 문구다.
//
// 반려는 최종 처리이므로 2단계(사유 입력 → 확인 팝업)로 재확인한다.
import { useEffect, useState } from 'react'
import { AlertTriangle, Loader2, Sparkles } from 'lucide-react'
import { Modal } from '../ui/Modal'
import { won } from '../../lib/format'
import type { Settlement } from '../../types/domain'

type DecisionReasonDraftDivergence = { expected: string; expectedFrom: 'AI' | 'RULE' | ''; diverges: boolean }
import { fetchDecisionReason, type DecisionKind } from '../../api/settlementService'
import { useAuth } from '../../context/AuthContext'

//  서버가 선택지를 못 줬을 때만 쓰는 최소 폴백. **정본은 서버**
//  (`domain/settlements/decision_reasons.py`)다 — 화면과 LLM이 같은 목록을 봐야 한다.
const FALLBACK_REASONS: Record<DecisionKind, string[]> = {
  APPROVE: ['업무관련성 확인됨', '증빙 별도 확인', '규정상 예외 인정', 'AI 과탐지(오탐)', '경미하여 통과', '기타'],
  RETURN: ['증빙 누락', '건당 한도 초과', '업무관련성 소명 부족', '사전승인 누락', '기타'],
  REJECT: ['명백한 규정 위반', '사적 사용 의심', '허위 증빙 의심', '중복 제출', '기타'],
}

const TITLE: Record<DecisionKind, string> = {
  APPROVE: '승인 사유 입력', RETURN: '보완요청 사유 입력', REJECT: '반려 사유 입력',
}
const SEND_LABEL: Record<DecisionKind, string> = {
  APPROVE: '승인 (APPROVE)', RETURN: '보완요청 전송 (RETURNED)', REJECT: '반려 전송 (REJECT)',
}
const EXPECTED_LABEL: Record<string, string> = {
  APPROVE: '승인', RETURN: '보완요청', REJECT: '반려',
}

export function DecisionReasonModal({
  item,
  decision,
  onClose,
  onConfirm,
  /** 전송 중 잠금 — 부모가 API를 호출하는 동안 두 번 눌리지 않게 한다. */
  busy = false,
}: {
  item: Settlement
  decision: DecisionKind
  onClose: () => void
  onConfirm: (reason: string, detail: string) => void
  busy?: boolean
}) {
  const isReject = decision === 'REJECT'
  const isApprove = decision === 'APPROVE'
  const { user } = useAuth()
  const [divergence, setDivergence] = useState<DecisionReasonDraftDivergence | null>(null)
  const [options, setOptions] = useState(FALLBACK_REASONS[decision])
  const [reason, setReason] = useState(FALLBACK_REASONS[decision][0])
  const [detail, setDetail] = useState('')
  const [confirming, setConfirming] = useState(false)  // 반려 2단계 확인
  const [drafting, setDrafting] = useState(true)
  const [source, setSource] = useState<'ai' | 'fallback' | null>(null)
  const [touched, setTouched] = useState(false)        // 사람이 손댔으면 초안으로 덮지 않는다

  /** 초안 적용 — 사람이 이미 손댔으면 덮지 않는다(늦게 도착한 응답이 입력을 지우는 사고). */
  const applyDraft = (draft: Awaited<ReturnType<typeof fetchDecisionReason>>, force = false) => {
    setDrafting(false)
    if (!draft) return              // 초안이 없어도 모달은 그대로 쓴다(직접 작성).
    if (!force && touched) return
    if (draft.options?.length) setOptions(draft.options)
    setReason(draft.reason || draft.options?.[0] || FALLBACK_REASONS[decision][0])
    setDetail(draft.detail)
    setSource(draft.source)
    setDivergence(draft.divergence ?? null)
  }

  /** 「다시 작성」 — 사람이 명시적으로 요청했으므로 손댄 내용도 덮는다. */
  const regenerate = async () => {
    setDrafting(true)
    applyDraft(await fetchDecisionReason(item.id, decision), true)
    setTouched(false)
  }

  //  모달이 열릴 때 한 번.
  useEffect(() => {
    let alive = true
    void (async () => {
      const draft = await fetchDecisionReason(item.id, decision)
      if (alive) applyDraft(draft)
    })()
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.id, decision])

  const subhead = `${item.id} · ${item.user} · ${won(item.amount)}`

  // 반려 확인 팝업(2단계)
  if (isReject && confirming) {
    const footer = (
      <>
        <button className="btn" onClick={() => setConfirming(false)} disabled={busy}>취소</button>
        <button className="btn reject" onClick={() => onConfirm(reason, detail)} disabled={busy}>
          {busy ? '처리 중…' : '반려 확정'}
        </button>
      </>
    )
    return (
      <Modal title="반려 확인" onClose={onClose} footer={footer}>
        <div className="stack" style={{ alignItems: 'center', textAlign: 'center', gap: 8 }}>
          <AlertTriangle size={28} color="var(--tone-red)" />
          <h3>정말 반려하시겠습니까?</h3>
          <p className="text-meta" style={{ margin: 0 }}>
            반려(REJECT)는 최종 처리이며, 담당자는 이 건을 재제출할 수 없습니다.
          </p>
        </div>
        <div className="note" style={{ marginTop: 16 }}>
          <div><span className="text-meta">대상 건</span> · {subhead}</div>
          <div style={{ marginTop: 4 }}><span className="text-meta">선택 사유</span> · {reason}</div>
        </div>
      </Modal>
    )
  }

  const footer = (
    <>
      <button className="btn" onClick={onClose} disabled={busy}>취소</button>
      {isReject ? (
        <button className="btn reject" onClick={() => setConfirming(true)} disabled={busy}>{SEND_LABEL.REJECT}</button>
      ) : (
        <button
          className={'btn ' + (isApprove ? 'approve' : 'return')}
          onClick={() => onConfirm(reason, detail)}
          disabled={busy}
        >
          {busy ? '처리 중…' : SEND_LABEL[decision]}
        </button>
      )}
    </>
  )

  return (
    <Modal title={TITLE[decision]} onClose={onClose} footer={footer}>
      {/* **무엇과 다른 판단인지 먼저 보여준다.** 사유를 왜 받는지 모르면 형식적으로 채워진다. */}
      {divergence?.diverges && (
        <div className="note" style={{ background: 'var(--tone-amber-bg)', border: '1px solid #ead9ad', marginBottom: 16 }}>
          {divergence.expectedFrom === 'AI' ? 'AI 권고' : '룰 판정'}는(은){' '}
          <b>{EXPECTED_LABEL[divergence.expected] ?? divergence.expected}</b>였습니다 —
          다르게 판단하시는 <b>이유</b>를 남겨주세요.
          <div className="text-meta" style={{ marginTop: 4 }}>
            이 사유는 <b>결정 사례</b>로 저장되어, 다음에 비슷한 건을 검토할 때 근거로 인용됩니다.
          </div>
        </div>
      )}
      <div className="row" style={{ justifyContent: 'space-between', marginBottom: 16 }}>
        <span className="text-meta">{subhead}</span>
        {/* 초안의 출처를 감추지 않는다 — 사람이 "이 문장을 누가 썼나"를 알고 고쳐야 한다. */}
        {drafting ? (
          <span className="tag"><Loader2 size={11} className="spin" /> 사유 초안 작성 중…</span>
        ) : source ? (
          <span className="row" style={{ gap: 6 }}>
            <span className="tag ai">
              <Sparkles size={11} /> {source === 'ai' ? 'AI 초안 · 수정 가능' : '판정 사유 기반 초안 · 수정 가능'}
            </span>
            <button className="btn sm" onClick={() => void regenerate()} disabled={busy}>다시 작성</button>
          </span>
        ) : (
          <span className="text-meta">초안을 만들지 못했습니다 — 직접 작성해 주세요.</span>
        )}
      </div>

      <div className="field">
        <label>사유 선택</label>
        <div className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
          {options.map((r) => (
            <button
              key={r}
              type="button"
              className={'tag' + (r === reason ? ' warn' : '')}
              style={{ font: 'inherit', cursor: 'pointer' }}
              aria-pressed={r === reason}
              onClick={() => { setReason(r); setTouched(true) }}
            >
              {r}
            </button>
          ))}
        </div>
      </div>

      <div className="field" style={{ marginBottom: 0 }}>
        <label>
          상세 사유{' '}
          {isApprove ? '— 왜 기계 판단을 따르지 않았는지 적어주세요(감사 기록)'
            : isReject ? '(선택)'
              : '— 지출자가 무엇을 하면 되는지 적어주세요'}
        </label>
        <textarea
          rows={4}
          placeholder={
            isReject
              ? '예) 사적 목적의 지출로 판단되며 업무 관련성이 소명되지 않아 반려합니다.'
              : isApprove
                ? '예) 참석자 명단을 별도 확인했고 거래처 미팅 목적이 확인되어 승인합니다.'
                : '예) 3만원 초과 접대비 건이나 적격증빙이 첨부되지 않았습니다. 재업로드 후 재제출 바랍니다.'
          }
          value={detail}
          onChange={(e) => { setDetail(e.target.value); setTouched(true) }}
        />
      </div>

      {/* **누가 결정했는지 남는다는 걸 그 자리에서 알린다.** 기록되는 줄 모르고 쓴 문장과
          알고 쓴 문장은 다르다(사례로 인용될 글이다). */}
      <div className="text-meta" style={{ marginTop: 10 }}>
        처리자 <b>{user?.name ?? '나'}</b> · 이 사유와 처리자가 상태 변경 이력에 함께 기록됩니다.
      </div>
    </Modal>
  )
}

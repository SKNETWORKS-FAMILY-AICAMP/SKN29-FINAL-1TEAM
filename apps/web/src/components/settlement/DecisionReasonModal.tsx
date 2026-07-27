// F-2 처리 사유 입력 모달 — 보완요청(RETURNED) / 반려(REJECT) 공용.
// 반려는 최종 처리이므로 2단계(사유 입력 → 확인 팝업)로 재확인한다.
import { useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { Modal } from '../ui/Modal'
import { won } from '../../lib/format'
import type { Settlement } from '../../types/domain'

const REASONS: Record<'RETURN' | 'REJECT', string[]> = {
  RETURN: ['증빙 누락', '건당 한도 초과', '업무관련성 소명 부족', '사전승인 누락', '기타'],
  REJECT: ['명백한 규정 위반', '사적 사용 의심', '허위 증빙 의심', '중복 제출', '기타'],
}

export function DecisionReasonModal({
  item,
  decision,
  onClose,
  onConfirm,
}: {
  item: Settlement
  decision: 'RETURN' | 'REJECT'
  onClose: () => void
  onConfirm: (reason: string, detail: string) => void
}) {
  const isReject = decision === 'REJECT'
  const [reason, setReason] = useState(REASONS[decision][0])
  const [detail, setDetail] = useState('')
  const [confirming, setConfirming] = useState(false) // 반려 2단계 확인

  const subhead = `${item.id} · ${item.user} · ${won(item.amount)}`

  // 반려 확인 팝업(2단계)
  if (isReject && confirming) {
    const footer = (
      <>
        <button className="btn" onClick={() => setConfirming(false)}>취소</button>
        <button className="btn reject" onClick={() => onConfirm(reason, detail)}>반려 확정</button>
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
      <button className="btn" onClick={onClose}>취소</button>
      {isReject ? (
        <button className="btn reject" onClick={() => setConfirming(true)}>반려 전송 (REJECT)</button>
      ) : (
        <button className="btn return" onClick={() => onConfirm(reason, detail)}>보완요청 전송 (RETURNED)</button>
      )}
    </>
  )

  return (
    <Modal title={isReject ? '반려 사유 입력' : '보완요청 사유 입력'} onClose={onClose} footer={footer}>
      <div className="text-meta" style={{ marginBottom: 16 }}>{subhead}</div>

      <div className="field">
        <label>사유 선택</label>
        <div className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
          {REASONS[decision].map((r) => (
            <button
              key={r}
              type="button"
              className={'tag' + (r === reason ? ' warn' : '')}
              style={{ font: 'inherit', cursor: 'pointer' }}
              aria-pressed={r === reason}
              onClick={() => setReason(r)}
            >
              {r}
            </button>
          ))}
        </div>
      </div>

      <div className="field" style={{ marginBottom: 0 }}>
        <label>상세 사유 (선택)</label>
        <textarea
          rows={3}
          placeholder={
            isReject
              ? '예) 사적 목적의 지출로 판단되며 업무 관련성이 소명되지 않아 반려합니다.'
              : '예) 3만원 초과 접대비 건이나 적격증빙이 첨부되지 않았습니다. 재업로드 후 재제출 바랍니다.'
          }
          value={detail}
          onChange={(e) => setDetail(e.target.value)}
        />
      </div>
    </Modal>
  )
}

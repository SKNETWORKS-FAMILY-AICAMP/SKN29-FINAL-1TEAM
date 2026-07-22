// F-2 처리 사유 입력 모달 — 회계 담당자가 "보완요청(RETURNED)" 처리 시 사유를 남긴다.
import { useState } from 'react'
import { Modal } from '../ui/Modal'
import { won } from '../../lib/format'
import type { Settlement } from '../../types/domain'

const REASONS = ['증빙 누락', '건당 한도 초과', '업무관련성 소명 부족', '사전승인 누락', '기타']

export function ReturnReasonModal({
  item,
  onClose,
  onSubmit,
}: {
  item: Settlement
  onClose: () => void
  onSubmit: (reason: string, detail: string) => void
}) {
  const [reason, setReason] = useState(REASONS[0])
  const [detail, setDetail] = useState('')

  const footer = (
    <>
      <button className="btn" onClick={onClose}>취소</button>
      <button className="btn return" onClick={() => onSubmit(reason, detail)}>보완요청 전송(RETURNED)</button>
    </>
  )

  return (
    <Modal title="보완요청 사유 입력" onClose={onClose} footer={footer}>
      <div className="text-meta" style={{ marginBottom: 16 }}>
        {item.id} · {item.user} · {won(item.amount)}
      </div>

      <div className="field">
        <label>사유 선택</label>
        <div className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
          {REASONS.map((r) => (
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

      <div className="field">
        <label>상세 사유 (선택)</label>
        <textarea
          rows={3}
          placeholder="예) 3만원 초과 접대비 건이나 적격증빙(카드매출전표)이 첨부되지 않았습니다. 재업로드 요청 바랍니다."
          value={detail}
          onChange={(e) => setDetail(e.target.value)}
        />
      </div>
    </Modal>
  )
}

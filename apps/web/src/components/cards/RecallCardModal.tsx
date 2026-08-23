// S-09 (모달) 카드 회수 확인 — 카드를 즉시 회수·사용정지 처리한다(되돌릴 수 없음).
import { useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { Modal } from '../ui/Modal'

//  조치 큐가 기본 선택으로 넘기는 사유(`RECALL_REASON_OF`)가 **이 목록 안에 있어야** 한다 —
//  없는 값을 select에 넣으면 아무것도 안 고른 것처럼 빈칸으로 뜬다.
const REASONS = [
  '퇴사 처리', '분실·도난 신고', '반복 이상사용 감지', '휴직·장기 파견',
  '장기 미사용', '한도 초과', '부정사용 의심', '기타',
]

export function RecallCardModal({
  number,
  assignee,
  statusLabel,
  defaultReason,
  onClose,
  onConfirm,
}: {
  number: string
  assignee: string
  statusLabel: string
  defaultReason?: string
  onClose: () => void
  onConfirm: (reason: string, detail: string) => void
}) {
  const [reason, setReason] = useState(defaultReason ?? REASONS[0])
  const [detail, setDetail] = useState('')

  const footer = (
    <>
      <button className="btn" onClick={onClose}>취소</button>
      <button className="btn reject" onClick={() => onConfirm(reason, detail)}>회수 확정</button>
    </>
  )

  return (
    <Modal title="카드 회수 처리" onClose={onClose} footer={footer} maxWidth={480}>
      <div style={{ background: 'var(--surface-2)', borderRadius: 'var(--radius)', padding: '12px 14px', marginBottom: 16 }}>
        <div className="row" style={{ gap: 8, marginBottom: 10 }}>
          <span style={{ position: 'relative', width: 24, height: 18, borderRadius: 4, background: 'var(--sidebar-bg)', flexShrink: 0 }}>
            <span style={{ position: 'absolute', left: 3, top: 4, width: 8, height: 6, borderRadius: 2, background: 'var(--accent-amber)' }} />
          </span>
          <b style={{ fontSize: 13.5 }}>{number}</b>
        </div>
        <div className="row" style={{ justifyContent: 'space-between', marginBottom: 4 }}>
          <span className="text-meta">배정 대상</span>
          <span style={{ fontSize: 12.5, fontWeight: 600 }}>{assignee}</span>
        </div>
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <span className="text-meta">현재 상태</span>
          <span className="badge" style={{ color: 'var(--tone-amber)', background: 'var(--tone-amber-bg)' }}>{statusLabel}</span>
        </div>
      </div>

      <div className="row" style={{
        gap: 8, alignItems: 'flex-start', background: 'var(--tone-amber-bg)', borderRadius: 'var(--radius-control)',
        padding: '10px 12px', marginBottom: 16,
      }}>
        <AlertTriangle size={15} color="var(--tone-amber)" style={{ flexShrink: 0, marginTop: 1 }} />
        <span style={{ fontSize: 12.5, lineHeight: 1.5 }}>카드를 회수하면 즉시 사용이 정지되며 이 작업은 되돌릴 수 없습니다.</span>
      </div>

      <div className="field">
        <label>회수 사유 <span style={{ color: 'var(--tone-red)' }}>*</span></label>
        <select
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          style={{ background: 'var(--primary-soft)', borderColor: 'var(--primary)', color: 'var(--primary)', fontWeight: 700 }}
        >
          {REASONS.map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
      </div>

      <div className="field" style={{ marginBottom: 0 }}>
        <label>상세 사유 (선택)</label>
        <textarea rows={2} placeholder="추가로 남길 메모가 있다면 입력하세요" value={detail} onChange={(e) => setDetail(e.target.value)} />
      </div>
    </Modal>
  )
}
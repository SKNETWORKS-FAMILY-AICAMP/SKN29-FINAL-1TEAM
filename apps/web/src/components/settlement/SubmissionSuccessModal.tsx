// F-1 제출완료 모달 — 정산 건을 회계로 제출한 직후 보여주는 확인 화면.
import { Check } from 'lucide-react'
import { Modal } from '../ui/Modal'
import { won } from '../../lib/format'
import { CARD_TYPE_LABEL, type Settlement } from '../../types/domain'

const ROWS: { label: string; render: (item: Settlement) => string }[] = [
  { label: '가맹점', render: (item) => item.merchant },
  { label: '금액', render: (item) => `${won(item.amount)}원` },
  //  방금 제출한 건의 **확정 분류**를 보여준다 — AI 제안을 띄우면 사람이 고쳐 올린
  //  값과 다른 것이 확인 화면에 뜬다. 안 골랐으면 그 사실을 그대로 적는다.
  { label: '비용분류', render: (item) => item.category || item.aiCategory || '미기재 — 회계 검토로 넘어갑니다' },
  { label: '카드', render: (item) => CARD_TYPE_LABEL[item.cardType] },
  { label: '상태', render: (item) => `${item.status} · 판정 대기` },
]

export function SubmissionSuccessModal({
  item,
  onCreateNew,
  onClose,
}: {
  item: Settlement
  /** "신규 지출 등록하기" — 이어서 다른 건을 등록 */
  onCreateNew: () => void
  /** "내 지출로 돌아가기" — 목록으로 복귀 */
  onClose: () => void
}) {
  const footer = (
    <>
      <button className="btn" onClick={onCreateNew}>신규 지출 등록하기</button>
      <button className="btn primary" onClick={onClose}>내 지출로 돌아가기</button>
    </>
  )

  return (
    <Modal title="제출 완료" onClose={onClose} footer={footer}>
      <div style={{ textAlign: 'center', padding: '8px 0 4px' }}>
        <div style={{
          width: 64, height: 64, borderRadius: '50%', background: 'var(--tone-green-bg)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 16px',
        }}>
          <Check size={28} color="var(--accent-green)" strokeWidth={3} />
        </div>
        <div style={{ fontSize: 18, fontWeight: 700 }}>제출이 완료되었습니다</div>
        <div className="text-meta" style={{ marginTop: 6 }}>
          지출 건이 정상적으로 제출되었습니다. Rule Agent가 자동으로 1차 판정을 진행합니다.
        </div>
      </div>

      <div style={{ background: 'var(--surface-2)', borderRadius: 'var(--radius)', padding: '14px 16px', margin: '20px 0' }}>
        {ROWS.map((row) => (
          <div key={row.label} className="row" style={{ justifyContent: 'space-between', padding: '6px 0' }}>
            <span className="text-meta">{row.label}</span>
            <span style={{ fontSize: 13, fontWeight: 700 }}>{row.render(item)}</span>
          </div>
        ))}
      </div>

      <div style={{
        textAlign: 'center', background: 'var(--primary-soft)', color: 'var(--primary)',
        borderRadius: 'var(--radius-pill)', padding: '8px 16px', fontSize: 12.5, fontWeight: 700,
      }}>
        {item.status} → Rule Agent 판정 대기 중
      </div>
    </Modal>
  )
}
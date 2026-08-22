// 제출 전 확인 — **조용히 지나가는 것이 기본이고, 여기 오면 예외다.**
//
//  띄울지 말지는 서버가 정한다(`prepare-submit`의 `shouldConfirm`). 화면이 그 기준을
//  갖고 있으면 곧 서버와 갈린다 — 팝업 조건이 두 곳에 생기는 순간 어느 쪽이 맞는지
//  아무도 모르게 된다.
//
//  두 가지를 보여준다:
//   ① 문체를 다듬은 결과가 **원문에 없던 내용을 담았을 때** — 원문과 나란히 놓고 고르게 한다.
//      사용자가 쓴 문장은 감사 기록으로 남고 결정 사례로 인용되므로, 몰래 바꾸지 않는다.
//   ② 지금 제출하면 되돌아올 사유 — 무엇을 하면 해소되는지.
import { AlertTriangle, Info } from 'lucide-react'
import { Modal } from '../ui/Modal'
import type { SubmitPreparation } from '../../api/settlementService'

export function SubmitConfirmModal({
  prep, busy, onCancel, onSubmit,
}: {
  prep: SubmitPreparation
  busy?: boolean
  onCancel: () => void
  /** `purpose`를 넘기면 그 문장으로 저장하고 제출한다. */
  onSubmit: (purpose: string) => void
}) {
  const { polish, notices } = prep
  //  `applied`가 거짓이면 서버가 다듬은 문장을 **적용하지 않았다**(원문이 그대로 저장돼 있다).
  const rewritten = !polish.applied && polish.polished && polish.polished !== polish.original
  const blockers = notices.filter((n) => n.level === 'blocker')
  const others = notices.filter((n) => n.level !== 'blocker')

  const footer = (
    <>
      <button className="btn" onClick={onCancel} disabled={busy}>돌아가서 수정</button>
      {rewritten && (
        <button className="btn" onClick={() => onSubmit(polish.polished)} disabled={busy}>
          다듬은 문장으로 제출
        </button>
      )}
      <button className="btn primary" onClick={() => onSubmit(polish.original)} disabled={busy}>
        {busy ? '제출 중…' : rewritten ? '내 문장 그대로 제출' : '이대로 제출'}
      </button>
    </>
  )

  return (
    <Modal title="제출 전 확인" onClose={onCancel} footer={footer} maxWidth={620}>
      <div className="stack" style={{ gap: 14 }}>
        {blockers.length > 0 && (
          <div className="card">
            <div className="card-head">
              <h3 style={{ color: 'var(--tone-red)' }}>
                <AlertTriangle size={13} style={{ verticalAlign: '-2px' }} /> 지금 제출하면 되돌아옵니다
              </h3>
            </div>
            <div className="card-body stack" style={{ gap: 8 }}>
              {blockers.map((n, i) => (
                <div key={`${n.code}-${i}`} style={{ fontSize: 13 }}>
                  <b>{n.label}</b>
                  {n.owner ? <span className="text-meta"> · {n.owner}</span> : null}
                  <div style={{ marginTop: 2 }}>{n.text}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {rewritten && (
          <div className="card">
            <div className="card-head"><h3>지출 목적 문장</h3></div>
            <div className="card-body stack" style={{ gap: 10 }}>
              <div className="text-meta">
                문체를 다듬은 결과가 원문에 없던 내용을 담고 있어 <b>자동 적용하지 않았습니다.</b>
                어느 쪽으로 기록할지 골라 주세요.
              </div>
              <div className="field" style={{ marginBottom: 0 }}>
                <label>내가 쓴 문장</label>
                <textarea rows={2} value={polish.original} readOnly />
              </div>
              <div className="field" style={{ marginBottom: 0 }}>
                <label>다듬은 문장</label>
                <textarea rows={2} value={polish.polished} readOnly />
              </div>
            </div>
          </div>
        )}

        {others.length > 0 && (
          <div className="card">
            <div className="card-head"><h3><Info size={13} style={{ verticalAlign: '-2px' }} /> 확인해 주세요</h3></div>
            <div className="card-body stack" style={{ gap: 8 }}>
              {others.map((n, i) => (
                <div key={`${n.code}-${i}`} style={{ fontSize: 13 }}>{n.text}</div>
              ))}
            </div>
          </div>
        )}
      </div>
    </Modal>
  )
}

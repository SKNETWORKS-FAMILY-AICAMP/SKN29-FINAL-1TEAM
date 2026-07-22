// S-06 정산 상세/증빙 확인 (공통 모달) — FR-DA-02~06, FR-ST-01~04, FR-AUD-01
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertTriangle, Check, Receipt } from 'lucide-react'
import { CARD_NEEDS_EXTRA_INPUT, CARD_TYPE_LABEL, CATEGORIES, type Settlement } from '../../types/domain'
import { won } from '../../lib/format'
import { Modal } from '../ui/Modal'
import { StatusBadge } from '../ui/StatusBadge'
import { useRole } from '../../context/RoleContext'
import { ReturnReasonModal } from './ReturnReasonModal'

export function SettlementDetailModal({
  item,
  onClose,
}: {
  item: Settlement
  onClose: () => void
}) {
  const { role } = useRole()
  const nav = useNavigate()
  const isAccountant = role === 'ACCOUNTANT'
  const needsExtra = CARD_NEEDS_EXTRA_INPUT[item.cardType]
  const [showReturnModal, setShowReturnModal] = useState(false)

  // F-2: 보완요청 사유는 별도 모달에서 받는다(단일 모달만 표시 — 상세 모달은 잠시 숨김).
  if (showReturnModal) {
    return (
      <ReturnReasonModal
        item={item}
        onClose={() => setShowReturnModal(false)}
        onSubmit={() => { setShowReturnModal(false); onClose() }}
      />
    )
  }

  const footer = (
    <>
      <button className="btn" onClick={onClose}>취소</button>
      {isAccountant ? (
        <>
          <button className="btn return" onClick={() => setShowReturnModal(true)}>보완요청(RETURNED)</button>
          <button className="btn reject">반려(REJECT)</button>
          {/* FR-ST-03: 확신 통과 건이라도 사람 확정 필수 */}
          <button className="btn approve" onClick={() => nav(`/erp/${item.id}`)}>승인 · 확정(CONFIRMED)</button>
        </>
      ) : (
        <button className="btn primary">제출(SUBMITTED)</button>
      )}
    </>
  )

  return (
    <Modal title={`정산 상세 · ${item.id}`} onClose={onClose} footer={footer}>
      <div className="row" style={{ justifyContent: 'space-between', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 16, fontWeight: 700 }}>{item.merchant}</div>
          <div className="text-meta">{item.date} · {CARD_TYPE_LABEL[item.cardType]} 카드</div>
        </div>
        <StatusBadge status={item.status} />
      </div>

      <div className="grid-2">
        {/* 영수증 뷰어 + 비전 판독 필드 (FR-DA-02) */}
        <div className="card">
          <div className="card-head"><h3>영수증 이미지</h3><span className="tag ai"><Check size={11} /> Vision 판독</span></div>
          <div className="card-body">
            <div style={{ height: 180, background: 'var(--surface-2)', borderRadius: 'var(--radius-control)', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6, color: item.evidence === 'OK' ? 'var(--muted)' : 'var(--tone-red)', border: '1px dashed var(--border-strong)' }}>
              {item.evidence === 'OK' ? <><Receipt size={16} /> 영수증 미리보기</> : <><AlertTriangle size={16} /> 증빙 누락</>}
            </div>
          </div>
        </div>

        {/* 추출 필드 폼 (FR-DA-02~04) */}
        <div className="card">
          <div className="card-head"><h3>추출 필드</h3></div>
          <div className="card-body">
            <div className="field"><label>가맹점</label><input defaultValue={item.merchant} /></div>
            <div className="field"><label>금액</label><input defaultValue={won(item.amount)} /></div>
            <div className="field">
              <label>비용 분류 <span className="tag ai">AI 제안</span></label>
              <select defaultValue={item.aiCategory}>
                {CATEGORIES.map((c) => <option key={c}>{c}</option>)}
              </select>
            </div>
            {needsExtra && (
              <div className="field">
                <label>실사용자 · 목적 (카드구분별 추가입력, FR-DA-04)</label>
                <input placeholder="공용/팀 카드는 실사용자·목적 지정 필요" />
              </div>
            )}
          </div>
        </div>
      </div>

      {/* 규정 힌트 (FR-DA-06) */}
      <div className="note" style={{ marginTop: 16 }}>
        <strong>규정 힌트</strong> — {item.aiCategory} 분류 한도·필요서류를 사전 안내합니다. (get_policy Tool 활용, 반려 예방 목적)
      </div>

      {/* Audit Trail (FR-AUD-01, 변경 불가 지향) */}
      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-head"><h3>상태 변경 이력 (Audit Trail)</h3></div>
        <div className="card-body">
          <ul className="timeline">
            <li><div>DRAFT — 초안 자동생성</div><div className="t-meta">Draft Agent · 2026-07-17 09:12</div></li>
            <li><div>SUBMITTED — 제출</div><div className="t-meta">{item.user} · 09:40</div></li>
            <li><div>RPA_JUDGED → IN_REVIEW — confidence=0.61(미매칭), 위험검토 이관</div><div className="t-meta">Rule Agent · 09:41</div></li>
            <li><div>①이상탐지 → ②RAG 내규검증 수행</div><div className="t-meta">Risk Review Agent · 09:41</div></li>
          </ul>
        </div>
      </div>
    </Modal>
  )
}

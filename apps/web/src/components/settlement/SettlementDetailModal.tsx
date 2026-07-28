// S-06 정산 상세/증빙 확인 (공통 모달) — FR-DA-02~06, FR-ST-01~04, FR-AUD-01
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertTriangle, Check, Receipt } from 'lucide-react'
import { CARD_NEEDS_EXTRA_INPUT, CARD_TYPE_LABEL, CATEGORIES, type ReviewItem, type Settlement, type SettlementStatus } from '../../types/domain'
import { won } from '../../lib/format'
import { Modal } from '../ui/Modal'
import { StatusBadge } from '../ui/StatusBadge'
import { useRole } from '../../context/RoleContext'
import { decideTeamSettlement, fetchSettlementDetail, reviewSettlement, submitSettlements } from '../../api/settlementService'
import { useAuth } from '../../context/AuthContext'
import { ReturnReasonModal } from './ReturnReasonModal'
import { AdditionalEvidenceModal } from './AdditionalEvidenceModal'

export function SettlementDetailModal({
  item,
  onClose,
  onStatusChange,
  context = 'default',
}: {
  item: Settlement
  onClose: () => void
  /** 정산 상태가 실제로 바뀌었을 때 호출 — 부모 화면이 목록의 해당 건 상태를 갱신한다. */
  onStatusChange?: (id: string, status: SettlementStatus) => void
  context?: 'default' | 'team'
}) {
  const { role } = useRole()
  const { user } = useAuth()
  const nav = useNavigate()
  const isAccountant = role === 'ACCOUNTANT'
  const needsExtra = CARD_NEEDS_EXTRA_INPUT[item.cardType]
  const [showReturnModal, setShowReturnModal] = useState(false)
  const [showEvidenceModal, setShowEvidenceModal] = useState(false)
  const [pending, setPending] = useState(false)
  const [detail, setDetail] = useState(item)
  const needsEvidenceResubmit = !isAccountant && item.status === 'RETURNED'
  const isOwner = item.user === user?.name
  const isTeamView = context === 'team'
  const canTeamDecide = isTeamView && role !== 'EMPLOYEE' && item.status === 'TEAM_COLLECTING'
  const readOnly = !isOwner
  const evidenceFiles = detail.additionalEvidence ?? (detail.evidence === 'OK' ? [{ id: 0, name: 'receipt.jpg', status: 'MATCHED' }] : [])
  const facts = detail.facts ?? {
    settlement_id: detail.id,
    transaction: { merchant: detail.merchant, amount: detail.amount, occurred_at: `${detail.date}${detail.time ? `T${detail.time}` : ''}`, has_receipt: detail.evidence === 'OK' },
    card: { type: detail.cardType },
    submitter: { username: detail.user, team: detail.dept ?? null },
    settlement: { category: detail.category ?? detail.aiCategory, ai_category: detail.aiCategory, merchant_industry: detail.merchantIndustry ?? '', purpose: detail.purpose ?? '', status: detail.status },
  }

  useEffect(() => {
    let active = true
    fetchSettlementDetail(item).then((loaded) => { if (active) setDetail(loaded) }).catch(() => undefined)
    return () => { active = false }
  }, [item])

  const submit = async () => {
    setPending(true)
    const status = await submitSettlements([item.id])
    onStatusChange?.(item.id, status)
    setPending(false)
    onClose()
  }

  const approve = async () => {
    setPending(true)
    const status = await reviewSettlement(item.id, 'APPROVE')
    onStatusChange?.(item.id, status)
    setPending(false)
    nav(`/erp/${item.id}`)
  }

  const reject = async () => {
    setPending(true)
    const status = await reviewSettlement(item.id, 'REJECT')
    onStatusChange?.(item.id, status)
    setPending(false)
    onClose()
  }

  const returnWithReason = async (reason: string, detail: string) => {
    const message = detail ? `${reason} — ${detail}` : reason
    const status = canTeamDecide
      ? await decideTeamSettlement(item.id, 'RETURN', message)
      : await reviewSettlement(item.id, 'RETURN', message)
    onStatusChange?.(item.id, status)
    setShowReturnModal(false)
    onClose()
  }

  // F-2: 보완요청 사유는 별도 모달에서 받는다(단일 모달만 표시 — 상세 모달은 잠시 숨김).
  if (showReturnModal) {
    return (
      <ReturnReasonModal
        item={item}
        onClose={() => setShowReturnModal(false)}
        onSubmit={returnWithReason}
      />
    )
  }

  // F-1 증빙 파일 추가 제출: 보완요청(RETURNED) 건을 임직원이 재제출할 때.
  if (showEvidenceModal) {
    return (
      <AdditionalEvidenceModal
        onClose={() => setShowEvidenceModal(false)}
        onSubmit={async () => {
          const status = await submitSettlements([item.id])
          onStatusChange?.(item.id, status)
          setShowEvidenceModal(false)
          onClose()
        }}
      />
    )
  }

  const footer = (
    <>
      <button className="btn" onClick={onClose} disabled={pending}>취소</button>
      {canTeamDecide ? (
        <>
          <button className="btn return" onClick={() => setShowReturnModal(true)} disabled={pending}>팀 보완요청</button>
          <button className="btn reject" onClick={async () => {
            setPending(true)
            const status = await decideTeamSettlement(item.id, 'REJECT')
            onStatusChange?.(item.id, status)
            setPending(false)
            onClose()
          }} disabled={pending}>팀 반려</button>
        </>
      ) : isAccountant ? (
        <>
          <button className="btn return" onClick={() => setShowReturnModal(true)} disabled={pending}>보완요청(RETURNED)</button>
          <button className="btn reject" onClick={reject} disabled={pending}>반려(REJECT)</button>
          {/* FR-ST-03: 확신 통과 건이라도 사람 확정 필수 */}
          <button className="btn approve" onClick={approve} disabled={pending}>승인 · 확정(CONFIRMED)</button>
        </>
      ) : needsEvidenceResubmit && isOwner ? (
        <button className="btn primary" onClick={() => setShowEvidenceModal(true)} disabled={pending}>증빙 파일 추가 제출</button>
      ) : isOwner ? (
        <button className="btn primary" onClick={submit} disabled={pending}>제출(SUBMITTED)</button>
      ) : (
        <span className="text-meta">본인 건이 아니어 조회만 가능합니다.</span>
      )}
    </>
  )

  return (
    <Modal title={`정산 상세 · ${item.id}`} onClose={onClose} footer={footer} maxWidth={1080}>
      <div className="row" style={{ justifyContent: 'space-between', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 16, fontWeight: 700 }}>{item.merchant}</div>
          <div className="text-meta">{item.date} · {CARD_TYPE_LABEL[item.cardType]} 카드</div>
        </div>
        <StatusBadge status={item.status} />
      </div>

      <div className="detail-value-grid" style={{ marginBottom: 16 }}>
        <div><span>사용자</span><b>{detail.user || '-'}</b></div>
        <div><span>소속 팀</span><b>{detail.dept || '-'}</b></div>
        <div><span>거래 일시</span><b>{detail.date}{detail.time ? ` ${detail.time}` : ''}</b></div>
        <div><span>카드 구분</span><b>{CARD_TYPE_LABEL[detail.cardType]}</b></div>
        <div><span>확정 분류</span><b>{detail.category || detail.aiCategory}</b></div>
        <div><span>가맹점 업종</span><b>{detail.merchantIndustry || '-'}</b></div>
        <div><span>증빙 상태</span><b>{detail.evidence === 'OK' ? '매칭 완료' : '누락'}</b></div>
        <div><span>정산 ID</span><b>{detail.id}</b></div>
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
            <div className="field"><label>가맹점</label><input defaultValue={item.merchant} disabled={readOnly} /></div>
            <div className="field"><label>금액</label><input defaultValue={won(item.amount)} disabled={readOnly} /></div>
            <div className="field">
              <label>비용 분류 <span className="tag ai">AI 제안</span></label>
              <select defaultValue={item.aiCategory} disabled={readOnly}>
                {CATEGORIES.map((c) => <option key={c}>{c}</option>)}
              </select>
            </div>
            {needsExtra && (
              <div className="field">
                <label>실사용자 · 목적 (카드구분별 추가입력, FR-DA-04)</label>
                <input placeholder="공용/팀 카드는 실사용자·목적 지정 필요" disabled={readOnly} />
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-head"><h3>지출 목적 및 사유</h3></div>
        <div className="card-body">{detail.purpose || '입력된 사유가 없습니다.'}</div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-head"><h3>추가 증빙 자료</h3><span className="tag">{evidenceFiles.length}개</span></div>
        <div className="card-body">
          {evidenceFiles.length ? (
            <ul className="evidence-list">
              {evidenceFiles.map((file) => <li key={file.id}><b>{file.name}</b><div className="src">{file.status}</div></li>)}
            </ul>
          ) : <span className="text-meta">추가로 제출된 증빙 자료가 없습니다.</span>}
        </div>
      </div>

      <div className="grid-2" style={{ marginTop: 16 }}>
        <div className="card">
          <div className="card-head"><h3>Facts JSON</h3></div>
          <div className="card-body"><pre className="json-viewer">{JSON.stringify(facts, null, 2)}</pre></div>
        </div>
        <div className="card">
          <div className="card-head"><h3>Rule 판정 결과</h3></div>
          <div className="card-body"><pre className="json-viewer">{JSON.stringify(detail.ruleHits ?? [], null, 2)}</pre></div>
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
            {detail.events?.map((ev) => (
              <li key={ev.id}>
                <div>{ev.fromState || '생성'} → {ev.toState}{ev.reason ? ` — ${ev.reason}` : ''}</div>
                <div className="t-meta">{ev.actor || '시스템'} · {new Date(ev.createdAt).toLocaleString('ko-KR')}</div>
              </li>
            )) ?? (item as ReviewItem).auditTrail?.map((ev, i) => (
              <li key={i}>
                <div style={{ fontSize: 13 }}>{ev.status}{ev.note ? ` — ${ev.note}` : ''}</div>
                <div className="t-meta">{ev.actor} · {ev.timestamp}</div>
              </li>
            )) ?? (
              <>
                <li><div>DRAFT — 초안 자동생성</div><div className="t-meta">Draft Agent · {item.date} 09:12</div></li>
                <li><div>SUBMITTED — 제출</div><div className="t-meta">{item.user} · 09:40</div></li>
                <li><div>RPA_JUDGED — Rule Agent 판정</div><div className="t-meta">Rule Agent · 09:41</div></li>
              </>
            )}
          </ul>
        </div>
      </div>
    </Modal>
  )
}

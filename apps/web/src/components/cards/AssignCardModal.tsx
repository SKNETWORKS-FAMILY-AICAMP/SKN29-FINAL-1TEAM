// S-09 (모달) 배정 변경 — 팀카드/개인카드 배정 대상을 바꾼다.
import { useState } from 'react'
import { Modal } from '../ui/Modal'
import type { CardOption } from '../../api/cardService'

export function AssignCardModal({
  number,
  currentLabel,
  teams,
  people,
  onClose,
  onConfirm,
}: {
  number: string
  currentLabel: string
  // 이름이 아니라 **id**로 고른다 — 동명이인이 있으면 이름 매칭은 조용히 엉뚱한 사람에게 붙는다.
  teams: CardOption[]
  people: CardOption[]
  onClose: () => void
  onConfirm: (target: { mode: 'TEAM' | 'PERSONAL'; teamId?: number; userId?: number; reason: string }) => void
}) {
  const [mode, setMode] = useState<'TEAM' | 'PERSONAL'>('TEAM')
  const [teamId, setTeamId] = useState<number | undefined>(teams[0]?.id)
  const [userId, setUserId] = useState<number | undefined>(people[0]?.id)
  const [reason, setReason] = useState('')

  const canConfirm = reason.trim() !== '' && (mode === 'TEAM' ? teamId != null : userId != null)

  const footer = (
    <>
      <button className="btn" onClick={onClose}>취소</button>
      <button
        className="btn primary"
        disabled={!canConfirm}
        onClick={() => onConfirm(mode === 'TEAM' ? { mode, teamId, reason } : { mode, userId, reason })}
      >
        배정 변경 확정
      </button>
    </>
  )

  return (
    <Modal title="카드 배정 변경" onClose={onClose} footer={footer} maxWidth={480}>
      <div style={{ background: 'var(--surface-2)', borderRadius: 'var(--radius)', padding: '12px 14px' }}>
        <div className="text-meta">현재 배정</div>
        <div className="row" style={{ gap: 8, margin: '6px 0' }}>
          <span style={{ position: 'relative', width: 24, height: 18, borderRadius: 4, background: 'var(--primary)', flexShrink: 0 }}>
            <span style={{ position: 'absolute', left: 3, top: 4, width: 8, height: 6, borderRadius: 2, background: '#fff' }} />
          </span>
          <b style={{ fontSize: 13.5 }}>{number}</b>
        </div>
        <div className="text-meta">현재: {currentLabel}</div>
      </div>

      <div style={{ textAlign: 'center', color: 'var(--muted)', margin: '10px 0' }}>↓</div>

      <div className="field">
        <label>새 배정 정보</label>
        <div className="row" style={{ gap: 8 }}>
          {(['TEAM', 'PERSONAL'] as const).map((m) => (
            <button
              key={m}
              type="button"
              className="btn"
              style={{
                flex: 1, justifyContent: 'center', fontWeight: 700,
                ...(mode === m
                  ? { background: 'var(--primary-soft)', borderColor: 'var(--primary)', color: 'var(--primary)' }
                  : undefined),
              }}
              aria-pressed={mode === m}
              onClick={() => setMode(m)}
            >
              {m === 'TEAM' ? '팀 배정' : '개인 배정'}
            </button>
          ))}
        </div>
      </div>

      <div className="field">
        <label>배정 팀 선택</label>
        <select value={teamId ?? ''} onChange={(e) => setTeamId(Number(e.target.value))} disabled={mode !== 'TEAM'}>
          {teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
      </div>

      <div className="field">
        <label>배정 개인 선택 (개인 배정 시)</label>
        <select value={userId ?? ''} onChange={(e) => setUserId(Number(e.target.value))} disabled={mode !== 'PERSONAL'}>
          {people.map((p) => <option key={p.id} value={p.id}>{p.team ? `${p.name} (${p.team})` : p.name}</option>)}
        </select>
      </div>

      <div className="field" style={{ marginBottom: 8 }}>
        <label>변경 사유 <span style={{ color: 'var(--tone-red)' }}>*</span></label>
        <textarea rows={2} placeholder="예: 부서 이동에 따른 카드 재배정" value={reason} onChange={(e) => setReason(e.target.value)} />
      </div>
      <div className="text-meta">배정 변경 내역은 카드 이력에 기록되며 되돌릴 수 없습니다.</div>
    </Modal>
  )
}
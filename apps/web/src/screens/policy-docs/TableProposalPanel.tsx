// 별표 승인 — 규정 문서에서 뽑은 한도표를 판정 임계값(`PolicyTable`)으로 승격한다.
//
// 이 화면의 존재 이유는 **자동 확정을 막는 것**이다. 승인하면 그 값은 `ctx.policy.*`가
// 되어 모든 정산 판정에 들어간다. 표 파싱은 셀 병합·줄바꿈 때문에 틀리기 쉽고, 축을
// 잘못 잡으면 에러 없이 항상 기본값으로 떨어진다(조용한 결함).
//
// 그래서 두 가지를 화면이 반드시 한다:
//   ① 표 원문을 **나란히** 보여준다 — 대조할 근거가 없으면 승인은 형식이 된다
//   ② 지금 누르면 걸릴 문제(`problems`)를 **누르기 전에** 보여준다
import { useState } from 'react'
import { AlertTriangle, Check, Table2, X } from 'lucide-react'
import type { AxisOption, PolicyTableProposal } from '../../types/domain'

const STATUS_META: Record<PolicyTableProposal['status'], { label: string; tone: string }> = {
  PENDING: { label: '승인 대기', tone: 'var(--tone-amber)' },
  APPROVED: { label: '승인됨', tone: 'var(--tone-green)' },
  REJECTED: { label: '반려', tone: 'var(--muted)' },
}

/** 중첩 payload를 사람이 고칠 수 있게 JSON 텍스트로 편다. 표 구조가 자유형식이라
 *  칸을 나눠 그리면 축이 2개인 표에서 곧 안 맞는다 — 원문 대조가 진짜 검증이다. */
function PayloadEditor({ value, onChange, disabled }: {
  value: Record<string, unknown>; onChange: (v: Record<string, unknown>) => void; disabled: boolean
}) {
  const [text, setText] = useState(() => JSON.stringify(value, null, 2))
  const [error, setError] = useState('')
  return (
    <div>
      <textarea
        className="pd-json" rows={10} value={text} disabled={disabled}
        onChange={(e) => {
          setText(e.target.value)
          try {
            const parsed = JSON.parse(e.target.value)
            setError('')
            onChange(parsed)
          } catch {
            // 저장은 막되 입력은 막지 않는다 — 타이핑 중간은 항상 깨진 JSON이다.
            setError('JSON 형식이 아직 올바르지 않아요')
          }
        }}
      />
      {error && <div className="text-meta" style={{ color: 'var(--tone-amber)' }}>{error}</div>}
    </div>
  )
}

function AxisPicker({ axes, options, onChange, disabled }: {
  axes: string[]; options: AxisOption[]; onChange: (v: string[]) => void; disabled: boolean
}) {
  return (
    <div>
      {axes.map((axis, i) => (
        <div key={i} className="row" style={{ gap: 6, marginBottom: 4 }}>
          <select
            value={axis} disabled={disabled}
            onChange={(e) => onChange(axes.map((a, j) => (j === i ? e.target.value : a)))}
          >
            {/* 목록에 없는 값(이전 적재의 잔재)도 선택지로 남긴다 — 안 그러면 화면이
                조용히 다른 축으로 바꿔버린다. */}
            {!options.some((o) => o.path === axis) && <option value={axis}>{axis} (알 수 없는 축)</option>}
            {options.map((o) => (
              <option key={o.path} value={o.path}>{o.section} · {o.path}</option>
            ))}
          </select>
          <button className="btn sm" disabled={disabled}
                  onClick={() => onChange(axes.filter((_, j) => j !== i))}>
            <X size={11} />
          </button>
        </div>
      ))}
      <div className="row" style={{ gap: 6 }}>
        <button className="btn sm" disabled={disabled || !options.length}
                onClick={() => onChange([...axes, options[0].path])}>
          축 추가
        </button>
        {axes.length === 0 && (
          <span className="text-meta">축 없음 — 표에 값이 하나뿐일 때 (payload는 {'{"value": 숫자}'})</span>
        )}
      </div>
    </div>
  )
}

/** 시행일이 비어 있으면 승인이 막힌다(서버 검사). 업로드 화면이 문서 시행일을 받지 않아
 *  실제로 전건이 그 상태였다 — 빈칸으로 두면 「고칠 것이 있다」는 사실조차 안 보이므로
 *  오늘로 채워 두고 사람이 고치게 한다. */
const TODAY = new Date().toISOString().slice(0, 10)

export function TableProposalCard({ proposal, axisOptions, busy, onSave, onDecide }: {
  proposal: PolicyTableProposal
  axisOptions: AxisOption[]
  busy: boolean
  onSave: (patch: Record<string, unknown>) => void
  onDecide: (action: 'APPROVE' | 'REJECT', note: string, patch?: Record<string, unknown>) => void
}) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState({
    key: proposal.key,
    title: proposal.title,
    keyAxes: proposal.keyAxes,
    payload: proposal.payload,
    strictKeys: proposal.strictKeys,
    effectiveDate: proposal.effectiveDate || TODAY,
  })
  const [note, setNote] = useState('')
  const [rejecting, setRejecting] = useState(false)
  const locked = proposal.status !== 'PENDING' || busy
  const meta = STATUS_META[proposal.status]

  return (
    <div className="pd-clause">
      <button type="button" className="pd-clause-head" onClick={() => setOpen(!open)}>
        <Table2 size={13} style={{ flexShrink: 0 }} />
        <span className="pd-clause-title">
          {proposal.sourceLabel || proposal.key || '이름 없는 표'}
          {proposal.title && <span className="text-meta"> · {proposal.title}</span>}
        </span>
        {proposal.problems.length > 0 && proposal.status === 'PENDING' && (
          <span className="pd-badge" style={{ background: 'var(--tone-amber-bg)', color: 'var(--tone-amber)' }}>
            확인 {proposal.problems.length}
          </span>
        )}
        <span className="pd-badge" style={{ color: meta.tone }}>{meta.label}</span>
        <span className="pd-caret">{open ? '⌃' : '⌄'}</span>
      </button>

      {!open && (
        <div className="pd-clause-peek">
          {proposal.status === 'APPROVED'
            ? `판정 변수 ${proposal.policyVar} 로 사용 중`
            : proposal.status === 'REJECTED'
              ? `반려 사유: ${proposal.reviewNote}`
              : `AI 확신도 ${Math.round(proposal.confidence * 100)}% · ${proposal.notes.slice(0, 60) || '표를 확인해 주세요'}`}
        </div>
      )}

      {open && (
        <div className="pd-clause-body">
          {/* ① 표 원문 — 대조 없이 승인하면 이 단계가 형식이 된다. */}
          <div className="text-meta">문서에 있는 표 원문 (p.{proposal.pageStart}~{proposal.pageEnd})</div>
          <pre className="pd-markdown">{proposal.rawMarkdown}</pre>

          {proposal.notes && (
            <div className="note" style={{ whiteSpace: 'pre-wrap' }}>
              <b>AI 메모</b> · 확신도 {Math.round(proposal.confidence * 100)}%
              <div>{proposal.notes}</div>
            </div>
          )}

          {/* ② 지금 누르면 걸릴 문제 — 누른 뒤가 아니라 누르기 전에. */}
          {proposal.status === 'PENDING' && proposal.problems.length > 0 && (
            <div className="note" style={{ borderColor: 'var(--tone-amber)', color: 'var(--tone-amber)' }}>
              <div className="row" style={{ gap: 6, alignItems: 'center' }}>
                <AlertTriangle size={13} /> <b>이대로는 승인할 수 없어요</b>
              </div>
              {proposal.problems.map((p, i) => <div key={i} style={{ marginTop: 4 }}>· {p}</div>)}
            </div>
          )}

          <div className="pd-field">
            <label>표 key</label>
            <input value={draft.key} disabled={locked}
                   onChange={(e) => setDraft({ ...draft, key: e.target.value })} />
            <div className="text-meta">
              판정에서 <code>policy.{(draft.key || '').replace(/_table$/, '')}</code> 로 쓰입니다
            </div>
          </div>

          <div className="pd-field">
            <label>표 이름</label>
            <input value={draft.title} disabled={locked}
                   onChange={(e) => setDraft({ ...draft, title: e.target.value })} />
          </div>

          <div className="pd-field">
            <label>축 — 이 표가 무엇으로 값을 고르는가</label>
            <AxisPicker axes={draft.keyAxes} options={axisOptions} disabled={locked}
                        onChange={(keyAxes) => setDraft({ ...draft, keyAxes })} />
          </div>

          <div className="pd-field">
            <label>표 내용</label>
            <PayloadEditor value={draft.payload} disabled={locked}
                           onChange={(payload) => setDraft({ ...draft, payload })} />
          </div>

          <div className="row" style={{ gap: 16, flexWrap: 'wrap' }}>
            <div className="pd-field" style={{ flex: '0 0 auto' }}>
              <label>시행일</label>
              <input type="date" value={draft.effectiveDate ?? ''} disabled={locked}
                     onChange={(e) => setDraft({ ...draft, effectiveDate: e.target.value })} />
            </div>
            <label className="row" style={{ gap: 6, alignItems: 'center' }}>
              <input type="checkbox" checked={draft.strictKeys} disabled={locked}
                     onChange={(e) => setDraft({ ...draft, strictKeys: e.target.checked })} />
              <span>축 값을 모르면 해소하지 않음
                <span className="text-meta"> (금지 목록처럼 「모르면 안전」이라 할 수 없는 표)</span>
              </span>
            </label>
          </div>

          {proposal.status === 'PENDING' && !rejecting && (
            <div className="row" style={{ gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
              <button className="btn" disabled={busy} onClick={() => onSave({ ...draft, effectiveDate: draft.effectiveDate || null })}>
                수정 저장
              </button>
              {/* 고친 값을 결정과 함께 보낸다 — 수정 저장을 잊어도 승인이 막히지 않는다. */}
              <button className="btn primary" disabled={busy}
                      onClick={() => onDecide('APPROVE', note,
                        { ...draft, effectiveDate: draft.effectiveDate || null })}>
                <Check size={11} /> 승인하고 판정에 반영
              </button>
              <button className="btn" disabled={busy} onClick={() => setRejecting(true)}>이 표는 임계값이 아님</button>
            </div>
          )}

          {rejecting && (
            <div className="pd-skipform">
              <label>이 표를 쓰지 않는 이유를 알려주세요</label>
              {/* 사유가 없으면 재색인 때 같은 표가 다시 올라와 같은 검토를 반복하게 된다. */}
              <textarea rows={2} value={note} autoFocus disabled={busy}
                        onChange={(e) => setNote(e.target.value)}
                        placeholder="예: 이건 결재선 서식이라 판정에 쓸 임계값이 없어요" />
              <div className="row" style={{ justifyContent: 'flex-end', gap: 6, marginTop: 8 }}>
                <button className="btn" disabled={busy} onClick={() => setRejecting(false)}>취소</button>
                <button className="btn primary" disabled={busy || !note.trim()}
                        onClick={() => { setRejecting(false); onDecide('REJECT', note.trim()) }}>
                  반려
                </button>
              </div>
            </div>
          )}

          {proposal.status !== 'PENDING' && (
            <div className="pd-decided">
              <div>
                <b>{meta.label}</b>
                {proposal.reviewNote && <> · {proposal.reviewNote}</>}
                {proposal.reviewedBy && <span className="text-meta"> · {proposal.reviewedBy}</span>}
                {proposal.status === 'APPROVED' && (
                  <div className="text-meta">
                    판정 변수 <code>{proposal.policyVar}</code> 로 사용 중입니다.
                    값을 바꾸려면 개정(새 시행일)으로 등록하세요.
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

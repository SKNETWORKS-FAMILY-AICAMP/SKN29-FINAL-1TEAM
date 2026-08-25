// 별표 승인 — 규정 문서에서 뽑은 한도표를 판정 임계값(`PolicyTable`)으로 승격한다.
//
// 이 화면의 존재 이유는 **자동 확정을 막는 것**이다. 승인하면 그 값은 `ctx.policy.*`가
// 되어 모든 정산 판정에 들어간다. 표 파싱은 셀 병합·줄바꿈 때문에 틀리기 쉽고, 축을
// 잘못 잡으면 에러 없이 항상 기본값으로 떨어진다(조용한 결함).
//
// 그래서 두 가지를 화면이 반드시 한다:
//   ① 표 원문을 **나란히** 보여준다 — 대조할 근거가 없으면 승인은 형식이 된다
//   ② 지금 누르면 걸릴 문제(`problems`)를 **누르기 전에** 보여준다
//   ③ **무엇을 승인하는지 사람 말로** 말한다(`comment`·`usageNote`). key·축·payload는
//      개발자 어휘라, 회계 담당자는 자기가 무엇에 서명하는지 알 수 없었다.
//
// `SKIPPED`는 AI가 "임계값 표가 아니다"라고 본 것이다. 조용히 버리지 않고 사유와 함께
// 남긴다 — 안 그러면 담당자는 「표가 있는데 왜 후보가 없지」를 스스로 알아내야 한다.
import { useState } from 'react'
import { AlertTriangle, Check, Table2, X } from 'lucide-react'
import type { AxisOption, PolicyTableProposal } from '../../types/domain'
import { Markdown } from '../../components/ui/Markdown'

const STATUS_META: Record<PolicyTableProposal['status'], { label: string; tone: string }> = {
  PENDING: { label: '승인 대기', tone: 'var(--tone-amber)' },
  APPROVED: { label: '승인됨', tone: 'var(--tone-green)' },
  REJECTED: { label: '반려', tone: 'var(--muted)' },
  SKIPPED: { label: '생성 안 함', tone: 'var(--muted)' },
}

const CHECK_TONE: Record<string, string> = {
  ok: 'var(--tone-green)', info: 'var(--muted)', warn: 'var(--tone-amber)',
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

/** 승인돼 저장된 임계값 표 — 축 개수에 따라 모양이 다르다.
 *
 *  자유형식 JSON을 그대로 보여주면(예전 상태) 승인 뒤에 남는 게 중괄호뿐이라 "내가 뭘
 *  승인했더라"를 확인할 길이 원문 대조밖에 없다. 축이 0~2개인 실제 모양만 그리고, 그보다
 *  깊으면 **접지 않고 JSON을 보여준다** — 잘못 접어 보여주느니 날것이 낫다.
 */
function ResolvedTable({ proposal }: { proposal: PolicyTableProposal }) {
  const axes = proposal.keyAxes ?? []
  const payload = (proposal.payload ?? {}) as Record<string, unknown>
  const label = (key: string) => (key === '*' ? '그 외(기본값)' : key)
  const cell = (v: unknown) =>
    typeof v === 'number' ? v.toLocaleString() : String(v ?? '—')

  if (axes.length === 0) {
    return (
      <div className="pd-resolved">
        <div className="text-meta">축 없음 — 모든 건에 같은 값</div>
        <b style={{ fontSize: 15 }}>{cell(payload.value)}</b>
      </div>
    )
  }

  if (axes.length === 1) {
    return (
      <div className="pd-resolved">
        <table className="table">
          <thead><tr><th>{axes[0]}</th><th className="num">값</th></tr></thead>
          <tbody>
            {Object.entries(payload).map(([k, v]) => (
              <tr key={k}>
                <td>{label(k)}</td>
                <td className="num">{cell(v)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }

  if (axes.length === 2) {
    //  두 번째 축의 값들을 열로 편다 — 행마다 열이 다를 수 있어 합집합을 쓴다.
    const cols = [...new Set(
      Object.values(payload).flatMap((row) =>
        row && typeof row === 'object' ? Object.keys(row as object) : []),
    )]
    return (
      <div className="pd-resolved" style={{ overflowX: 'auto' }}>
        <table className="table">
          <thead>
            <tr>
              <th>{axes[0]} \ {axes[1]}</th>
              {cols.map((c) => <th key={c} className="num">{label(c)}</th>)}
            </tr>
          </thead>
          <tbody>
            {Object.entries(payload).map(([k, row]) => (
              <tr key={k}>
                <td>{label(k)}</td>
                {cols.map((c) => (
                  <td key={c} className="num">
                    {cell((row as Record<string, unknown>)?.[c])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }

  return <pre className="pd-json">{JSON.stringify(payload, null, 2)}</pre>
}


export function TableProposalCard({ proposal, axisOptions, busy, onSave, onDecide, error }: {
  proposal: PolicyTableProposal
  axisOptions: AxisOption[]
  busy: boolean
  onSave: (patch: Record<string, unknown>) => void
  onDecide: (action: 'APPROVE' | 'REJECT', note: string, patch?: Record<string, unknown>) => void
  /** 이 제안의 결정 실패 사유. 카드 안에서 보여준다(상단 배너는 화면 밖일 수 있다). */
  error?: string
}) {
  const [open, setOpen] = useState(false)
  //  기본은 표. 원문은 렌더가 잘못 접혔는지 확인할 때만 편다.
  const [raw, setRaw] = useState(false)
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
        {proposal.checks.some((c) => c.level === 'warn') && proposal.status === 'PENDING' && (
          <span className="pd-badge" style={{ background: 'var(--tone-amber-bg)', color: 'var(--tone-amber)' }}>
            검사 {proposal.checks.filter((c) => c.level === 'warn').length}
          </span>
        )}
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
              : proposal.status === 'SKIPPED'
                ? proposal.skipReason || '임계값 표가 아니라고 판단했습니다.'
                //  접힌 상태에서 먼저 보여줄 것은 **사람 말 설명**이다. 확신도만 있으면
                //  담당자는 숫자를 보고도 무엇을 확인할지 모른다.
                : `${proposal.comment || proposal.notes || '표를 확인해 주세요'} (AI 확신도 ${Math.round(proposal.confidence * 100)}%)`}
        </div>
      )}

      {open && (
        <div className="pd-clause-body">
          {/* ① 표 원문 — 대조 없이 승인하면 이 단계가 형식이 된다.
              **마크다운 표로 그린다.** 파이프 문자가 그대로 보이면 셀 경계를 눈으로 세어야
              해서, 아래 추출 결과와 대조하는 데 시간이 걸린다(그러면 대충 누르게 된다).
              원문 그대로도 볼 수 있게 남긴다 — 렌더가 표를 잘못 접었을 때 확인할 길이
              없으면 안 된다. */}
          <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
            <span className="text-meta">
              문서에 있는 표 원문 (p.{proposal.pageStart}~{proposal.pageEnd})
            </span>
            <button className="btn sm" onClick={() => setRaw((v) => !v)}>
              {raw ? '표로 보기' : '원문 보기'}
            </button>
          </div>
          {raw
            ? <pre className="pd-markdown">{proposal.rawMarkdown}</pre>
            : <div className="pd-md-table"><Markdown source={proposal.rawMarkdown} /></div>}

          {/* AI가 표가 아니라고 본 건 여기서 끝난다 — 편집·승인 UI를 띄우지 않는다. */}
          {proposal.status === 'SKIPPED' && (
            <div className="note" style={{ whiteSpace: 'pre-wrap' }}>
              <b>임계값 표로 만들지 않았습니다</b>
              <div style={{ marginTop: 4 }}>{proposal.skipReason}</div>
              {proposal.comment && <div style={{ marginTop: 6 }}>{proposal.comment}</div>}
              <div className="text-meta" style={{ marginTop: 6 }}>
                판단이 틀렸다면 문서를 재색인하면 다시 계산됩니다.
              </div>
            </div>
          )}

          {/* ③ 무엇을 승인하는지 — 사람 말이 먼저, 개발자 어휘는 아래 편집 칸에. */}
          {proposal.status !== 'SKIPPED' && proposal.comment && (
            <div className="note" style={{ whiteSpace: 'pre-wrap' }}>
              <b>AI 코멘트</b> · 확신도 {Math.round(proposal.confidence * 100)}%
              <div style={{ marginTop: 4 }}>{proposal.comment}</div>
            </div>
          )}

          {proposal.status !== 'SKIPPED' && proposal.usageNote && (
            <div className="note" style={{ whiteSpace: 'pre-wrap' }}>
              <b>승인하면 이렇게 쓰입니다</b>
              <div style={{ marginTop: 4 }}>{proposal.usageNote}</div>
            </div>
          )}

          {/*  추출 시점 자동검사. **재시도로도 안 풀린 문제를 숨기지 않는다** —
              통과 항목까지 함께 보여야 "검사를 했다"는 사실이 전달된다. */}
          {proposal.status !== 'SKIPPED' && proposal.checks.length > 0 && (
            <div className="note">
              <b>자동 검사</b>
              {proposal.checks.map((c, i) => (
                <div key={i} style={{ marginTop: 4, color: CHECK_TONE[c.level] }}>
                  {c.level === 'warn' ? '⚠' : c.level === 'ok' ? '✓' : '·'} {c.message}
                </div>
              ))}
            </div>
          )}

          {proposal.status !== 'SKIPPED' && proposal.notes && (
            <div className="note" style={{ whiteSpace: 'pre-wrap' }}>
              <b>AI 메모</b>
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

          {error && (
            <div className="note" style={{ borderColor: 'var(--tone-red)', color: 'var(--tone-red)', whiteSpace: 'pre-wrap' }}>
              <div className="row" style={{ gap: 6, alignItems: 'center' }}>
                <AlertTriangle size={13} /> <b>처리하지 못했습니다</b>
              </div>
              <div style={{ marginTop: 4 }}>{error}</div>
            </div>
          )}

          {proposal.status === 'PENDING' && !rejecting && (
            <div className="row" style={{ gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
              <button className="btn" disabled={busy} onClick={() => onSave({ ...draft, effectiveDate: draft.effectiveDate || null })}>
                수정 저장
              </button>
              {/* ⚠️ 실패 사유를 **버튼 옆에** 둔다. 페이지 상단 배너로만 띄우면 목록을
                  스크롤해 내려온 사람에게는 화면 밖에서 뜬다 — "승인을 눌러도 아무 반응이
                  없다"로 보고된 증상이 그것이었다(서버는 400과 사유를 주고 있었다). */}
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
                  <>
                    <div className="text-meta">
                      판정 변수 <code>{proposal.policyVar}</code> 로 사용 중입니다.
                      값을 바꾸려면 개정(새 시행일)으로 등록하세요.
                    </div>
                    {/* **무엇이 저장됐는지**를 보여준다. 승인 뒤에 남는 게 한 줄 문장뿐이면
                        "내가 뭘 승인했더라"를 확인할 길이 원문 대조밖에 없다. */}
                    <ResolvedTable proposal={proposal} />
                  </>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

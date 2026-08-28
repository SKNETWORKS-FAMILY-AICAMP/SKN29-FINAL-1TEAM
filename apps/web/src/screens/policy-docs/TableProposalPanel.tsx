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
//
// 목록(TableProposalListRow)에서 표를 고르면 상세(TableProposalDetail)가 오른쪽에
// 뜬다 — 조항과 같은 목록→상세 패턴(ClauseAccordion.tsx 참고).
import { type ReactNode, useMemo, useRef, useState } from 'react'
import { AlertTriangle, Check, Table2, X } from 'lucide-react'
import type { AxisOption, PolicyTableProposal } from '../../types/domain'
import { Markdown } from '../../components/ui/Markdown'

/** 원문이 **진짜 GFM 표인지** 가리는 판별기. 구분선(---)이 없거나 못 알아보는 형식이면
 *  null이고, 그때는 표로 그리지 않고 원문(pre) 그대로 둔다 — 잘못 잘라 보여주는 것보다
 *  낫다. 그리는 일은 `Markdown`이 한다(원문에 표가 둘 이상이거나 표 밖 문장이 섞여도
 *  블록별로 나눠 그린다 — 여기서 헤더/행을 직접 쓰면 그 경우가 한 표로 뭉친다). */
function parseMarkdownTable(md: string): { headers: string[]; rows: string[][] } | null {
  const lines = md.split('\n').map((l) => l.trim()).filter((l) => l.startsWith('|'))
  if (lines.length < 2) return null
  const splitRow = (line: string) =>
    line.slice(1, line.endsWith('|') ? -1 : undefined).split('|').map((c) => c.trim())
  const sepCells = splitRow(lines[1])
  if (!sepCells.length || !sepCells.every((c) => /^:?-{2,}:?$/.test(c))) return null
  const headers = splitRow(lines[0])
  const rows = lines.slice(2).map(splitRow).filter((r) => r.some((c) => c))
  return rows.length ? { headers, rows } : null
}

const STATUS_META: Record<PolicyTableProposal['status'], { label: string; tone: string }> = {
  PENDING: { label: '승인 대기', tone: 'var(--tone-amber)' },
  APPROVED: { label: '승인됨', tone: 'var(--tone-green)' },
  REJECTED: { label: '반려', tone: 'var(--muted)' },
  SKIPPED: { label: '생성 안 함', tone: 'var(--muted)' },
}

/** 대기 → 그 외 → id 순 — **사람이 판단할 것이 먼저다.** AI가 「표가 아니다」라고 본
 *  건(`SKIPPED`)은 버리지 않되 맨 뒤로 보낸다. 목록 정렬과 상세가 같은 순서를 써야
 *  하므로 한 곳에만 둔다. */
const STATUS_RANK = { PENDING: 0, APPROVED: 1, REJECTED: 2, SKIPPED: 3 } as const
export function orderProposals(proposals: PolicyTableProposal[]): PolicyTableProposal[] {
  return [...proposals].sort((a, b) => STATUS_RANK[a.status] - STATUS_RANK[b.status] || a.id - b.id)
}

/** 축 경로(`tx.dining.headcount`)를 사람이 읽는 라벨로 바꾼다. 목록에 없는 축(이전
 *  적재의 잔재)은 원래 경로를 그대로 남긴다 — 조용히 다른 이름으로 보이면 안 된다. */
function axisLabel(path: string, options: AxisOption[]): string {
  return options.find((o) => o.path === path)?.section ?? path
}

/** "무엇으로 값을 고르는가"를 한 문장으로. 개발자 경로 대신 사람말 라벨을 쓴다 —
 *  DSL 경로는 `pd-resolved-ref`(하단 참조줄)에서만 보인다. */
function axisSentence(axes: string[], options: AxisOption[]): string {
  if (!axes.length) return '축 구분 없이 모든 정산 건에 같은 값이 적용돼요.'
  return `정산 건의 ${axes.map((a) => axisLabel(a, options)).join(' · ')}에 따라 값이 달라져요.`
}

/** AI 확신도를 문장 속 숫자가 아니라 제목 옆 작은 칩으로 — 읽는 정보가 아니라
 *  훑는 정보라서다. 낮을수록 눈에 띄어야 하니 색은 구간별로 다르게. */
function ConfidenceChip({ value }: { value: number }) {
  const pct = Math.round((value ?? 0) * 100)
  const tone = pct >= 80 ? 'green' : pct >= 50 ? 'amber' : 'red'
  return <span className={`pd-chip ${tone}`}>확신 {pct}%</span>
}

/** 셀 입력 문자열 → 저장값. 숫자로 읽히면 숫자로, 아니면 문자열 그대로 —
 *  회계 담당자가 "30,000" 대신 "30000"만 치면 되게 쉼표는 미리 걷어낸다. */
function parseCellValue(raw: string): unknown {
  const trimmed = raw.trim()
  if (trimmed === '') return ''
  const n = Number(trimmed.replace(/,/g, ''))
  return trimmed !== '' && Number.isFinite(n) ? n : raw
}

const cellText = (v: unknown) => (v === undefined || v === null ? '' : String(v))

/** 축이 0개인 표 — 값 하나. */
function SingleValueEditor({ value, onChange, disabled }: {
  value: Record<string, unknown>; onChange: (v: Record<string, unknown>) => void; disabled: boolean
}) {
  return (
    <input
      className="pd-grid-single" disabled={disabled} value={cellText(value.value)}
      onChange={(e) => onChange({ ...value, value: parseCellValue(e.target.value) })}
    />
  )
}

/** 축이 1개인 표 — 행 키·값 두 열의 편집 가능한 표. 행 순서를 배열로 들고 있어서
 *  키를 고치는 중에도(매 글자마다) 행이 재정렬되며 포커스를 잃지 않는다
 *  (Record를 바로 펼쳐 다시 만들면 rename이 곧 삭제+append라 순서가 흔들린다). */
function AxisTableEditor({ label, value, onChange, disabled }: {
  label: string; value: Record<string, unknown>; onChange: (v: Record<string, unknown>) => void; disabled: boolean
}) {
  const [rows, setRows] = useState(() => Object.entries(value).map(([k, v], id) => ({ id, key: k, value: cellText(v) })))
  const nextId = useRef(rows.length)
  const commit = (next: typeof rows) => {
    setRows(next)
    const payload: Record<string, unknown> = {}
    for (const r of next) if (r.key.trim()) payload[r.key] = parseCellValue(r.value)
    onChange(payload)
  }
  return (
    <table className="pd-grid">
      <thead><tr><th>{label}</th><th className="num">값</th><th /></tr></thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={r.id}>
            <td>
              <input value={r.key} disabled={disabled} placeholder="* = 그 외"
                     onChange={(e) => commit(rows.map((row, j) => (j === i ? { ...row, key: e.target.value } : row)))} />
            </td>
            <td>
              <input className="num" value={r.value} disabled={disabled}
                     onChange={(e) => commit(rows.map((row, j) => (j === i ? { ...row, value: e.target.value } : row)))} />
            </td>
            <td>
              <button className="btn sm" disabled={disabled} onClick={() => commit(rows.filter((_, j) => j !== i))}>
                <X size={11} />
              </button>
            </td>
          </tr>
        ))}
      </tbody>
      <tfoot>
        <tr>
          <td colSpan={3}>
            <button className="btn sm" disabled={disabled}
                    onClick={() => commit([...rows, { id: nextId.current++, key: '', value: '' }])}>
              행 추가
            </button>
          </td>
        </tr>
      </tfoot>
    </table>
  )
}

type GridCol = { id: number; key: string }
type GridRow2 = { id: number; key: string; cells: Record<number, string> }

/** 축이 2개인 표 — 행×열 그리드. 셀은 열 id로 찾는다(열 이름을 고치는 중에도 다른
 *  행의 값이 밀리지 않게 — 열 이름이 아니라 열 순서가 셀의 진짜 주소다). */
function Grid2Editor({ labels, value, onChange, disabled }: {
  labels: [string, string]; value: Record<string, unknown>; onChange: (v: Record<string, unknown>) => void; disabled: boolean
}) {
  const [{ rows, cols }, setState] = useState<{ rows: GridRow2[]; cols: GridCol[] }>(() => {
    const colKeys = [...new Set(
      Object.values(value).flatMap((r) => (r && typeof r === 'object' ? Object.keys(r as object) : [])),
    )]
    const cols: GridCol[] = colKeys.map((key, id) => ({ id, key }))
    const rows: GridRow2[] = Object.entries(value).map(([key, row], id) => ({
      id, key,
      cells: Object.fromEntries(cols.map((c) => [c.id, cellText(row && typeof row === 'object' ? (row as Record<string, unknown>)[c.key] : undefined)])),
    }))
    return { rows, cols }
  })
  const rowSeq = useRef(rows.length)
  const colSeq = useRef(cols.length)

  const commit = (rows: GridRow2[], cols: GridCol[]) => {
    setState({ rows, cols })
    const payload: Record<string, unknown> = {}
    for (const r of rows) {
      if (!r.key.trim()) continue
      const rowObj: Record<string, unknown> = {}
      for (const c of cols) if (c.key.trim()) rowObj[c.key] = parseCellValue(r.cells[c.id] ?? '')
      payload[r.key] = rowObj
    }
    onChange(payload)
  }

  return (
    <div className="pd-grid-scroll">
      <table className="pd-grid">
        <thead>
          <tr>
            <th title={`${labels[0]} \\ ${labels[1]}`}>{labels[0]} \ {labels[1]}</th>
            {cols.map((c, ci) => (
              <th key={c.id}>
                <input value={c.key} disabled={disabled}
                       onChange={(e) => commit(rows, cols.map((col, j) => (j === ci ? { ...col, key: e.target.value } : col)))} />
              </th>
            ))}
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map((r, ri) => (
            <tr key={r.id}>
              <td>
                <input value={r.key} disabled={disabled} placeholder="* = 그 외"
                       onChange={(e) => commit(rows.map((row, j) => (j === ri ? { ...row, key: e.target.value } : row)), cols)} />
              </td>
              {cols.map((c) => (
                <td key={c.id}>
                  <input className="num" disabled={disabled} value={r.cells[c.id] ?? ''}
                         onChange={(e) => commit(
                           rows.map((row, j) => (j === ri ? { ...row, cells: { ...row.cells, [c.id]: e.target.value } } : row)),
                           cols,
                         )} />
                </td>
              ))}
              <td>
                <button className="btn sm" disabled={disabled} onClick={() => commit(rows.filter((_, j) => j !== ri), cols)}>
                  <X size={11} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="row" style={{ gap: 6, marginTop: 6 }}>
        <button className="btn sm" disabled={disabled}
                onClick={() => commit([...rows, { id: rowSeq.current++, key: '', cells: {} }], cols)}>
          행 추가
        </button>
        <button className="btn sm" disabled={disabled}
                onClick={() => commit(rows, [...cols, { id: colSeq.current++, key: '' }])}>
          열 추가
        </button>
      </div>
    </div>
  )
}

/** 중첩 payload를 사람이 고칠 수 있게 JSON 텍스트로 편다. 축이 3개 이상인 드문 표만
 *  이 폼을 쓴다(0~2개는 위의 표 모양 그리드로 충분하다). */
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
function ResolvedTable({ proposal, axisOptions }: { proposal: PolicyTableProposal; axisOptions: AxisOption[] }) {
  const axes = proposal.keyAxes ?? []
  const payload = (proposal.payload ?? {}) as Record<string, unknown>
  const label = (key: string) => (key === '*' ? '그 외(기본값)' : key)
  const cell = (v: unknown) =>
    typeof v === 'number' ? v.toLocaleString() : String(v ?? '—')
  const field = (proposal.key || '').replace(/_table$/, '') || '이름 없음'

  //  **무엇이 되는지가 표보다 먼저다.** 숫자만 보면 「어느 판정 변수에 어떤 축으로
  //  들어가는가」를 알 수 없고, 그게 승인에서 실제로 판단할 것이다.
  //  사람말이 1번 줄, DSL 경로(`policy.xxx`·축 원문)는 참조용으로 맨 아래 작게 —
  //  개발자 어휘를 지우는 게 아니라(추적은 되어야 한다) 위계에서만 내린다.
  const head = (
    <div className="pd-resolved-head">
      <div className="pd-resolved-title">
        {proposal.title || proposal.sourceLabel || '이름 없는 표'}
        <ConfidenceChip value={proposal.confidence} />
      </div>
      <div className="pd-resolved-sub">
        {axisSentence(axes, axisOptions)}
        {proposal.effectiveDate && ` ${proposal.effectiveDate}부터 적용돼요.`}
        {proposal.strictKeys && ' 해당 사항을 모르면 이 표는 적용하지 않아요.'}
      </div>
      <div className="pd-resolved-ref">
        <code>policy.{field}</code>
        {axes.map((a) => (
          <span key={a} title={axisOptions.find((o) => o.path === a)?.desc}> · {a}</span>
        ))}
      </div>
    </div>
  )

  const wrap = (body: ReactNode, scroll = false) => (
    <div className="pd-resolved" style={scroll ? { overflowX: 'auto' } : undefined}>
      {head}
      {body}
    </div>
  )

  if (axes.length === 0) {
    return wrap(<div className="pd-resolved-single">{cell(payload.value)}</div>)
  }

  if (axes.length === 1) {
    return wrap(
      <table className="table">
          <thead><tr><th title={axes[0]}>{axisLabel(axes[0], axisOptions)}</th><th className="num">값</th></tr></thead>
          <tbody>
            {Object.entries(payload).map(([k, v]) => (
              <tr key={k}>
                <td>{label(k)}</td>
                <td className="num">{cell(v)}</td>
              </tr>
            ))}
          </tbody>
      </table>,
    )
  }

  if (axes.length === 2) {
    //  두 번째 축의 값들을 열로 편다 — 행마다 열이 다를 수 있어 합집합을 쓴다.
    const cols = [...new Set(
      Object.values(payload).flatMap((row) =>
        row && typeof row === 'object' ? Object.keys(row as object) : []),
    )]
    return wrap(
      <table className="table">
          <thead>
            <tr>
              <th title={`${axes[0]} \\ ${axes[1]}`}>
                {axisLabel(axes[0], axisOptions)} \ {axisLabel(axes[1], axisOptions)}
              </th>
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
      </table>,
      true,
    )
  }

  //  축이 셋 이상이면 표로 접지 않는다 — 잘못 접어 보여주느니 날것이 낫다.
  return wrap(<pre className="pd-json" style={{ marginTop: 6 }}>{JSON.stringify(payload, null, 2)}</pre>)
}

/** 목록 행 — 가운데 열에서 별표 하나를 고르는 자리. */
export function TableProposalListRow({ proposal, active, onSelect }: {
  proposal: PolicyTableProposal
  active: boolean
  onSelect: () => void
}) {
  const meta = STATUS_META[proposal.status]
  const warnChecks = proposal.checks.filter((c) => c.level === 'warn').length
  const peek = proposal.status === 'APPROVED'
    ? `판정 변수 ${proposal.policyVar} 로 사용 중`
    : proposal.status === 'REJECTED'
      ? `반려 사유: ${proposal.reviewNote}`
      : proposal.status === 'SKIPPED'
        ? proposal.skipReason || '임계값 표가 아니라고 판단했습니다.'
        : `${proposal.comment || proposal.notes || '표를 확인해 주세요'} · 확신 ${Math.round(proposal.confidence * 100)}%`

  return (
    <button type="button" className={'pd-list-row' + (active ? ' active' : '')} onClick={onSelect}>
      <span className="pd-list-row-title">
        <Table2 size={12} style={{ verticalAlign: -1, marginRight: 5, flexShrink: 0 }} />
        {proposal.sourceLabel || proposal.title || proposal.key || '이름 없는 표'}
      </span>
      <span className="pd-list-row-badges">
        {warnChecks > 0 && proposal.status === 'PENDING' && (
          <span className="pd-badge amber">검사 {warnChecks}</span>
        )}
        {/* 승인을 막는 문제라 통과 경고(위 배지, amber)와 색을 다르게 해 구분한다. */}
        {proposal.problems.length > 0 && proposal.status === 'PENDING' && (
          <span className="pd-badge red">확인 {proposal.problems.length}</span>
        )}
        <span className="pd-badge" style={{ color: meta.tone }}>{meta.label}</span>
      </span>
      <span className="pd-list-row-peek">{peek}</span>
    </button>
  )
}

/** 상세 패널 — 선택한 별표 하나의 처리 결과·근거·원문 대조·값 고치기·결정 버튼.
 *  목록에서 다른 표를 고르면(부모가 `key={proposal.id}`로 새로 마운트해) draft·note 같은
 *  내부 상태가 자연히 초기화된다. */
export function TableProposalDetail({ proposal, axisOptions, busy, onSave, onDecide, error }: {
  proposal: PolicyTableProposal
  axisOptions: AxisOption[]
  busy: boolean
  onSave: (patch: Record<string, unknown>) => void
  onDecide: (action: 'APPROVE' | 'REJECT', note: string, patch?: Record<string, unknown>) => void
  /** 이 제안의 결정 실패 사유. 패널 안에서 보여준다(페이지 상단 배너는 스크롤 밖일 수 있다). */
  error?: string
}) {
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
  const parsedTable = useMemo(() => parseMarkdownTable(proposal.rawMarkdown), [proposal.rawMarkdown])
  const pageLabel = proposal.pageStart === proposal.pageEnd
    ? `p.${proposal.pageStart}` : `p.${proposal.pageStart}~${proposal.pageEnd}`

  return (
    <div className="pd-detail-body">
      <div className="pd-detail-title-row">
        <h3 className="pd-detail-title" style={{ fontSize: 14 }}>
          <Table2 size={14} style={{ verticalAlign: -2, marginRight: 6 }} />
          {proposal.sourceLabel || proposal.title || proposal.key || '이름 없는 표'}
        </h3>
        <span className="pd-badge" style={{ color: meta.tone, flexShrink: 0 }}>{meta.label}</span>
      </div>

      {/*  **결론이 맨 위다.** 예전엔 표 원문 → 코멘트 → 활용안내 → 검사 → 메모 →
          문제 → 편집 폼 순서라, 「그래서 무슨 값이 들어가나」를 보려면 여섯 블록을
          지나야 했다. 지금은 **처리된 결과**를 먼저 그리고, 대조용 원문과 손볼 칸은
          접어 둔다(필요한 사람만 편다). */}

      {proposal.status === 'SKIPPED' ? (
        <div className="note" style={{ whiteSpace: 'pre-wrap' }}>
          <b>임계값 표로 만들지 않았습니다</b>
          <div style={{ marginTop: 4 }}>{proposal.skipReason}</div>
          {proposal.comment && <div style={{ marginTop: 6 }}>{proposal.comment}</div>}
          <div className="text-meta" style={{ marginTop: 6 }}>
            판단이 틀렸다면 문서를 재색인하면 다시 계산됩니다.
          </div>
        </div>
      ) : (
        <>
          {/* ① 처리된 결과 — 1·2축은 표로, 3축 이상은 JSON으로. 확신도는 제목 옆 칩. */}
          <ResolvedTable proposal={proposal} axisOptions={axisOptions} />

          {/* ② AI가 하는 말을 한 곳에 — 코멘트·통과한 자동검사·메모. 예전엔 이 셋이
              박스 3개로 항상 펼쳐져 있었다. 문제가 없으면 안 읽어도 되는 정보라
              기본은 접는다(승인/반려에 필요한 건 위 표뿐이다). */}
          {(() => {
            const passed = proposal.checks.filter((c) => c.level !== 'warn')
            if (!proposal.comment && !proposal.notes && !passed.length) return null
            return (
              <details className="pd-ai-fold">
                <summary>AI 설명 보기 <span className="text-meta">근거 · 검사결과</span></summary>
                <div className="pd-ai-fold-body">
                  {proposal.comment && <div className="pd-ai-line">{proposal.comment}</div>}
                  {passed.length > 0 && (
                    <div className="pd-ai-line">
                      자동 검사 {passed.length}건 통과 — {passed.map((c) => c.message).join(' · ')}
                    </div>
                  )}
                  {proposal.notes && <div className="pd-ai-line">{proposal.notes}</div>}
                </div>
              </details>
            )
          })()}

          {/* ③ 확인이 필요한 것 — 승인을 막진 않지만 눈에 띄어야 해서 접지 않는다. */}
          {proposal.checks.some((c) => c.level === 'warn') && (
            <div className="note" style={{ borderColor: 'var(--tone-amber)' }}>
              <div className="row" style={{ gap: 6, alignItems: 'center', color: 'var(--tone-amber)' }}>
                <AlertTriangle size={13} /> <b>확인이 필요합니다</b>
              </div>
              {proposal.checks.filter((c) => c.level === 'warn').map((c, i) => (
                <div key={i} style={{ marginTop: 4 }}>· {c.message}</div>
              ))}
            </div>
          )}

          {/* ④ 지금 누르면 걸릴 문제 — 누른 뒤가 아니라 누르기 전에. */}
          {proposal.status === 'PENDING' && proposal.problems.length > 0 && (
            <div className="note" style={{ borderColor: 'var(--tone-red)', color: 'var(--tone-red)' }}>
              <div className="row" style={{ gap: 6, alignItems: 'center' }}>
                <AlertTriangle size={13} /> <b>이대로는 승인할 수 없어요</b>
              </div>
              {proposal.problems.map((p, i) => <div key={i} style={{ marginTop: 4 }}>· {p}</div>)}
            </div>
          )}
        </>
      )}

      {/* ⑥ 표 원문 — **대조할 근거는 반드시 남긴다.** 다만 접어 둔다: 결과가 맞는지
          의심될 때만 펴면 되고, 늘 펼쳐 두면 패널이 길어져 결론이 안 보인다.
          GFM 표로 안 읽히는 원문은 그리지 않고 원문 그대로 둔다(잘못 잘라 보여주는
          것보다 파이프가 보이는 편이 낫다). */}
      <details className="pd-fold">
        <summary>
          문서 원문 대조 <span className="text-meta">{pageLabel}</span>
        </summary>
        {parsedTable && (
          <button className="btn sm" style={{ marginBottom: 8 }} onClick={() => setRaw((v) => !v)}>
            {raw ? '표로 보기' : '마크다운 원문'}
          </button>
        )}
        {raw || !parsedTable
          ? <pre className="pd-markdown">{proposal.rawMarkdown}</pre>
          : <div className="pd-md-table"><Markdown source={proposal.rawMarkdown} /></div>}
      </details>

      {/* ⑦ 손볼 칸 — 개발자 어휘(key·축·payload)는 여기 모아 접는다. 대부분의 승인은
          고칠 것이 없고, 늘 펼쳐 두면 「무엇을 승인하는가」보다 「어떻게 저장되는가」가
          패널을 차지한다. */}
      {proposal.status !== 'SKIPPED' && (
        <details className="pd-fold" open={proposal.problems.length > 0}>
          <summary>값 고치기</summary>

          {/* 사람 말(표 이름)이 넓게, 개발자 경로(key)는 좁고 참조용으로 — 한 줄에
              나란히 둔다(예전엔 두 줄을 다 차지해 「값 고치기」의 절반이 이름표였다). */}
          <div className="pd-field pd-field-row">
            <div style={{ flex: 2, minWidth: 0 }}>
              <label>표 이름</label>
              <input value={draft.title} disabled={locked}
                     onChange={(e) => setDraft({ ...draft, title: e.target.value })} />
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <label>표 key <span className="text-meta" style={{ fontWeight: 400 }}>· policy.{(draft.key || '').replace(/_table$/, '') || '—'}</span></label>
              <input className="mono" value={draft.key} disabled={locked}
                     onChange={(e) => setDraft({ ...draft, key: e.target.value })} />
            </div>
          </div>

          <div className="pd-field">
            <label>축 — 이 표가 무엇으로 값을 고르는가</label>
            <AxisPicker axes={draft.keyAxes} options={axisOptions} disabled={locked}
                        onChange={(keyAxes) => setDraft({ ...draft, keyAxes })} />
          </div>

          <div className="pd-field">
            <label>표 내용</label>
            {/* 축 0~2개는 표 모양 그대로 셀을 고친다 — JSON 문법을 몰라도 된다.
                축 3개 이상은 드문 경우라 JSON 폴백을 그대로 둔다. */}
            {draft.keyAxes.length === 0 && (
              <SingleValueEditor value={draft.payload} disabled={locked}
                                 onChange={(payload) => setDraft({ ...draft, payload })} />
            )}
            {draft.keyAxes.length === 1 && (
              <AxisTableEditor label={axisLabel(draft.keyAxes[0], axisOptions)} value={draft.payload} disabled={locked}
                               onChange={(payload) => setDraft({ ...draft, payload })} />
            )}
            {draft.keyAxes.length === 2 && (
              <Grid2Editor
                labels={[axisLabel(draft.keyAxes[0], axisOptions), axisLabel(draft.keyAxes[1], axisOptions)]}
                value={draft.payload} disabled={locked}
                onChange={(payload) => setDraft({ ...draft, payload })}
              />
            )}
            {draft.keyAxes.length >= 3 && (
              <PayloadEditor value={draft.payload} disabled={locked}
                             onChange={(payload) => setDraft({ ...draft, payload })} />
            )}
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
        </details>
      )}

      {error && (
        <div className="note" style={{ borderColor: 'var(--tone-red)', color: 'var(--tone-red)', whiteSpace: 'pre-wrap' }}>
          <div className="row" style={{ gap: 6, alignItems: 'center' }}>
            <AlertTriangle size={13} /> <b>처리하지 못했습니다</b>
          </div>
          <div style={{ marginTop: 4 }}>{error}</div>
        </div>
      )}

      {proposal.status === 'PENDING' && !rejecting && (
        <div className="pd-detail-actions">
          <button className="btn" disabled={busy} onClick={() => onSave({ ...draft, effectiveDate: draft.effectiveDate || null })}>
            수정 저장
          </button>
          {/* ⚠️ 실패 사유를 **버튼 옆에** 둔다. 페이지 상단 배너로만 띄우면 스크롤해
              내려온 사람에게는 화면 밖에서 뜬다 — "승인을 눌러도 아무 반응이 없다"로
              보고된 증상이 그것이었다(서버는 400과 사유를 주고 있었다). */}
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
  )
}
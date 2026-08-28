// 조항 — S-05 작업 중심 재구성.
//
// 목록(ClauseListRow)에서 조를 고르면 상세(ClauseDetail)가 오른쪽에 뜨는 목록→상세
// 패턴이다(예전엔 조마다 아코디언이 펼쳐졌다 — 조가 수십 개면 스크롤이 길어지고,
// 담당자가 지금 무엇을 보고 있는지 스크롤 위치로만 알 수 있었다).
//
// 담당자가 여기서 보는 것은 세 가지이고, 그게 곧 세 상태다:
//   · 규칙 연결됨   — 이 조항이 어떤 자동 판단으로 이어졌는지(쉬운 문장으로)
//   · 확인 필요     — 아직 아무 결정도 안 된 조항. 규칙을 만들지, 만들지 않을지 정해야 한다
//   · 규칙 생성 안 함 — 사람이 "안 만들겠다"고 정한 조항 + 그 사유
//
// 상태는 백엔드가 계산해서 준다(저장 안 함) — 룰은 나중에 생기고 지워지므로.
import { type ReactNode, useState } from 'react'
import { Check, Copy, X } from 'lucide-react'
import {
  CLAUSE_KIND_META, CLAUSE_STATUS_META, PRIORITY_META,
  type ClauseRuleStatus, type PolicyClause,
} from '../../types/domain'

/** AI가 매긴 룰 생성 우선순위. 사람의 결정(`ruleStatus`)과 **나란히** 놓는다 —
 *  한 배지로 합치면 "AI가 제외로 봤다"와 "사람이 제외로 정했다"가 구분되지 않는다.
 *  색·모양은 화면 전체가 공유하는 `.pd-badge`(policy-docs.css)를 그대로 쓴다 —
 *  여기서 따로 만들면 별표 카드(TableProposalPanel)의 배지와 미묘하게 달라진다. */
export function PriorityBadge({ clause }: { clause: PolicyClause }) {
  if (!clause.triagePriority && !clause.triageKind) return null
  const meta = PRIORITY_META[clause.triagePriority]
  const kind = CLAUSE_KIND_META[clause.triageKind]?.label
  return (
    <span className={`pd-status-text ${meta.tone}`} title={clause.triageReason}>
      {kind && clause.triagePriority === 'SKIP' ? kind : meta.label}
    </span>
  )
}

export function StatusBadge({ status }: { status: ClauseRuleStatus }) {
  const meta = CLAUSE_STATUS_META[status]
  return <span className={`pd-status-text ${meta.tone}`}>{meta.label}</span>
}

function CopyButton({ text }: { text: string }) {
  const [done, setDone] = useState(false)
  return (
    <button
      className="btn sm"
      onClick={() => {
        void navigator.clipboard?.writeText(text)
        setDone(true)
        setTimeout(() => setDone(false), 1500)
      }}
    >
      {done ? <Check size={11} /> : <Copy size={11} />} {done ? '복사됨' : '복사'}
    </button>
  )
}

function SkipForm({ onCancel, onSubmit, busy }: {
  onCancel: () => void; onSubmit: (reason: string) => void; busy: boolean
}) {
  const [reason, setReason] = useState('')
  return (
    <div className="pd-skipform">
      <label>규칙을 만들지 않는 이유를 알려주세요</label>
      <textarea
        rows={3} value={reason} onChange={(e) => setReason(e.target.value)} disabled={busy}
        placeholder="예: 이 조항은 예외 승인 절차라 자동 판단보다 담당자 확인이 더 적절하다고 판단했어요"
        autoFocus
      />
      <div className="row" style={{ justifyContent: 'flex-end', gap: 6, marginTop: 8 }}>
        <button className="btn" onClick={onCancel} disabled={busy}>취소</button>
        {/* 사유가 없으면 저장할 수 없다 — 나중에 "왜 규칙이 없지"를 묻는 사람이 반드시 나온다. */}
        <button className="btn primary" disabled={busy || !reason.trim()} onClick={() => onSubmit(reason.trim())}>
          결정 완료
        </button>
      </div>
    </div>
  )
}

// 청킹이 주는 `articleTitle`은 조 라벨을 **이미 포함한 전체 헤딩**이다("제1조 (목적)").
// 그걸 모르고 `라벨 + (제목)`으로 조합하면 "제1조(제1조 (목적))"이 된다(실측으로 잡음).
// 라벨이 빠진 제목이 올 수도 있으므로 양쪽 모양을 다 받는다. 목록 행과 상세 패널이
// 같은 헤딩을 써야 하므로 한 곳(함수)에만 둔다.
function clauseHeading(clause: PolicyClause): string {
  const title = clause.articleTitle?.trim() ?? ''
  if (!title) return clause.articleLabel
  if (title.startsWith(clause.articleLabel)) return title
  return `${clause.articleLabel} ${title.startsWith('(') ? title : `(${title})`}`
}

function clausePeek(clause: PolicyClause): string {
  if (clause.ruleStatus === 'SKIPPED' && clause.decisionReason) return `결정 사유: ${clause.decisionReason}`
  if (clause.triageSummary) return clause.triageSummary
  return `${clause.body.replace(/^#+\s*/gm, '').replace(/\s+/g, ' ').slice(0, 70)}...`
}

/** "이 문서의 조항 내용 찾기" 검색이 조 라벨·제목·원문 어디에 걸렸는지 판정한다.
 *  목록 필터링과 하이라이트가 **같은 기준**을 써야 "검색됐는데 안 보인다"가 안 생긴다. */
export function clauseMatchesQuery(clause: PolicyClause, query: string): boolean {
  const q = query.trim().toLowerCase()
  if (!q) return true
  return (
    clauseHeading(clause).toLowerCase().includes(q)
    || clause.body.toLowerCase().includes(q)
  )
}

/** 일치하는 모든 구간을 `<mark>`로 감싼다. 쿼리가 비어 있으면 원문 문자열 그대로 반환한다
 *  (평소엔 아무 것도 감싸지 않아 렌더링 비용·DOM 구조가 검색 전과 같다). */
function highlightAll(text: string, query: string): ReactNode {
  const q = query.trim()
  if (!q) return text
  const lower = text.toLowerCase()
  const qLower = q.toLowerCase()
  const parts: ReactNode[] = []
  let cursor = 0
  let idx = lower.indexOf(qLower)
  while (idx !== -1) {
    if (idx > cursor) parts.push(text.slice(cursor, idx))
    parts.push(<mark key={idx}>{text.slice(idx, idx + q.length)}</mark>)
    cursor = idx + q.length
    idx = lower.indexOf(qLower, cursor)
  }
  parts.push(text.slice(cursor))
  return parts
}

/** 목록 행 미리보기 — 검색어가 있으면 본문에서 일치 지점 주변으로 스니펫을 다시 자른다.
 *  기본 미리보기(`clausePeek`)는 항상 앞 70자라, 일치 지점이 그보다 뒤에 있으면
 *  하이라이트가 화면에 아예 안 보이는 문제가 있었다. */
function clausePeekFor(clause: PolicyClause, query: string): ReactNode {
  const q = query.trim()
  if (!q) return clausePeek(clause)
  const body = clause.body.replace(/^#+\s*/gm, '').replace(/\s+/g, ' ')
  const idx = body.toLowerCase().indexOf(q.toLowerCase())
  if (idx === -1) return clausePeek(clause)
  const start = Math.max(0, idx - 20)
  const end = Math.min(body.length, idx + q.length + 40)
  const snippet = (start > 0 ? '…' : '') + body.slice(start, end) + (end < body.length ? '…' : '')
  return highlightAll(snippet, q)
}

/** 목록 행 — 가운데 열에서 조 하나를 고르는 자리. 본문은 여기서 보여주지 않는다
 *  (한 줄 미리보기만) — 본문·근거·결정 버튼은 오른쪽 상세 패널의 몫이다. */
/** 목록 행 — "확인 필요"가 16개 중 12개처럼 **기본값**인 탭에서는, 행마다 같은 배지를
 *  반복하는 게 정보가 아니라 잡음이었다(실사용 화면 리뷰로 확인). 배지·테두리색을 없애고
 *  굵기·명도만으로 나눈다: 기본(확인 필요)은 진하게, **이미 처리된 소수**(연결됨·제외)만
 *  흐리게 눌러 자연히 대비로 도드라지게 한다 — 새 색을 쓰지 않는다(`--muted`만 재사용). */
export function ClauseListRow({ clause, active, query = '', onSelect }: {
  clause: PolicyClause
  active: boolean
  /** "이 문서의 조항 내용 찾기" 검색어 — 있으면 제목·미리보기에 하이라이트한다. */
  query?: string
  onSelect: () => void
}) {
  const resolved = clause.ruleStatus !== 'NEEDS_REVIEW'
  const peek = query.trim() ? clausePeekFor(clause, query) : null
  return (
    <button
      type="button"
      className={'pd-list-row' + (active ? ' active' : '') + (resolved ? ' resolved' : '')}
      onClick={onSelect}
    >
      <span className="pd-list-row-top">
        <span className="pd-list-row-title">{highlightAll(clauseHeading(clause), query)}</span>
        {resolved && <span className="pd-list-row-note">{CLAUSE_STATUS_META[clause.ruleStatus].label}</span>}
      </span>
      {peek && <span className="pd-list-row-peek">{peek}</span>}
    </button>
  )
}

/** 원본 조항 — 파싱이 준 그대로 줄바꿈만 있고 번호·하위 항목 구분이 없어 한 덩어리
 *  문단처럼 보였다(실사용 화면 리뷰로 확인). 단어는 하나도 안 바꾸고 **표시만** 정돈한다:
 *  "1./2./3."로 시작하는 줄은 새 항목(마커를 굵게, 위 여백을 더), 그 아래 번호 없는
 *  줄은 그 항목의 하위 목록으로 보고 살짝 들여쓰기 + 가운뎃점을 붙인다(가운뎃점은 CSS
 *  장식일 뿐 실제 텍스트에는 없다). 번호가 아예 없는 조항(라벨: 설명 나열형 등)은
 *  전부 하위 취급 없이 문단으로만 나눈다. */
function ClauseBody({ text, query }: { text: string; query: string }) {
  const lines = text.split('\n').map((l) => l.trim()).filter(Boolean)
  let sawNumbered = false
  return (
    <div className="pd-clause-body">
      {lines.map((line, i) => {
        const m = line.match(/^(\d+\.)\s*(.*)$/)
        if (m) {
          sawNumbered = true
          return (
            <p key={i} className="pd-clause-line num">
              <b className="pd-clause-marker">{m[1]}</b> {highlightAll(m[2], query)}
            </p>
          )
        }
        return (
          <p key={i} className={'pd-clause-line' + (sawNumbered ? ' sub' : '')}>
            {highlightAll(line, query)}
          </p>
        )
      })}
    </div>
  )
}

/** 상세 패널 — 선택한 조 하나의 원문·AI 근거·연결된 규칙·결정 버튼. 목록에서 다른
 *  조를 고르면(부모가 `key={clause.id}`로 이 컴포넌트를 새로 마운트해) `skipping` 같은
 *  내부 상태가 자연히 초기화된다 — 여기서 직접 리셋할 필요가 없다. */
export function ClauseDetail({ clause, query = '', onSkip, onReset, onCreateRule, busy }: {
  clause: PolicyClause
  query?: string
  onSkip: (reason: string) => void
  onReset: () => void
  onCreateRule: () => void
  busy: boolean
}) {
  const [skipping, setSkipping] = useState(false)

  return (
    <div className="pd-detail-body">
      <div className="pd-detail-title-row">
        <h3 className="pd-detail-title">{highlightAll(clauseHeading(clause), query)}</h3>
        <span className="row" style={{ gap: 6, flexShrink: 0 }}>
          <PriorityBadge clause={clause} />
          <StatusBadge status={clause.ruleStatus} />
        </span>
      </div>

      {/* AI 분류 근거 — 별표 상세의 "AI 설명 보기"와 같은 관용구로 통일한다. 분류
          배지(위)는 이미 보이니, 왜 그렇게 분류했는지는 필요한 사람만 펴서 본다. */}
      {clause.triageReason && (
        <details className="pd-ai-fold">
          <summary>
            AI 설명 보기
            <span className="text-meta" style={{ fontWeight: 400 }}>
              {CLAUSE_KIND_META[clause.triageKind]?.label || '분류 없음'}
              {clause.triagePriority && ` · ${PRIORITY_META[clause.triagePriority].label}`}
            </span>
          </summary>
          <div className="pd-ai-fold-body">
            <div className="pd-ai-line">{clause.triageReason}</div>
            {clause.triageSummary && <div className="pd-ai-line">만들 규칙: {clause.triageSummary}</div>}
          </div>
        </details>
      )}

      <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center', marginTop: 14 }}>
        <span className="text-meta">원본 조항</span>
        <CopyButton text={clause.body} />
      </div>
      <ClauseBody text={clause.body} query={query} />

      {clause.ruleStatus === 'LINKED' && (
        <div className="pd-linked">
          <b>이렇게 자동으로 판단돼요</b>
          {clause.linkedRules.map((rule) => (
            <div key={`${rule.graphId}-${rule.nodeKey}`} style={{ marginTop: 8 }}>
              {/* conditionText는 "언제 걸리나요/걸리면 어떻게 되나요" 문장이다(DSL 아님). */}
              {(rule.conditionText || rule.title).split('\n').map((line, i) => (
                <div key={i} className="pd-linked-line">· {line}</div>
              ))}
              <a className="pd-link" href={`/rules?graph=${rule.graphId}&node=${rule.nodeKey}`}>
                {rule.title || rule.nodeKey} 자세히 보기 →
              </a>
            </div>
          ))}
        </div>
      )}

      {clause.ruleStatus === 'NEEDS_REVIEW' && !skipping && (
        <div className="pd-decide">
          <p>
            {clause.triagePriority === 'SKIP'
              // AI가 규칙 대상이 아니라고 본 조항. **차단하지 않는다** — 모델이 못
              // 알아본 규칙이 반드시 있고, 통로가 없으면 그 조항은 영영 룰이 못 된다.
              ? 'AI는 규칙 대상이 아니라고 봤어요. 그래도 필요하면 직접 만들 수 있어요.'
              : '이 조항은 아직 자동 판단 규칙이 없어요. 규칙을 만들지, 만들지 않을지 결정해주세요.'}
          </p>
          <div className="row" style={{ gap: 8 }}>
            <button className={'btn' + (clause.triagePriority === 'SKIP' ? '' : ' primary')}
                    onClick={onCreateRule} disabled={busy}>규칙 생성하기</button>
            <button className="btn" onClick={() => setSkipping(true)} disabled={busy}>
              규칙 생성 안 함으로 표시
            </button>
          </div>
        </div>
      )}

      {skipping && (
        <SkipForm
          busy={busy}
          onCancel={() => setSkipping(false)}
          onSubmit={(reason) => { setSkipping(false); onSkip(reason) }}
        />
      )}

      {clause.ruleStatus === 'SKIPPED' && !skipping && (
        <div className="pd-decided">
          <div>
            <b>결정 사유:</b> {clause.decisionReason}
            {clause.decidedBy && <span className="text-meta"> · {clause.decidedBy}</span>}
          </div>
          <div className="row" style={{ gap: 6 }}>
            {/* 「안 만들겠다」고 정한 뒤에도 만들 수 있다 — 결정은 되돌릴 수 있어야 한다. */}
            <button className="btn sm" onClick={onCreateRule} disabled={busy}>규칙 생성하기</button>
            <button className="btn sm" onClick={onReset} disabled={busy}>
              <X size={11} /> 수정
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
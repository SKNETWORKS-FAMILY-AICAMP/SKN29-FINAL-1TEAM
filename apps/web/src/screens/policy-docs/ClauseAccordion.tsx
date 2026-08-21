// 조항 아코디언 — 목업 S-05 v4 ③ 우측 패널.
//
// 조 하나가 하나의 카드다. 담당자가 여기서 보는 것은 세 가지이고, 그게 곧 세 상태다:
//   · 규칙 연결됨   — 이 조항이 어떤 자동 판단으로 이어졌는지(쉬운 문장으로)
//   · 확인 필요     — 아직 아무 결정도 안 된 조항. 규칙을 만들지, 만들지 않을지 정해야 한다
//   · 규칙 생성 안 함 — 사람이 "안 만들겠다"고 정한 조항 + 그 사유
//
// 상태는 백엔드가 계산해서 준다(저장 안 함) — 룰은 나중에 생기고 지워지므로.
import { useState } from 'react'
import { Check, Copy, X } from 'lucide-react'
import {
  CLAUSE_STATUS_META, type ClauseRuleStatus, type PolicyClause,
} from '../../types/domain'

const TONE = {
  green: { bg: 'var(--tone-green-bg)', color: 'var(--tone-green)', border: '#bfe6d1' },
  amber: { bg: 'var(--tone-amber-bg)', color: 'var(--tone-amber)', border: '#e8d5a3' },
  gray: { bg: 'var(--surface-muted)', color: 'var(--muted)', border: 'var(--border-strong)' },
}

function StatusBadge({ status }: { status: ClauseRuleStatus }) {
  const meta = CLAUSE_STATUS_META[status]
  const t = TONE[meta.tone]
  return (
    <span style={{ padding: '2px 8px', borderRadius: 999, fontSize: 11, fontWeight: 700, background: t.bg, color: t.color, border: `1px solid ${t.border}`, whiteSpace: 'nowrap' }}>
      {meta.label}
    </span>
  )
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

export function ClauseCard({ clause, expanded, onToggle, onSkip, onReset, onCreateRule, busy }: {
  clause: PolicyClause
  expanded: boolean
  onToggle: () => void
  onSkip: (reason: string) => void
  onReset: () => void
  onCreateRule: () => void
  busy: boolean
}) {
  const [skipping, setSkipping] = useState(false)
  // 청킹이 주는 `articleTitle`은 조 라벨을 **이미 포함한 전체 헤딩**이다("제1조 (목적)").
  // 그걸 모르고 `라벨 + (제목)`으로 조합하면 "제1조(제1조 (목적))"이 된다(실측으로 잡음).
  // 라벨이 빠진 제목이 올 수도 있으므로 양쪽 모양을 다 받는다.
  const title = clause.articleTitle?.trim() ?? ''
  const heading = !title
    ? clause.articleLabel
    : title.startsWith(clause.articleLabel)
      ? title
      : `${clause.articleLabel} ${title.startsWith('(') ? title : `(${title})`}`

  return (
    <div className={'pd-clause' + (expanded && clause.ruleStatus === 'NEEDS_REVIEW' ? ' pd-clause-attn' : '')}>
      <button type="button" className="pd-clause-head" onClick={onToggle}>
        <span className="pd-clause-title">{heading}</span>
        <StatusBadge status={clause.ruleStatus} />
        <span className="pd-caret">{expanded ? '⌃' : '⌄'}</span>
      </button>

      {!expanded && (
        <div className="pd-clause-peek">
          {clause.ruleStatus === 'SKIPPED' && clause.decisionReason
            ? `결정 사유: ${clause.decisionReason}`
            : `${clause.body.replace(/^#+\s*/gm, '').replace(/\s+/g, ' ').slice(0, 60)}...`}
        </div>
      )}

      {expanded && (
        <div className="pd-clause-body">
          <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
            <span className="text-meta">원본 조항 (Markdown)</span>
            <CopyButton text={clause.body} />
          </div>
          <pre className="pd-markdown">{clause.body}</pre>

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
              <p>이 조항은 아직 자동 판단 규칙이 없어요. 규칙을 만들지, 만들지 않을지 결정해주세요.</p>
              <div className="row" style={{ gap: 8 }}>
                <button className="btn primary" onClick={onCreateRule} disabled={busy}>규칙 생성하기</button>
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
              <button className="btn sm" onClick={onReset} disabled={busy}>
                <X size={11} /> 수정
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

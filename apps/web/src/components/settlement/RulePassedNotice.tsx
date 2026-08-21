// 「이상탐지를 거치지 않았다」를 사실대로 알리는 안내 — 검토 화면 ①이상탐지 카드 자리.
//
// 룰 판정이 `PASS`를 내면 정산은 **승인 대기로 바로 간다**. Risk Review(이상탐지 +
// RAG 내규검증)는 `IN_REVIEW`로 넘어간 건에만 붙으므로(`risk_review.schedule`),
// 이 건들에는 anomaly_score가 **아예 없다**.
//
// 그 자리를 `0.00`으로 채우면 "이상 없음 0점"으로 읽힌다 — 아무도 안 본 건을 검토된
// 것처럼 보여주는 셈이다. 그래서 점수는 `-`로 두고, **대신 무엇이 이 건을 통과시켰는지**
// (어느 그래프의 어느 노드를 지났는지)를 보여준다. 확정 버튼을 누르는 사람이 근거 없이
// 누르지 않게 하는 게 이 카드의 목적이다.
import { ShieldCheck } from 'lucide-react'
import type { RuleDecision, Settlement } from '../../types/domain'
import { decisionLabel } from '../../lib/judgement'

export function RulePassedNotice({ item }: { item: Settlement }) {
  const hits = item.ruleHits ?? []

  return (
    <div className="stack" style={{ gap: 10 }}>
      <div className="row" style={{ gap: 8, alignItems: 'flex-start' }}>
        <ShieldCheck size={16} color="var(--tone-green)" style={{ flexShrink: 0, marginTop: 2 }} />
        <div>
          <div style={{ fontWeight: 700, fontSize: 13 }}>룰 판정으로 통과된 건입니다</div>
          <div className="text-meta" style={{ lineHeight: 1.5 }}>
            결정론적 규칙 검사를 모두 통과해 <b>이상탐지·RAG 내규검증을 거치지 않았습니다</b>.
            AI 위험도 점수가 없는 것이 정상입니다 — 아래 판정 경로가 이 건의 근거입니다.
          </div>
        </div>
      </div>

      {hits.length > 0 ? (
        <div className="stack" style={{ gap: 6 }}>
          <div className="text-meta">판정 경로</div>
          {hits.map((h, i) => (
            <div
              key={i}
              style={{
                fontSize: 12, background: 'var(--surface-2)',
                borderRadius: 'var(--radius-control)', padding: '8px 10px',
              }}
            >
              <div className="row" style={{ justifyContent: 'space-between' }}>
                {/* 그래프가 없어도 한 행이 남는다 — "적용할 규칙이 없었다"도 판정 기록이다. */}
                <b>{h.graph ?? '적용 그래프 없음'}{h.graph ? ` v${h.graphVersion}` : ''}</b>
                <span>{decisionLabel(h.decision as RuleDecision)}</span>
              </div>
              {h.path?.length > 0 && (
                <div className="text-meta" style={{ fontFamily: 'monospace', marginTop: 4, wordBreak: 'break-all' }}>
                  {h.path.join(' → ')}
                </div>
              )}
            </div>
          ))}
        </div>
      ) : (
        <div className="text-meta">판정 경로 기록이 없습니다(판정 전이거나 기록이 남지 않은 건).</div>
      )}
    </div>
  )
}

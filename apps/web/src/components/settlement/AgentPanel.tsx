// 초안 Agent 진행 상태 · 설명 · 안내 — 정산 상세 모달 우측 상단.
//
//  **진행률을 꾸며내지 않는다.** 비전 판독은 실제로 수십 초가 걸리므로, 퍼센트 대신
//  지금 무엇을 하는 중인지를 단계로 보여준다(가짜 진행 바는 멈춘 것보다 나쁘다 —
//  끝나지 않는데 90%에서 서 있으면 사용자는 고장으로 읽는다).
//
//  안내(notice)의 `level`은 **서버가 정한다**. 화면이 규칙을 갖고 있으면 서버와 갈린다.
//   · blocker — 지금 제출하면 되돌아온다(RETURN/REJECT 예상)
//   · warn    — 사람이 봐야 한다(문장이 과하게 바뀜, 정보 부족)
//   · info    — 알고만 있으면 된다. **REVIEW는 여기다**(회계가 보는 정상 경로).
import { AlertTriangle, CheckCircle2, Info, Loader2, Sparkles } from 'lucide-react'
import type { DraftNotice, JudgementPreview } from '../../api/settlementService'

export type AgentPhase = '' | 'saving' | 'reading' | 'drafting'

const PHASE_TEXT: Record<Exclude<AgentPhase, ''>, { title: string; detail: string }> = {
  saving: { title: '지출 건을 등록하는 중…', detail: '영수증을 서버에 올리고 있습니다.' },
  reading: {
    title: '영수증을 판독하는 중…',
    detail: '가맹점·금액·품목을 읽고 있습니다. 문서에 따라 수십 초 걸릴 수 있습니다.',
  },
  drafting: { title: '초안을 작성하는 중…', detail: '판독한 사실로 분류와 지출 목적을 채우고 있습니다.' },
}

const LEVEL_STYLE: Record<DraftNotice['level'], { tone: string; Icon: typeof Info }> = {
  blocker: { tone: 'red', Icon: AlertTriangle },
  warn: { tone: 'amber', Icon: AlertTriangle },
  info: { tone: 'blue', Icon: Info },
}

/** 판정 미리보기 한 줄. **엔진이 낸 값이지 모델이 예측한 값이 아니다.** */
function JudgementLine({ judgement }: { judgement: JudgementPreview }) {
  if (!judgement.available) {
    return (
      <div className="text-meta">
        판정 미리보기를 확인하지 못했습니다{judgement.error ? ` (${judgement.error})` : ''}.
      </div>
    )
  }
  const map: Record<string, { text: string; tone: string }> = {
    PASS: { text: '통과 — 회계 확정 대기로 넘어갑니다', tone: 'green' },
    REVIEW: { text: '회계 검토 — 담당자가 직접 확인하는 정상 경로입니다', tone: 'blue' },
    RETURN: { text: '보완요청 예상 — 지금 제출하면 되돌아옵니다', tone: 'amber' },
    REJECT: { text: '반려 예상 — 지금 제출하면 최종 반려될 수 있습니다', tone: 'red' },
  }
  const row = map[judgement.decision] ?? { text: `판정 결과: ${judgement.decision || '미정'}`, tone: 'gray' }
  const graph = judgement.graphs?.[judgement.graphs.length - 1]
  return (
    <div>
      <span className="tag" style={{
        color: `var(--tone-${row.tone})`, background: `var(--tone-${row.tone}-bg)`, borderColor: 'transparent',
      }}>
        {row.text}
      </span>
      {graph && (
        <div className="text-meta" style={{ marginTop: 4 }}>
          {graph.name} v{graph.version} · 경로 {graph.path.join(' → ') || '—'}
        </div>
      )}
    </div>
  )
}

export function AgentPanel({
  phase, error, reasoning, notices, judgement,
}: {
  phase: AgentPhase
  error?: string
  reasoning?: string
  notices: DraftNotice[]
  judgement: JudgementPreview | null
}) {
  const busy = phase !== ''
  if (!busy && !error && !reasoning && notices.length === 0 && !judgement) return null

  return (
    <div className="card">
      <div className="card-head">
        <h3><Sparkles size={13} style={{ verticalAlign: '-2px' }} /> 초안 Agent</h3>
        {busy && <span className="tag ai"><Loader2 size={11} className="spin" /> 진행 중</span>}
      </div>
      <div className="card-body stack" style={{ gap: 10 }}>
        {busy && (
          <div className="row" style={{ gap: 8, alignItems: 'flex-start' }}>
            <Loader2 size={16} className="spin" style={{ marginTop: 2, flexShrink: 0 }} />
            <div>
              <div style={{ fontWeight: 600, fontSize: 13 }}>{PHASE_TEXT[phase].title}</div>
              <div className="text-meta">{PHASE_TEXT[phase].detail}</div>
            </div>
          </div>
        )}

        {/* 실패는 폴백으로 덮지 않는다 — 사유를 그대로 보여주고 사람이 직접 채우게 한다. */}
        {error && (
          <div className="row" style={{ gap: 8, alignItems: 'flex-start', color: 'var(--tone-red)' }}>
            <AlertTriangle size={15} style={{ marginTop: 2, flexShrink: 0 }} />
            <div style={{ fontSize: 13 }}>{error}</div>
          </div>
        )}

        {!busy && reasoning && (
          <div style={{ fontSize: 13, lineHeight: 1.6 }}>{reasoning}</div>
        )}

        {!busy && judgement && <JudgementLine judgement={judgement} />}

        {!busy && notices.length > 0 && (
          <ul className="stack" style={{ gap: 6, listStyle: 'none', padding: 0, margin: 0 }}>
            {notices.map((n, i) => {
              const { tone, Icon } = LEVEL_STYLE[n.level] ?? LEVEL_STYLE.info
              return (
                <li key={`${n.code}-${i}`} className="row" style={{ gap: 7, alignItems: 'flex-start' }}>
                  <Icon size={14} style={{ marginTop: 2, flexShrink: 0, color: `var(--tone-${tone})` }} />
                  <div style={{ fontSize: 13 }}>
                    <b>{n.label}</b>
                    {n.owner ? <span className="text-meta"> · {n.owner}</span> : null}
                    <div style={{ marginTop: 2 }}>{n.text}</div>
                  </div>
                </li>
              )
            })}
          </ul>
        )}

        {!busy && !error && notices.length === 0 && judgement?.available && judgement.decision === 'PASS' && (
          <div className="row" style={{ gap: 7, color: 'var(--tone-green)', fontSize: 13 }}>
            <CheckCircle2 size={14} /> 확인이 필요한 사항이 없습니다.
          </div>
        )}
      </div>
    </div>
  )
}

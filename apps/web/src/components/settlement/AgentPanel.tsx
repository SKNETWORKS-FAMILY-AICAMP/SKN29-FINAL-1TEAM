// AI 작업 카드 — **한 번의 AI 실행이 낸 것을 한 자리에서 보여준다.**
//
//  예전엔 둘로 갈려 있었다: 상단 「초안 Agent」 패널(진행·설명·안내)과 하단 「AI 코멘트」
//  로그. 같은 실행의 결과가 두 카드에 나뉘어 떠서, 사용자는 위아래를 오가며 맞춰 봐야 했다.
//  갈린 이유는 의도가 달라서가 아니라 **출력 구조가 달랐기 때문**이다 — 하단은
//  `{icon, text}` 평문뿐이라 안내 등급·플래그 라벨·판정 배지를 담을 수 없었다.
//
//  ## 누적되는 것과 교체되는 것을 구분한다 (이 컴포넌트의 핵심)
//
//   · **누적(logs)**  — "영수증을 올렸다", "증빙 3건을 읽었다" 같은 **일어난 일**. 쌓인다.
//   · **교체(reasoning·notices·judgement)** — "지금 이 건은 이렇다"는 **현재 상태**.
//     새 실행이 오면 갈아끼운다. 안 그러면 이미 고친 문제를 계속 지적한다.
//
//  호출부가 이 구분을 지켜야 한다 — `logs`는 push, 나머지는 set.
//
//  ## 진행 표시는 헤더에도 둔다
//
//  이 카드는 화면 **아래쪽**이라 저장→판독→초안이 도는 동안 스크롤 밖일 수 있다.
//  그래서 헤더 배지로도 알린다. 진행률은 꾸며내지 않는다 — 단계만 말한다.
import {
  AlertTriangle, CheckCircle2, FileText, Info, Loader2, Receipt, Sparkles,
} from 'lucide-react'
import type { DraftNotice, JudgementPreview } from '../../api/settlementService'

export type AgentPhase = '' | 'saving' | 'reading' | 'drafting'

/** 누적 로그 한 줄 — 무엇이 일어났는지. */
export interface AgentLog {
  icon: 'ocr' | 'doc' | 'ai'
  text: string
}

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

const LOG_ICON = {
  ocr: <Receipt size={11} />,
  doc: <FileText size={11} />,
  ai: <Sparkles size={11} />,
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
  phase, error, reasoning, notices, judgement, logs, readOnly, readOnlyNote,
}: {
  phase: AgentPhase
  error?: string
  /** 왜 이렇게 했는지 — 실행마다 **교체**된다. */
  reasoning?: string
  /** 판정 사유 안내 — 실행마다 **교체**된다. */
  notices: DraftNotice[]
  /** 엔진 dry-run 결과 — 실행마다 **교체**된다. */
  judgement: JudgementPreview | null
  /** 무엇이 일어났는지 — **누적**된다. */
  logs: AgentLog[]
  readOnly?: boolean
  readOnlyNote?: string
}) {
  const busy = phase !== ''
  const hasState = Boolean(reasoning) || notices.length > 0 || Boolean(judgement)

  return (
    <div className="card">
      <div className="card-head">
        <h3><Sparkles size={13} style={{ verticalAlign: '-2px' }} /> AI 코멘트</h3>
        {/*  카드가 화면 아래쪽이라 진행 중인 걸 헤더에서도 알 수 있어야 한다. */}
        {busy && <span className="tag ai"><Loader2 size={11} className="spin" /> 진행 중</span>}
      </div>
      <div className="card-body stack" style={{ gap: 10 }}>
        {/* ── 진행 ── */}
        {busy && (
          <div className="row" style={{ gap: 8, alignItems: 'flex-start' }}>
            <Loader2 size={16} className="spin" style={{ marginTop: 2, flexShrink: 0 }} />
            <div>
              <div style={{ fontWeight: 600, fontSize: 13 }}>{PHASE_TEXT[phase].title}</div>
              <div className="text-meta">{PHASE_TEXT[phase].detail}</div>
            </div>
          </div>
        )}

        {/*  실패는 폴백으로 덮지 않는다 — 사유를 그대로 보여주고 사람이 직접 채우게 한다. */}
        {error && (
          <div className="row" style={{ gap: 8, alignItems: 'flex-start', color: 'var(--tone-red)' }}>
            <AlertTriangle size={15} style={{ marginTop: 2, flexShrink: 0 }} />
            <div style={{ fontSize: 13 }}>{error}</div>
          </div>
        )}

        {/* ── 현재 상태(교체) ── */}
        {!busy && reasoning && <div style={{ fontSize: 13, lineHeight: 1.6 }}>{reasoning}</div>}
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

        {!busy && !error && hasState && notices.length === 0
          && judgement?.available && judgement.decision === 'PASS' && (
          <div className="row" style={{ gap: 7, color: 'var(--tone-green)', fontSize: 13 }}>
            <CheckCircle2 size={14} /> 확인이 필요한 사항이 없습니다.
          </div>
        )}

        {/* ── 일어난 일(누적) ── */}
        {logs.length > 0 && (
          <ul
            className="stack"
            style={{
              gap: 8, listStyle: 'none', padding: hasState || busy ? '10px 0 0' : 0, margin: 0,
              borderTop: hasState || busy ? '1px solid var(--border)' : undefined,
            }}
          >
            {logs.map((c, i) => (
              <li key={i} className="row" style={{ gap: 8, alignItems: 'flex-start' }}>
                <span className="tag ai" style={{ flexShrink: 0 }}>{LOG_ICON[c.icon]}</span>
                <span style={{ fontSize: 12.5, lineHeight: 1.5 }}>{c.text}</span>
              </li>
            ))}
          </ul>
        )}

        {/* ── 빈 상태 ── */}
        {!busy && !error && !hasState && logs.length === 0 && (
          <div className="text-meta">
            {readOnly
              ? (readOnlyNote || '조회 전용 화면입니다.')
              : '영수증·증빙을 업로드하거나 AI 버튼을 누르면 무엇을 반영해 어디를 수정했는지 안내합니다.'}
          </div>
        )}
      </div>
    </div>
  )
}

// Risk Review(이상탐지 + RAG 내규검증) 진행 상태 표시 — 검토 화면 ①·② 카드 자리.
//
// **「결과가 없다」는 세 가지 다른 상황을 뭉갠다.** 결과 유무만 보면 검토 중인 건에
// "룰 판정으로 통과된 건입니다"라는 안내가 뜬다(실제로 겪은 오표시). 그래서 서버가
// 상태를 기록하고(`Settlement.risk_review_state`) 화면은 그걸 그대로 읽는다:
//
//   NOT_STARTED  룰이 통과시켜 **검토 대상이 아니다** → 판정 경로가 근거다
//   RUNNING      예약돼 **돌고 있다**(최대 60초) → 기다리는 중임을 명시하고 폴링한다
//   FAILED       돌았는데 결과를 못 받았다 → **오지 않을 결과를 기다리게 두지 않는다**
//   DONE         결과가 있다 → 호출부가 실제 결과를 그린다
import { AlertTriangle, Loader2, RefreshCw, ShieldCheck } from 'lucide-react'
import type { RiskReviewState, Settlement } from '../../types/domain'
import { RulePassedNotice } from './RulePassedNotice'

/** 목록 위험도 셀 표기 — 점수가 없을 때 무엇을 보여줄지. */
export function riskScoreLabel(state: RiskReviewState | undefined, score: number): string {
  if (state === 'DONE') return String(Math.round(score * 100))
  if (state === 'RUNNING') return '…'
  return '-'
}

export function riskScoreTitle(state: RiskReviewState | undefined): string | undefined {
  switch (state) {
    case 'RUNNING': return 'AI 위험 검토가 진행 중입니다'
    case 'FAILED': return 'AI 위험 검토가 실패했습니다 — 재실행이 필요합니다'
    case 'NOT_STARTED': return '룰 판정으로 통과돼 위험 검토를 거치지 않은 건입니다'
    default: return undefined
  }
}

/**
 * ①이상탐지 카드의 본문 — `DONE`이 아닐 때 무엇을 보여줄지.
 * `DONE`이면 이 컴포넌트를 쓰지 않고 호출부가 실제 결과를 그린다.
 */
export function RiskReviewStatusBody({
  item, onRetry, retrying = false,
}: {
  item: Settlement
  /** 실패 건 재실행 — 없으면 버튼을 띄우지 않는다(권한이 없는 화면도 있다). */
  onRetry?: () => void
  retrying?: boolean
}) {
  const state = item.riskReviewState ?? 'NOT_STARTED'

  if (state === 'RUNNING') {
    return (
      <div className="row" style={{ gap: 10, alignItems: 'flex-start' }}>
        <Loader2 size={18} className="spin" color="var(--tone-blue)" style={{ flexShrink: 0, marginTop: 2 }} />
        <div>
          <div style={{ fontWeight: 700, fontSize: 13 }}>AI 위험 검토를 진행 중입니다</div>
          <div className="text-meta" style={{ lineHeight: 1.5 }}>
            이상탐지(1차)와 RAG 내규검증(2차)이 순서대로 돌고 있습니다 — <b>보통 수십 초</b>가
            걸립니다. 결과가 도착하면 이 화면이 자동으로 갱신됩니다.
            <br />
            <b>아직 결론이 나오지 않았습니다</b> — 지금 보이는 값으로 판단하지 마세요.
          </div>
        </div>
      </div>
    )
  }

  if (state === 'FAILED') {
    return (
      <div className="row" style={{ gap: 10, alignItems: 'flex-start' }}>
        <AlertTriangle size={18} color="var(--tone-red)" style={{ flexShrink: 0, marginTop: 2 }} />
        <div style={{ minWidth: 0 }}>
          <div style={{ fontWeight: 700, fontSize: 13 }}>AI 위험 검토가 실패했습니다</div>
          <div className="text-meta" style={{ lineHeight: 1.5 }}>
            결과가 오지 않았습니다. <b>AI 결과 없이</b> 증빙과 판정 사유만 보고 판단하시거나,
            아래에서 다시 실행해 주세요.
          </div>
          {item.riskReviewError && (
            <div className="text-meta" style={{ marginTop: 4, wordBreak: 'break-all' }}>
              사유: {item.riskReviewError}
            </div>
          )}
          {onRetry && (
            <button className="btn sm" style={{ marginTop: 8 }} onClick={onRetry} disabled={retrying}>
              <RefreshCw size={12} /> {retrying ? '재실행 중…' : '위험 검토 다시 실행'}
            </button>
          )}
        </div>
      </div>
    )
  }

  // NOT_STARTED — 룰이 통과시켜 검토 대상이 아니다. 판정 경로가 근거가 된다.
  return <RulePassedNotice item={item} />
}

/** 카드 헤더의 anomaly 배지 — 상태에 따라 값·색이 갈린다. */
export function RiskScoreBadge({ item }: { item: Settlement & { anomalyScore: number } }) {
  const state = item.riskReviewState ?? 'NOT_STARTED'
  if (state === 'DONE') {
    return (
      <span className="tag" style={{ color: 'var(--tone-purple)', background: 'var(--tone-purple-bg)' }}>
        anomaly {item.anomalyScore.toFixed(2)}
      </span>
    )
  }
  if (state === 'RUNNING') {
    return (
      <span className="tag" style={{ color: 'var(--tone-blue)', background: 'var(--tone-blue-bg)' }}>
        <Loader2 size={11} className="spin" /> 검토 중
      </span>
    )
  }
  if (state === 'FAILED') {
    return <span className="tag caution"><AlertTriangle size={11} /> 검토 실패</span>
  }
  return <span className="tag" style={{ color: 'var(--muted)' }}><ShieldCheck size={11} /> anomaly -</span>
}

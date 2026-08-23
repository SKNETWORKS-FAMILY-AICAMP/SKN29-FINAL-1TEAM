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
//
// **`DONE` 안에도 「못 잰 경우」가 있다.** 호출은 성공했는데 1차 이상탐지만 못 돈 건이
// 실재한다(모델 미배치·경로 어긋남). 그때 서버는 `anomalyStatus`를 `no_model`/`error`로
// 주고 점수 0·등급 빈 문자열을 보낸다 — 화면은 **0.00을 그리지 않는다.** 0을 그리면
// 「검사해보니 안전」으로 읽히는데, 실제로는 검사를 못 한 것이다.
import { AlertTriangle, Loader2, RefreshCw, ShieldCheck } from 'lucide-react'
import type { RiskReviewState, Settlement } from '../../types/domain'
import { RulePassedNotice } from './RulePassedNotice'

/** 1차 이상탐지가 실제로 채점했는가. 빈 값·`ok`가 아니면 점수를 믿을 수 없다. */
export function anomalyScored(item: Pick<Settlement, 'anomalyStatus'>): boolean {
  const status = item.anomalyStatus
  return !status || status === 'ok'
}

/** 목록 위험도 셀 표기 — 점수가 없을 때 무엇을 보여줄지. */
export function riskScoreLabel(
  state: RiskReviewState | undefined, score: number, scored = true,
): string {
  if (state === 'DONE') return scored ? String(Math.round(score * 100)) : '-'
  if (state === 'RUNNING') return '…'
  return '-'
}

export function riskScoreTitle(
  state: RiskReviewState | undefined, item?: Pick<Settlement, 'anomalyStatus' | 'anomalyNote'>,
): string | undefined {
  //  못 잰 이유가 있으면 그걸 먼저 보여준다 — 「-」만 있으면 왜인지 알 수 없다.
  if (state === 'DONE' && item && !anomalyScored(item)) {
    return item.anomalyNote || '이상탐지가 실행되지 않아 위험 점수가 없습니다'
  }
  switch (state) {
    case 'RUNNING': return 'AI 위험 검토가 진행 중입니다'
    case 'FAILED': return 'AI 위험 검토가 실패했습니다 — 재실행이 필요합니다'
    case 'NOT_STARTED': return '룰 판정으로 통과돼 위험 검토를 거치지 않은 건입니다'
    default: return undefined
  }
}

/**
 * ①이상탐지 카드 자리 — **결과는 왔는데 1차만 못 돈** 건의 본문.
 * 2차 RAG 검증은 정상적으로 돌았으므로 그 사실도 함께 말한다.
 */
export function AnomalyUnavailableNotice({ item }: { item: Settlement }) {
  return (
    <div className="row" style={{ gap: 10, alignItems: 'flex-start' }}>
      <AlertTriangle size={18} color="var(--tone-amber)" style={{ flexShrink: 0, marginTop: 2 }} />
      <div>
        <div style={{ fontWeight: 700, fontSize: 13 }}>이상탐지 점수를 계산하지 못했습니다</div>
        <div className="text-meta" style={{ marginTop: 4 }}>
          {item.anomalyNote || '학습된 이상탐지 모델이 없습니다.'}
        </div>
        <div className="text-meta" style={{ marginTop: 6 }}>
          <b>점수 0이 아니라 「측정 못 함」입니다</b> — 이상 신호가 낮다는 뜻이 아닙니다.
          아래 ② 내규 검증 결과와 룰 판정으로 검토해 주세요.
        </div>
      </div>
    </div>
  )
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
    //  결과는 왔는데 1차만 못 돈 건 — `0.00`을 그리면 「이상 없음」으로 읽힌다.
    if (!anomalyScored(item)) {
      return (
        <span className="tag caution" title={item.anomalyNote || undefined}>
          <AlertTriangle size={11} /> anomaly 측정 안 됨
        </span>
      )
    }
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

// ③ Risk Review Agent 실험실 — 운영과 같은 `risk_review_agent.run()`을 그대로 부른다
//  (1차 이상탐지 → 2차 RAG 내규 검증). 부작용 없음: FastAPI는 Postgres에 쓰지 않는다
//  (RiskReview 저장은 Django `services.judge`의 커밋-후 콜백 몫) — 몇 번을 돌려도
//  검토 큐·판정 결과는 그대로다.
import { useState } from 'react'
import { Play } from 'lucide-react'
import { labApi, labErrorMessage, type RiskRunLabResponse } from './data/labApi'
import { Collapsible, EmptyHint, ErrorBanner, FactRow, JsonBlock } from './components/LabPrimitives'

export function RiskLab() {
  const [settlementId, setSettlementId] = useState('')
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')
  const [res, setRes] = useState<RiskRunLabResponse | null>(null)

  const run = async () => {
    const id = Number(settlementId)
    if (!id) { setError('정산 id를 숫자로 입력하세요.'); return }
    setRunning(true)
    setError('')
    try {
      setRes(await labApi.runRisk(id))
    } catch (err) {
      setError(labErrorMessage(err))
    } finally {
      setRunning(false)
    }
  }

  const s1 = res?.result.stage1_anomaly as {
    anomaly_score?: number; risk_tier?: string; percentile_band?: string; calibrated_rate?: number
    contribs?: unknown[]
  } | undefined
  const s2 = res?.result.stage2_rag_review as {
    violation_verdict?: string; recommendation?: string; review_reasons?: string[]; citations?: unknown[]
    similar_cases?: unknown[]
  } | undefined

  return (
    <div className="stack-lg">
      <div className="card">
        <div className="card-head"><h3>실행 입력</h3></div>
        <div className="card-body">
          <div className="field" style={{ marginBottom: 0 }}>
            <label>정산 id</label>
            <input
              value={settlementId}
              onChange={(e) => setSettlementId(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') void run() }}
              placeholder="예) 475"
              inputMode="numeric"
            />
          </div>
          <div className="text-meta" style={{ marginTop: 8 }}>
            상태와 무관하게 어떤 정산 id든 재현·비교용으로 돌려볼 수 있습니다(운영에서는 판정이
            `IN_REVIEW`로 보낸 건에만 자동 호출됩니다).
          </div>
        </div>
        <div className="lab-runbar">
          <button className="btn primary" onClick={run} disabled={running}>
            <Play size={13} /> {running ? '실행 중…' : '실행'}
          </button>
        </div>
      </div>

      {error && <ErrorBanner message={error} />}
      {!res && !error && (
        <EmptyHint>정산 id를 넣고 실행하면 1차 이상탐지 점수와 2차 RAG 검증 결과가 함께 나옵니다.</EmptyHint>
      )}

      {res && s1 && s2 && (
        <>
          <div className="card">
            <div className="card-head"><h3>1차 이상탐지</h3></div>
            <div className="card-body">
              <FactRow
                items={[
                  ['anomaly_score', s1.anomaly_score?.toFixed(4) ?? '—'],
                  ['risk_tier', s1.risk_tier || '—'],
                  ['percentile_band', s1.percentile_band || '—'],
                  ['calibrated_rate', s1.calibrated_rate != null ? `${(s1.calibrated_rate * 100).toFixed(1)}%` : '—'],
                  ['feature 기여도', s1.contribs?.length ? `${s1.contribs.length}개` : '없음(모델에 feature_stats 없음)'],
                  ['지연', `${res.latencyMs}ms`],
                ]}
              />
            </div>
          </div>

          <div className="card">
            <div className="card-head">
              <h3>2차 RAG 내규 검증</h3>
              <span className={'tag' + (s2.violation_verdict === 'VIOLATION' ? ' warn' : '')}>
                {s2.violation_verdict || '—'}
              </span>
            </div>
            <div className="card-body">
              <FactRow items={[['권고', s2.recommendation || '—']]} />
              {!!s2.review_reasons?.length && (
                <>
                  <div className="lab-subhead">검토 사유</div>
                  <ul className="lab-list">{s2.review_reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
                </>
              )}
              <div className="stack" style={{ marginTop: 12 }}>
                {!!s2.citations?.length && (
                  <Collapsible title="RAG 인용" meta={`${s2.citations.length}건`} defaultOpen>
                    <JsonBlock value={s2.citations} label="citations" maxHeight={240} />
                  </Collapsible>
                )}
                {!!s2.similar_cases?.length && (
                  <Collapsible title="유사 과거 사례" meta={`${s2.similar_cases.length}건`}>
                    <JsonBlock value={s2.similar_cases} label="similar_cases" maxHeight={200} />
                  </Collapsible>
                )}
              </div>
            </div>
          </div>

          <div className="card">
            <div className="card-head"><h3>전체 응답</h3></div>
            <div className="card-body">
              <JsonBlock value={res} label="POST /api/ai-lab/risk/run" maxHeight={420} />
            </div>
          </div>
        </>
      )}
    </div>
  )
}

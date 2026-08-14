// apps/web/src/risk_review_v0/ReviewListV0.tsx
// Review List v0 — 독립 개발 화면(별도 라우트 /risk-review-v0, 메인 네비게이션 미연결).
// 승인/보완/반려는 기존 상태 전이 서비스(Django services.review)를 그대로 태운다 — 새 판정
// 로직은 여기 없다. v0 알려진 한계: featureContribs는 이 pkl 세대엔 feature_stats가 없어
// 빈 배열일 수 있다(CLAUDE.md 참조). 재학습 트리거 없음(FR-RL-02, post-MVP).
import { useEffect, useState } from 'react'
import { isAxiosError } from 'axios'
import { won } from '../lib/format'
import { riskReviewV0Api, type Decision, type ReviewListItem } from './api'

const VERDICT_BADGE: Record<string, { label: string; cls: string }> = {
  VIOLATION: { label: '위반의심', cls: 'tone-red' },
  NO_VIOLATION: { label: '정상', cls: 'tone-green' },
  INSUFFICIENT_INFO: { label: '정보부족', cls: 'tone-amber' },
}

function VerdictBadge({ verdict }: { verdict?: string }) {
  const info = verdict ? VERDICT_BADGE[verdict] : undefined
  if (!info) return <span className="tag">미검증</span>
  return (
    <span className="tag" style={{ color: `var(--${info.cls})`, background: `var(--${info.cls}-bg)` }}>
      {info.label}
    </span>
  )
}

export function ReviewListV0() {
  const [items, setItems] = useState<ReviewListItem[]>([])
  const [selectedId, setSelectedId] = useState<number | undefined>(undefined)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [reasonDraft, setReasonDraft] = useState('')

  const load = () => {
    setLoading(true)
    setError('')
    riskReviewV0Api
      .list()
      .then((res) => {
        setItems(res.data)
        setSelectedId((prev) => prev ?? res.data[0]?.id)
      })
      .catch((e) => {
        const detail = isAxiosError(e) ? e.response?.data?.detail : undefined
        setError(detail || (isAxiosError(e) && e.response?.status === 403
          ? '회계 검토 권한이 없습니다.'
          : '목록을 불러오지 못했습니다.'))
      })
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  const selected = items.find((i) => i.id === selectedId)

  const decide = async (decision: Decision) => {
    if (!selected) return
    if (decision !== 'APPROVE' && !reasonDraft.trim()) {
      setError('보완요청·반려는 사유 입력이 필수입니다.')
      return
    }
    setBusy(true)
    setError('')
    try {
      await riskReviewV0Api.decide(selected.id, decision, reasonDraft.trim() || undefined)
      setReasonDraft('')
      setItems((prev) => prev.filter((i) => i.id !== selected.id))
      setSelectedId(undefined)
    } catch (e) {
      const detail = isAxiosError(e) ? e.response?.data?.detail : undefined
      setError(detail || '처리에 실패했습니다.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page">
      <div className="page-head">
        <h1>Review List <span className="screen-id">v0</span></h1>
        <div className="sub">IN_REVIEW 건 · anomaly_score 내림차순 · 독립 개발(risk_review_v0) — 메인 네비게이션 미연결</div>
      </div>

      {error && <div className="note" style={{ borderColor: 'var(--tone-red)', color: 'var(--tone-red)', marginBottom: 12 }}>{error}</div>}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.2fr', gap: 16, alignItems: 'start' }}>
        <div className="card">
          <div className="card-head"><h3>대기 {items.length}건</h3></div>
          <div className="card-body" style={{ padding: 0 }}>
            {loading && <div className="text-meta" style={{ padding: 16 }}>불러오는 중…</div>}
            {!loading && items.length === 0 && <div className="text-meta" style={{ padding: 16 }}>검토 대기 건이 없습니다.</div>}
            <table className="table">
              <tbody>
                {items.map((item) => (
                  <tr
                    key={item.id}
                    className={item.id === selectedId ? 'anomaly-row' : undefined}
                    style={{ cursor: 'pointer' }}
                    onClick={() => { setSelectedId(item.id); setReasonDraft('') }}
                  >
                    <td>#{item.id}</td>
                    <td>{item.merchant}</td>
                    <td>{won(item.amount)}</td>
                    <td>{item.category}</td>
                    <td>{item.anomalyScore.toFixed(2)}</td>
                    <td><VerdictBadge verdict={item.violationVerdict} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="card">
          {!selected ? (
            <div className="card-body text-meta">건을 선택하세요.</div>
          ) : (
            <>
              <div className="card-head">
                <h3>#{selected.id} · {selected.merchant}</h3>
                <span className="tag" style={{ color: 'var(--tone-purple)', background: 'var(--tone-purple-bg)' }}>
                  anomaly {selected.anomalyScore.toFixed(2)}
                </span>
              </div>
              <div className="card-body stack" style={{ gap: 12 }}>
                <div>{won(selected.amount)} · {selected.category} · {selected.submittedBy}</div>
                <div className="text-meta">{selected.purpose || '(목적 미기재)'}</div>

                <div>
                  <VerdictBadge verdict={selected.violationVerdict} />
                  {selected.recommendation && <span className="tag" style={{ marginLeft: 8 }}>권장: {selected.recommendation}</span>}
                </div>

                {(selected.stage2Verdict.review_reasons?.length ?? 0) > 0 && (
                  <div>
                    <div className="text-meta">검토 사유</div>
                    <ul>{selected.stage2Verdict.review_reasons!.map((r, i) => <li key={i}>{r}</li>)}</ul>
                  </div>
                )}

                {(selected.stage2Verdict.citations?.length ?? 0) > 0 && (
                  <div>
                    <div className="text-meta">근거 조항(citations)</div>
                    <ul>
                      {selected.stage2Verdict.citations!.map((c, i) => (
                        <li key={i}>「{c.doc}」{c.article} — {c.quote_summary}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {(selected.stage2Verdict.similar_cases?.length ?? 0) > 0 && (
                  <div>
                    <div className="text-meta">유사 사례(similar_cases)</div>
                    <ul>
                      {selected.stage2Verdict.similar_cases!.map((c, i) => (
                        <li key={i}>[{c.outcome}] {c.case_id} — {c.relevance}</li>
                      ))}
                    </ul>
                  </div>
                )}

                <div>
                  <div className="text-meta">1차 이상탐지 feature_contribs {selected.featureContribs.length === 0 && '(빈 배열 — v0 알려진 한계, CLAUDE.md 참조)'}</div>
                  {selected.featureContribs.length > 0 && (
                    <ul>{selected.featureContribs.map((c, i) => <li key={i}>{c.feature} ({c.weight})</li>)}</ul>
                  )}
                </div>

                <div className="stack" style={{ gap: 8 }}>
                  <textarea
                    placeholder="보완요청·반려 사유(승인은 생략 가능)"
                    value={reasonDraft}
                    onChange={(e) => setReasonDraft(e.target.value)}
                    rows={2}
                  />
                  <div style={{ display: 'flex', gap: 8 }}>
                    <button className="btn approve" disabled={busy} onClick={() => decide('APPROVE')}>승인</button>
                    <button className="btn return" disabled={busy} onClick={() => decide('RETURN')}>보완요청</button>
                    <button className="btn reject" disabled={busy} onClick={() => decide('REJECT')}>반려</button>
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

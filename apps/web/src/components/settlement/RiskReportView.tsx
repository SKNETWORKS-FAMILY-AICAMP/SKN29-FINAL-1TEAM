// 2차 위험 검토 보고서 — **미리보기(요약) + 자세히(특징·근거·안내)**.
//
//  마크다운 한 덩어리를 받던 자리를 대신한다. 텍스트 블록이면 화면이 미리보기와 자세히를
//  가를 수 없고, 근거가 본문과 `ragRefs` 양쪽에 이중으로 존재한다.
//
//  **근거 없는 판단은 판단으로 그리지 않는다.** 서버가 이미 근거 없는 finding을 advisories로
//  강등하지만, 화면도 finding에 근거가 없으면 그 사실을 표시한다.
import { useState } from 'react'
import { AlertTriangle, ChevronDown, ChevronRight, FileText, Info, Quote } from 'lucide-react'
import type { RiskReport } from '../../types/domain'

const RECO: Record<string, { text: string; tone: string }> = {
  APPROVE: { text: '승인 권장', tone: 'green' },
  SUPPLEMENT: { text: '보완요청 권장', tone: 'amber' },
  REJECT: { text: '반려 권장', tone: 'red' },
}

export function RiskReportView({
  report, tierPath,
}: {
  report: RiskReport
  /** low = 심층 검증을 하지 않은 건. 그 사실을 숨기지 않는다. */
  tierPath?: string
}) {
  //  기본은 접힘 — 담당자는 먼저 요약과 추천을 보고, 필요할 때 근거를 편다.
  const [open, setOpen] = useState(false)
  const reco = RECO[report.recommendation] ?? { text: report.recommendation, tone: 'gray' }
  const evidenceCount = report.findings.reduce((n, f) => n + f.evidence.length, 0)

  return (
    <div className="stack" style={{ gap: 12 }}>
      {/* ── 미리보기 ── */}
      <div className="row" style={{ gap: 8, alignItems: 'flex-start' }}>
        <span
          className="tag"
          style={{
            color: `var(--tone-${reco.tone})`, background: `var(--tone-${reco.tone}-bg)`,
            borderColor: 'transparent', flexShrink: 0,
          }}
        >
          {reco.text}
        </span>
        <div style={{ fontSize: 13, lineHeight: 1.6 }}>{report.summary}</div>
      </div>

      {/*  심층 검증을 안 한 건은 그 사실이 요약보다 중요하다 — 「문제없음」이 아니라
          「대조하지 않음」이다. */}
      {tierPath === 'low' && (
        <div className="row" style={{ gap: 7, alignItems: 'flex-start', color: 'var(--muted)' }}>
          <Info size={13} style={{ marginTop: 2, flexShrink: 0 }} />
          <div className="text-meta">내규 대조를 수행하지 않은 건입니다(일반 거래 구간).</div>
        </div>
      )}

      <button
        className="btn sm"
        style={{ alignSelf: 'flex-start' }}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        자세히 보기
        <span className="text-meta" style={{ marginLeft: 4 }}>
          근거 {evidenceCount}건
          {report.advisories.length > 0 ? ` · 확인 ${report.advisories.length}건` : ''}
        </span>
      </button>

      {/* ── 자세히 ── */}
      {open && (
        <div className="stack" style={{ gap: 14 }}>
          {/* ① 눈여겨볼 특징 */}
          {report.highlights.length > 0 && (
            <section>
              <div className="text-meta" style={{ fontWeight: 700, marginBottom: 6 }}>
                내역에서 눈여겨볼 점
              </div>
              <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, lineHeight: 1.7 }}>
                {report.highlights.map((h, i) => <li key={i}>{h}</li>)}
              </ul>
            </section>
          )}

          {/* ② 근거와 판단 이유 — claim/reasoning/evidence를 한 덩어리로 */}
          <section>
            <div className="text-meta" style={{ fontWeight: 700, marginBottom: 6 }}>
              판단 근거
            </div>
            <div className="stack" style={{ gap: 10 }}>
              {report.findings.map((f, i) => (
                <div
                  key={i}
                  style={{
                    border: '1px solid var(--border)', borderRadius: 'var(--radius-control)',
                    padding: '10px 12px', background: 'var(--surface-2)',
                  }}
                >
                  <div style={{ fontSize: 13, fontWeight: 600 }}>{f.claim}</div>
                  <div className="text-meta" style={{ marginTop: 4, lineHeight: 1.6 }}>{f.reasoning}</div>
                  {f.evidence.length === 0 ? (
                    <div className="row text-meta" style={{ gap: 5, marginTop: 8, color: 'var(--tone-amber)' }}>
                      <AlertTriangle size={12} /> 연결된 근거 조항 없음
                    </div>
                  ) : (
                    <div className="stack" style={{ gap: 6, marginTop: 8 }}>
                      {f.evidence.map((e, j) => (
                        <div key={j} className="row" style={{ gap: 6, alignItems: 'flex-start' }}>
                          <span className="tag" style={{ flexShrink: 0 }}>
                            {e.kind === 'case' ? '사례' : '내규'}
                          </span>
                          <div style={{ minWidth: 0 }}>
                            <div className="text-meta" style={{ fontWeight: 600 }}>
                              <FileText size={11} style={{ verticalAlign: '-1px' }} /> {e.label}
                            </div>
                            {e.quote && (
                              <div className="text-meta" style={{ marginTop: 2, fontStyle: 'italic' }}>
                                <Quote size={10} style={{ verticalAlign: '-1px' }} /> {e.quote}
                              </div>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </section>

          {/* ③ 담당자가 추가로 고려할 것 */}
          {report.advisories.length > 0 && (
            <section>
              <div className="text-meta" style={{ fontWeight: 700, marginBottom: 6 }}>
                추가로 확인해 주세요
              </div>
              <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, lineHeight: 1.7 }}>
                {report.advisories.map((a, i) => <li key={i}>{a}</li>)}
              </ul>
            </section>
          )}
        </div>
      )}
    </div>
  )
}

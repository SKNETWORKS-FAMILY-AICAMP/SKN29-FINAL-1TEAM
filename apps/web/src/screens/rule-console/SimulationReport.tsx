// 검증 시뮬레이션 보고서 — 실행 전 빈 상태 / 실행 결과(통계 · Agent 의견 · 결과 리스트).
import { useState } from 'react'
import { ArrowRight, FlaskConical, Play, RotateCw, Sliders } from 'lucide-react'
import { Markdown } from '../../components/ui/Markdown'
import { won } from '../../lib/format'
import {
  DECISION_LABEL, decisionTone, gradeTone,
  type Decision, type Grade, type SimReport, type SimResultRow,
} from './data/simulationTypes'

const percent = (value: number) => `${(value * 100).toFixed(1)}%`
const decisionText = (decision: string) => DECISION_LABEL[decision as Decision] ?? decision ?? '미처리'

export function SimulationEmptyState({ caseCount, running, error, onRun, onEditCases }: {
  caseCount: number; running: boolean; error: string; onRun: () => void; onEditCases: () => void
}) {
  return (
    <div className="card">
      <div className="card-head"><h3>검증 시뮬레이션 보고서</h3><span className="text-meta">미실행</span></div>
      <div className="card-body stack" style={{ alignItems: 'center', gap: 10, padding: '40px 16px', textAlign: 'center' }}>
        <FlaskConical size={30} className="muted" />
        <b style={{ fontSize: 14 }}>아직 시뮬레이션을 실행하지 않았습니다.</b>
        <div className="text-meta" style={{ maxWidth: 560, lineHeight: 1.7 }}>
          선택한 그래프를 <b>커스텀 검증셋</b>과 <b>직전 달 실제 정산 내역</b>에 적용해 판정 결과·통계·Agent 의견을 만듭니다.
          결과를 확인한 뒤에만 승인대기로 전환할 수 있습니다.
        </div>
        {error && <div className="note" style={{ color: 'var(--tone-red)', borderColor: 'var(--tone-red)' }}>{error}</div>}
        <div className="row" style={{ gap: 8, marginTop: 6 }}>
          <button className="btn primary" onClick={onRun} disabled={running}>
            <Play size={13} /> {running ? '실행 중…' : '시뮬레이션 실행하기'}
          </button>
          <button className="btn" onClick={onEditCases} disabled={running}>
            <Sliders size={13} /> 테스트케이스(커스텀 검증셋) 만들기 ({caseCount})
          </button>
        </div>
      </div>
    </div>
  )
}

export function SimulationReportView({ report, caseCount, running, error, onRun, onEditCases }: {
  report: SimReport; caseCount: number; running: boolean; error: string; onRun: () => void; onEditCases: () => void
}) {
  const { stats } = report
  return (
    <>
      <div className="row" style={{ justifyContent: 'space-between', marginBottom: 8, gap: 8, flexWrap: 'wrap' }}>
        <span className="text-meta">
          <b>{report.graphName}</b> v{report.graphVersion} — 검증셋 {stats.testTotal}건 · {report.periodLabel} 내역 {stats.historyTotal}건
          으로 시뮬레이션 완료 ({report.ranAt}{report.ranBy && ` · ${report.ranBy}`}) · 실행 #{report.runId}
          {report.placeholder && <span className="tag ai" style={{ marginLeft: 6 }}>플레이스홀더 보고서</span>}
          {report.stale && <span className="tag warn" style={{ marginLeft: 6 }}>실행 이후 그래프 변경됨 — 다시 실행 필요</span>}
        </span>
        <span className="row" style={{ gap: 8 }}>
          <button className="btn sm" onClick={onEditCases} disabled={running}><Sliders size={12} /> 검증셋 수정 ({caseCount})</button>
          <button className="btn sm" onClick={onRun} disabled={running}><RotateCw size={12} /> {running ? '실행 중…' : '다시 실행'}</button>
        </span>
      </div>
      {error && <div className="note" style={{ color: 'var(--tone-red)', borderColor: 'var(--tone-red)', marginBottom: 8 }}>{error}</div>}

      <div className="kpi-grid" style={{ gridTemplateColumns: 'repeat(4, 1fr)' }}>
        <div className="kpi">
          <div className="label">자동처리율</div><div className="value">{percent(stats.autoRate)}</div>
          <div className="text-meta">검토 없이 자동 분류 {stats.autoCount}/{stats.historyTotal}건 · 사람 확인 {stats.manualCount}건</div>
        </div>
        <div className="kpi">
          <div className="label">검토 감소량</div>
          <div className="value" style={{ fontSize: 'var(--text-value)' }}>
            {percent(stats.prevAutoRate)} <ArrowRight size={14} style={{ verticalAlign: 'middle' }} /> {percent(stats.autoRate)}
          </div>
          <div className="text-meta">
            {stats.hasPrevVersion ? `직전 버전 ${stats.prevVersionLabel} 대비` : '직전 버전 시뮬레이션 이력 없음 ·'}
            {' '}자동처리율 {stats.reviewReduction >= 0 ? '+' : ''}{(stats.reviewReduction * 100).toFixed(1)}%p
          </div>
        </div>
        <div className={'kpi ' + (stats.testGraded > 0 && stats.testFailed === 0 ? 'ok' : 'warn')}>
          <div className="label">테스트 수치</div>
          <div className="value">{stats.testPassed}/{stats.testGraded || stats.testTotal}</div>
          <div className="text-meta">기대 판정 일치 · 불일치 {stats.testFailed}건</div>
        </div>
        <div className={'kpi ' + (stats.nodeCoverage >= 1 ? 'ok' : 'warn')}>
          <div className="label">노드 커버리지</div><div className="value">{percent(stats.nodeCoverage)}</div>
          <div className="text-meta">평가된 노드 {stats.visitedNodes}/{report.structure.nodeCount}개</div>
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-head">
          <h3>🤖 Agent 의견 — 종합 개요</h3>
          <span className={'tag ' + (report.grades.action.level === 'good' ? 'ok' : 'warn')}>
            권장 처리 · {report.grades.action.label}
          </span>
        </div>
        <div className="card-body">
          <div className="kpi-grid" style={{ gridTemplateColumns: 'repeat(3, 1fr)', marginBottom: 16 }}>
            <GradeTile label="그래프 구조 평가" grade={report.grades.structure} />
            <GradeTile label="실행결과 평가" grade={report.grades.result} />
            <GradeTile label="권장 처리" grade={report.grades.action} />
          </div>
          {report.quality && (
            <div className="kpi-grid" style={{ gridTemplateColumns: 'repeat(2, 1fr)', marginBottom: 16 }}>
              <div className={'kpi ' + (report.quality.stability.score >= 0.85 ? 'ok' : report.quality.stability.score >= 0.6 ? 'caution' : 'warn')}>
                <div className="label">안정성 — 켰을 때 사고 여지</div>
                <div className="value">{percent(report.quality.stability.score)}</div>
                <div className="text-meta">
                  자동 반려 노드 {report.quality.stability.autoRejectNodes.length}개 · 안전 폴백 {report.quality.stability.fallbackCount}건
                  · 도달 불가 {report.quality.stability.unreachableCount}개
                </div>
              </div>
              <div className={'kpi ' + (report.quality.reviewability.score >= 0.85 ? 'ok' : report.quality.reviewability.score >= 0.6 ? 'caution' : 'warn')}>
                <div className="label">검토 용이성 — 사람에게 남는 일</div>
                <div className="value">{percent(report.quality.reviewability.score)}</div>
                <div className="text-meta">
                  사람 확인 {report.quality.reviewability.humanQueue}건({percent(report.quality.reviewability.humanRate)})
                  · 근거 부착률 {percent(report.quality.reviewability.flaggedRate)}
                </div>
              </div>
            </div>
          )}
          <Markdown source={report.agentReport} />
        </div>
      </div>

      <ResultList title="테스트셋 결과" rows={report.testResults}
        emptyText="검증셋이 비어 있습니다. ‘검증셋 수정’에서 케이스를 추가하세요." showExpected />
      <HistoryList periodLabel={report.periodLabel} rows={report.historyResults} />
    </>
  )
}

function GradeTile({ label, grade }: { label: string; grade: Grade }) {
  return (
    <div className={'kpi ' + gradeTone(grade.level)}>
      <div className="label">{label}</div>
      <div className="value" style={{ fontSize: 'var(--text-value)' }}>{grade.label}</div>
      <div className="text-meta">{grade.note}</div>
    </div>
  )
}

/** 직전 기간 내역 — 핵심 미리보기 + 기존→현재 분류 + 변경건 AI 코멘트. */
function HistoryList({ periodLabel, rows }: { periodLabel: string; rows: SimResultRow[] }) {
  const [filter, setFilter] = useState<'risk' | 'changed' | 'all'>('risk')
  const risky = rows.filter((row) => row.risk)
  const changed = rows.filter((row) => row.changed)
  const visible = filter === 'all' ? rows : filter === 'changed' ? changed : risky

  return (
    <div className="card" style={{ marginTop: 16 }}>
      <div className="card-head">
        <div>
          <h3>{periodLabel} 내역 결과</h3>
          <div className="text-meta">전체 {rows.length}건 · 위험 {risky.length}건 · 분류 변경 {changed.length}건</div>
        </div>
        <div className="seg-toggle">
          <button className={filter === 'risk' ? 'active' : ''} onClick={() => setFilter('risk')}>위험건</button>
          <button className={filter === 'changed' ? 'active' : ''} onClick={() => setFilter('changed')}>변경건</button>
          <button className={filter === 'all' ? 'active' : ''} onClick={() => setFilter('all')}>전체</button>
        </div>
      </div>
      <div className="card-body stack" style={{ gap: 10 }}>
        {rows.length === 0 && <div className="text-meta">해당 기간의 정산 내역이 없습니다.</div>}
        {rows.length > 0 && visible.length === 0 && (
          <div className="text-meta">이 조건에 해당하는 건이 없습니다. ‘전체’로 {rows.length}건을 모두 볼 수 있습니다.</div>
        )}
        {visible.map((row) => (
          <div key={row.id} className={'hist-row' + (row.risk ? ' risk' : '')}>
            <div className="row" style={{ gap: 8, alignItems: 'flex-start' }}>
              <div style={{ minWidth: 0, flex: 1 }}>
                <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
                  <b style={{ fontSize: 13 }}>{row.merchant || row.label}</b>
                  <span className="text-meta">{row.date && `${row.date} · `}{row.category || '분류 없음'} · {won(row.amount)}</span>
                </div>
                <div className="text-meta" style={{ marginTop: 2 }}>{row.label}</div>
              </div>
              <div className="hist-flow">
                <span className="tag">{row.baseline ? decisionText(row.baseline) : '미처리'}</span>
                <ArrowRight size={13} className="muted" />
                <span className={'tag ' + decisionTone(row.decision)}>{decisionText(row.decision)}</span>
                {row.changed && (
                  <span className={'tag ' + (row.commentVerdict === 'risk' ? 'warn' : 'ok')}>
                    {row.commentVerdict === 'risk' ? '⚠ 위험 변경' : '✅ 정상 변경'}
                  </span>
                )}
                {!row.changed && row.risk && <span className="tag warn">⚠ 위험</span>}
              </div>
            </div>
            {row.aiComment && (
              <div className={'hist-comment ' + row.commentVerdict}>
                <b>{row.commentVerdict === 'risk' ? '⚠ AI 코멘트 · 위험' : '💬 AI 코멘트 · 의도된 변경'}</b>
                <div style={{ marginTop: 3 }}>{row.aiComment}</div>
              </div>
            )}
            <div className="text-meta" style={{ fontSize: 11 }}>
              평가 경로 {row.path.join(' → ') || '-'}
              {row.flags.length > 0 && <span style={{ color: 'var(--tone-red)' }}> · {row.flags.join(', ')}</span>}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function ResultList({ title, rows, emptyText, showExpected }: {
  title: string; rows: SimResultRow[]; emptyText: string; showExpected?: boolean
}) {
  const [showAll, setShowAll] = useState(false)
  const risky = rows.filter((row) => row.risk)
  const visible = showAll ? rows : risky

  return (
    <div className="card" style={{ marginTop: 16 }}>
      <div className="card-head">
        <div><h3>{title}</h3><div className="text-meta">전체 {rows.length}건 · 위험건 {risky.length}건</div></div>
        <div className="seg-toggle">
          <button className={showAll ? '' : 'active'} onClick={() => setShowAll(false)}>위험건만</button>
          <button className={showAll ? 'active' : ''} onClick={() => setShowAll(true)}>전체 펼치기</button>
        </div>
      </div>
      {rows.length === 0 && <div className="card-body text-meta">{emptyText}</div>}
      {rows.length > 0 && visible.length === 0 && (
        <div className="card-body text-meta">위험으로 분류된 건이 없습니다. ‘전체 펼치기’로 {rows.length}건을 모두 볼 수 있습니다.</div>
      )}
      {visible.length > 0 && (
        <table className="table">
          <thead><tr>
            <th>내역</th><th className="num">금액</th><th>분류</th>
            {showExpected && <th>기대</th>}
            <th>판정</th><th>평가 경로</th>
          </tr></thead>
          <tbody>
            {visible.map((row) => (
              <tr key={row.id} className={row.risk ? 'anomaly-row' : undefined}>
                <td>
                  <b style={{ fontSize: 12.5 }}>{row.label}</b>
                  <div className="text-meta">{row.merchant}{row.currentStatus ? ` · 현재 ${row.currentStatus}` : ''}</div>
                </td>
                <td className="num">{won(row.amount)}</td>
                <td className="text-meta">{row.category || '-'}</td>
                {showExpected && <td>
                  {row.expected
                    ? <span className={'tag ' + (row.matchedExpectation ? 'ok' : 'warn')}>
                        {decisionText(row.expected)}{row.matchedExpectation ? '' : ' 불일치'}
                      </span>
                    : <span className="text-meta">채점 안 함</span>}
                </td>}
                <td><span className={'tag ' + decisionTone(row.decision)}>{decisionText(row.decision)}</span></td>
                <td className="text-meta" style={{ fontSize: 11 }}>
                  {row.path.join(' → ') || '-'}
                  {row.flags.length > 0 && <div style={{ color: 'var(--tone-red)' }}>{row.flags.join(', ')}</div>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

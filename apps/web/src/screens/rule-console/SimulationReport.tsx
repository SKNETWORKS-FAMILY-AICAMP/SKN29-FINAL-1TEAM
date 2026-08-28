// 검증 시뮬레이션 보고서 — 실행 이력 있으면 그대로 표시 / 없으면 빈 상태("실행하기").
// (2026-08-19) 실행 버튼 한 번이면 검증셋 생성부터 결과까지 한 번에 — 중간 단계 없음.
import { useState } from 'react'
import { ArrowRight, FlaskConical, Play, RotateCw } from 'lucide-react'
import { Markdown } from '../../components/ui/Markdown'
import { won } from '../../lib/format'
import {
  DECISION_LABEL, decisionTone, gradeTone,
  type Decision, type Grade, type SimReport, type SimResultRow,
} from './data/simulationTypes'

const percent = (value: number) => `${(value * 100).toFixed(1)}%`
const decisionText = (decision: string) => DECISION_LABEL[decision as Decision] ?? decision ?? '미처리'

/** Agent 보고서를 "한눈에 보기"(항상 보임) / 나머지 상세 섹션(접힘)으로 나눈다.
 * narrate.py·simulation.py 둘 다 `## 한눈에 보기`로 시작하도록 프롬프트/템플릿을
 * 맞춰뒀다 — 그다음 두 번째 `## ` 헤딩부터를 "상세"로 취급한다. 헤딩이 1개뿐이면
 * (구버전 캐시 응답 등) 전부 요약으로 보고 접을 것도 없다고 처리한다. */
function splitAgentReport(source: string): { summary: string; detail: string } {
  const headingIndices: number[] = []
  const re = /^##\s/gm
  let match: RegExpExecArray | null
  while ((match = re.exec(source))) headingIndices.push(match.index)
  if (headingIndices.length < 2) return { summary: source, detail: '' }
  const cut = headingIndices[1]
  return { summary: source.slice(0, cut).trim(), detail: source.slice(cut).trim() }
}

export function SimulationEmptyState({ running, error, onRun }: {
  running: boolean; error: string
  onRun: () => void
}) {
  return (
    <div className="card">
      <div className="card-head">
        <h3>검증 시뮬레이션 보고서</h3>
        <span className="text-meta">미실행</span>
      </div>
      <div className="card-body stack" style={{ alignItems: 'center', gap: 10, padding: '40px 16px', textAlign: 'center' }}>
        <FlaskConical size={30} className="muted" />
        <b style={{ fontSize: 14 }}>아직 시뮬레이션을 실행하지 않았습니다.</b>
        <div className="text-meta" style={{ maxWidth: 960, lineHeight: 1.7 }}>
          선택한 그래프의 현재 조건으로 <b>검증셋을 자동생성</b>하고 <b>직전 달 실제 정산 내역</b>에도 적용해
          판정 결과·통계·Agent 의견을 만듭니다
          <br />
          (Rule Agent가 조건을 역산해 만들고 자체 검증까지 마칩니다).
          <br />
          결과를 확인한 뒤에만 승인대기로 전환할 수 있습니다.
        </div>
        {error && <div className="note" style={{ color: 'var(--tone-red)', borderColor: 'var(--tone-red)' }}>{error}</div>}
        <button className="btn primary" onClick={onRun} disabled={running} style={{ marginTop: 6 }}>
          <Play size={13} /> {running ? '실행 중…' : '시뮬레이션 실행하기'}
        </button>
      </div>
    </div>
  )
}

export function SimulationReportView({ report, running, error, onRun }: {
  report: SimReport; running: boolean; error: string
  onRun: () => void
}) {
  const { stats } = report
  const [detailOpen, setDetailOpen] = useState(false)
  const { summary, detail } = splitAgentReport(report.agentReport)
  return (
    <>
      <div className="row" style={{ justifyContent: 'space-between', marginBottom: 8, gap: 8, flexWrap: 'wrap' }}>
        <span className="text-meta">
          <b>{report.graphName}</b> v{report.graphVersion} — 검증셋 {stats.testTotal}건 · {report.periodLabel} 내역 {stats.historyTotal}건
          으로 시뮬레이션 완료 ({report.ranAt}{report.ranBy && ` · ${report.ranBy}`}) · 실행 #{report.runId}
          {report.placeholder && <span className="tag ai" style={{ marginLeft: 6 }}>플레이스홀더 보고서</span>}
          {report.stale && <span className="tag warn" style={{ marginLeft: 6 }}>실행 이후 그래프 변경됨 — 다시 실행 필요</span>}
        </span>
        <button className="btn sm" onClick={onRun} disabled={running}><RotateCw size={12} /> {running ? '실행 중…' : '다시 실행'}</button>
      </div>
      {error && <div className="note" style={{ color: 'var(--tone-red)', borderColor: 'var(--tone-red)', marginBottom: 8 }}>{error}</div>}

      <div className="kpi-grid">
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
          <h3>Agent 의견 — 종합 개요</h3>
          <span className={'tag ' + (report.grades.action.level === 'good' ? 'ok' : 'warn')}>
            권장 처리 · {report.grades.action.label}
          </span>
        </div>
        <div className="card-body">
          <div className="kpi-grid cols-3" style={{ marginBottom: 16 }}>
            <GradeTile label="그래프 구조 평가" grade={report.grades.structure} />
            <GradeTile label="실행결과 평가" grade={report.grades.result} />
            <GradeTile label="권장 처리" grade={report.grades.action} />
          </div>
          <div className="note" style={{ borderColor: 'var(--primary)', background: 'var(--primary-soft)' }}>
            <Markdown source={summary} />
          </div>
          {detail && (
            <>
              <button className="btn sm" onClick={() => setDetailOpen((v) => !v)} style={{ marginTop: 12 }}>
                {detailOpen ? '상세 보고서 접기 ▲' : '상세 보고서 보기 ▼'}
              </button>
              {detailOpen && (
                <div style={{ marginTop: 10 }}>
                  <Markdown source={detail} />
                </div>
              )}
            </>
          )}
        </div>
      </div>

      <TestResultList rows={report.testResults} stats={stats} />
      <HistoryList periodLabel={report.periodLabel} rows={report.historyResults} />
    </>
  )
}

const CAUSE_LABEL: Record<'structure' | 'result', string> = { structure: '구조 문제', result: '실행결과 문제' }

function GradeTile({ label, grade }: { label: string; grade: Grade }) {
  return (
    <div className={'kpi ' + gradeTone(grade.level)}>
      <div className="label">{label}</div>
      <div className="value" style={{ fontSize: 'var(--text-value)' }}>{grade.label}</div>
      {(grade.cause && grade.cause.length > 0) || grade.aiAdjusted ? (
        <div className="row" style={{ gap: 4, marginTop: 2, flexWrap: 'wrap' }}>
          {grade.cause?.map((c) => <span key={c} className="tag warn" style={{ fontSize: 10 }}>원인 · {CAUSE_LABEL[c]}</span>)}
          {grade.aiAdjusted && <span className="tag ai" style={{ fontSize: 10 }} title="Agent가 실행 결과 전체를 보고 재판단한 등급입니다">Agent 판단</span>}
        </div>
      ) : null}
      <div className="text-meta">{grade.note}</div>
    </div>
  )
}

const HIST_VERDICT_META: Record<'reversal' | 'risk' | 'intended', { badge: string; tone: string; heading: string }> = {
  reversal: { badge: '완전 반전', tone: 'danger', heading: '가장 먼저 확인하세요 · 완전 반전' },
  risk: { badge: '위험 변경', tone: 'warn', heading: 'AI 코멘트 · 위험' },
  intended: { badge: '정상 변경', tone: 'ok', heading: 'AI 코멘트 · 의도된 변경' },
}

/** 직전 기간 내역 — 위험건(완전 반전 포함) / 정상변경건 / 전체. 변경건에만 AI 코멘트가 붙는다. */
function HistoryList({ periodLabel, rows }: { periodLabel: string; rows: SimResultRow[] }) {
  const [filter, setFilter] = useState<'risk' | 'intended' | 'all'>('risk')
  // 위험건 = 변경건 중 AI가 위험하다고 판단한 건(완전 반전 포함) / 정상변경건 = 의도된 변경
  const risky = rows.filter((row) => row.changed && (row.commentVerdict === 'risk' || row.commentVerdict === 'reversal'))
  const reversals = rows.filter((row) => row.changed && row.commentVerdict === 'reversal')
  const intended = rows.filter((row) => row.changed && row.commentVerdict === 'intended')
  const visible = filter === 'all' ? rows : filter === 'intended' ? intended : risky
  const emptyText = filter === 'risk'
    ? '위험으로 판단된 변경건이 없습니다. 기존 처리와 달라진 건은 모두 의도된 변경으로 분류됐습니다.'
    : '의도된 변경으로 분류된 건이 없습니다.'

  return (
    <div className="card" style={{ marginTop: 16 }}>
      <div className="card-head">
        <div>
          <h3>{periodLabel} 내역 결과</h3>
          <div className="text-meta">
            전체 {rows.length}건 · 변경 {risky.length + intended.length}건
            (위험 {risky.length}{reversals.length > 0 && ` · 완전 반전 ${reversals.length}`} / 정상 {intended.length})
          </div>
        </div>
        <div className="seg-toggle">
          <button className={filter === 'risk' ? 'active' : ''} onClick={() => setFilter('risk')}>위험건 {risky.length}</button>
          <button className={filter === 'intended' ? 'active' : ''} onClick={() => setFilter('intended')}>정상변경건 {intended.length}</button>
          <button className={filter === 'all' ? 'active' : ''} onClick={() => setFilter('all')}>전체</button>
        </div>
      </div>
      <div className="card-body stack" style={{ gap: 10 }}>
        {rows.length === 0 && <div className="text-meta">해당 기간의 정산 내역이 없습니다.</div>}
        {rows.length > 0 && visible.length === 0 && (
          <div className="text-meta">{emptyText} ‘전체’로 {rows.length}건을 모두 볼 수 있습니다.</div>
        )}
        {visible.map((row) => <HistoryRow key={row.id} row={row} />)}
      </div>
    </div>
  )
}

function HistoryRow({ row }: { row: SimResultRow }) {
  const [expanded, setExpanded] = useState(false)
  const verdictMeta = row.commentVerdict ? HIST_VERDICT_META[row.commentVerdict] : null
  const hasDetail = Boolean(row.aiCommentDetail || row.path.length > 0 || row.flags.length > 0)
  return (
    <div className={'hist-row' + (verdictMeta?.tone === 'danger' ? ' risk reversal' : verdictMeta?.tone === 'warn' ? ' risk' : '')}>
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
          {row.changed
            ? <span className={'tag ' + (verdictMeta?.tone === 'danger' ? 'warn' : verdictMeta?.tone === 'warn' ? 'warn' : 'ok')}>
                {verdictMeta?.badge}
              </span>
            : <span className="tag">변경 없음</span>}
        </div>
      </div>
      {row.aiComment && verdictMeta && (
        <div className={'hist-comment ' + row.commentVerdict}>
          <b>{verdictMeta.heading}</b>
          <div style={{ marginTop: 3 }}>{row.aiComment}</div>
          {hasDetail && (
            <button
              className="btn sm" style={{ marginTop: 6 }}
              onClick={() => setExpanded((prev) => !prev)}
            >
              {expanded ? '자세히 숨기기 ▲' : '자세히 보기 ▼'}
            </button>
          )}
          {expanded && (
            <div className="text-meta" style={{ marginTop: 6, fontSize: 11 }}>
              {row.aiCommentDetail && <div>{row.aiCommentDetail}</div>}
              {row.path.length > 0 && <div>평가 경로: {row.path.join(' → ')}</div>}
              {row.flags.length > 0 && <div>플래그 원문: {row.flags.join(', ')}</div>}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/** 테스트셋 결과 — KPI(테스트 수치)와 같은 기준으로 불일치(위험)·일치(정상)를 표시한다. */
function TestResultList({ rows, stats }: { rows: SimResultRow[]; stats: SimReport['stats'] }) {
  const [filter, setFilter] = useState<'fail' | 'pass' | 'all'>('fail')
  const failed = rows.filter((row) => row.matchedExpectation === false)
  const passed = rows.filter((row) => row.matchedExpectation === true)
  const visible = filter === 'all' ? rows : filter === 'pass' ? passed : failed

  return (
    <div className="card" style={{ marginTop: 16 }}>
      <div className="card-head">
        <div>
          <h3>테스트셋 결과</h3>
          <div className="text-meta">
            검증셋 {rows.length}건 · 채점 {stats.testGraded}건 —
            <b style={{ color: 'var(--tone-green)' }}> 일치 {stats.testPassed}</b> /
            <b style={{ color: 'var(--tone-red)' }}> 불일치 {stats.testFailed}</b>
            {rows.length - stats.testGraded > 0 && ` · 채점 제외 ${rows.length - stats.testGraded}건`}
          </div>
        </div>
        <div className="seg-toggle">
          <button className={filter === 'fail' ? 'active' : ''} onClick={() => setFilter('fail')}>불일치 {failed.length}</button>
          <button className={filter === 'pass' ? 'active' : ''} onClick={() => setFilter('pass')}>정상 {passed.length}</button>
          <button className={filter === 'all' ? 'active' : ''} onClick={() => setFilter('all')}>전체</button>
        </div>
      </div>
      {rows.length === 0 && (
        <div className="card-body text-meta">검증셋이 비어 있습니다. ‘검증셋 수정’에서 케이스를 추가하세요.</div>
      )}
      {rows.length > 0 && visible.length === 0 && (
        <div className="card-body text-meta">
          {filter === 'fail'
            ? '기대 판정과 어긋난 케이스가 없습니다 — 검증셋 전건이 의도대로 판정됐습니다.'
            : '기대 판정이 지정된 케이스가 없습니다.'}
          {' '}‘전체’로 {rows.length}건을 모두 볼 수 있습니다.
        </div>
      )}
      {visible.length > 0 && (
        <table className="table">
          <thead><tr>
            <th>결과</th><th>케이스</th><th className="num">금액</th><th>분류</th>
            <th>기대</th><th>판정</th><th>평가 경로</th>
          </tr></thead>
          <tbody>
            {visible.map((row) => (
              <tr key={row.id} className={row.matchedExpectation === false ? 'anomaly-row' : undefined}>
                <td>
                  {row.matchedExpectation === null
                    ? <span className="tag">채점 안 함</span>
                    : row.matchedExpectation
                      ? <span className="tag ok">정상</span>
                      : <span className="tag warn">불일치</span>}
                </td>
                <td>
                  <b style={{ fontSize: 12.5 }}>{row.label}</b>
                  <div className="text-meta">{row.merchant}</div>
                </td>
                {/* 검증셋 자동생성 케이스는 노드 조건 하나만 골라 값을 역산한다 — 그 조건이
                    금액과 무관하면(예: 참석자 수·2차 여부) tx.amount 자체를 안 다뤄 0으로
                    남는다. 실제 0원 지출이 아니라 "이 케이스에서 금액은 판정 근거가 아님"
                    이므로 ₩0으로 보이면 데이터 오류처럼 오해된다 — 구분해 보여준다. */}
                <td className="num">{row.amount > 0 ? won(row.amount) : <span className="text-meta">해당없음</span>}</td>
                <td className="text-meta">{row.category || '-'}</td>
                <td>{row.expected
                  ? <span className="tag">{decisionText(row.expected)}</span>
                  : <span className="text-meta">-</span>}</td>
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

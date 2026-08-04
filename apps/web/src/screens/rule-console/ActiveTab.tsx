// Tab3 — Active 관리. 실제 API(/api/rules/) 연동.
//  ① 승인대기 목록(스코프당 1건) — 펼치면 KPI·검토보고서, 룰 활성 권한자가 ACTIVE 전환
//  ② 현재 활성 그래프 — 전체 KPI 대시보드 + 스코프별 목록(클릭 시 버전 이력·롤백)
import { useEffect, useMemo, useState } from 'react'
import { ChevronDown, ChevronRight, History, Lock } from 'lucide-react'
import { endpoints } from '../../api/client'
import { activateRule } from '../../api/ruleService'
import { Markdown } from '../../components/ui/Markdown'
import { useCan } from '../../lib/capabilities'
import { gradeTone, type Grade, type SimReport } from './data/simulationTypes'
import { VersionHistoryModal } from './VersionHistoryModal'

interface ApiGraphRow {
  id: string | number
  familyKey: string
  name: string
  scope: string
  status: string
  statusLabel: string
  version: number
  nodeCount?: number
  nodes?: unknown[]
  sourceClause: string
  activated_at?: string | null
  activatedBy?: string
  reviewedBy?: string
  reviewedAt?: string | null
  reviewComment?: string
  simResult?: {
    runId?: number
    ranAt?: string
    stats?: SimReport['stats']
    grades?: SimReport['grades']
  }
}

const percent = (value?: number) => value === undefined ? '-' : `${(value * 100).toFixed(1)}%`
const nodeCountOf = (row: ApiGraphRow) => row.nodeCount ?? row.nodes?.length ?? 0
const dateText = (value?: string | null) => value ? value.slice(0, 16).replace('T', ' ') : '-'

export function ActiveTab() {
  const canActivate = useCan()('rule_activate')
  const [rows, setRows] = useState<ApiGraphRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState('')          // 승인대기 아코디언 — 하나만 펼침
  const [reports, setReports] = useState<Record<string, SimReport | null>>({})
  const [busy, setBusy] = useState('')
  const [historyGraph, setHistoryGraph] = useState<ApiGraphRow | null>(null)

  const load = () => {
    setLoading(true)
    endpoints.rules()
      .then(({ data }) => setRows(data as ApiGraphRow[]))
      .catch(() => setError('룰 그래프를 불러오지 못했습니다. Core API 연결을 확인해주세요.'))
      .finally(() => setLoading(false))
  }
  useEffect(load, [])

  const pending = useMemo(() => rows.filter((row) => row.status === 'SIMULATED'), [rows])
  const active = useMemo(() => rows.filter((row) => row.status === 'ACTIVE'), [rows])

  // 활성 그래프 전체 통계 — 시뮬레이션 이력이 있는 그래프만 평균에 넣는다.
  const dashboard = useMemo(() => {
    const rated = active.filter((row) => row.simResult?.stats?.autoRate !== undefined)
    const sum = (pick: (stats: NonNullable<SimReport['stats']>) => number) =>
      rated.reduce((total, row) => total + pick(row.simResult!.stats!), 0)
    return {
      graphCount: active.length,
      scopeCount: new Set(active.map((row) => row.scope)).size,
      nodeCount: active.reduce((total, row) => total + nodeCountOf(row), 0),
      ratedCount: rated.length,
      avgAutoRate: rated.length ? sum((stats) => stats.autoRate) / rated.length : undefined,
      riskCount: sum((stats) => stats.riskChangedCount ?? 0),
      unrated: active.length - rated.length,
    }
  }, [active])

  const toggle = (row: ApiGraphRow) => {
    const id = String(row.id)
    if (expanded === id) { setExpanded(''); return }
    setExpanded(id)
    if (reports[id] === undefined) {
      endpoints.ruleSimulation(id)
        .then(({ data, status }) => setReports((previous) => ({ ...previous, [id]: status === 200 ? data as SimReport : null })))
        .catch(() => setReports((previous) => ({ ...previous, [id]: null })))
    }
  }

  const approve = async (row: ApiGraphRow) => {
    if (!window.confirm(`${row.name} v${row.version}을(를) ACTIVE로 전환합니다. 계속할까요?`)) return
    setBusy(String(row.id))
    setError('')
    try {
      await activateRule(String(row.id))
      setExpanded('')
      load()
    } catch {
      setError('ACTIVE 전환에 실패했습니다. 구조 검증(사이클·EvalContext 경로)과 권한을 확인해주세요.')
    } finally {
      setBusy('')
    }
  }

  // 반려 — 사유를 남기고 초안(수정중)으로 되돌린다. 작성자가 고쳐 다시 올릴 수 있다.
  const reject = async (row: ApiGraphRow) => {
    const comment = window.prompt(
      `${row.name} v${row.version} 활성화 요청을 반려합니다.\n작성자에게 전달할 사유를 입력하세요.`,
      '',
    )
    if (comment === null || !comment.trim()) return
    setBusy(String(row.id))
    setError('')
    try {
      await endpoints.rejectRuleActivation(String(row.id), comment.trim())
      setExpanded('')
      load()
    } catch {
      setError('반려에 실패했습니다. 권한을 확인해주세요.')
    } finally {
      setBusy('')
    }
  }

  return (
    <>
      {loading && <div className="card"><div className="card-body text-meta">룰 그래프를 불러오는 중입니다.</div></div>}
      {error && <div className="note" style={{ color: 'var(--tone-red)', borderColor: 'var(--tone-red)', marginBottom: 16 }}>{error}</div>}

      {/* ① 승인대기 목록 */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-head">
          <div>
            <h3>승인대기 목록</h3>
            <div className="text-meta">스코프(비용분류)당 1건만 올라올 수 있습니다. 처리해야 다음 요청이 가능합니다.</div>
          </div>
          <span className="tag ai">{pending.length}건 대기</span>
        </div>
        {!loading && pending.length === 0 && <div className="card-body text-meta">승인대기 중인 그래프가 없습니다.</div>}
        <div className="stack" style={{ padding: pending.length ? 8 : 0, gap: 8 }}>
          {pending.map((row) => {
            const id = String(row.id)
            const open = expanded === id
            const report = reports[id]
            const stats = report?.stats ?? row.simResult?.stats
            const grades = report?.grades ?? row.simResult?.grades
            return (
              <div key={id} style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius-control)' }}>
                <div className="rule-graph-row" role="button" tabIndex={0} onClick={() => toggle(row)}
                  onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); toggle(row) } }}>
                  {open ? <ChevronDown size={14} className="muted" /> : <ChevronRight size={14} className="muted" />}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
                      <span className="tag">{row.scope}</span>
                      <b style={{ fontSize: 13 }}>{row.name}</b>
                      <span className="tag ai">v{row.version} 승인대기</span>
                      {grades && <span className={'tag ' + (grades.action.level === 'good' ? 'ok' : 'warn')}>권장 {grades.action.label}</span>}
                    </div>
                    <div className="text-meta">
                      노드 {nodeCountOf(row)}개 · 검토자 {row.reviewedBy || '-'} · 요청 {dateText(row.reviewedAt)}
                      {stats?.autoRate !== undefined && ` · 자동처리율 ${percent(stats.autoRate)}`}
                    </div>
                  </div>
                </div>

                {open && (
                  <div className="card-body stack" style={{ gap: 16, borderTop: '1px solid var(--border)' }}>
                    {report === undefined && <div className="text-meta">시뮬레이션 보고서를 불러오는 중입니다.</div>}
                    {stats && (
                      <div className="kpi-grid" style={{ gridTemplateColumns: 'repeat(4, 1fr)', marginBottom: 0 }}>
                        <div className="kpi">
                          <div className="label">자동처리율</div><div className="value">{percent(stats.autoRate)}</div>
                          <div className="text-meta">자동 {stats.autoCount} / 사람 확인 {stats.manualCount}건</div>
                        </div>
                        <div className="kpi">
                          <div className="label">검토 감소량</div>
                          <div className="value" style={{ fontSize: 'var(--text-value)' }}>
                            {percent(stats.prevAutoRate)} → {percent(stats.autoRate)}
                          </div>
                          <div className="text-meta">{stats.reviewReduction >= 0 ? '+' : ''}{(stats.reviewReduction * 100).toFixed(1)}%p</div>
                        </div>
                        <div className={'kpi ' + (stats.testGraded > 0 && stats.testFailed === 0 ? 'ok' : 'warn')}>
                          <div className="label">테스트 수치</div>
                          <div className="value">{stats.testPassed}/{stats.testGraded || stats.testTotal}</div>
                          <div className="text-meta">불일치 {stats.testFailed}건</div>
                        </div>
                        <div className={'kpi ' + (stats.nodeCoverage >= 1 ? 'ok' : 'warn')}>
                          <div className="label">노드 커버리지</div><div className="value">{percent(stats.nodeCoverage)}</div>
                          <div className="text-meta">위험 변경 {stats.riskChangedCount ?? 0}건 · 정상 변경 {stats.intendedChangedCount ?? 0}건</div>
                        </div>
                      </div>
                    )}
                    {grades && (
                      <div className="kpi-grid" style={{ gridTemplateColumns: 'repeat(3, 1fr)', marginBottom: 0 }}>
                        <GradeTile label="그래프 구조 평가" grade={grades.structure} />
                        <GradeTile label="실행결과 평가" grade={grades.result} />
                        <GradeTile label="권장 처리" grade={grades.action} />
                      </div>
                    )}

                    <div className="card">
                      <div className="card-head">
                        <h3>검토보고서 — {row.reviewedBy || '검토자 미상'}</h3>
                        <span className="text-meta">요청 {dateText(row.reviewedAt)}</span>
                      </div>
                      <div className="card-body">
                        {row.reviewComment
                          ? <Markdown source={row.reviewComment} />
                          : <div className="text-meta">검토자 코멘트가 없습니다.</div>}
                      </div>
                    </div>

                    {report && (
                      <div className="card">
                        <div className="card-head">
                          <h3>🤖 Agent 의견</h3>
                          <span className="text-meta">
                            실행 #{report.runId} · {report.ranAt}
                            {report.stale && ' · 실행 이후 그래프 변경됨'}
                          </span>
                        </div>
                        <div className="card-body"><Markdown source={report.agentReport} /></div>
                      </div>
                    )}
                    {report === null && <div className="note">이 그래프의 시뮬레이션 실행 이력이 없습니다.</div>}

                    <div className="row" style={{ justifyContent: 'flex-end', gap: 8 }}>
                      <span className="text-meta">{canActivate ? '룰 활성 권한 보유' : '룰 활성 권한이 없어 처리할 수 없습니다.'}</span>
                      <button className="btn reject" disabled={!canActivate || busy === id} onClick={() => void reject(row)}>
                        {!canActivate && <Lock size={12} />} 반려 (초안으로 되돌리기)
                      </button>
                      <button className="btn approve" disabled={!canActivate || busy === id} onClick={() => void approve(row)}>
                        {!canActivate && <Lock size={12} />} 승인 · ACTIVE 전환 →
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>

      {/* ② 현재 활성 그래프 */}
      <div className="kpi-grid" style={{ gridTemplateColumns: 'repeat(4, 1fr)' }}>
        <div className="kpi">
          <div className="label">활성 그래프</div><div className="value">{dashboard.graphCount}개</div>
          <div className="text-meta">{dashboard.scopeCount}개 스코프 커버</div>
        </div>
        <div className="kpi">
          <div className="label">활성 노드 총계</div><div className="value">{dashboard.nodeCount}개</div>
          <div className="text-meta">활성 그래프의 룰 노드 합계</div>
        </div>
        <div className="kpi">
          <div className="label">평균 자동처리율</div><div className="value">{percent(dashboard.avgAutoRate)}</div>
          <div className="text-meta">
            시뮬레이션 이력 {dashboard.ratedCount}개 기준{dashboard.unrated > 0 && ` · 미측정 ${dashboard.unrated}개`}
          </div>
        </div>
        <div className={'kpi ' + (dashboard.riskCount > 0 ? 'warn' : 'ok')}>
          <div className="label">위험 변경 누계</div><div className="value">{dashboard.riskCount}건</div>
          <div className="text-meta">최근 시뮬레이션 기준</div>
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <div><h3>현재 활성 그래프</h3><div className="text-meta">그래프를 클릭하면 버전 이력에서 롤백할 수 있습니다.</div></div>
          <span className="tag ok">{active.length}개 활성</span>
        </div>
        {!loading && active.length === 0 && <div className="card-body text-meta">활성 상태의 룰 그래프가 없습니다.</div>}
        {/* 스코프별로 좌우 배치 — 스코프당 활성 그래프는 하나뿐이라 한눈에 비교된다 */}
        <div className="card-body active-scope-grid">
          {Object.entries(active.reduce<Record<string, ApiGraphRow[]>>((groups, row) => {
            ;(groups[row.scope] ??= []).push(row)
            return groups
          }, {})).map(([scope, scopeRows]) => (
            <div key={scope} className="active-scope">
              <div className="text-meta" style={{ fontWeight: 700, marginBottom: 6 }}>{scope}</div>
              <div className="stack" style={{ gap: 8 }}>
                {scopeRows.map((row) => (
                  <div key={String(row.id)} className="rule-node-item" role="button" tabIndex={0}
                    style={{ border: '1px solid var(--border)', borderLeftWidth: 3, borderLeftColor: 'var(--tone-green)', padding: 12 }}
                    onClick={() => setHistoryGraph(row)}
                    onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setHistoryGraph(row) } }}>
                    <div className="row" style={{ gap: 6, justifyContent: 'space-between' }}>
                      <b style={{ fontSize: 12.5 }}>{row.name}</b>
                      <span className="tag ok">v{row.version}</span>
                    </div>
                    <div className="text-meta" style={{ marginTop: 4 }}>
                      노드 {nodeCountOf(row)}개 · 활성 {dateText(row.activated_at)}
                      {row.activatedBy && ` · ${row.activatedBy}`}
                    </div>
                    <div className="text-meta">
                      자동처리율 {percent(row.simResult?.stats?.autoRate)} · <History size={11} /> 버전 이력 보기
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      {historyGraph && (
        <VersionHistoryModal graphId={String(historyGraph.id)} graphName={historyGraph.name}
          onClose={() => setHistoryGraph(null)} onChanged={load} />
      )}
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

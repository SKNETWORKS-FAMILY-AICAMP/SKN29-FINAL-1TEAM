// Tab2 — 시뮬레이션 검증 (그래프 단위).
//  대상: 실제 API의 룰 그래프 중 "모든 노드가 검증대기"인 그래프만.
//  구성: ① 그래프 선택 → ② 그래프 구조(플로우차트) + 노드 상세 읽기 → ③ 검증 시뮬레이션 보고서.
import { useEffect, useMemo, useState } from 'react'
import { endpoints } from '../../api/client'
import { SkeletonLines } from '../../components/ui/Skeleton'
import { isSimulatable, toGraph, type ApiGraph } from './data/graphApi'
import { type SimReport } from './data/simulationTypes'
import { type RuleGraph } from './data/ruleConsoleMock'
import { GraphFlowView } from './GraphFlowView'
import { NodeDetailRead } from './NodeDetailRead'
import { SimulationEmptyState, SimulationReportView } from './SimulationReport'
import { ActivationRequestModal } from './ActivationRequestModal'

export function SimulationTab() {
  const [graphs, setGraphs] = useState<RuleGraph[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [graphId, setGraphId] = useState('')
  const [nodeKey, setNodeKey] = useState('')
  // 과거 실행 결과가 있으면 그대로 보여준다(2026-08-19, "결과를 굳이 숨길 이유가 없다"는
  // 재요청) — report가 곧 "보여줄 결과 있음"이라 별도 revealed 플래그가 필요 없다.
  const [report, setReport] = useState<SimReport | null>(null)
  const [reportLoadFailed, setReportLoadFailed] = useState(false)
  const [running, setRunning] = useState(false)
  const [runError, setRunError] = useState('')
  const [genNote, setGenNote] = useState<{ tone: 'ok' | 'warn'; text: string } | null>(null)
  // §2-2 — 이번 생성에서 제외되거나 발견으로 반영된 케이스의 사유("왜 이 케이스들이 이렇게 됐는지").
  const [generationLog, setGenerationLog] = useState<{ nodeKey: string; kind: string; outcome: string; problem: string }[]>([])
  const [logOpen, setLogOpen] = useState(false)
  const [activationOpen, setActivationOpen] = useState(false)
  const [requesting, setRequesting] = useState(false)
  const [requestError, setRequestError] = useState('')
  const [requested, setRequested] = useState('')
  const [pendingScopes, setPendingScopes] = useState<Set<string>>(new Set())

  useEffect(() => {
    let cancelled = false
    endpoints.rules().then(({ data }) => {
      if (cancelled) return
      const all = (data as ApiGraph[]).map(toGraph)
      // 승인대기는 스코프당 1건 — 이미 대기 중인 스코프는 Active 요청을 막는다.
      setPendingScopes(new Set(all.filter((item) => item.status === 'SIMULATED').map((item) => item.scope)))
      const loaded = all.filter(isSimulatable)
      setGraphs(loaded)
      const first = loaded[0]
      if (first) {
        setGraphId(first.id)
        setNodeKey(first.entryNodeKey || first.nodes[0].nodeKey)
      }
    }).catch(() => {
      if (!cancelled) setError('룰 그래프를 불러오지 못했습니다. Core API 연결을 확인해주세요.')
    }).finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  // 그래프(버전)마다 최신 보고서를 불러온다. 화면에는 최신 실행만 보여준다.
  useEffect(() => {
    if (!graphId) return
    let cancelled = false
    setReport(null)
    setReportLoadFailed(false)
    setRunError('')
    setRequested('')
    setGenNote(null)
    setGenerationLog([])
    setLogOpen(false)
    endpoints.ruleSimulation(graphId).then(({ data, status }) => {
      if (!cancelled && status === 200 && data) setReport(data as SimReport)
    }).catch(() => {
      // 「이력이 없다」와 「불러오지 못했다」는 다른 상태 — 실패를 삼키면 빈 상태 문구가 거짓말을 한다.
      if (!cancelled) setReportLoadFailed(true)
    })
    return () => { cancelled = true }
  }, [graphId])

  const graph = useMemo(() => graphs.find((candidate) => candidate.id === graphId), [graphs, graphId])
  const node = graph?.nodes.find((candidate) => candidate.nodeKey === nodeKey) ?? graph?.nodes[0]

  const selectGraph = (next: RuleGraph) => {
    setGraphId(next.id)
    setNodeKey(next.entryNodeKey || next.nodes[0]?.nodeKey || '')
  }

  // 시뮬레이션 실행 = 검증셋 자동생성(그래프 현재 조건 기준 replace) + 그 결과로 시뮬레이션까지
  // 한 번에. 예전엔 "검증셋 자동생성"과 "시뮬레이션 실행"이 별도 버튼이었는데, 검증셋을
  // 사람이 직접 관리할 일이 없어진 뒤로는(자동생성이 유일한 경로) 따로 눌러야 할 이유가
  // 없다 — 실행 버튼 하나로 통합한다(2026-08-19).
  const run = async () => {
    if (!graph) return
    setRunning(true)
    setRunError('')
    setGenNote(null)
    try {
      const { data } = await endpoints.generateRuleTestCases(graph.id)
      const result = data as {
        status: string; detail?: string; attempted?: number; generated?: number
        unresolved?: { nodeKey: string; kind: string; reason: string }[]
        skippedNodes?: { node_key: string; reason: string }[]
        belowTarget?: boolean; minTarget?: number
        generationLog?: { nodeKey: string; kind: string; outcome: string; problem: string }[]
        simulationReport?: SimReport
      }
      if (result.status !== 'DONE') {
        setGenNote({ tone: 'warn', text: result.detail || '역산 가능한 노드가 없어 생성하지 못했습니다.' })
        return
      }
      if (result.simulationReport) setReport(result.simulationReport)
      setGenerationLog(result.generationLog ?? [])
      const attempted = result.attempted ?? result.generated ?? 0
      const generated = result.generated ?? 0
      const unresolvedCount = result.unresolved?.length ?? 0
      const skippedCount = result.skippedNodes?.length ?? 0
      // "전체 N건 중 M건 반영" — 시도 자체가 생성 건수와 같으면(전부 통과) 굳이 분모를 안 보인다.
      const parts = [attempted > generated ? `총 ${attempted}건 중 ${generated}건 검증셋에 반영` : `${generated}건 생성`]
      if (unresolvedCount) parts.push(`${unresolvedCount}건은 자체검증 실패로 제외`)
      if (skippedCount) parts.push(`${skippedCount}개 노드는 지원 범위 밖 조건이라 건너뜀`)
      if (result.belowTarget) parts.push(`그래프 구조상 최소 ${result.minTarget}건을 채울 소스가 없어 ${generated}건까지만 생성됨`)
      setGenNote({ tone: unresolvedCount || skippedCount || result.belowTarget ? 'warn' : 'ok', text: parts.join(' · ') })
    } catch (failure) {
      const detail = (failure as { response?: { data?: { detail?: string } } }).response?.data?.detail
      setRunError(detail || '시뮬레이션을 실행하지 못했습니다. Core API 연결과 권한을 확인해주세요.')
    } finally {
      setRunning(false)
    }
  }

  const requestActivation = async (comment: string) => {
    if (!graph) return
    setRequesting(true)
    setRequestError('')
    try {
      await endpoints.requestRuleActivation(graph.id, comment)
      setActivationOpen(false)
      setRequested('Active 요청을 보냈습니다. 그래프가 승인대기로 전환되어 룰 활성 권한자의 최종 승인을 기다립니다.')
      setGraphs((previous) => previous.filter((candidate) => candidate.id !== graph.id))
      setPendingScopes((previous) => new Set(previous).add(graph.scope))
    } catch (failure) {
      const detail = (failure as { response?: { data?: { detail?: string } } }).response?.data?.detail
      setRequestError(detail || 'Active 요청에 실패했습니다. 권한과 시뮬레이션 실행 여부를 확인해주세요.')
    } finally {
      setRequesting(false)
    }
  }

  return (
    <>
      {/* ① 검증할 룰 그래프 선택 — 모든 노드가 검증대기인 그래프만 */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-head">
          <div><h3>검증할 룰 그래프 선택</h3><div className="text-meta">모든 노드가 <b>검증대기</b> 상태인 그래프만 표시됩니다.</div></div>
          <span className="text-meta">{graphs.length}개 대상</span>
        </div>
        {loading && (
          <div style={{ padding: 16 }}>
            <span className="text-meta">룰 그래프를 불러오는 중…</span>
            <div style={{ marginTop: 8 }}><SkeletonLines rows={2} /></div>
          </div>
        )}
        {error && <div className="note error" style={{ margin: 12 }}>{error}</div>}
        {!loading && !error && graphs.length === 0 && (
          <div className="text-meta" style={{ padding: 16 }}>
            검증 대상 그래프가 없습니다. 초안 그래프 탭에서 노드를 “초안 완료 · 검증 대기로 전환” 하면 이곳에 나타납니다.
          </div>
        )}
        {graphs.length > 0 && (
          <div className="card-body" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 12 }}>
            {graphs.map((candidate) => (
              <label key={candidate.id} className="row" style={{
                gap: 8, alignItems: 'flex-start', padding: 12, border: '1px solid var(--border)',
                borderRadius: 'var(--radius-control)', background: candidate.id === graphId ? 'var(--primary-soft)' : undefined,
                cursor: 'pointer',
              }}>
                <input type="radio" name="sim-graph" checked={candidate.id === graphId}
                  onChange={() => selectGraph(candidate)} style={{ marginTop: 3 }} />
                <div style={{ minWidth: 0 }}>
                  <div className="row" style={{ gap: 6 }}>
                    <b style={{ fontSize: 12.5 }}>{candidate.name}</b>
                    <span className="tag">v{candidate.version ?? 1}</span>
                  </div>
                  <div className="text-meta">{candidate.scope} · 노드 {candidate.nodes.length}개 · 전부 검증대기</div>
                </div>
              </label>
            ))}
          </div>
        )}
      </div>

      {graph && (
        <>
          {/* ② 그래프 구조 — 좌: 플로우차트 / 우: 노드 상세 읽기 */}
          <div className="sim-structure-grid" style={{ marginBottom: 16 }}>
            <div className="card">
              <div className="card-head">
                <div><h3>그래프 구조</h3><div className="text-meta">노드를 클릭하면 우측에 상세가 표시됩니다.</div></div>
                <span className="tag ai">노드 {graph.nodes.length} · 라우팅 {graph.routings.length}</span>
              </div>
              <GraphFlowView graph={graph} selectedKey={node?.nodeKey ?? ''} onSelect={setNodeKey} />
            </div>
            {node
              ? <NodeDetailRead key={`${graph.id}-${node.nodeKey}`} graph={graph} node={node} />
              : <div className="card"><div className="card-body text-meta">표시할 노드가 없습니다.</div></div>}
          </div>

          {genNote && (
            <div className="note" style={{
              marginBottom: generationLog.length ? 0 : 12,
              color: genNote.tone === 'ok' ? 'var(--tone-green)' : 'var(--tone-amber)',
              borderColor: genNote.tone === 'ok' ? 'var(--tone-green)' : 'var(--tone-amber)',
            }}>
              검증셋: {genNote.text}
              {generationLog.length > 0 && (
                <>
                  {' · '}
                  <button className="btn sm" style={{ marginLeft: 4 }} onClick={() => setLogOpen((v) => !v)}>
                    {logOpen ? '사유 숨기기 ▲' : `이번 생성에서 발견한 사항 ${generationLog.length}건 보기 ▼`}
                  </button>
                </>
              )}
            </div>
          )}
          {logOpen && generationLog.length > 0 && (
            <div className="card" style={{ marginBottom: 12 }}>
              <div className="card-body stack" style={{ gap: 8, fontSize: 12.5 }}>
                {generationLog.map((entry, i) => (
                  <div key={i} className="row" style={{ gap: 8, alignItems: 'flex-start' }}>
                    <span className={'tag ' + (entry.outcome === '제외됨' ? 'warn' : 'ok')} style={{ flexShrink: 0 }}>
                      {entry.nodeKey} · {entry.outcome}
                    </span>
                    <span className="text-meta">{entry.problem}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* ③ 검증 시뮬레이션 보고서 — 과거 실행 이력이 있으면 그대로 보여주고, 없으면 빈
              상태("실행하기") — "실행하기" 한 번이면 검증셋 생성부터 시뮬레이션까지 끝나
              전체 보고서로 펼쳐진다 — 별도의 "검증셋 자동생성" 버튼 없이. */}
          {reportLoadFailed && !report && (
            <div className="note error" style={{ marginBottom: 12 }}>
              기존 시뮬레이션 보고서를 불러오지 못했습니다 — 실행 이력이 없는 것이 아닐 수 있습니다. 아래에서 새로 실행할 수 있습니다.
            </div>
          )}
          {report
            ? <SimulationReportView report={report} running={running} error={runError} onRun={() => void run()} />
            : <SimulationEmptyState running={running} error={runError} onRun={() => void run()} />}

          {report && (
            <div className="row" style={{ gap: 8, marginTop: 16, justifyContent: 'flex-end' }}>
              {report.structureError && <span className="text-meta" style={{ color: 'var(--tone-red)' }}>구조 오류가 있어 Active 요청을 보낼 수 없습니다.</span>}
              {!report.structureError && pendingScopes.has(graph.scope) && (
                <span className="text-meta" style={{ color: 'var(--tone-red)' }}>
                  같은 분류({graph.scope})에 승인대기 그래프가 있어 요청할 수 없습니다. Active 관리 탭에서 먼저 처리하세요.
                </span>
              )}
              <button className="btn approve" onClick={() => { setRequestError(''); setActivationOpen(true) }}
                disabled={!!report.structureError || pendingScopes.has(graph.scope)}>Active 요청 →</button>
            </div>
          )}
        </>
      )}

      {requested && <div className="note" style={{ marginTop: 16, color: 'var(--tone-green)', borderColor: 'var(--tone-green)' }}>{requested}</div>}

      {activationOpen && report && graph && (
        <ActivationRequestModal report={report} graphName={graph.name} submitting={requesting} error={requestError}
          onClose={() => setActivationOpen(false)} onSubmit={(comment) => void requestActivation(comment)} />
      )}
    </>
  )
}

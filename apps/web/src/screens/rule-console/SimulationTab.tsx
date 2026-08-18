// Tab2 — 시뮬레이션 검증 (그래프 단위).
//  대상: 실제 API의 룰 그래프 중 "모든 노드가 검증대기"인 그래프만.
//  구성: ① 그래프 선택 → ② 그래프 구조(플로우차트) + 노드 상세 읽기 → ③ 검증 시뮬레이션 보고서.
import { useEffect, useMemo, useState } from 'react'
import { endpoints } from '../../api/client'
import { isSimulatable, toGraph, type ApiGraph } from './data/graphApi'
import { DEFAULT_TEST_CASES, type SimReport, type TestCase } from './data/simulationTypes'
import { type RuleGraph } from './data/ruleConsoleMock'
import { GraphFlowView } from './GraphFlowView'
import { NodeDetailRead } from './NodeDetailRead'
import { SimulationEmptyState, SimulationReportView } from './SimulationReport'
import { TestCaseModal } from './TestCaseModal'
import { ActivationRequestModal } from './ActivationRequestModal'

// 저장된 검증셋(API) ↔ 화면 모델 변환
type ApiTestCase = {
  id: string; label: string; merchant: string; amount: number; category: string
  merchantType: string; paymentMethod: string; expected: string; facts: Record<string, boolean | number>
}
const fromApiCase = (raw: ApiTestCase): TestCase => ({
  id: raw.id, label: raw.label, merchant: raw.merchant, amount: raw.amount, category: raw.category,
  merchantType: raw.merchantType, paymentMethod: raw.paymentMethod || '법인카드',
  expected: (raw.expected || '') as TestCase['expected'], facts: raw.facts || {},
})
const toApiCase = (item: TestCase) => ({
  id: item.id, label: item.label, merchant: item.merchant, amount: item.amount, category: item.category,
  merchantType: item.merchantType, paymentMethod: item.paymentMethod, expected: item.expected, facts: item.facts,
})

export function SimulationTab() {
  const [graphs, setGraphs] = useState<RuleGraph[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [graphId, setGraphId] = useState('')
  const [nodeKey, setNodeKey] = useState('')
  const [testCases, setTestCases] = useState<TestCase[]>([])
  const [caseModalOpen, setCaseModalOpen] = useState(false)
  const [report, setReport] = useState<SimReport | null>(null)
  const [running, setRunning] = useState(false)
  const [runError, setRunError] = useState('')
  const [generating, setGenerating] = useState(false)
  const [genNote, setGenNote] = useState<{ tone: 'ok' | 'warn'; text: string } | null>(null)
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

  // 그래프(버전)마다 저장된 검증셋과 최신 보고서를 불러온다. 화면에는 최신 실행만 보여준다.
  useEffect(() => {
    if (!graphId) return
    let cancelled = false
    setReport(null)
    setTestCases([])
    setRunError('')
    setRequested('')
    setGenNote(null)
    endpoints.ruleTestCases(graphId).then(({ data }) => {
      if (cancelled) return
      const saved = (data as ApiTestCase[]).map(fromApiCase)
      setTestCases(saved.length ? saved : DEFAULT_TEST_CASES)
    }).catch(() => { if (!cancelled) setTestCases(DEFAULT_TEST_CASES) })
    endpoints.ruleSimulation(graphId).then(({ data, status }) => {
      if (!cancelled && status === 200 && data) setReport(data as SimReport)
    }).catch(() => undefined)
    return () => { cancelled = true }
  }, [graphId])

  const graph = useMemo(() => graphs.find((candidate) => candidate.id === graphId), [graphs, graphId])
  const node = graph?.nodes.find((candidate) => candidate.nodeKey === nodeKey) ?? graph?.nodes[0]

  const selectGraph = (next: RuleGraph) => {
    setGraphId(next.id)
    setNodeKey(next.entryNodeKey || next.nodes[0]?.nodeKey || '')
  }

  const run = async () => {
    if (!graph) return
    setRunning(true)
    setRunError('')
    try {
      const { data } = await endpoints.simulateRule(graph.id, testCases.map(toApiCase))
      setReport(data as SimReport)
    } catch {
      setRunError('시뮬레이션을 실행하지 못했습니다. Core API 연결과 권한을 확인해주세요.')
    } finally {
      setRunning(false)
    }
  }

  // 검증셋 자동생성 — 대화형 아님, 완제품을 한 번에 만들어 기존 검증셋에 추가(append)한다.
  // 응답에 최신 시뮬레이션 보고서가 이미 포함돼 있어 별도 실행 없이 바로 결과를 보여준다.
  const autoGenerate = async () => {
    if (!graph) return
    setGenerating(true)
    setRunError('')
    setGenNote(null)
    try {
      const { data } = await endpoints.generateRuleTestCases(graph.id)
      const result = data as {
        status: string; detail?: string; generated?: number
        unresolved?: { nodeKey: string; kind: string; reason: string }[]
        skippedNodes?: { node_key: string; reason: string }[]
        simulationReport?: SimReport
      }
      if (result.status !== 'DONE') {
        setGenNote({ tone: 'warn', text: result.detail || '역산 가능한 노드가 없어 생성하지 못했습니다.' })
        return
      }
      const { data: casesData } = await endpoints.ruleTestCases(graph.id)
      setTestCases((casesData as ApiTestCase[]).map(fromApiCase))
      if (result.simulationReport) setReport(result.simulationReport)
      const unresolvedCount = result.unresolved?.length ?? 0
      const skippedCount = result.skippedNodes?.length ?? 0
      const parts = [`${result.generated ?? 0}건 생성`]
      if (unresolvedCount) parts.push(`${unresolvedCount}건은 자체검증 실패로 제외`)
      if (skippedCount) parts.push(`${skippedCount}개 노드는 지원 범위 밖 조건이라 건너뜀`)
      setGenNote({ tone: unresolvedCount || skippedCount ? 'warn' : 'ok', text: parts.join(' · ') })
    } catch (failure) {
      const detail = (failure as { response?: { data?: { detail?: string } } }).response?.data?.detail
      setGenNote({ tone: 'warn', text: detail || '검증셋 자동생성에 실패했습니다. 권한과 그래프 상태(초안)를 확인해주세요.' })
    } finally {
      setGenerating(false)
    }
  }

  const saveCases = async (next: TestCase[]) => {
    setTestCases(next)
    setCaseModalOpen(false)
    if (!graph) return
    try {
      await endpoints.saveRuleTestCases(graph.id, next.map(toApiCase))
    } catch {
      setRunError('검증셋을 저장하지 못했습니다. 실행 시 다시 시도됩니다.')
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
        {loading && <div className="text-meta" style={{ padding: 16 }}>룰 그래프를 불러오는 중입니다.</div>}
        {error && <div className="note" style={{ margin: 12, color: 'var(--tone-red)' }}>{error}</div>}
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
              marginBottom: 12,
              color: genNote.tone === 'ok' ? 'var(--tone-green)' : 'var(--tone-amber)',
              borderColor: genNote.tone === 'ok' ? 'var(--tone-green)' : 'var(--tone-amber)',
            }}>
              검증셋 자동생성: {genNote.text}
            </div>
          )}

          {/* ③ 검증 시뮬레이션 보고서 — 실행 전에는 빈 상태 + 실행/검증셋/자동생성 버튼만 */}
          {report
            ? <SimulationReportView report={report} caseCount={testCases.length} running={running} generating={generating}
                error={runError} onRun={() => void run()} onEditCases={() => setCaseModalOpen(true)} onAutoGenerate={() => void autoGenerate()} />
            : <SimulationEmptyState caseCount={testCases.length} running={running} generating={generating}
                error={runError} onRun={() => void run()} onEditCases={() => setCaseModalOpen(true)} onAutoGenerate={() => void autoGenerate()} />}

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

      {caseModalOpen && (
        <TestCaseModal cases={testCases} onClose={() => setCaseModalOpen(false)} onSave={(next) => void saveCases(next)} />
      )}

      {activationOpen && report && graph && (
        <ActivationRequestModal report={report} graphName={graph.name} submitting={requesting} error={requestError}
          onClose={() => setActivationOpen(false)} onSubmit={(comment) => void requestActivation(comment)} />
      )}
    </>
  )
}

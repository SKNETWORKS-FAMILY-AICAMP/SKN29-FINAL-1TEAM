// ② Rule Agent 실험실 — 운영과 같은 `rule_agent_v0.agent.generate()`를 그대로 부른다.
//  Draft/RAG 탭과 달리 **부작용이 있다**: 실행하면 Django에 실제 RuleGraph(DRAFT)가
//  생긴다(Rule Agent의 산출물 자체가 "저장된 그래프"라 dry-run 경로를 따로 두지 않았다).
import { useState } from 'react'
import { AlertTriangle, Play } from 'lucide-react'
import { labApi, labErrorMessage, type RuleGenerateLabResponse } from './data/labApi'
import { EmptyHint, ErrorBanner, FactRow, JsonBlock } from './components/LabPrimitives'
import { useCategories } from '../../lib/categories'

//  scope 목록도 서버가 정한다(GLOBAL ∪ Category) — `useCategories().ruleScopes`.

export function RuleLab() {
  const [scope, setScope] = useState<string>('GLOBAL')
  const { ruleScopes } = useCategories()
  const [query, setQuery] = useState('')
  const [topK, setTopK] = useState(6)
  const [name, setName] = useState('')
  const [includeLaw, setIncludeLaw] = useState(false)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')
  const [res, setRes] = useState<RuleGenerateLabResponse | null>(null)

  const run = async () => {
    if (!window.confirm('이 실행은 Django에 실제 RuleGraph(DRAFT)를 생성합니다. 계속할까요?')) return
    setRunning(true)
    setError('')
    try {
      setRes(
        await labApi.runRuleGenerate({
          scope, query: query.trim() || undefined, topK, name: name.trim() || undefined, includeLaw,
        }),
      )
    } catch (err) {
      setError(labErrorMessage(err))
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="stack-lg">
      <div className="note" style={{ borderColor: 'var(--tone-amber)', color: 'var(--tone-amber)' }}>
        <AlertTriangle size={13} style={{ verticalAlign: -2, marginRight: 4 }} />
        실행하면 RAG 검색 + LLM 노드 초안 + 결정론적 조립을 거쳐 <b>Django에 실제 DRAFT 그래프</b>가
        생성됩니다(룰 콘솔·S-04에서 확인·삭제 가능). 실험 전용 dry-run은 없습니다 — 운영과 같은
        코드를 부르기 때문입니다.
      </div>

      <div className="card">
        <div className="card-head"><h3>생성 입력</h3></div>
        <div className="card-body">
          <div className="lab-controls">
            <div className="field" style={{ marginBottom: 0, minWidth: 160 }}>
              <label>scope</label>
              <select value={scope} onChange={(e) => setScope(e.target.value)}>
                {ruleScopes.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <div className="field" style={{ marginBottom: 0, width: 100 }}>
              <label>top-K</label>
              <input type="number" min={1} max={20} value={topK} onChange={(e) => setTopK(Number(e.target.value))} />
            </div>
            <label className="lab-check">
              <input type="checkbox" checked={includeLaw} onChange={(e) => setIncludeLaw(e.target.checked)} />
              세법(tax_refs)도 근거로 검색
            </label>
          </div>
          <div className="field">
            <label>질의 (비우면 scope별 기본 질의)</label>
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="예) 회식비 1인당 한도와 2차 규정" />
          </div>
          <div className="field" style={{ marginBottom: 0 }}>
            <label>그래프 이름 (비우면 자동 생성)</label>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="예) 회식비 검증 그래프 v1" />
          </div>
        </div>
        <div className="lab-runbar">
          <button className="btn primary" onClick={run} disabled={running}>
            <Play size={13} /> {running ? '생성 중… (수십 초 소요)' : '생성 실행'}
          </button>
        </div>
      </div>

      {error && <ErrorBanner message={error} />}
      {!res && !error && (
        <EmptyHint>scope를 고르고 생성을 누르면 RAG 근거·LLM 조립 결과·저장된 그래프 id가 나옵니다.</EmptyHint>
      )}

      {res && (
        <>
          <div className="card">
            <div className="card-head"><h3>생성 결과</h3></div>
            <div className="card-body">
              <div className="note" style={{ marginBottom: 12 }}>{res.sideEffectNote}</div>
              <FactRow
                items={[
                  ['상태', res.result.status],
                  ['그래프', res.result.graph && 'id' in res.result.graph
                    ? `${(res.result.graph as { name: string }).name} (id ${(res.result.graph as { id: string }).id})`
                    : '—'],
                  ['진입 노드', res.result.entry_node_key ?? '—'],
                  ['근거 문서 수', Array.isArray(res.result.sources) ? res.result.sources.length : '—'],
                  ['거부된 노드', Array.isArray(res.result.rejected_nodes) ? res.result.rejected_nodes.length : '—'],
                  ['재시도 횟수', res.result.attempts ?? '—'],
                  ['지연', `${res.latencyMs}ms`],
                ]}
              />
            </div>
          </div>
          <div className="card">
            <div className="card-head"><h3>전체 응답</h3></div>
            <div className="card-body">
              <JsonBlock value={res} label="POST /api/ai-lab/rule/generate" maxHeight={420} />
            </div>
          </div>
        </>
      )}
    </div>
  )
}

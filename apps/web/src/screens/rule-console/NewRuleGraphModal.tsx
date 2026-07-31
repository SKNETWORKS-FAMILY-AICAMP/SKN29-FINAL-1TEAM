// 신규 룰 생성 모달 — ① 기존 룰그래프 버전에 노드 추가 or ② 빈 룰그래프 생성.
//  확정 시 빈 룰노드가 만들어져 상세에 올라오고, 이후 대화/직접입력으로 세부 설정한다.
import { useState } from 'react'
import { FilePlus2, GitBranch } from 'lucide-react'
import { Modal } from '../../components/ui/Modal'
import type { RuleGraph } from './data/ruleConsoleMock'
import { GRAPH_STATUS_LABEL, workingVersion } from './data/ruleConsoleMock'

export type NewRuleChoice =
  | { kind: 'existing'; graphId: string }
  | { kind: 'new'; name: string; scope: string }

export function NewRuleGraphModal({
  graphs, onClose, onConfirm,
}: {
  /** 노드를 붙일 수 있는 초안 단계 그래프 목록 */
  graphs: RuleGraph[]
  onClose: () => void
  onConfirm: (choice: NewRuleChoice) => void
}) {
  const [mode, setMode] = useState<'existing' | 'new'>(graphs.length ? 'existing' : 'new')
  const [graphId, setGraphId] = useState(graphs[0]?.id ?? '')
  const [name, setName] = useState('')
  const [scope, setScope] = useState('')

  const canConfirm = mode === 'existing' ? !!graphId : name.trim() !== '' && scope.trim() !== ''
  const confirm = () => {
    if (!canConfirm) return
    onConfirm(mode === 'existing' ? { kind: 'existing', graphId } : { kind: 'new', name: name.trim(), scope: scope.trim() })
  }

  const footer = (
    <>
      <button className="btn" onClick={onClose}>취소</button>
      <button className="btn primary" onClick={confirm} disabled={!canConfirm}>빈 룰 노드 생성 →</button>
    </>
  )

  return (
    <Modal title="신규 룰 생성" onClose={onClose} footer={footer} maxWidth={620}>
      <p className="text-meta" style={{ marginBottom: 16 }}>
        룰은 <b>그래프 단위</b>로 관리됩니다. 기존 룰그래프의 새 버전(초안)에 노드를 추가하거나, 빈 룰그래프를 새로 만든 뒤
        <b> 빈 룰 노드</b>를 생성합니다. 세부 조건·액션은 다음 단계(상세)에서 대화·직접입력으로 설정합니다.
      </p>

      <div className="stack" style={{ gap: 10 }}>
        {/* ① 기존 그래프 버전에 추가 */}
        <label className={'newrule-opt' + (mode === 'existing' ? ' active' : '')}>
          <input type="radio" checked={mode === 'existing'} onChange={() => setMode('existing')} disabled={!graphs.length} />
          <div style={{ flex: 1 }}>
            <div className="row" style={{ gap: 6 }}><GitBranch size={14} /> <b>기존 룰그래프 버전에 노드 추가</b></div>
            <div className="text-meta" style={{ margin: '2px 0 8px' }}>선택한 그래프의 작업중 버전(초안)에 빈 노드를 추가합니다.</div>
            <select value={graphId} onChange={(e) => setGraphId(e.target.value)} disabled={mode !== 'existing' || !graphs.length} style={{ width: '100%' }}>
              {graphs.length === 0 && <option value="">추가 가능한 초안 그래프가 없습니다</option>}
              {graphs.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name} · {g.scope} · {workingVersion(g)?.label} {GRAPH_STATUS_LABEL[g.status]}
                </option>
              ))}
            </select>
          </div>
        </label>

        {/* ② 빈 그래프 생성 */}
        <label className={'newrule-opt' + (mode === 'new' ? ' active' : '')}>
          <input type="radio" checked={mode === 'new'} onChange={() => setMode('new')} />
          <div style={{ flex: 1 }}>
            <div className="row" style={{ gap: 6 }}><FilePlus2 size={14} /> <b>빈 룰그래프 생성</b></div>
            <div className="text-meta" style={{ margin: '2px 0 8px' }}>새 그래프(v1 초안)를 만들고 첫 빈 노드를 생성합니다.</div>
            <div className="grid-2" style={{ gap: 8 }}>
              <input placeholder="그래프 이름 (예: 출장 여비 검증)" value={name} onChange={(e) => setName(e.target.value)} disabled={mode !== 'new'} />
              <input placeholder="적용 범위/계정과목 (예: 출장)" value={scope} onChange={(e) => setScope(e.target.value)} disabled={mode !== 'new'} />
            </div>
          </div>
        </label>
      </div>
    </Modal>
  )
}

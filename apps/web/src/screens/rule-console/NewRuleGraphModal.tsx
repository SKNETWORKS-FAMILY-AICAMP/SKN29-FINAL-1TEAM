// 신규 그래프 생성 모달 — ① 빈 룰그래프 ② 규정 문서(RAG)에서 Rule Agent가 자동 생성.
//  기존 그래프의 새 버전은 여기서 만들지 않는다(그래프를 열어 노드를 수정하면 자동으로 다음 버전 초안이 생성됨).
import { useState } from 'react'
import { FilePlus2, Sparkles } from 'lucide-react'
import { Modal } from '../../components/ui/Modal'

// GLOBAL ∪ settlements.Category. SoT는 Django `Category`이며 규정 표기(기업업무추진비·회식)는
// 백엔드 `normalize_scope`가 접는다 — 회식은 식대 scope 그래프에 편성된다.
const RULE_SCOPES = ['업무활성', '회의', '식대', '출장', '접대', '비품'] as const

export type NewRuleChoice =
  | { kind: 'new'; name: string; scope: string }
  | { kind: 'generate'; name: string; scope: string; query: string; includeLaw: boolean }

export function NewRuleGraphModal({
  onClose, onConfirm, busy = false,
}: {
  onClose: () => void
  onConfirm: (choice: NewRuleChoice) => void
  /** 생성 진행 중 — 룰 생성은 LLM·임베딩이 얹혀 수십 초 걸린다. 중복 제출을 막는다. */
  busy?: boolean
}) {
  const [mode, setMode] = useState<'new' | 'generate'>('new')
  const [name, setName] = useState('')
  const [scope, setScope] = useState('')
  const [query, setQuery] = useState('')
  const [includeLaw, setIncludeLaw] = useState(false)

  const canConfirm = !busy && name.trim() !== '' && scope.trim() !== ''
  const confirm = () => {
    if (!canConfirm) return
    if (mode === 'generate') {
      onConfirm({ kind: 'generate', name: name.trim(), scope: scope.trim(), query: query.trim(), includeLaw })
    } else {
      onConfirm({ kind: 'new', name: name.trim(), scope: scope.trim() })
    }
  }

  const footer = (
    <>
      <button className="btn" onClick={onClose} disabled={busy}>취소</button>
      <button className="btn primary" onClick={confirm} disabled={!canConfirm}>
        {busy ? '생성 중…' : mode === 'generate' ? '규정에서 생성 →' : '그래프 생성 →'}
      </button>
    </>
  )

  const scopeField = (
    <div className="field" style={{ marginBottom: 0 }}><label>비용분류 (scope)</label>
      <select value={scope} onChange={(e) => setScope(e.target.value)} disabled={busy}>
        <option value="">비용분류 선택</option>
        {RULE_SCOPES.map((value) => <option key={value} value={value}>{value}</option>)}
      </select>
    </div>
  )

  return (
    <Modal title="신규 그래프 생성" onClose={onClose} footer={footer} maxWidth={560}>
      <p className="text-meta" style={{ marginBottom: 16 }}>
        룰은 <b>그래프 단위</b>로 관리됩니다. 빈 그래프로 시작하거나, 적재된 사내 규정에서
        Rule Agent가 초안을 만들게 할 수 있습니다. 어느 쪽이든 결과는 <b>초안(DRAFT)</b>이며,
        검토·시뮬레이션을 거쳐야 활성화됩니다.
      </p>

      <div
        className={`newrule-opt${mode === 'new' ? ' active' : ''}`}
        onClick={() => !busy && setMode('new')}
      >
        <FilePlus2 size={16} style={{ marginTop: 2 }} />
        <div style={{ flex: 1 }}>
          <b>빈 룰그래프</b>
          <div className="text-meta" style={{ margin: '2px 0 10px' }}>
            같은 비용분류(scope)에는 활성 그래프가 하나만 존재할 수 있습니다.
          </div>
          {mode === 'new' && (
            <>
              <div className="field"><label>그래프 이름</label>
                <input placeholder="예) 출장 여비 검증 그래프" value={name}
                       onChange={(e) => setName(e.target.value)} disabled={busy} autoFocus />
              </div>
              {scopeField}
            </>
          )}
        </div>
      </div>

      <div
        className={`newrule-opt${mode === 'generate' ? ' active' : ''}`}
        style={{ marginTop: 12 }}
        onClick={() => !busy && setMode('generate')}
      >
        <Sparkles size={16} style={{ marginTop: 2 }} />
        <div style={{ flex: 1 }}>
          <b>규정 문서에서 생성 (Rule Agent)</b>
          <div className="text-meta" style={{ margin: '2px 0 10px' }}>
            적재된 사내 규정에서 해당 분류의 조항을 찾아 룰 노드 초안을 만듭니다.
            각 노드에는 근거 조문이 함께 기록됩니다. 규정이 아직 적재되지 않았다면 실패합니다.
          </div>
          {mode === 'generate' && (
            <>
              <div className="field"><label>그래프 이름</label>
                <input placeholder="예) 기업업무추진비 자동생성 초안" value={name}
                       onChange={(e) => setName(e.target.value)} disabled={busy} autoFocus />
              </div>
              <div className="field">{scopeField}</div>
              <div className="field"><label>검색 질의 <span className="text-meta">(비우면 분류별 기본 질의)</span></label>
                <input placeholder="예) 사전승인 기준 금액, 증빙 기재사항" value={query}
                       onChange={(e) => setQuery(e.target.value)} disabled={busy} />
              </div>
              <label className="text-meta" style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 0 }}>
                <input type="checkbox" checked={includeLaw} disabled={busy}
                       onChange={(e) => setIncludeLaw(e.target.checked)} />
                세법(법인세법·부가가치세법 등)도 근거로 함께 검색
              </label>
            </>
          )}
        </div>
      </div>
    </Modal>
  )
}

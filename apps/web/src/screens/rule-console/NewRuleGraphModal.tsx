// 신규 그래프 생성 모달 — 빈 룰그래프(v1 초안) + 첫 빈 노드를 만든다.
//  기존 그래프의 새 버전은 여기서 만들지 않는다(그래프를 열어 노드를 수정하면 자동으로 다음 버전 초안이 생성됨).
import { useState } from 'react'
import { FilePlus2 } from 'lucide-react'
import { Modal } from '../../components/ui/Modal'

const RULE_SCOPES = ['업무활성', '회의', '식대', '출장', '접대', '비품'] as const

export type NewRuleChoice = { kind: 'new'; name: string; scope: string }

export function NewRuleGraphModal({
  onClose, onConfirm,
}: {
  onClose: () => void
  onConfirm: (choice: NewRuleChoice) => void
}) {
  const [name, setName] = useState('')
  const [scope, setScope] = useState('')

  const canConfirm = name.trim() !== '' && scope.trim() !== ''
  const confirm = () => {
    if (canConfirm) onConfirm({ kind: 'new', name: name.trim(), scope: scope.trim() })
  }

  const footer = (
    <>
      <button className="btn" onClick={onClose}>취소</button>
      <button className="btn primary" onClick={confirm} disabled={!canConfirm}>그래프 생성 →</button>
    </>
  )

  return (
    <Modal title="신규 그래프 생성" onClose={onClose} footer={footer} maxWidth={560}>
      <p className="text-meta" style={{ marginBottom: 16 }}>
        룰은 <b>그래프 단위</b>로 관리됩니다. 비어 있는 룰그래프(v1 초안)와 첫 빈 노드를 만들고,
        세부 조건·액션은 다음 단계(노드 상세)에서 대화 또는 직접 입력으로 설정합니다.
      </p>

      <div className="newrule-opt active" style={{ cursor: 'default' }}>
        <FilePlus2 size={16} style={{ marginTop: 2 }} />
        <div style={{ flex: 1 }}>
          <b>빈 룰그래프</b>
          <div className="text-meta" style={{ margin: '2px 0 10px' }}>
            같은 비용분류(scope)에는 활성 그래프가 하나만 존재할 수 있습니다.
          </div>
          <div className="field"><label>그래프 이름</label>
            <input placeholder="예) 출장 여비 검증 그래프" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
          </div>
          <div className="field" style={{ marginBottom: 0 }}><label>비용분류 (scope)</label>
            <select value={scope} onChange={(e) => setScope(e.target.value)}>
              <option value="">비용분류 선택</option>
              {RULE_SCOPES.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </div>
        </div>
      </div>
    </Modal>
  )
}

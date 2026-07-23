// S-04 Rule 콘솔 — 회계/운영(관리자). FR-UI-04, FR-RB-01~03, FR-RV-01~04
// v4~v6 통합: 탭 3개(초안 대기 / 시뮬레이션 결과 / Active Rule) + 대화형 AI 편집 + 그래프·트리 시각화 + 버전관리 + 규정문서 업로드.
import { useState } from 'react'
import { Plus, Upload } from 'lucide-react'
import { DRAFT_RULES } from './data/ruleConsoleMock'
import { DraftTab } from './DraftTab'
import { SimulationTab } from './SimulationTab'
import { ActiveTab } from './ActiveTab'
import { PolicyUploadModal } from './PolicyUploadModal'

type Tab = 'DRAFT' | 'SIMULATION' | 'ACTIVE'
const TAB_LABEL: Record<Tab, string> = { DRAFT: `Rule 초안 대기 (${DRAFT_RULES.length})`, SIMULATION: '시뮬레이션 결과', ACTIVE: 'Active Rule (38, 버전관리)' }

export function RuleConsole() {
  const [tab, setTab] = useState<Tab>('DRAFT')
  const [showUpload, setShowUpload] = useState(false)

  return (
    <>
      <div className="page-head row" style={{ justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <span className="screen-id">S-04</span>
          <h1>Rule 콘솔</h1>
          <div className="sub">RAG로 추출된 조항 기반 Rule 초안을 시뮬레이션 검토 후 승인/수정/폐기/롤백합니다. (자동 승인 금지)</div>
        </div>
        <div className="row" style={{ gap: 8 }}>
          <button className="btn" onClick={() => setShowUpload(true)}><Upload size={14} /> 규정 문서 업로드</button>
          <button className="btn primary"><Plus size={14} /> 신규 Rule 생성</button>
        </div>
      </div>

      <div className="filter-bar">
        {(['DRAFT', 'SIMULATION', 'ACTIVE'] as Tab[]).map((t) => (
          <button key={t} className={'btn' + (tab === t ? ' primary' : '')} onClick={() => setTab(t)}>
            {TAB_LABEL[t]}
          </button>
        ))}
      </div>

      {tab === 'DRAFT' && <DraftTab />}
      {tab === 'SIMULATION' && <SimulationTab />}
      {tab === 'ACTIVE' && <ActiveTab />}

      {showUpload && <PolicyUploadModal onClose={() => setShowUpload(false)} />}
    </>
  )
}

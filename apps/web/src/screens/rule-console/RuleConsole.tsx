// S-04 Rule 콘솔 — 회계/운영(관리자). FR-UI-04, FR-RB-01~03, FR-RV-01~04
//  룰 도메인 = 그래프. 초안/시뮬레이션/활성·버전관리·롤백은 전부 "그래프 단위".
//  탭: 초안 그래프(노드 세부설정) / 시뮬레이션(그래프 단위) / Active 그래프(버전관리).
import { useState } from 'react'
import { Plus } from 'lucide-react'
import { DraftTab } from './DraftTab'
import { SimulationTab } from './SimulationTab'
import { ActiveTab } from './ActiveTab'

type Tab = 'DRAFT' | 'SIMULATION' | 'ACTIVE'
const TAB_LABEL: Record<Tab, string> = {
  DRAFT: '초안 그래프',
  SIMULATION: '시뮬레이션 (그래프 단위)',
  ACTIVE: 'Active 관리',
}

export function RuleConsole() {
  const [tab, setTab] = useState<Tab>('DRAFT')
  const [newRuleOpen, setNewRuleOpen] = useState(false)

  return (
    <>
      <div className="hero-band" style={{ paddingBottom: 20 }}>
        <div className="page-head row" style={{ justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            <h1>Rule 콘솔</h1>
            <div className="sub">룰그래프 단위로 초안 작성 → 시뮬레이션 검증 → Active 전환/롤백. (자동 승인 금지)</div>
          </div>
          <div className="row" style={{ gap: 8 }}>
            <button className="btn" onClick={() => { setTab('DRAFT'); setNewRuleOpen(true) }}>
              <Plus size={14} /> 신규 그래프 생성
            </button>
          </div>
        </div>

        <div className="filter-bar rule-console-tabs" role="tablist" aria-label="룰 그래프 화면 전환" style={{ marginTop: 16 }}>
          {(['DRAFT', 'SIMULATION', 'ACTIVE'] as Tab[]).map((t) => (
            <button key={t} role="tab" aria-selected={tab === t} className={'btn' + (tab === t ? ' primary' : '')} onClick={() => setTab(t)}>
              {TAB_LABEL[t]}
            </button>
          ))}
        </div>
      </div>

      <div className="rule-console-full" style={{ padding: 'var(--space-6)' }}>
        {tab === 'DRAFT' && <DraftTab newRuleOpen={newRuleOpen} setNewRuleOpen={setNewRuleOpen} />}
        {tab === 'SIMULATION' && <SimulationTab />}
        {tab === 'ACTIVE' && <ActiveTab />}
      </div>
    </>
  )
}

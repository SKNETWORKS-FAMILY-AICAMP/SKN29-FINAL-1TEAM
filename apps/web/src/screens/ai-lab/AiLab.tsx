// AI-LAB (관리자) — AI 기능을 정산 흐름 없이 독립 실행하는 실험 화면.
//  · 운영과 같은 코드를 부른다(별도 구현 금지) — 실험 결과가 운영과 갈리면 도구로서 값을 잃는다.
//  · 결과만이 아니라 근거(프롬프트·원본 응답·토큰·지연·점수·메타데이터)를 그대로 펼친다.
//  · 인가는 Capability `ai_lab`(백엔드 `CanUseAiLab`). 호출 경로는 Django `/api/ai-lab/*` 프록시.
//
// 기능이 추가되면 아래 MODULES에 한 줄 더하고 패널 컴포넌트를 하나 붙인다.
import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { FlaskConical } from 'lucide-react'
import { USE_MOCK } from '../../api/config'
import { labApi, labErrorMessage, type LabStatus } from './data/labApi'
import { StatusPanel, StatusStrip } from './StatusPanel'
import { DraftLab } from './DraftLab'
import { RuleLab } from './RuleLab'
import { RiskLab } from './RiskLab'
import { ExtractLab } from './ExtractLab'
import { RagSearchLab } from './RagSearchLab'
import { EmbeddingLab } from './EmbeddingLab'
import { CollectionsLab } from './CollectionsLab'

interface StatusCtx {
  status: LabStatus | null
  error: string
  loading: boolean
  onReload: () => void
}

interface LabModule {
  key: string
  label: string
  group: '환경' | 'Agent' | 'RAG'
  render: (ctx: StatusCtx) => ReactNode
}

const MODULES: LabModule[] = [
  { key: 'STATUS', label: '상태 점검', group: '환경', render: (ctx) => <StatusPanel {...ctx} /> },
  { key: 'DRAFT', label: '① Draft Agent', group: 'Agent', render: () => <DraftLab /> },
  { key: 'RULE', label: '② Rule Agent', group: 'Agent', render: () => <RuleLab /> },
  { key: 'RISK', label: '③ Risk Review', group: 'Agent', render: () => <RiskLab /> },
  { key: 'EXTRACT', label: '증빙자료 추출', group: 'Agent', render: () => <ExtractLab /> },
  { key: 'RAG', label: 'RAG 검색', group: 'RAG', render: () => <RagSearchLab /> },
  { key: 'EMBED', label: '임베딩 인스펙터', group: 'RAG', render: () => <EmbeddingLab /> },
  { key: 'COLLECTIONS', label: '적재 현황', group: 'RAG', render: () => <CollectionsLab /> },
]

// 미착수 기능 없음(2026-08-21) — Draft·Rule·Risk Review·증빙자료 추출 4개 Agent 모두
// 단독 실행 탭을 갖췄다. 새 기능이 stub 상태로 남으면 다시 여기 적는다.
const PLANNED: { label: string; note: string }[] = []

export function AiLab() {
  const [tab, setTab] = useState('STATUS')
  const [status, setStatus] = useState<LabStatus | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const loadStatus = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setStatus(await labApi.status())
    } catch (err) {
      setStatus(null)
      setError(labErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadStatus() }, [loadStatus])

  const ctx: StatusCtx = { status, error, loading, onReload: loadStatus }
  const active = MODULES.find((m) => m.key === tab) ?? MODULES[0]

  return (
    <div className="ai-lab-full">
      <div className="hero-band">
        <div className="page-head row" style={{ justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            <span className="screen-id">AI-LAB</span>
            <h1><FlaskConical size={18} style={{ verticalAlign: -3, marginRight: 6 }} />AI 기능 실험실 (관리자)</h1>
            <div className="sub">
              정산 흐름을 거치지 않고 AI 기능만 단독 실행합니다. 운영과 <b>같은 코드</b>를 호출하며,
              결과에 더해 프롬프트·원본 응답·토큰·지연·검색 점수를 그대로 보여줍니다.
            </div>
          </div>
        </div>

        <div className="filter-bar rule-console-tabs" role="tablist" aria-label="AI-LAB 기능 전환" style={{ marginTop: 16 }}>
          {MODULES.map((m) => (
            <button
              key={m.key}
              role="tab"
              aria-selected={tab === m.key}
              className={'btn' + (tab === m.key ? ' primary' : '')}
              onClick={() => setTab(m.key)}
            >
              {m.label}
            </button>
          ))}
          {/* 예정 목록이 비면 "예정:" 라벨만 남는다 — 빈 배열이면 통째로 감춘다. */}
            {PLANNED.length > 0 && (
            <span className="lab-planned">
              예정:
              {PLANNED.map((p) => (
                <span key={p.label} className="lab-chip disabled" title={p.note}>{p.label}</span>
              ))}
          </span>
          )}
        </div>
      </div>

      <div style={{ padding: 'var(--space-6)' }}>
        {USE_MOCK && (
          <div className="note" style={{ marginBottom: 12 }}>
            현재 프론트가 <b>mock 모드</b>(VITE_USE_MOCK=true)입니다 — AI-LAB은 mock이 없고 실제 백엔드(core·ai)를
            호출하므로, 서비스가 떠 있지 않으면 실행이 실패합니다.
          </div>
        )}

        <StatusStrip {...ctx} />

        {active.render(ctx)}
      </div>
    </div>
  )
}

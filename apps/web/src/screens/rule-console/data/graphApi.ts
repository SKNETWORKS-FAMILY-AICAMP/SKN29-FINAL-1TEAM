// Core API(/api/rules/) 응답 → 화면 모델(RuleGraph) 변환 + 노드 표시용 텍스트 유틸.
//  초안 탭·시뮬레이션 탭이 같은 실데이터를 쓰도록 공유한다.
import type { GraphNode, GraphStatus, RuleGraph } from './ruleConsoleMock'

export type ApiNode = {
  nodeKey: string
  condition: unknown
  /** "이 Rule이 하는 일" — 백엔드 RuleNode.condition_text(Agent 생성 문장). 비면 describeDsl로 폴백. */
  conditionText?: string
  action: Record<string, unknown>
  priority: number
}
export type ApiRouting = { fromNodeKey: string; onResult: 'MATCH' | 'NO_MATCH'; toNodeKey: string; priority: number }
export type ApiGraph = {
  id: number | string
  familyKey: string
  name: string
  scope: string
  status: GraphStatus
  version: number
  entryNodeKey: string
  sourceClause: string
  nodes: ApiNode[]
  routings: ApiRouting[]
  versions: { version: number; approved_at?: string; isActive: boolean }[]
}

const actionText = (action: Record<string, unknown>) =>
  [action.decision, action.severity, action.flag].filter(Boolean).join(' · ')

export const toGraph = (raw: ApiGraph): RuleGraph => ({
  id: String(raw.id),
  familyKey: raw.familyKey,
  version: raw.version,
  name: raw.name,
  scope: raw.scope,
  status: raw.status,
  sourceClause: raw.sourceClause ?? '',
  entryNodeKey: raw.entryNodeKey ?? '',
  nodes: (raw.nodes ?? []).map((node) => ({
    nodeKey: node.nodeKey,
    title: String(node.action?.title ?? node.nodeKey),
    origin: node.action?.origin === 'new' || node.nodeKey.startsWith('R-N') ? 'new' : 'existing',
    plain: { category: raw.scope === 'GLOBAL' ? undefined : raw.scope, action: actionText(node.action ?? {}) },
    conditionExpr: JSON.stringify(node.condition ?? {}, null, 2),
    conditionText: node.conditionText ?? '',
    sourceClause: String(node.action?.source_clause ?? raw.sourceClause ?? ''),
    aiReason: String(node.action?.ai_reason ?? ''),
    description: String(node.action?.description ?? ''),
    actionDetail: {
      decision: String(node.action?.decision ?? ''), severity: String(node.action?.severity ?? ''),
      flag: String(node.action?.flag ?? ''), note: String(node.action?.note ?? ''),
      approver: String(node.action?.approver ?? ''),
    },
    priority: node.priority,
    workflowStatus: String(node.action?.workflow_status ?? (
      raw.status === 'ACTIVE' ? 'ACTIVE' : raw.status === 'SIMULATED' ? 'VERIFIED' : 'DRAFT'
    )) as GraphNode['workflowStatus'],
  })),
  routings: (raw.routings ?? []).map((route) => ({
    from: route.fromNodeKey, onResult: route.onResult, to: route.toNodeKey, priority: route.priority,
  })),
  versions: (raw.versions ?? []).map((version) => ({
    version: version.version, label: `v${version.version}`,
    status: version.isActive ? '현재 활성' : '과거', approvedAt: version.approved_at,
  })),
})

export const NODE_STATUS_LABEL = { DRAFT: '초안', WAITING: '검증대기', VERIFIED: '검증완료', ACTIVE: '활성' } as const
export const nodeStatusLabel = (status?: GraphNode['workflowStatus']) => NODE_STATUS_LABEL[status ?? 'DRAFT']
export const nodeStatusTone = (status?: GraphNode['workflowStatus']) =>
  status === 'ACTIVE' ? 'ok' : status === 'WAITING' ? 'ai' : ''

/** 그래프의 모든 노드가 "검증대기"인가 — 시뮬레이션 대상 판별 기준 */
export const isSimulatable = (graph: RuleGraph) =>
  graph.nodes.length > 0 && graph.nodes.every((node) => node.workflowStatus === 'WAITING')

// ── 조건 DSL → 비개발자용 자연어 (폴백 전용) ────────────────────────
//  쉽게보기 본문은 백엔드가 내려주는 RuleNode.conditionText(Agent 생성 문장)를 그대로 쓴다.
//  아래 기계 번역은 그 값이 아직 없는 노드(신규 생성 직후·구버전 데이터)에만 쓰인다.
const PATH_LABELS: Record<string, string> = {
  'merchant.merchant_type': '가맹점 업종', 'category.item_type': '항목 유형',
  'tx.payment_method': '결제 수단', 'tx.amount': '결제 금액',
}
const literalText = (value: unknown) => typeof value === 'string' ? `“${value}”` : String(value)

export const describeDsl = (value: unknown): string => {
  if (value === true) return '항상 적용됩니다.'
  if (!value || typeof value !== 'object' || Array.isArray(value)) return String(value ?? '')
  const expression = value as Record<string, unknown>
  const [operator, args] = Object.entries(expression)[0] ?? []
  if (operator === 'var') return PATH_LABELS[String(args)] ?? String(args)
  if (operator === 'and' || operator === 'or') {
    const items = (args as unknown[]).map(describeDsl)
    return `${operator === 'and' ? '다음 조건을 모두 만족합니다.' : '다음 조건 중 하나를 만족합니다.'}\n• ${items.join('\n• ')}`
  }
  if (operator === 'not') return `${describeDsl(args)} 조건이 아닌 경우`
  if (Array.isArray(args) && args.length === 2) {
    const left = describeDsl(args[0])
    if (operator === 'in' && Array.isArray(args[1])) {
      const choices = args[1].map(literalText)
      return `${left}이 ${choices.join(' 또는 ')}에 해당합니다.`
    }
    const right = typeof args[1] === 'object' ? describeDsl(args[1]) : literalText(args[1])
    const sentence: Record<string, string> = {
      '==': `${left}이 ${right}입니다.`, '!=': `${left}이 ${right}이 아닙니다.`,
      '>': `${left}이 ${right}보다 큽니다.`, '>=': `${left}이 ${right} 이상입니다.`,
      '<': `${left}이 ${right}보다 작습니다.`, '<=': `${left}이 ${right} 이하입니다.`,
    }
    return sentence[operator] ?? `${left} ${operator} ${right}`
  }
  return '설정된 DSL 조건에 일치하는 경우'
}

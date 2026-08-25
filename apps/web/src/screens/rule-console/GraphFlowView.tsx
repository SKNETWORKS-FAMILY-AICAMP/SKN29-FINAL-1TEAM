// 룰 그래프 구조 — 진입 노드에서 라우팅을 따라 위→아래로 내려가는 스크롤 플로우차트.
//  같은 레벨(깊이)의 노드는 한 행에 나란히 놓이고, 화살표는 항상 아래 방향으로만 흐른다.
//  노드 제목 + 라우팅(MATCH/NO_MATCH) 구조만 보여주고, 상세는 우측 읽기 패널이 담당한다.
import { useMemo } from 'react'
import { activateOnEnterOrSpace } from '../../lib/a11y'
import { nodeStatusLabel, nodeStatusTone } from './data/graphApi'
import type { GraphNode, RuleGraph } from './data/ruleConsoleMock'

const CARD_W = 208
const CARD_H = 78
const GAP_COL = 32 // 같은 레벨(행) 안 좌우 간격
const GAP_ROW = 74 // 레벨 사이 상하 간격 — 라우팅 라벨이 들어갈 자리
const PAD = 24
const END_W = 76
const END_H = 32
const BACK_DETOUR = 84 // 순환 라우팅 우회선이 오른쪽으로 나가는 폭

type FlowItem =
  | { kind: 'node'; key: string; node: GraphNode; x: number; y: number }
  | { kind: 'end'; key: string; x: number; y: number }

interface FlowEdge {
  key: string
  label: '' | 'MATCH' | 'NO_MATCH'
  /** 아래로 흐르지 않는 엣지 = 순환 — 빨간 우회선으로 표시한다. */
  back: boolean
  path: string
  labelX: number
  labelY: number
}

/** 진입 노드 기준 최장경로 레벨 배치 — 도달 불가 노드는 첫 행에 이어붙인다. */
function layout(graph: RuleGraph) {
  const nodeKeys = graph.nodes.map((node) => node.nodeKey)
  const outgoing = (key: string) => graph.routings.filter((route) => route.from === key)
  const entry = nodeKeys.includes(graph.entryNodeKey) ? graph.entryNodeKey : nodeKeys[0]

  const level = new Map<string, number>()
  const order: string[] = []
  const queue: string[] = []
  let guard = nodeKeys.length * nodeKeys.length + 16
  const relax = () => {
    while (queue.length && guard-- > 0) {
      const current = queue.shift() as string
      if (!order.includes(current)) order.push(current)
      const currentLevel = level.get(current) ?? 0
      for (const route of outgoing(current)) {
        if (!route.to || !nodeKeys.includes(route.to)) continue
        if ((level.get(route.to) ?? -1) < currentLevel + 1) { level.set(route.to, currentLevel + 1); queue.push(route.to) }
      }
    }
  }
  if (entry) { level.set(entry, 0); queue.push(entry); relax() }
  // 진입점에서 도달하지 못하는 노드도 첫 행에서 다시 펼친다.
  for (const key of nodeKeys) if (!level.has(key)) { level.set(key, 0); queue.push(key); relax() }
  for (const key of nodeKeys) if (!order.includes(key)) order.push(key)

  // 행 구성 — 레벨별로 노드를 먼저 채우고, 종료(빈 라우팅) 칩을 뒤에 붙인다.
  const rows: { key: string; node?: GraphNode }[][] = []
  const put = (rowIndex: number, item: { key: string; node?: GraphNode }) => {
    while (rows.length <= rowIndex) rows.push([])
    rows[rowIndex].push(item)
    return { level: rowIndex, column: rows[rowIndex].length - 1 }
  }
  const slot = new Map<string, { level: number; column: number }>()
  for (const key of order) {
    const node = graph.nodes.find((candidate) => candidate.nodeKey === key)
    if (node) slot.set(key, put(level.get(key) ?? 0, { key, node }))
  }

  const rawEdges: { key: string; from: string; to: string; label: '' | 'MATCH' | 'NO_MATCH' }[] = []
  for (const key of order) {
    const routes = outgoing(key)
    const nextLevel = (level.get(key) ?? 0) + 1
    if (routes.length === 0) {
      const endKey = `end:${key}`
      slot.set(endKey, put(nextLevel, { key: endKey }))
      rawEdges.push({ key: `edge:${key}:end`, from: key, to: endKey, label: '' })
      continue
    }
    routes.forEach((route, index) => {
      if (route.to && nodeKeys.includes(route.to)) {
        rawEdges.push({ key: `edge:${key}:${index}`, from: key, to: route.to, label: route.onResult })
        return
      }
      const endKey = `end:${key}:${index}`
      slot.set(endKey, put(nextLevel, { key: endKey }))
      rawEdges.push({ key: `edge:${key}:${index}`, from: key, to: endKey, label: route.onResult })
    })
  }

  // 각 행은 가운데 정렬 — 가장 넓은 행을 기준으로 좌우 여백을 나눈다.
  const widest = rows.reduce((max, row) => Math.max(max, row.length), 1)
  const canvasWidth = PAD * 2 + widest * CARD_W + Math.max(0, widest - 1) * GAP_COL
  const at = (key: string) => {
    const place = slot.get(key)
    if (!place) return null
    const rowCount = rows[place.level]?.length ?? 1
    const rowWidth = rowCount * CARD_W + Math.max(0, rowCount - 1) * GAP_COL
    return {
      x: (canvasWidth - rowWidth) / 2 + place.column * (CARD_W + GAP_COL),
      y: PAD + place.level * (CARD_H + GAP_ROW),
    }
  }

  const items: FlowItem[] = []
  rows.forEach((row) => row.forEach((item) => {
    const point = at(item.key)
    if (!point) return
    items.push(item.node
      ? { kind: 'node', key: item.key, node: item.node, x: point.x, y: point.y }
      : { kind: 'end', key: item.key, x: point.x, y: point.y })
  }))

  const edges: FlowEdge[] = []
  for (const edge of rawEdges) {
    const from = at(edge.from)
    const to = at(edge.to)
    if (!from || !to) continue
    if (to.y > from.y) { // 정상: 위 → 아래
      const x1 = from.x + CARD_W / 2, y1 = from.y + CARD_H, x2 = to.x + CARD_W / 2, y2 = to.y
      const bend = Math.max(28, (y2 - y1) / 2)
      edges.push({
        key: edge.key, label: edge.label, back: false,
        path: `M ${x1} ${y1} C ${x1} ${y1 + bend}, ${x2} ${y2 - bend}, ${x2} ${y2}`,
        labelX: (x1 + x2) / 2, labelY: (y1 + y2) / 2,
      })
      continue
    }
    // 되돌아가는(순환) 라우팅 — 오른쪽으로 우회시켜 눈에 띄게 그린다.
    const x1 = from.x + CARD_W, y1 = from.y + CARD_H / 2, x2 = to.x + CARD_W, y2 = to.y + CARD_H / 2
    const detour = Math.max(x1, x2) + BACK_DETOUR
    edges.push({
      key: edge.key, label: edge.label, back: true,
      path: `M ${x1} ${y1} C ${detour} ${y1}, ${detour} ${y2}, ${x2} ${y2}`,
      labelX: detour - 24, labelY: (y1 + y2) / 2,
    })
  }

  const hasCycle = edges.some((edge) => edge.back)
  return {
    items, edges, entry, hasCycle,
    width: canvasWidth + (hasCycle ? BACK_DETOUR + PAD : 0),
    height: Math.max(160, PAD * 2 + rows.length * (CARD_H + GAP_ROW) - GAP_ROW),
  }
}

const arrowId = (edge: FlowEdge) => edge.back ? 'flow-arrow-back'
  : edge.label === 'MATCH' ? 'flow-arrow-match' : edge.label === 'NO_MATCH' ? 'flow-arrow-nomatch' : 'flow-arrow'
const edgeClass = (edge: FlowEdge) => 'flow-edge' + (edge.back ? ' back'
  : edge.label === 'MATCH' ? ' match' : edge.label === 'NO_MATCH' ? ' nomatch' : '')

export function GraphFlowView({ graph, selectedKey, onSelect }: {
  graph: RuleGraph; selectedKey: string; onSelect: (nodeKey: string) => void
}) {
  const flow = useMemo(() => layout(graph), [graph])

  if (graph.nodes.length === 0) return <div className="card-body text-meta">노드가 없는 그래프입니다.</div>

  return (
    <>
    {flow.hasCycle && (
      <div className="note" style={{ margin: '12px 16px 0', color: 'var(--tone-red)', borderColor: 'var(--tone-red)' }}>
        ⚠ 되돌아가는 라우팅(순환)이 있습니다. 순환 그래프는 Active 전환 시 거부됩니다.
      </div>
    )}
    {/* 프레임이 남은 높이를 차지하고, 스크롤 영역은 그 안에 절대배치 —
        플로우차트 내용이 카드 높이를 밀어올리지 않아 옆 노드 상세 높이에 맞춰진다. */}
    <div className="flow-frame">
    <div className="flow-scroll">
      <div className="flow-canvas" style={{ width: flow.width, height: flow.height }}>
        <svg className="flow-edges" width={flow.width} height={flow.height} aria-hidden="true">
          <defs>
            {([['flow-arrow', 'var(--border-strong)'], ['flow-arrow-match', 'var(--tone-green)'],
              ['flow-arrow-nomatch', 'var(--tone-gray)'], ['flow-arrow-back', 'var(--tone-red)']] as const).map(([id, fill]) => (
              <marker key={id} id={id} markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
                <path d="M 0 0 L 8 4 L 0 8 z" fill={fill} />
              </marker>
            ))}
          </defs>
          {flow.edges.map((edge) => (
            <path key={edge.key} d={edge.path} markerEnd={`url(#${arrowId(edge)})`} className={edgeClass(edge)} />
          ))}
        </svg>

        {flow.edges.filter((edge) => edge.label || edge.back).map((edge) => (
          <div key={`label-${edge.key}`}
            className={'flow-edge-label' + (edge.back ? ' back' : edge.label === 'MATCH' ? ' match' : '')}
            style={{ left: edge.labelX, top: edge.labelY }}>{edge.back ? `↺ ${edge.label}` : edge.label}</div>
        ))}

        {flow.items.map((item) => item.kind === 'end'
          ? <div key={item.key} className="flow-end" style={{ left: item.x + (CARD_W - END_W) / 2, top: item.y, width: END_W, height: END_H }}>종료</div>
          : (
            <div key={item.key} className={'flow-node' + (item.node.nodeKey === selectedKey ? ' selected' : '')}
              style={{ left: item.x, top: item.y, width: CARD_W, height: CARD_H }}
              role="button" tabIndex={0} aria-pressed={item.node.nodeKey === selectedKey}
              onClick={() => onSelect(item.node.nodeKey)} onKeyDown={activateOnEnterOrSpace(() => onSelect(item.node.nodeKey))}>
              <div className="row" style={{ gap: 6 }}>
                {item.node.nodeKey === flow.entry && <span className="tag ai">시작</span>}
                <span className={'tag ' + nodeStatusTone(item.node.workflowStatus)}>{nodeStatusLabel(item.node.workflowStatus)}</span>
                <span className="text-meta flow-node-key" style={{ marginLeft: 'auto' }} title={item.node.nodeKey}>{item.node.nodeKey}</span>
              </div>
              <div className="flow-node-title">{item.node.title}</div>
            </div>
          ))}
      </div>
    </div>
    </div>
    </>
  )
}

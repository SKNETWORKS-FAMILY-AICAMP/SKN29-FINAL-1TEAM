// Tab2(v5) — Rule 관계 그래프. 고정 좌표 SVG(정적 배치, 드래그 재배치 없음) + 노드 클릭 시 우측 패널 갱신.
import { useState } from 'react'
import { Modal } from '../../components/ui/Modal'
import { GRAPH_RELATED_EDGES, RULE_CONFLICTS, RULE_NODES } from './data/ruleConsoleMock'
import { activateOnEnterOrSpace } from '../../lib/a11y'

const VB_W = 1000
const VB_H = 560
const pos = (id: string) => {
  const n = RULE_NODES.find((x) => x.id === id)!
  return { x: (n.graphX / 100) * VB_W, y: (n.graphY / 100) * VB_H }
}

function GraphSvg({
  interactive,
  selectedId,
  onSelect,
}: {
  interactive: boolean
  selectedId?: string | null
  onSelect?: (id: string) => void
}) {
  return (
    <svg viewBox={`0 0 ${VB_W} ${VB_H}`} style={{ width: '100%', height: interactive ? 460 : 140 }}>
      {GRAPH_RELATED_EDGES.map(([a, b]) => {
        const pa = pos(a), pb = pos(b)
        return <line key={`e-${a}-${b}`} x1={pa.x} y1={pa.y} x2={pb.x} y2={pb.y} stroke="var(--border-strong)" strokeWidth={1.5} />
      })}
      {RULE_CONFLICTS.map(([a, b]) => {
        const pa = pos(a), pb = pos(b)
        return <line key={`x-${a}-${b}`} x1={pa.x} y1={pa.y} x2={pb.x} y2={pb.y} stroke="var(--tone-red)" strokeWidth={2} strokeDasharray="5 4" />
      })}
      {RULE_NODES.map((n) => {
        const p = pos(n.id)
        const isSelected = interactive && selectedId === n.id
        const isConflict = RULE_CONFLICTS.some((pair) => pair.includes(n.id))
        return (
          <g key={n.id} onClick={interactive ? () => onSelect?.(n.id) : undefined} style={interactive ? { cursor: 'pointer' } : undefined}>
            <circle
              cx={p.x} cy={p.y} r={interactive ? 9 : 5}
              fill={n.status === 'new' ? 'var(--primary)' : isConflict ? 'var(--tone-red)' : 'var(--muted)'}
              stroke={isSelected ? 'var(--primary)' : 'none'} strokeWidth={4}
            />
            {interactive && (
              <text x={p.x} y={p.y - 14} textAnchor="middle" fontSize={10.5} fill="var(--text)">
                {n.id}{n.status === 'new' ? '(신규)' : ''}
              </text>
            )}
          </g>
        )
      })}
    </svg>
  )
}

export function RuleGraphMini({ onExpand }: { onExpand: () => void }) {
  const newCount = RULE_NODES.filter((n) => n.status === 'new').length
  return (
    <div className="card">
      <div className="card-head">
        <h3>🔗 Rule 관계 그래프</h3>
        <span className="tag ai">{RULE_NODES.length}개 노드 · 신규 {newCount} · 충돌 감지 {RULE_CONFLICTS.length}</span>
      </div>
      <div className="card-body">
        <GraphSvg interactive={false} />
        <p className="text-meta" style={{ marginTop: 8 }}>
          현재 활성 Rule 9개 + 신규 배치 {newCount}개 = 총 {RULE_NODES.length}개 노드. 순환 참조 없음 · 조건 중첩 가능 {RULE_CONFLICTS.length}건 감지
        </p>
        <button className="btn sm" onClick={onExpand}>전체 구성도 펼쳐보기 ▸</button>
      </div>
    </div>
  )
}

export function RuleGraphExplorer({ onClose }: { onClose: () => void }) {
  const [selectedId, setSelectedId] = useState<string | null>('R-102')
  const selected = RULE_NODES.find((n) => n.id === selectedId)
  const related = selected
    ? GRAPH_RELATED_EDGES.filter(([a, b]) => a === selected.id || b === selected.id).map(([a, b]) => (a === selected.id ? b : a))
    : []
  const conflictWith = selected ? RULE_CONFLICTS.find((pair) => pair.includes(selected.id))?.find((id) => id !== selected.id) : undefined

  return (
    <Modal title="Rule 관계 그래프 — 전체 구성도" onClose={onClose} maxWidth={1360}>
      <p className="text-meta" style={{ marginBottom: 12 }}>Rule 간 관련성·충돌을 네트워크 형태로 표시합니다.</p>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 320px', gap: 16 }}>
        <div className="card" style={{ padding: 8 }}>
          <GraphSvg interactive selectedId={selectedId} onSelect={setSelectedId} />
        </div>
        <div className="card">
          <div className="card-head"><h3>선택된 노드</h3>{selected?.status === 'new' && <span className="tag ai">신규 배치</span>}</div>
          {selected ? (
            <div className="card-body stack">
              <div>
                <b>{selected.id}</b>
                <div className="text-meta">{selected.sub}</div>
              </div>
              <div><span className="text-meta">소속 분류</span><div>{selected.category}</div></div>
              <div><span className="text-meta">관련 노드</span><div>{related.join(' · ') || '없음'}</div></div>
              {conflictWith && (
                <div className="note" style={{ borderColor: 'var(--tone-red)', color: 'var(--tone-red)' }}>
                  ⚠ 충돌 감지 — {conflictWith}와 조건이 겹칩니다. 순서·의존관계 확인 필요
                </div>
              )}
              <button
                className="btn sm"
                tabIndex={0}
                onKeyDown={activateOnEnterOrSpace(() => setSelectedId(conflictWith ?? selectedId))}
                onClick={() => conflictWith && setSelectedId(conflictWith)}
                disabled={!conflictWith}
              >
                충돌 노드로 이동
              </button>
            </div>
          ) : (
            <div className="card-body text-meta">노드를 클릭하면 이 패널의 내용이 바뀝니다.</div>
          )}
        </div>
      </div>
    </Modal>
  )
}

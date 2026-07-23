// Tab2(v6) — Rule 트리 구조. 고정 좌표 SVG(정적 배치, 드래그 재배치 없음) + 노드 클릭 시 우측 패널 갱신.
import { useMemo, useState } from 'react'
import { Modal } from '../../components/ui/Modal'
import { RULE_CATEGORIES, RULE_CONFLICTS, RULE_NODES } from './data/ruleConsoleMock'
import { activateOnEnterOrSpace } from '../../lib/a11y'

const VB_W = 1000
const VB_H = 380
const ROOT = { x: 500, y: 30 }
const CAT_Y = 150
const LEAF_Y = 320

function useTreeLayout() {
  return useMemo(() => {
    const categories = RULE_CATEGORIES.map((name, i) => ({
      name,
      x: (i + 0.5) * (VB_W / RULE_CATEGORIES.length),
      y: CAT_Y,
    }))
    const leaves = RULE_CATEGORIES.flatMap((cat, i) => {
      const nodes = RULE_NODES.filter((n) => n.category === cat)
      const catX = categories[i].x
      return nodes.map((n, j) => ({
        ...n,
        x: catX + (j - (nodes.length - 1) / 2) * 68,
        y: LEAF_Y,
      }))
    })
    return { categories, leaves }
  }, [])
}

function TreeSvg({
  interactive,
  selectedId,
  onSelect,
}: {
  interactive: boolean
  selectedId?: string | null
  onSelect?: (id: string) => void
}) {
  const { categories, leaves } = useTreeLayout()
  const leafById = (id: string) => leaves.find((l) => l.id === id)

  return (
    <svg viewBox={`0 0 ${VB_W} ${VB_H}`} style={{ width: '100%', height: interactive ? 420 : 140 }}>
      {categories.map((c) => (
        <line key={`r-${c.name}`} x1={ROOT.x} y1={ROOT.y} x2={c.x} y2={c.y} stroke="var(--border-strong)" strokeWidth={1.5} />
      ))}
      {leaves.map((l) => {
        const cat = categories.find((c) => c.name === l.category)!
        return <line key={`c-${l.id}`} x1={cat.x} y1={cat.y} x2={l.x} y2={l.y} stroke="var(--border-strong)" strokeWidth={1.5} />
      })}
      {RULE_CONFLICTS.map(([a, b]) => {
        const pa = leafById(a), pb = leafById(b)
        if (!pa || !pb) return null
        return <line key={`x-${a}-${b}`} x1={pa.x} y1={pa.y} x2={pb.x} y2={pb.y} stroke="var(--tone-red)" strokeWidth={2} strokeDasharray="5 4" />
      })}

      <circle cx={ROOT.x} cy={ROOT.y} r={interactive ? 8 : 5} fill="#111827" />
      {interactive && <text x={ROOT.x} y={ROOT.y - 16} textAnchor="middle" fontSize={12} fontWeight={700} fill="var(--text)">Rule 실행 트리</text>}

      {categories.map((c) => (
        <g key={c.name}>
          <circle cx={c.x} cy={c.y} r={interactive ? 6 : 4} fill="var(--muted)" />
          {interactive && <text x={c.x} y={c.y - 12} textAnchor="middle" fontSize={11} fill="var(--muted)">{c.name}</text>}
        </g>
      ))}

      {leaves.map((l) => {
        const isSelected = interactive && selectedId === l.id
        const isConflict = RULE_CONFLICTS.some((pair) => pair.includes(l.id))
        return (
          <g
            key={l.id}
            onClick={interactive ? () => onSelect?.(l.id) : undefined}
            style={interactive ? { cursor: 'pointer' } : undefined}
          >
            <circle
              cx={l.x} cy={l.y} r={interactive ? 7 : 4}
              fill={l.status === 'new' ? 'var(--primary)' : isConflict ? 'var(--tone-red)' : 'var(--muted)'}
              stroke={isSelected ? 'var(--primary)' : 'none'} strokeWidth={4}
            />
            {interactive && (
              <text x={l.x} y={l.y + 20} textAnchor="middle" fontSize={10.5} fill="var(--text)">
                {l.id} {l.status === 'new' ? '(신규)' : ''}
              </text>
            )}
          </g>
        )
      })}
    </svg>
  )
}

export function RuleTreeMini({ onExpand }: { onExpand: () => void }) {
  const newCount = RULE_NODES.filter((n) => n.status === 'new').length
  return (
    <div className="card">
      <div className="card-head">
        <h3>🌳 Rule 트리 구조</h3>
        <span className="tag ai">{RULE_CATEGORIES.length}개 분류 · {RULE_NODES.length}개 Rule · 신규 {newCount} · 충돌 감지 {RULE_CONFLICTS.length}</span>
      </div>
      <div className="card-body">
        <TreeSvg interactive={false} />
        <p className="text-meta" style={{ marginTop: 8 }}>
          충돌 감지 {RULE_CONFLICTS.length}건 — {RULE_CONFLICTS.map(([a, b]) => `${a}↔${b}`).join(', ')}. 지금은 요약(접힘) 상태입니다.
        </p>
        <button className="btn sm" onClick={onExpand}>전체 트리 구조 펼쳐보기 ▸</button>
      </div>
    </div>
  )
}

export function RuleTreeExplorer({ onClose }: { onClose: () => void }) {
  const { leaves } = useTreeLayout()
  const [selectedId, setSelectedId] = useState<string | null>('R-102')
  const selected = leaves.find((l) => l.id === selectedId)
  const siblings = selected ? leaves.filter((l) => l.category === selected.category && l.id !== selected.id) : []
  const conflictWith = selected ? RULE_CONFLICTS.find((pair) => pair.includes(selected.id))?.find((id) => id !== selected.id) : undefined

  return (
    <Modal title="Rule 트리 구조 — 전체 구성도" onClose={onClose} maxWidth={1360}>
      <p className="text-meta" style={{ marginBottom: 12 }}>분류(Root) → 세부 분류 → 개별 Rule 순서의 계층 구조입니다.</p>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 320px', gap: 16 }}>
        <div className="card" style={{ padding: 8 }}>
          <TreeSvg interactive selectedId={selectedId} onSelect={setSelectedId} />
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
              <div><span className="text-meta">형제 노드</span><div>{siblings.map((s) => s.id).join(' · ') || '없음'}</div></div>
              {conflictWith && (
                <div className="note" style={{ borderColor: 'var(--tone-red)', color: 'var(--tone-red)' }}>
                  ⚠ 충돌 감지 — {conflictWith}와 조건이 겹칩니다. 실행 순서 확인 필요
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

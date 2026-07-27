// Tab1 — Rule 초안 대기 · 상세/수정 (v5, 대화형 AI 편집 + 비개발자 친화 자연어)
import { useState } from 'react'
import { Code2, Send, Sparkles, Wand2 } from 'lucide-react'
import { DRAFT_CHAT_SCRIPT, DRAFT_RULES, type ChatMessage, type DraftRule } from './data/ruleConsoleMock'
import { activateOnEnterOrSpace } from '../../lib/a11y'

export function DraftTab() {
  const [selected, setSelected] = useState<DraftRule>(DRAFT_RULES[0])
  const [chat, setChat] = useState<ChatMessage[]>(DRAFT_CHAT_SCRIPT)
  const [input, setInput] = useState('')
  const [showCode, setShowCode] = useState(false)
  const [threshold, setThreshold] = useState<number | undefined>(DRAFT_RULES[0].plain.threshold)

  const selectRule = (r: DraftRule) => {
    setSelected(r)
    setThreshold(r.plain.threshold)
    setShowCode(false)
    setChat(r.id === DRAFT_RULES[0].id ? DRAFT_CHAT_SCRIPT : [])
  }

  const send = () => {
    const text = input.trim()
    if (!text) return
    setChat((prev) => [
      ...prev,
      { role: 'user', text },
      { role: 'ai', text: '네, 반영했습니다. 좌측 "이 Rule이 하는 일"에서 변경 내용을 확인해주세요.', appliedNote: '로직·설명 필드에 적용됨' },
    ])
    setInput('')
  }

  const plain = selected.plain

  return (
    <>
      <div className="note" style={{ marginBottom: 16, display: 'flex', gap: 8, alignItems: 'center' }}>
        <Sparkles size={14} />
        v5 반영: 로직(코드)은 기본 숨김 — "이 Rule이 하는 일"을 쉬운 문장 + 수치 조정칸으로 보여주고, 코드는 [개발자용 코드로 보기]로만 펼칩니다.
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '280px 1fr 340px', gap: 16, alignItems: 'start' }}>
        {/* 대기 중 Rule 리스트 — 제목 강조, ID는 가볍게 */}
        <div className="card">
          <div className="card-head"><h3>대기 중 Rule ({DRAFT_RULES.length})</h3></div>
          <div className="stack" style={{ padding: 8 }}>
            {DRAFT_RULES.map((r) => (
              <div
                key={r.id}
                role="button"
                tabIndex={0}
                style={{
                  padding: '10px 12px', borderRadius: 'var(--radius-control)', cursor: 'pointer',
                  background: r.id === selected.id ? 'var(--primary-soft)' : undefined,
                }}
                onClick={() => selectRule(r)}
                onKeyDown={activateOnEnterOrSpace(() => selectRule(r))}
              >
                <div className="row" style={{ justifyContent: 'space-between', gap: 8 }}>
                  <b style={{ fontSize: 13 }}>{r.title}</b>
                  <span className="tag">{r.status}</span>
                </div>
                <div className="text-meta">{r.id} · {r.sourceClause}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Rule 상세 — 제목 강조, ID는 가볍게 */}
        <div className="card">
          <div className="card-head">
            <div>
              <h3>{selected.title}</h3>
              <div className="text-meta">{selected.id} · Rule 상세</div>
            </div>
            <span className="tag">{selected.status}</span>
          </div>
          <div className="card-body stack">
            <div className="field">
              <label className="row" style={{ justifyContent: 'space-between' }}>
                제목
                <button className="btn sm"><Wand2 size={11} /> 수정</button>
              </label>
              <input defaultValue={selected.title} />
            </div>
            <div className="field">
              <label className="row" style={{ justifyContent: 'space-between' }}>
                설명
                <button className="btn sm"><Wand2 size={11} /> 수정</button>
              </label>
              <textarea rows={2} defaultValue={selected.description} />
            </div>

            {/* 이 Rule이 하는 일 — 자연어 + 수치 조정칸 */}
            <div className="field">
              <label className="row" style={{ justifyContent: 'space-between' }}>
                이 Rule이 하는 일
                <button className="btn sm" onClick={() => setShowCode((v) => !v)}>
                  <Code2 size={11} /> {showCode ? '코드 숨기기' : '개발자용 코드로 보기'}
                </button>
              </label>
              <div className="note" style={{ lineHeight: 2, color: 'var(--text)' }}>
                {plain.category && (
                  <>비용 분류가 <span className="tag ai">{plain.category}</span> 이고, 지출 금액이{' '}</>
                )}
                {plain.threshold !== undefined && (
                  <input
                    type="number"
                    value={threshold ?? plain.threshold}
                    onChange={(e) => setThreshold(Number(e.target.value))}
                    style={{ width: 130, display: 'inline-block', margin: '0 4px', padding: '4px 8px' }}
                  />
                )}
                {plain.threshold !== undefined && <>원을 초과{plain.extraCondition ? '하고, ' : '하면 '}</>}
                {plain.extraCondition && <><b>{plain.extraCondition}</b> </>}
                → <b style={{ color: 'var(--primary)' }}>{plain.action}</b> 합니다.
              </div>
              {showCode && (
                <pre style={{ margin: '8px 0 0', padding: '10px 12px', background: 'var(--sidebar-bg)', color: '#d1fae5', borderRadius: 'var(--radius-control)', fontSize: 12, whiteSpace: 'pre-wrap' }}>
                  {selected.logic}
                </pre>
              )}
            </div>

            <div className="field">
              <label>관련 조항</label>
              <div><span className="tag">📎 {selected.sourceClause}</span></div>
            </div>
            <div className="field">
              <label>생성 이유 (AI 근거)</label>
              <div className="note">{selected.aiReason}</div>
            </div>
          </div>
          <div className="modal-foot">
            <button className="btn">임시저장</button>
            <div className="spacer" />
            <button className="btn primary">시뮬레이션으로 보내기 →</button>
          </div>
        </div>

        {/* 대화형 지시·수정 */}
        <div className="card" style={{ borderColor: 'var(--primary)' }}>
          <div className="card-head"><h3>대화형 지시·수정</h3></div>
          <div className="text-meta" style={{ padding: '0 16px' }}>자연어로 말하면 AI가 필드를 직접 수정합니다.</div>
          <div className="stack" style={{ padding: 16, maxHeight: 420, overflowY: 'auto' }}>
            {chat.map((m, i) => (
              <div key={i} style={{ alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start', maxWidth: '92%' }}>
                <div
                  style={{
                    padding: '8px 12px', borderRadius: 'var(--radius-control)', fontSize: 12.5, whiteSpace: 'pre-line',
                    background: m.role === 'user' ? 'var(--primary)' : 'var(--surface-2)',
                    color: m.role === 'user' ? '#fff' : 'var(--text)',
                  }}
                >
                  {m.text}
                </div>
                {m.appliedNote && (
                  <div className="text-meta" style={{ color: 'var(--tone-green)', marginTop: 4 }}>✓ {m.appliedNote}</div>
                )}
              </div>
            ))}
          </div>
          <div className="row" style={{ padding: 16, borderTop: '1px solid var(--border)', gap: 8 }}>
            <input
              placeholder='예) 금액 기준을 40만원으로 올려줘'
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') send() }}
              style={{ flex: 1 }}
            />
            <button className="btn primary" onClick={send} aria-label="전송"><Send size={14} /></button>
          </div>
        </div>
      </div>
    </>
  )
}

// Tab1 — Rule 초안 대기 · 상세/수정 (Figma v5 · 대화형 AI 편집)
// v5 변형: 로직(코드) 블록을 기본적으로 숨기고 "이 Rule이 하는 일"을 쉬운 문장으로 먼저 보여줌.
// 코드는 토글 클릭 시에만 펼침.
import { useState } from 'react'
import { ChevronDown, ChevronUp, Send, Sparkles, Wand2 } from 'lucide-react'
import { DRAFT_CHAT_SCRIPT, DRAFT_RULES, type ChatMessage, type DraftRule } from './data/ruleConsoleMock'
import { activateOnEnterOrSpace } from '../../lib/a11y'

// DraftRule의 logic을 자연어 "이 Rule이 하는 일" 형태로 변환 (mock)
function logicToNaturalLanguage(logic: string): { pill1: string; pill2: string; action: string } {
  if (logic.includes('amount > 300000') && logic.includes('식대')) {
    return { pill1: '비용 분류가  식대  이고', pill2: '지출 금액이  300,000원  을 초과하면', action: '사전승인 필요  로 자동 표시합니다.' }
  }
  if (logic.includes('amount > 200000') && logic.includes('경조')) {
    return { pill1: '비용 분류가  경조사비  이고', pill2: '지출 금액이  200,000원  을 초과하면', action: '손금경고  플래그를 설정합니다.' }
  }
  if (logic.includes('SHARED')) {
    return { pill1: '카드 구분이  공용카드  이고', pill2: '실사용자가  미지정  이면', action: '실사용자 삽입  을 요청합니다.' }
  }
  if (logic.includes('amount > 30000') && logic.includes('접대')) {
    return { pill1: '비용 분류가  접대  이고', pill2: '지출 금액이  30,000원  을 초과하면', action: '증빙플래그  를 설정합니다.' }
  }
  return { pill1: '조건 1', pill2: '조건 2', action: '플래그를 설정합니다.' }
}

function NaturalLanguageBlock({ logic }: { logic: string }) {
  const nl = logicToNaturalLanguage(logic)
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, alignItems: 'center', fontSize: 13, lineHeight: 1.8 }}>
      <span style={{ background: '#fff3cd', color: '#856404', border: '1px solid #ffc107', borderRadius: 4, padding: '1px 8px', fontWeight: 600 }}>{nl.pill1.trim()}</span>
      <span style={{ color: 'var(--muted)' }}>이고,</span>
      <span style={{ background: '#d1ecf1', color: '#0c5460', border: '1px solid #bee5eb', borderRadius: 4, padding: '1px 8px', fontWeight: 600 }}>{nl.pill2.trim()}</span>
      <span style={{ color: 'var(--muted)' }}>→</span>
      <span style={{ background: '#d4edda', color: '#155724', border: '1px solid #c3e6cb', borderRadius: 4, padding: '1px 8px', fontWeight: 700 }}>{nl.action}</span>
    </div>
  )
}

export function DraftTab() {
  const [selected, setSelected] = useState<DraftRule>(DRAFT_RULES[0])
  const [chat, setChat] = useState<ChatMessage[]>(DRAFT_CHAT_SCRIPT)
  const [input, setInput] = useState('')
  const [showCode, setShowCode] = useState(false)

  const selectRule = (r: DraftRule) => {
    setSelected(r)
    setChat(r.id === DRAFT_RULES[0].id ? DRAFT_CHAT_SCRIPT : [])
    setShowCode(false)
  }

  const send = () => {
    const text = input.trim()
    if (!text) return
    setChat((prev) => [
      ...prev,
      { role: 'user', text },
      { role: 'ai', text: '네, 반영했습니다. 좌측 로직·설명 필드에서 변경 내용을 확인해주세요.', appliedNote: '로직·설명 필드에 적용됨' },
    ])
    setInput('')
  }

  return (
    <>
      <div className="note" style={{ marginBottom: 16, display: 'flex', gap: 8, alignItems: 'center', fontSize: 12 }}>
        <Sparkles size={13} />
        v5 번형: 로직(코드) 블록을 기본적으로 숨기고, "이 Rule이 하는 일"을 쉬운 문장으로 먼저 보여줍니다. 코드는 아이콘 클릭 시에만 펼칩니다.
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '260px 1fr 320px', gap: 16, alignItems: 'start' }}>
        {/* 대기 중 Rule 리스트 */}
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
                  border: r.id === selected.id ? '1px solid var(--primary)' : '1px solid transparent',
                }}
                onClick={() => selectRule(r)}
                onKeyDown={activateOnEnterOrSpace(() => selectRule(r))}
              >
                <div className="row" style={{ justifyContent: 'space-between' }}>
                  <b style={{ fontSize: 13, color: r.id === selected.id ? 'var(--primary)' : 'var(--text)' }}>{r.id}</b>
                  <span className="tag" style={{ fontSize: 10 }}>{r.status}</span>
                </div>
                <div className="text-meta" style={{ marginTop: 2 }}>{r.title}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Rule 상세 */}
        <div className="card">
          <div className="card-head">
            <h3>{selected.id} · Rule 상세</h3>
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

            {/* "이 Rule이 하는 일" — 자연어 블록 (기본 표시) */}
            <div className="field">
              <label className="row" style={{ justifyContent: 'space-between' }}>
                이 Rule이 하는 일
                <button className="btn sm"><Sparkles size={11} /> AI로 다시 쓰기</button>
              </label>
              <div style={{ padding: '10px 12px', background: 'var(--surface-2)', borderRadius: 'var(--radius-control)', border: '1px solid var(--border)' }}>
                <NaturalLanguageBlock logic={selected.logic} />
              </div>
            </div>

            {/* 개발자용 코드 토글 */}
            <div>
              <button
                className="btn sm"
                style={{ width: '100%', justifyContent: 'center', gap: 6, color: 'var(--muted)' }}
                onClick={() => setShowCode((v) => !v)}
              >
                {showCode ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                {'</>'} 개발자용 코드로 {showCode ? '숨기기' : '보기'}
              </button>
              {showCode && (
                <pre style={{ margin: '8px 0 0', padding: '10px 12px', background: 'var(--sidebar-bg)', color: '#d1fae5', borderRadius: 'var(--radius-control)', fontSize: 11.5, whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>
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
              <div className="note" style={{ fontSize: 12 }}>{selected.aiReason}</div>
            </div>
          </div>
          <div className="modal-foot">
            <button className="btn">임시저장</button>
            <div className="spacer" />
            <button className="btn primary">시뮬레이션으로 보내기 →</button>
          </div>
        </div>

        {/* 대화형 지시·수정 (AI Chat) */}
        <div className="card" style={{ borderColor: 'var(--primary)' }}>
          <div className="card-head">
            <h3>대화형 지시·수정</h3>
          </div>
          <div className="text-meta" style={{ padding: '0 14px 8px', fontSize: 11 }}>자연어로 말하면 AI가 필드를 직접 수정합니다</div>
          <div className="stack" style={{ padding: '0 14px', maxHeight: 380, overflowY: 'auto', gap: 8 }}>
            {chat.map((m, i) => (
              <div key={i} style={{ alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start', maxWidth: '95%' }}>
                <div style={{
                  padding: '8px 11px', borderRadius: 10, fontSize: 12.5, whiteSpace: 'pre-line', lineHeight: 1.55,
                  background: m.role === 'user' ? 'var(--primary)' : 'var(--surface-2)',
                  color: m.role === 'user' ? '#fff' : 'var(--text)',
                  borderBottomRightRadius: m.role === 'user' ? 2 : 10,
                  borderBottomLeftRadius: m.role === 'user' ? 10 : 2,
                }}>
                  {m.text}
                </div>
                {m.appliedNote && (
                  <div style={{ fontSize: 11, color: 'var(--tone-green)', marginTop: 3 }}>✓ {m.appliedNote}</div>
                )}
              </div>
            ))}
          </div>
          <div className="row" style={{ padding: '12px 14px', borderTop: '1px solid var(--border)', gap: 8, marginTop: 8 }}>
            <input
              placeholder='예) 관련 조항을 제11조로 바꿔줘'
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') send() }}
              style={{ flex: 1, fontSize: 12 }}
            />
            <button className="btn primary sm" onClick={send} aria-label="전송"><Send size={13} /></button>
          </div>
        </div>
      </div>
    </>
  )
}

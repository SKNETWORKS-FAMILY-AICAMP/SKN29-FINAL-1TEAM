// 테스트케이스(커스텀 검증셋) 만들기 — 내역 미리보기 / 내역 세부 직접 수정 / 대화 Agent.
//  Agent는 mock이다(실제 LLM 호출 없음). 자연어를 규칙으로 해석해 선택된 케이스 필드를 바꾼다.
import { useState } from 'react'
import { Plus, Send, Trash2 } from 'lucide-react'
import { Modal } from '../../components/ui/Modal'
import { won } from '../../lib/format'
import { activateOnEnterOrSpace } from '../../lib/a11y'
import {
  BOOLEAN_FACTS, CATEGORIES, DECISIONS, DECISION_LABEL, NUMBER_FACTS,
  decisionTone, type TestCase,
} from './data/simulationTypes'

interface ChatLine { role: 'user' | 'ai'; text: string; applied?: string }

const blankCase = (seq: number): TestCase => ({
  id: `TC-N${seq}`, label: `새 테스트 케이스 ${seq}`, merchant: '', amount: 0, category: '식대',
  merchantType: '', paymentMethod: '법인카드', expected: '', facts: {},
})

/** 자연어 지시 → 케이스 패치(mock Agent). 해석한 항목의 설명 문구를 함께 돌려준다. */
function interpret(text: string, target: TestCase): { patch: Partial<TestCase>; notes: string[] } {
  const patch: Partial<TestCase> = {}
  const facts = { ...target.facts }
  const notes: string[] = []

  const amount = /([\d,]+)\s*(만원|원)/.exec(text)
  if (amount) {
    const value = Number(amount[1].replace(/,/g, '')) * (amount[2] === '만원' ? 10000 : 1)
    patch.amount = value
    notes.push(`금액 → ${won(value)}`)
  }
  const category = CATEGORIES.find((item) => text.includes(item))
  if (category) { patch.category = category; notes.push(`분류 → ${category}`) }

  const toggle = (path: string, on: boolean, label: string) => { facts[path] = on; notes.push(`${label} → ${on ? '예' : '아니오'}`) }
  if (/증빙/.test(text)) toggle('evidence.has_valid_receipt', !/없|누락|미첨부/.test(text), '적격증빙 있음')
  if (/사전\s*승인/.test(text)) toggle('approval.pre_approval_obtained', !/없|누락|안\s*받/.test(text), '사전승인 받음')
  if (/목적/.test(text)) toggle('evidence.purpose_missing', /없|누락|비어/.test(text), '사용 목적 누락')
  if (/심야|새벽/.test(text)) toggle('derived.is_late_night', !/아니|제외/.test(text), '심야 결제')
  if (/주말|토요일|일요일/.test(text)) toggle('derived.is_weekend', !/아니|제외/.test(text), '주말 결제')
  // 정산 지연은 "경과 영업일 > policy.settlement_deadline_days" 비교로 판정한다.
  // 지연 언급이 있으면 기한을 넉넉히 넘긴 경과일을 넣어 룰이 발동하는지 확인할 수 있게 한다.
  if (/지연|늦게/.test(text)) {
    const late = !/아니/.test(text)
    facts['derived.business_days_since_expense'] = late ? 10 : 1
    notes.push(`결제 후 경과 영업일 → ${late ? 10 : 1}일`)
  }

  const people = /참석(?:자|\s*인원)?\s*([\d]+)\s*명/.exec(text)
  if (people) { facts['participants.participant_count'] = Number(people[1]); notes.push(`참석 인원 → ${people[1]}명`) }
  const external = /외부\s*([\d]+)\s*명/.exec(text)
  if (external) { facts['participants.external_participant_count'] = Number(external[1]); notes.push(`외부 참석자 → ${external[1]}명`) }

  const expected = DECISIONS.find((decision) => text.toUpperCase().includes(decision) || text.includes(DECISION_LABEL[decision]))
  if (expected) { patch.expected = expected; notes.push(`기대 판정 → ${DECISION_LABEL[expected]}`) }

  if (Object.keys(facts).length !== Object.keys(target.facts).length
    || Object.entries(facts).some(([key, value]) => target.facts[key] !== value)) patch.facts = facts
  return { patch, notes }
}

export function TestCaseModal({ cases, onClose, onSave }: {
  cases: TestCase[]; onClose: () => void; onSave: (cases: TestCase[]) => void
}) {
  const [draft, setDraft] = useState<TestCase[]>(cases)
  const [selectedId, setSelectedId] = useState(cases[0]?.id ?? '')
  const [seq, setSeq] = useState(1)
  const [chat, setChat] = useState<ChatLine[]>([])
  const [input, setInput] = useState('')

  const selected = draft.find((item) => item.id === selectedId) ?? draft[0]
  const patch = (changes: Partial<TestCase>) =>
    setDraft((previous) => previous.map((item) => item.id === selected?.id ? { ...item, ...changes } : item))
  const setFact = (path: string, value: boolean | number | undefined) => {
    if (!selected) return
    const facts = { ...selected.facts }
    if (value === undefined) delete facts[path]
    else facts[path] = value
    patch({ facts })
  }

  const addCase = () => {
    const next = blankCase(seq)
    setSeq((value) => value + 1)
    setDraft((previous) => [...previous, next])
    setSelectedId(next.id)
  }
  const removeCase = (id: string) => {
    setDraft((previous) => previous.filter((item) => item.id !== id))
    if (selectedId === id) setSelectedId(draft.find((item) => item.id !== id)?.id ?? '')
  }

  const send = () => {
    const text = input.trim()
    if (!text || !selected) return
    const { patch: changes, notes } = interpret(text, selected)
    if (notes.length) patch(changes)
    setChat((previous) => [...previous, { role: 'user', text }, {
      role: 'ai',
      text: notes.length
        ? `“${selected.label}” 케이스에 반영했습니다.\n${notes.map((note) => `· ${note}`).join('\n')}`
        : '아직 해석하지 못한 지시입니다. 예) “금액 50만원으로 올리고 증빙 누락으로 바꿔줘”, “외부 2명 참석, 기대 판정은 보완요청”',
      applied: notes.length ? `${notes.length}개 항목이 케이스에 적용됨` : undefined,
    }])
    setInput('')
  }

  return (
    <Modal title="테스트케이스(커스텀 검증셋) 만들기" maxWidth={1360} onClose={onClose}
      footer={<>
        <span className="text-meta">시뮬레이션 실행 시 이 검증셋이 그래프 판정에 그대로 투입됩니다.</span>
        <div className="spacer" />
        <button className="btn" onClick={onClose}>취소</button>
        <button className="btn primary" onClick={() => onSave(draft)}>검증셋 저장 ({draft.length}건)</button>
      </>}>
      <div className="testcase-grid">
        {/* ① 내역 리스트 미리보기 */}
        <div className="card">
          <div className="card-head">
            <div><h3>내역 리스트</h3><div className="text-meta">제목 · 정답(기대) 판정</div></div>
            <span className="tag">{draft.length}건</span>
          </div>
          <div className="stack" style={{ padding: 8, gap: 4, maxHeight: 460, overflowY: 'auto' }}>
            {draft.length === 0 && <div className="text-meta" style={{ padding: 8 }}>케이스가 없습니다. 아래에서 추가하세요.</div>}
            {draft.map((item) => (
              <div key={item.id} className={'testcase-item' + (item.id === selected?.id ? ' selected' : '')}
                role="button" tabIndex={0} onClick={() => setSelectedId(item.id)}
                onKeyDown={activateOnEnterOrSpace(() => setSelectedId(item.id))}>
                <div className="testcase-item-top">
                  <span className="name" title={item.label}>{item.label}</span>
                  {/* 정답(기대) 판정 — 비어 있어도 자리를 비우지 않고 '채점 안 함'으로 표시해 열을 맞춘다. */}
                  {item.expected
                    ? <span className={'tag ' + decisionTone(item.expected)}>{DECISION_LABEL[item.expected]}</span>
                    : <span className="tag" title="기대 판정이 없어 채점에서 제외됩니다">채점 안 함</span>}
                </div>
                <div className="testcase-item-meta">
                  {item.merchant || '가맹점 미입력'} · {won(item.amount)} · {item.category || '분류 없음'}
                </div>
              </div>
            ))}
          </div>
          <div style={{ padding: 8, borderTop: '1px solid var(--border)' }}>
            <button className="routing-add" onClick={addCase}><Plus size={13} /> 케이스 추가</button>
          </div>
        </div>

        {/* ② 내역 세부 — 직접 수정 */}
        {selected ? (
          <div className="card">
            <div className="card-head">
              <div><h3>내역 세부 — 직접 수정</h3><div className="text-meta">{selected.id}</div></div>
              <button className="btn sm warn" onClick={() => removeCase(selected.id)}><Trash2 size={12} /> 삭제</button>
            </div>
            <div className="card-body" style={{ maxHeight: 460, overflowY: 'auto' }}>
              <div className="field"><label>케이스 이름</label>
                <input value={selected.label} onChange={(event) => patch({ label: event.target.value })} /></div>
              <div className="grid-2" style={{ gap: 8 }}>
                <div className="field"><label>가맹점</label>
                  <input value={selected.merchant} onChange={(event) => patch({ merchant: event.target.value })} /></div>
                <div className="field"><label>금액(원)</label>
                  <input type="number" value={selected.amount} onChange={(event) => patch({ amount: Number(event.target.value) })} /></div>
                <div className="field"><label>비용 분류</label>
                  <select value={selected.category} onChange={(event) => patch({ category: event.target.value })}>
                    <option value="">분류 없음</option>
                    {CATEGORIES.map((item) => <option key={item}>{item}</option>)}
                  </select></div>
                <div className="field"><label>가맹점 업종</label>
                  <input value={selected.merchantType} placeholder="예) 주점, 골프장"
                    onChange={(event) => patch({ merchantType: event.target.value })} /></div>
                <div className="field"><label>결제 수단</label>
                  <input value={selected.paymentMethod} onChange={(event) => patch({ paymentMethod: event.target.value })} /></div>
                <div className="field"><label>기대 판정 (채점 기준)</label>
                  <select value={selected.expected} onChange={(event) => patch({ expected: event.target.value as TestCase['expected'] })}>
                    <option value="">채점 안 함</option>
                    {DECISIONS.map((decision) => <option key={decision} value={decision}>{DECISION_LABEL[decision]} ({decision})</option>)}
                  </select></div>
              </div>

              <div className="field"><label>판정 입력값 — 예/아니오</label>
                <div className="stack" style={{ gap: 6 }}>
                  {BOOLEAN_FACTS.map((fact) => (
                    <label key={fact.path} className="row" style={{ gap: 8, fontSize: 12.5 }}>
                      <input type="checkbox" checked={selected.facts[fact.path] === true}
                        onChange={(event) => setFact(fact.path, event.target.checked)} />
                      {fact.label}
                    </label>
                  ))}
                </div>
              </div>

              <div className="field" style={{ marginBottom: 0 }}><label>판정 입력값 — 수치</label>
                <div className="grid-2" style={{ gap: 8 }}>
                  {NUMBER_FACTS.map((fact) => (
                    <label key={fact.path} className="stack" style={{ gap: 2 }}>
                      <span className="text-meta">{fact.label}</span>
                      <input type="number" value={String(selected.facts[fact.path] ?? '')} placeholder="미설정"
                        onChange={(event) => setFact(fact.path, event.target.value === '' ? undefined : Number(event.target.value))} />
                    </label>
                  ))}
                </div>
              </div>
            </div>
          </div>
        ) : <div className="card"><div className="card-body text-meta">좌측에서 케이스를 선택하거나 새로 추가하세요.</div></div>}

        {/* ③ 대화 Agent 작업화면 */}
        <div className="card" style={{ borderColor: 'var(--primary)' }}>
          <div className="card-head"><h3>대화 Agent</h3><span className="tag ai">mock</span></div>
          <div className="text-meta" style={{ padding: '0 16px' }}>자연어로 지시하면 선택된 케이스를 바로 수정합니다.</div>
          <div className="stack" style={{ padding: 16, gap: 10, height: 380, overflowY: 'auto' }}>
            {chat.length === 0 && (
              <div className="note">예) “금액 50만원으로 올리고 증빙 누락으로 바꿔줘”<br />“외부 2명 참석, 심야 결제, 기대 판정은 검토 필요”</div>
            )}
            {chat.map((line, index) => (
              <div key={index} style={{ alignSelf: line.role === 'user' ? 'flex-end' : 'flex-start', maxWidth: '92%' }}>
                <div style={{
                  padding: '8px 12px', borderRadius: 'var(--radius-control)', fontSize: 12.5, whiteSpace: 'pre-line',
                  background: line.role === 'user' ? 'var(--primary)' : 'var(--surface-2)',
                  color: line.role === 'user' ? '#fff' : 'var(--text)',
                }}>{line.text}</div>
                {line.applied && <div className="text-meta" style={{ color: 'var(--tone-green)', marginTop: 4 }}>✓ {line.applied}</div>}
              </div>
            ))}
          </div>
          <div className="row" style={{ padding: 16, borderTop: '1px solid var(--border)', gap: 8 }}>
            <input placeholder="예) 금액 80만원, 증빙 누락" value={input} disabled={!selected}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => { if (event.key === 'Enter') send() }} style={{ flex: 1 }} />
            <button className="btn primary" onClick={send} disabled={!selected} aria-label="전송"><Send size={14} /></button>
          </div>
        </div>
      </div>
    </Modal>
  )
}

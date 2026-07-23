// F-1 신규 지출 등록 — 업로드 → AI 판독 확인 → 제출 완료. AppLayout 밖 풀스크린 라우트.
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Check, Sparkles, Upload, X } from 'lucide-react'
import { CATEGORIES, type Category } from '../types/domain'
import { createSettlement } from '../api/settlementService'
import { useSettlements } from '../context/SettlementsContext'
import { useAuth } from '../context/AuthContext'

type Step = 1 | 2 | 3

const STEP_LABEL: Record<Step, string> = { 1: '영수증 업로드', 2: 'AI 판독 결과 확인', 3: '제출 완료' }

export function NewExpense() {
  const nav = useNavigate()
  const { addExpense } = useSettlements()
  const { user } = useAuth()
  const [step, setStep] = useState<Step>(1)
  const [uploaded, setUploaded] = useState(false)
  const [category, setCategory] = useState<Category>('접대')
  const [merchant, setMerchant] = useState('강남한식당')
  const [dateTime, setDateTime] = useState('2026-07-18 19:20')
  const [amountText, setAmountText] = useState('452,000')
  const [submitting, setSubmitting] = useState(false)

  const close = () => nav('/my-expenses')

  const submit = async () => {
    setSubmitting(true)
    const amount = Number(amountText.replace(/[^0-9]/g, '')) || 0
    const draft = {
      date: dateTime.slice(0, 10),
      merchant,
      amount,
      cardType: 'SHARED' as const,
      aiCategory: category,
      aiSuggested: true,
      evidence: 'OK' as const,
      user: user?.name ?? '홍길동',
    }
    const created = await createSettlement(draft)
    addExpense(created)
    setSubmitting(false)
    setStep(3)
  }

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)', padding: 'var(--space-6)' }}>
      <div className="row" style={{ justifyContent: 'space-between', marginBottom: 24 }}>
        <div>
          <h1 style={{ fontSize: 20 }}>신규 지출 등록</h1>
          <div className="text-meta">내 지출 &gt; 신규 등록</div>
        </div>
        <button className="x-btn" onClick={close} aria-label="닫기"><X size={18} /></button>
      </div>

      <div className="row" style={{ gap: 8, marginBottom: 24 }}>
        {([1, 2, 3] as Step[]).map((s, i) => (
          <div key={s} className="row" style={{ gap: 8 }}>
            <span
              className="tag"
              style={
                s < step
                  ? { background: 'var(--tone-green-bg)', color: 'var(--tone-green)', borderColor: 'transparent' }
                  : s === step
                  ? { background: 'var(--primary-soft)', color: 'var(--primary)', borderColor: 'transparent' }
                  : undefined
              }
            >
              {s < step ? <Check size={11} /> : s}{' '}{STEP_LABEL[s]}
            </span>
            {i < 2 && <span className="muted">─</span>}
          </div>
        ))}
      </div>

      {step === 1 && (
        <div className="card" style={{ maxWidth: 480 }}>
          <div className="card-body stack">
            <div
              style={{
                border: '1px dashed var(--border-strong)', borderRadius: 'var(--radius-control)', padding: 'var(--space-6)',
                textAlign: 'center', color: 'var(--muted)', background: 'var(--surface-2)',
              }}
            >
              <Upload size={28} style={{ margin: '0 auto 8px' }} />
              <div>영수증 이미지를 드래그하거나 파일을 선택하세요</div>
            </div>
            <button className="btn primary" style={{ justifyContent: 'center' }} onClick={() => setUploaded(true)}>
              파일 선택
            </button>
            {uploaded && <div className="text-meta">✓ receipt_0718.jpg 업로드됨</div>}
          </div>
          <div className="modal-foot" style={{ border: 'none' }}>
            <div className="spacer" />
            <button className="btn primary" disabled={!uploaded} onClick={() => setStep(2)}>다음</button>
          </div>
        </div>
      )}

      {step === 2 && (
        <div className="grid-2">
          <div className="card">
            <div className="card-head"><h3>업로드된 영수증</h3></div>
            <div className="card-body">
              <div style={{ height: 220, background: 'var(--surface-2)', borderRadius: 'var(--radius-control)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--muted)' }}>
                receipt_0718.jpg
              </div>
              <div className="text-meta" style={{ marginTop: 8 }}><Check size={12} style={{ verticalAlign: -2 }} /> 업로드 완료 · AI 판독 완료</div>
            </div>
          </div>

          <div className="card">
            <div className="card-head"><h3>AI 판독 결과</h3></div>
            <div className="card-body">
              <div className="note" style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 16 }}>
                <Sparkles size={14} /> AI가 자동으로 인식했어요 — 내용을 확인하고 필요하면 수정하세요.
              </div>
              <div className="field"><label>가맹점명 <span className="tag ai">AI</span></label><input value={merchant} onChange={(e) => setMerchant(e.target.value)} /></div>
              <div className="field"><label>거래일시 <span className="tag ai">AI</span></label><input value={dateTime} onChange={(e) => setDateTime(e.target.value)} /></div>
              <div className="field"><label>금액 <span className="tag ai">AI</span></label><input value={amountText} onChange={(e) => setAmountText(e.target.value)} /></div>
              <div className="field"><label>카드 선택</label><select><option>공용카드 (국민카드 ****5678)</option></select></div>
              <div className="field">
                <label>비용 분류</label>
                <div className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
                  {CATEGORIES.map((c) => (
                    <button
                      key={c}
                      type="button"
                      className={'tag' + (c === category ? ' ai' : '')}
                      style={{ font: 'inherit', cursor: 'pointer' }}
                      onClick={() => setCategory(c)}
                    >
                      {c}
                    </button>
                  ))}
                </div>
              </div>
              <div className="note">규정 힌트 — 3만원 초과 시 적격증빙 필수 · 30만원 이하로 사전승인 대상 아님</div>
            </div>
            <div className="modal-foot">
              <button className="btn" disabled={submitting} onClick={() => setStep(1)}>이전</button>
              <div className="spacer" />
              <button className="btn primary" disabled={submitting} onClick={submit}>
                {submitting ? '제출 중…' : '저장하고 제출하기'}
              </button>
            </div>
          </div>
        </div>
      )}

      {step === 3 && (
        <div className="card" style={{ maxWidth: 420 }}>
          <div className="card-body stack" style={{ alignItems: 'center', textAlign: 'center', padding: 'var(--space-6) var(--space-4)' }}>
            <div className="step-badge" style={{ background: 'var(--tone-green-bg)', color: 'var(--tone-green)' }}>
              <Check size={20} />
            </div>
            <h2 style={{ fontSize: 18 }}>제출 완료</h2>
            <p className="text-meta">지출 등록이 완료됐습니다. 내 지출 목록에서 바로 확인할 수 있어요.</p>
            <button className="btn primary" style={{ width: '100%', justifyContent: 'center' }} onClick={close}>
              내 지출로 이동
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

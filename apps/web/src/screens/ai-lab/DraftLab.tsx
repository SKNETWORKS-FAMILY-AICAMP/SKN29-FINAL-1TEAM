// ① 초안 작성 Agent 실험실 — 정산 등록 화면(S-01)을 거치지 않고 Agent만 단독 실행한다.
//  운영과 같은 엔드포인트 분기(`instruction` 유무 = 수정/생성)를 쓰고, 결과에 더해
//  실행 추적(모델·프롬프트·원본 응답·토큰·지연·정책 출처)을 그대로 펼친다.
import { useMemo, useState } from 'react'
import { ArrowRight, Play, RotateCcw } from 'lucide-react'
import {
  labApi,
  labErrorMessage,
  type DraftCategory,
  type DraftRunResponse,
} from './data/labApi'
import { Collapsible, EmptyHint, ErrorBanner, FactRow, JsonBlock, TextBlock } from './components/LabPrimitives'

const CARD_TYPES = ['PERSONAL', 'TEAM', 'SHARED', 'POST_PAID', 'PREPAID'] as const
const CATEGORIES: DraftCategory[] = ['회식', '회의', '식대', '출장', '접대', '비품']

interface CreateForm {
  merchant: string
  amount: number
  date: string
  cardType: string
  evidence: 'OK' | 'MISSING'
  headcount: number
}

interface ReviseForm {
  instruction: string
  merchant: string
  amount: number
  category: DraftCategory
  purpose: string
  evidence: 'OK' | 'MISSING'
  headcount: number
}

const TODAY = new Date().toISOString().slice(0, 10)

const CREATE_DEFAULT: CreateForm = {
  merchant: '대치동 한우마을',
  amount: 180000,
  date: TODAY,
  cardType: 'TEAM',
  evidence: 'OK',
  headcount: 4,
}

const REVISE_DEFAULT: ReviseForm = {
  instruction: '거래처 임원 2명이 함께한 저녁이었어. 접대비로 바꾸고 인원은 6명으로 고쳐줘.',
  merchant: '대치동 한우마을',
  amount: 180000,
  category: '식대',
  purpose: '팀 저녁 식사',
  evidence: 'OK',
  headcount: 4,
}

interface HistoryEntry {
  id: number
  at: string
  label: string
  response: DraftRunResponse
}

export function DraftLab() {
  const [mode, setMode] = useState<'create' | 'revise'>('create')
  const [createForm, setCreateForm] = useState<CreateForm>(CREATE_DEFAULT)
  const [reviseForm, setReviseForm] = useState<ReviseForm>(REVISE_DEFAULT)
  const [rawMode, setRawMode] = useState(false)
  const [rawText, setRawText] = useState('')
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')
  const [response, setResponse] = useState<DraftRunResponse | null>(null)
  const [history, setHistory] = useState<HistoryEntry[]>([])

  // 폼 → 요청 payload. 원문 편집 모드에서는 이 값이 편집 시작점이 된다.
  const payload = useMemo<Record<string, unknown>>(() => {
    if (mode === 'create') {
      return {
        merchant: createForm.merchant,
        amount: Number(createForm.amount) || 0,
        date: createForm.date,
        cardType: createForm.cardType,
        evidence: createForm.evidence,
        headcount: Number(createForm.headcount) || 0,
      }
    }
    return {
      instruction: reviseForm.instruction,
      current: {
        merchant: reviseForm.merchant,
        amount: Number(reviseForm.amount) || 0,
        category: reviseForm.category,
        purpose: reviseForm.purpose,
        evidence: reviseForm.evidence,
        headcount: Number(reviseForm.headcount) || 0,
      },
    }
  }, [mode, createForm, reviseForm])

  const run = async () => {
    let body: Record<string, unknown> = payload
    if (rawMode) {
      try {
        body = JSON.parse(rawText)
      } catch (e) {
        setError(`요청 JSON을 해석하지 못했습니다: ${(e as Error).message}`)
        return
      }
    }
    setRunning(true)
    setError('')
    try {
      const res = await labApi.runDraft(body)
      setResponse(res)
      setHistory((prev) =>
        [
          {
            id: Date.now(),
            at: new Date().toLocaleTimeString('ko-KR', { hour12: false }),
            label:
              res.result.mode === 'revise'
                ? `수정 · ${String((body as { instruction?: string }).instruction ?? '').slice(0, 18)}…`
                : `생성 · ${res.result.draft.merchant}`,
            response: res,
          },
          ...prev,
        ].slice(0, 12),
      )
    } catch (err) {
      setError(labErrorMessage(err))
    } finally {
      setRunning(false)
    }
  }

  /** 방금 나온 초안을 수정 모드의 `current`로 옮긴다 — 생성→수정 연쇄를 화면에서 그대로 재현. */
  const carryToRevise = () => {
    if (!response) return
    const d = response.result.draft
    setReviseForm((prev) => ({
      ...prev,
      merchant: d.merchant,
      amount: d.amount,
      category: d.category,
      purpose: d.purpose,
      evidence: d.evidence,
      headcount: d.headcount,
    }))
    setMode('revise')
    setRawMode(false)
  }

  const toggleRaw = () => {
    if (!rawMode) setRawText(JSON.stringify(payload, null, 2))
    setRawMode((v) => !v)
  }

  return (
    <div className="lab-split">
      {/* ── 입력 ───────────────────────────────── */}
      <div className="stack-lg">
        <div className="card">
          <div className="card-head">
            <h3>실행 입력</h3>
            <div className="lab-seg" role="tablist" aria-label="Draft 실행 모드">
              {(['create', 'revise'] as const).map((m) => (
                <button
                  key={m}
                  role="tab"
                  aria-selected={mode === m}
                  className={'btn sm' + (mode === m ? ' primary' : '')}
                  onClick={() => setMode(m)}
                >
                  {m === 'create' ? '생성' : '수정'}
                </button>
              ))}
            </div>
          </div>
          <div className="card-body">
            {rawMode ? (
              <div className="field" style={{ marginBottom: 0 }}>
                <label>요청 JSON (POST /api/ai-lab/draft/run 본문)</label>
                <textarea
                  className="lab-code-input"
                  rows={16}
                  value={rawText}
                  onChange={(e) => setRawText(e.target.value)}
                  spellCheck={false}
                />
                <div className="text-meta" style={{ marginTop: 6 }}>
                  <code>instruction</code>이 있으면 수정 모드, 없으면 생성 모드로 처리됩니다(운영과 동일 분기).
                </div>
              </div>
            ) : mode === 'create' ? (
              <>
                <div className="field">
                  <label>가맹점</label>
                  <input
                    value={createForm.merchant}
                    onChange={(e) => setCreateForm({ ...createForm, merchant: e.target.value })}
                  />
                </div>
                <div className="grid-2">
                  <div className="field">
                    <label>금액(원)</label>
                    <input
                      type="number"
                      value={createForm.amount}
                      onChange={(e) => setCreateForm({ ...createForm, amount: Number(e.target.value) })}
                    />
                  </div>
                  <div className="field">
                    <label>거래일자</label>
                    <input
                      type="date"
                      value={createForm.date}
                      onChange={(e) => setCreateForm({ ...createForm, date: e.target.value })}
                    />
                  </div>
                </div>
                <div className="grid-3">
                  <div className="field">
                    <label>카드 구분</label>
                    <select
                      value={createForm.cardType}
                      onChange={(e) => setCreateForm({ ...createForm, cardType: e.target.value })}
                    >
                      {CARD_TYPES.map((c) => (
                        <option key={c} value={c}>{c}</option>
                      ))}
                    </select>
                  </div>
                  <div className="field">
                    <label>증빙</label>
                    <select
                      value={createForm.evidence}
                      onChange={(e) =>
                        setCreateForm({ ...createForm, evidence: e.target.value as 'OK' | 'MISSING' })
                      }
                    >
                      <option value="OK">OK</option>
                      <option value="MISSING">MISSING</option>
                    </select>
                  </div>
                  <div className="field">
                    <label>참석 인원</label>
                    <input
                      type="number"
                      value={createForm.headcount}
                      onChange={(e) => setCreateForm({ ...createForm, headcount: Number(e.target.value) })}
                    />
                  </div>
                </div>
                <div className="note">
                  참석 인원 0은 "정보 없음"으로 취급됩니다(프롬프트 규칙 4). 영수증 비전 판독은 이 실험 범위 밖입니다.
                </div>
              </>
            ) : (
              <>
                <div className="field">
                  <label>자연어 수정 지시</label>
                  <textarea
                    rows={3}
                    value={reviseForm.instruction}
                    onChange={(e) => setReviseForm({ ...reviseForm, instruction: e.target.value })}
                  />
                </div>
                <div className="lab-subhead">현재 초안 (current)</div>
                <div className="grid-2">
                  <div className="field">
                    <label>가맹점</label>
                    <input
                      value={reviseForm.merchant}
                      onChange={(e) => setReviseForm({ ...reviseForm, merchant: e.target.value })}
                    />
                  </div>
                  <div className="field">
                    <label>금액(원)</label>
                    <input
                      type="number"
                      value={reviseForm.amount}
                      onChange={(e) => setReviseForm({ ...reviseForm, amount: Number(e.target.value) })}
                    />
                  </div>
                </div>
                <div className="grid-3">
                  <div className="field">
                    <label>분류</label>
                    <select
                      value={reviseForm.category}
                      onChange={(e) =>
                        setReviseForm({ ...reviseForm, category: e.target.value as DraftCategory })
                      }
                    >
                      {CATEGORIES.map((c) => (
                        <option key={c} value={c}>{c}</option>
                      ))}
                    </select>
                  </div>
                  <div className="field">
                    <label>증빙</label>
                    <select
                      value={reviseForm.evidence}
                      onChange={(e) =>
                        setReviseForm({ ...reviseForm, evidence: e.target.value as 'OK' | 'MISSING' })
                      }
                    >
                      <option value="OK">OK</option>
                      <option value="MISSING">MISSING</option>
                    </select>
                  </div>
                  <div className="field">
                    <label>참석 인원</label>
                    <input
                      type="number"
                      value={reviseForm.headcount}
                      onChange={(e) => setReviseForm({ ...reviseForm, headcount: Number(e.target.value) })}
                    />
                  </div>
                </div>
                <div className="field" style={{ marginBottom: 0 }}>
                  <label>지출 목적</label>
                  <textarea
                    rows={2}
                    value={reviseForm.purpose}
                    onChange={(e) => setReviseForm({ ...reviseForm, purpose: e.target.value })}
                  />
                </div>
              </>
            )}
          </div>
          <div className="lab-runbar">
            <button className="btn primary" onClick={run} disabled={running}>
              <Play size={13} /> {running ? '실행 중…' : '실행'}
            </button>
            <button className="btn" onClick={toggleRaw}>
              {rawMode ? '폼으로' : '요청 JSON 직접 편집'}
            </button>
            <button
              className="btn"
              onClick={() => {
                setCreateForm(CREATE_DEFAULT)
                setReviseForm(REVISE_DEFAULT)
                setRawMode(false)
                setError('')
              }}
            >
              <RotateCcw size={12} /> 초기화
            </button>
          </div>
        </div>

        {!rawMode && (
          <div className="card">
            <div className="card-head"><h3>전송될 요청</h3></div>
            <div className="card-body">
              <JsonBlock value={payload} label="request body" maxHeight={200} />
            </div>
          </div>
        )}

        {history.length > 0 && (
          <div className="card">
            <div className="card-head">
              <h3>실행 이력 (이 세션)</h3>
              <button className="btn sm" onClick={() => setHistory([])}>비우기</button>
            </div>
            <div className="card-body" style={{ padding: 8 }}>
              {history.map((h) => (
                <button key={h.id} className="lab-history-row" onClick={() => setResponse(h.response)}>
                  <span className="text-meta">{h.at}</span>
                  <span className="lab-history-label">{h.label}</span>
                  <span className={'tag' + (h.response.trace.fallbackUsed ? ' warn' : ' ok')}>
                    {h.response.trace.fallbackUsed ? '폴백' : `${h.response.trace.totalMs ?? 0}ms`}
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* ── 결과 ───────────────────────────────── */}
      <div className="stack-lg">
        {error && <ErrorBanner message={error} />}
        {!response && !error && (
          <EmptyHint>
            왼쪽에서 값을 채우고 <b>실행</b>을 누르면, 초안 결과와 함께 모델·프롬프트·원본 응답·토큰·지연이
            이 자리에 펼쳐집니다.
          </EmptyHint>
        )}
        {response && <DraftResultView res={response} onCarry={carryToRevise} />}
      </div>
    </div>
  )
}

function DraftResultView({ res, onCarry }: { res: DraftRunResponse; onCarry: () => void }) {
  const { result, trace } = res
  const d = result.draft
  const pct = Math.round((result.confidence ?? 0) * 100)

  return (
    <>
      <div className="card">
        <div className="card-head">
          <h3>
            초안 결과{' '}
            <span className="tag" style={{ marginLeft: 6 }}>{result.mode === 'revise' ? '수정 모드' : '생성 모드'}</span>
          </h3>
          <button className="btn sm" onClick={onCarry}>
            이 결과로 수정 이어가기 <ArrowRight size={11} />
          </button>
        </div>
        <div className="card-body">
          {trace.fallbackUsed && (
            <div className="note" style={{ marginBottom: 12, borderColor: 'var(--tone-red)', color: 'var(--tone-red)' }}>
              LLM 경로가 실패해 <b>폴백 초안</b>이 나왔습니다. 아래 추적의 오류 문구를 확인하세요 — 이 값은 모델 판단이 아닙니다.
            </div>
          )}
          <table className="table">
            <tbody>
              <tr style={{ cursor: 'default' }}><th style={{ width: 120 }}>가맹점</th><td>{d.merchant}</td></tr>
              <tr style={{ cursor: 'default' }}><th>금액</th><td className="num" style={{ textAlign: 'left' }}>{d.amount.toLocaleString()}원</td></tr>
              <tr style={{ cursor: 'default' }}>
                <th>비용 분류</th>
                <td>
                  {d.category}
                  {d.aiSuggested && <span className="tag ai" style={{ marginLeft: 6 }}>AI 제안</span>}
                  {d.aiCategory !== d.category && (
                    <span className="text-meta" style={{ marginLeft: 6 }}>(AI 원안: {d.aiCategory})</span>
                  )}
                </td>
              </tr>
              <tr style={{ cursor: 'default' }}><th>가맹점 업종</th><td>{d.merchantIndustry || '—'} <span className="text-meta">(보조 힌트, 세무 판단 아님)</span></td></tr>
              <tr style={{ cursor: 'default' }}><th>지출 목적</th><td>{d.purpose}</td></tr>
              <tr style={{ cursor: 'default' }}><th>증빙 / 인원</th><td>{d.evidence} · {d.headcount}명</td></tr>
              <tr style={{ cursor: 'default' }}>
                <th>확신도</th>
                <td>
                  <div className="lab-meter"><span style={{ width: `${pct}%` }} /></div>
                  <span className="text-meta">{result.confidence?.toFixed(2)} ({pct}%)</span>
                </td>
              </tr>
            </tbody>
          </table>

          {!!result.changes?.length && (
            <>
              <div className="lab-subhead">변경 사항 (changes)</div>
              <ul className="lab-list">
                {result.changes.map((c, i) => <li key={i}>{c}</li>)}
              </ul>
            </>
          )}

          <div className="lab-subhead">Agent 코멘트 (comments)</div>
          {result.comments.length === 0 ? (
            <div className="text-meta">없음</div>
          ) : (
            <ul className="lab-list">
              {result.comments.map((c, i) => (
                <li key={i}><span className="tag">{c.icon}</span> {c.text}</li>
              ))}
            </ul>
          )}

          <div className="lab-subhead">규정 힌트 (policyHints)</div>
          {result.policyHints.length === 0 ? (
            <div className="text-meta">해당 없음 — 서버가 정책 숫자를 근거로 결정론적으로 생성합니다(LLM 생성 아님).</div>
          ) : (
            <ul className="lab-list">
              {result.policyHints.map((h, i) => (
                <li key={i}>
                  <span className={'tag' + (h.level === 'warn' ? ' warn' : '')}>{h.clause}</span> {h.text}
                  <div className="text-meta">{h.status}</div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="card">
        <div className="card-head"><h3>실행 추적</h3></div>
        <div className="card-body">
          <FactRow
            items={[
              ['모델', trace.model ?? '—'],
              ['temperature', trace.temperature ?? '—'],
              ['LLM 지연', trace.latencyMs != null ? `${trace.latencyMs}ms` : '—'],
              ['총 처리', trace.totalMs != null ? `${trace.totalMs}ms` : '—'],
              ['토큰(입력/출력)', trace.usage ? `${trace.usage.promptTokens ?? '?'} / ${trace.usage.completionTokens ?? '?'}` : '—'],
              ['종료 사유', trace.finishReason ?? '—'],
              ['정책 출처', trace.policy ? (trace.policy.source === 'core' ? 'Django Policy 실조회' : `폴백 (${trace.policy.reason ?? '이유 미상'})`) : '조회 안 함'],
              ['폴백 사용', trace.fallbackUsed ? '예' : '아니오'],
            ]}
          />
          {trace.error && <div style={{ marginTop: 12 }}><ErrorBanner message={trace.error} /></div>}
          {trace.refusal && <div className="note" style={{ marginTop: 12 }}>모델 거부(refusal): {trace.refusal}</div>}

          <div className="stack" style={{ marginTop: 12 }}>
            {trace.systemPrompt && (
              <Collapsible title="시스템 프롬프트" meta={`${trace.systemPrompt.length}자`}>
                <TextBlock text={trace.systemPrompt} label="system" />
              </Collapsible>
            )}
            {trace.userPrompt && (
              <Collapsible title="사용자 프롬프트 (실제 전송값)" meta={`${trace.userPrompt.length}자`}>
                <TextBlock text={trace.userPrompt} label="user" />
              </Collapsible>
            )}
            {trace.rawOutput && (
              <Collapsible title="LLM 원본 출력 (Structured Output)" defaultOpen>
                <TextBlock text={trace.rawOutput} label="assistant" maxHeight={260} />
              </Collapsible>
            )}
            {trace.policy?.value && (
              <Collapsible title="조회된 정책 값">
                <JsonBlock value={trace.policy.value} label="get_policy" maxHeight={200} />
              </Collapsible>
            )}
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-head"><h3>전체 응답</h3></div>
        <div className="card-body">
          <JsonBlock value={res} label="POST /api/ai-lab/draft/run" maxHeight={420} />
        </div>
      </div>
    </>
  )
}

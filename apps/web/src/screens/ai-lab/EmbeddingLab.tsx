// ③ 임베딩 인스펙터 — 문장을 벡터로 바꿔 보고, 문장끼리 얼마나 닮았는지(cosine) 직접 잰다.
//  검색이 이상할 때 "임베딩이 문제인가 적재가 문제인가"를 가르는 데 쓴다.
//  벡터는 L2 정규화되어 있으므로 cosine = 내적이다(서버가 계산해 행렬로 준다).
import { useState } from 'react'
import { Play } from 'lucide-react'
import { labApi, labErrorMessage, type RagEmbedResponse } from './data/labApi'
import { EmptyHint, ErrorBanner, FactRow, JsonBlock } from './components/LabPrimitives'

const SAMPLE = [
  '회식비 한도는 어떻게 정해져 있나',
  '팀 회식 1인당 지출 상한',
  '출장 숙박비 증빙 기준',
].join('\n')

/** 유사도에 따라 셀 배경을 진하게 — 값을 읽기 전에 덩어리가 먼저 보이게 한다. */
function simStyle(v: number) {
  const t = Math.max(0, Math.min(1, (v - 0.3) / 0.7))
  return { background: `rgba(43, 92, 224, ${(t * 0.35).toFixed(3)})`, fontVariantNumeric: 'tabular-nums' as const }
}

export function EmbeddingLab() {
  const [text, setText] = useState(SAMPLE)
  const [mode, setMode] = useState<'query' | 'raw'>('query')
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')
  const [res, setRes] = useState<RagEmbedResponse | null>(null)

  const lines = text.split('\n').map((l) => l.trim()).filter(Boolean)

  const run = async () => {
    if (lines.length === 0) {
      setError('임베딩할 문장을 한 줄 이상 입력하세요.')
      return
    }
    if (lines.length > 16) {
      setError(`한 번에 16줄까지 처리합니다 (현재 ${lines.length}줄).`)
      return
    }
    setRunning(true)
    setError('')
    try {
      setRes(await labApi.ragEmbed({ texts: lines, mode }))
    } catch (err) {
      setError(labErrorMessage(err))
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="stack-lg">
      <div className="card">
        <div className="card-head">
          <h3>임베딩 실행</h3>
          <span className="text-meta">한 줄 = 한 문장 · 최대 16줄</span>
        </div>
        <div className="card-body">
          <div className="field">
            <label>문장</label>
            <textarea rows={6} value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} />
          </div>
          <div className="lab-controls">
            <div className="field" style={{ marginBottom: 0, minWidth: 260 }}>
              <label>입력 규약</label>
              <select value={mode} onChange={(e) => setMode(e.target.value as 'query' | 'raw')}>
                <option value="query">query — 질의 접두(Q_ctx) 부착</option>
                <option value="raw">raw — 원문 그대로</option>
              </select>
            </div>
            <span className="text-meta" style={{ flex: 1 }}>
              문서 쪽 계층 헤더 주입은 청킹 단계의 몫이라 임의 문장에는 붙지 않습니다.
            </span>
          </div>
        </div>
        <div className="lab-runbar">
          <button className="btn primary" onClick={run} disabled={running}>
            <Play size={13} /> {running ? '임베딩 중…' : `임베딩 (${lines.length}줄)`}
          </button>
        </div>
      </div>

      {error && <ErrorBanner message={error} />}
      {!res && !error && <EmptyHint>문장을 넣고 실행하면 벡터 요약과 문장 간 유사도 행렬이 나옵니다.</EmptyHint>}

      {res && (
        <>
          <div className="card">
            <div className="card-head"><h3>실행 정보</h3></div>
            <div className="card-body">
              <FactRow
                items={[
                  ['모델', `${res.model} @ ${res.dimensions}차원`],
                  ['입력 규약', res.mode],
                  ['부착된 접두', res.appliedPrefix ? <code key="p">{res.appliedPrefix}</code> : '(없음)'],
                  ['과금 토큰', res.billedTokens.toLocaleString()],
                  ['지연', `${res.latencyMs}ms`],
                ]}
              />
            </div>
          </div>

          <div className="card">
            <div className="card-head">
              <h3>유사도 행렬 (cosine)</h3>
              <span className="text-meta">대각선은 자기 자신 = 1.0</span>
            </div>
            <div className="card-body" style={{ padding: 0, overflowX: 'auto' }}>
              <table className="table">
                <thead>
                  <tr>
                    <th style={{ minWidth: 220 }}>문장</th>
                    {res.vectors.map((_, i) => <th key={i} className="num">#{i + 1}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {res.similarity.map((row, i) => (
                    <tr key={i} style={{ cursor: 'default' }}>
                      <td>
                        <span className="lab-rank">#{i + 1}</span> {res.vectors[i].text}
                      </td>
                      {row.map((v, j) => (
                        <td key={j} className="num" style={i === j ? undefined : simStyle(v)}>
                          {v.toFixed(4)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="card">
            <div className="card-head"><h3>벡터 미리보기</h3></div>
            <div className="card-body" style={{ padding: 0 }}>
              <table className="table">
                <thead>
                  <tr>
                    <th>문장</th>
                    <th className="num">차원</th>
                    <th>앞 8개 성분</th>
                  </tr>
                </thead>
                <tbody>
                  {res.vectors.map((v, i) => (
                    <tr key={i} style={{ cursor: 'default' }}>
                      <td>{v.text}</td>
                      <td className="num">{v.dim}</td>
                      <td className="text-meta" style={{ fontFamily: 'Consolas, monospace' }}>
                        [{v.head.join(', ')} …]
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="card">
            <div className="card-head"><h3>전체 응답</h3></div>
            <div className="card-body">
              <JsonBlock value={res} label="POST /api/ai-lab/rag/embed" maxHeight={360} />
            </div>
          </div>
        </>
      )}
    </div>
  )
}

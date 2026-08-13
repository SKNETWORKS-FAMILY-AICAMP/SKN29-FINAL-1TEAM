// ② RAG 검색 실험실 — 운영 검색(`store.search`)을 그대로 호출한다.
//  "이 질의에 왜 이 조문이 걸렸는지"를 점수·인용·메타데이터·부모 확장까지 열어 확인한다.
//  질의 접두(Q_ctx) on/off는 임베딩 전략 §7의 비대칭 입력을 직접 재보기 위한 스위치다.
import { useState } from 'react'
import { Play, Search } from 'lucide-react'
import { labApi, labErrorMessage, type RagHit, type RagSearchResponse } from './data/labApi'
import { Collapsible, EmptyHint, ErrorBanner, FactRow, JsonBlock, TextBlock } from './components/LabPrimitives'

const COLLECTIONS = [
  { name: 'policy_docs', label: 'policy_docs (사내 규정)' },
  { name: 'tax_refs', label: 'tax_refs (법령)' },
  { name: 'case_history', label: 'case_history (과거 사례)' },
  { name: 'org_docs', label: 'org_docs (조직 문서 · 판정 비사용)' },
]

const PRESETS = [
  '회식비 한도는 어떻게 정해져 있나',
  '출장 숙박비는 어떤 증빙이 필요한가',
  '법인카드로 결제하면 안 되는 업종',
  '업무추진비 사전승인 절차',
  '주말·공휴일 사용 시 필요한 소명',
]

export function RagSearchLab() {
  const [query, setQuery] = useState(PRESETS[0])
  const [collection, setCollection] = useState('policy_docs')
  const [topK, setTopK] = useState(5)
  const [expandParent, setExpandParent] = useState(true)
  const [useQueryPrefix, setUseQueryPrefix] = useState(true)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')
  const [res, setRes] = useState<RagSearchResponse | null>(null)

  const run = async () => {
    if (!query.trim()) {
      setError('질의를 입력하세요.')
      return
    }
    setRunning(true)
    setError('')
    try {
      setRes(await labApi.ragSearch({ query, collection, topK, expandParent, useQueryPrefix }))
    } catch (err) {
      setError(labErrorMessage(err))
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="stack-lg">
      <div className="card">
        <div className="card-head"><h3>검색 실행</h3></div>
        <div className="card-body">
          <div className="field">
            <label>질의</label>
            <textarea
              rows={2}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) run()
              }}
              placeholder="회계 담당자가 실제로 물어볼 법한 문장으로 (Ctrl+Enter 실행)"
            />
          </div>
          <div className="lab-chips">
            {PRESETS.map((p) => (
              <button key={p} className="lab-chip" onClick={() => setQuery(p)}>
                <Search size={10} /> {p}
              </button>
            ))}
          </div>
          <div className="lab-controls">
            <div className="field" style={{ marginBottom: 0, minWidth: 240 }}>
              <label>컬렉션</label>
              <select value={collection} onChange={(e) => setCollection(e.target.value)}>
                {COLLECTIONS.map((c) => (
                  <option key={c.name} value={c.name}>{c.label}</option>
                ))}
              </select>
            </div>
            <div className="field" style={{ marginBottom: 0, width: 110 }}>
              <label>top-K</label>
              <input type="number" min={1} max={50} value={topK} onChange={(e) => setTopK(Number(e.target.value))} />
            </div>
            <label className="lab-check">
              <input type="checkbox" checked={expandParent} onChange={(e) => setExpandParent(e.target.checked)} />
              부모(조 전문) 확장
            </label>
            <label className="lab-check">
              <input type="checkbox" checked={useQueryPrefix} onChange={(e) => setUseQueryPrefix(e.target.checked)} />
              질의 접두(Q_ctx) 사용
            </label>
          </div>
        </div>
        <div className="lab-runbar">
          <button className="btn primary" onClick={run} disabled={running}>
            <Play size={13} /> {running ? '검색 중…' : '검색'}
          </button>
          <span className="text-meta">
            검색은 잎 청크만 대상으로 합니다(부모 청크는 조 전문이라 무엇과도 어중간하게 닮습니다).
          </span>
        </div>
      </div>

      {error && <ErrorBanner message={error} />}
      {!res && !error && <EmptyHint>질의를 넣고 검색하면 조문 단위 히트가 점수·인용과 함께 나열됩니다.</EmptyHint>}

      {res && (
        <>
          <div className="card">
            <div className="card-head">
              <h3>검색 결과 {res.hits.length}건</h3>
              {!res.judgementCollection && (
                <span className="tag warn">판정 근거로 인용 금지 컬렉션</span>
              )}
            </div>
            <div className="card-body">
              <FactRow
                items={[
                  ['컬렉션', res.collection],
                  ['임베딩 신원', <code key="v">{res.embedderVersion}</code>],
                  ['질의 접두', res.queryPrefix ? <code key="p">{res.queryPrefix}</code> : '(없음)'],
                  ['지연', `${res.latencyMs}ms`],
                ]}
              />
              {res.hits.length === 0 && (
                <div className="note" style={{ marginTop: 12 }}>
                  히트 0건입니다 — 해당 컬렉션이 비어 있을 수 있습니다(상태 탭의 적재 현황 확인).
                </div>
              )}
            </div>
          </div>

          {res.hits.map((hit, i) => <HitCard key={hit.chunk_id} hit={hit} rank={i + 1} />)}

          <div className="card">
            <div className="card-head"><h3>전체 응답</h3></div>
            <div className="card-body">
              <JsonBlock value={res} label="POST /api/ai-lab/rag/search" maxHeight={420} />
            </div>
          </div>
        </>
      )}
    </div>
  )
}

function HitCard({ hit, rank }: { hit: RagHit; rank: number }) {
  const meta = hit.metadata ?? {}
  const pct = Math.max(0, Math.min(100, Math.round(hit.score * 100)))
  return (
    <div className="card">
      <div className="card-head">
        <h3>
          <span className="lab-rank">#{rank}</span> {hit.citation || hit.chunk_id}
        </h3>
        <div className="row" style={{ gap: 8 }}>
          <div className="lab-meter" style={{ width: 120 }}><span style={{ width: `${pct}%` }} /></div>
          <span className="text-meta">유사도 {hit.score.toFixed(4)}</span>
        </div>
      </div>
      <div className="card-body">
        <div className="lab-chips" style={{ marginBottom: 10 }}>
          {['doc_name', 'chunk_role', 'chunk_type', 'chapter_title', 'article_label', 'article_title'].map((k) =>
            meta[k] ? <span key={k} className="tag">{String(meta[k])}</span> : null,
          )}
        </div>
        <TextBlock text={hit.document} label="청크 본문 (저장된 문서)" maxHeight={260} />
        <div className="stack" style={{ marginTop: 10 }}>
          {hit.parent_document && (
            <Collapsible title="부모 확장 (조 전문)" meta={`${hit.parent_document.length}자`}>
              <TextBlock text={hit.parent_document} label="parent" maxHeight={300} />
            </Collapsible>
          )}
          <Collapsible title="메타데이터">
            <JsonBlock value={meta} label="metadata" maxHeight={260} />
          </Collapsible>
        </div>
      </div>
    </div>
  )
}

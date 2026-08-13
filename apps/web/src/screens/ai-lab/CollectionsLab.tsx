// ④ 적재 현황 — 검색이 이상할 때 "무엇이 들어가 있는지"부터 본다.
//  컬렉션별 건수·임베딩 신원(혼입 여부)과, 실제 적재된 청크 원본을 그대로 열어 확인한다.
import { useEffect, useState } from 'react'
import { RotateCw, Search } from 'lucide-react'
import { labApi, labErrorMessage, type CollectionStat, type RagSampleResponse } from './data/labApi'
import { Collapsible, EmptyHint, ErrorBanner, JsonBlock, TextBlock } from './components/LabPrimitives'

const NAMES = ['policy_docs', 'tax_refs', 'case_history', 'org_docs']

export function CollectionsLab() {
  const [rows, setRows] = useState<CollectionStat[] | null>(null)
  const [listError, setListError] = useState('')
  const [loading, setLoading] = useState(false)

  const [collection, setCollection] = useState('policy_docs')
  const [limit, setLimit] = useState(10)
  const [docName, setDocName] = useState('')
  const [sample, setSample] = useState<RagSampleResponse | null>(null)
  const [sampleError, setSampleError] = useState('')
  const [sampling, setSampling] = useState(false)

  const load = async () => {
    setLoading(true)
    setListError('')
    try {
      setRows((await labApi.ragCollections()).collections)
    } catch (err) {
      setListError(labErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const runSample = async () => {
    setSampling(true)
    setSampleError('')
    try {
      setSample(await labApi.ragSample(collection, limit, docName.trim() || undefined))
    } catch (err) {
      setSampleError(labErrorMessage(err))
    } finally {
      setSampling(false)
    }
  }

  return (
    <div className="stack-lg">
      <div className="card">
        <div className="card-head">
          <h3>컬렉션</h3>
          <button className="btn sm" onClick={load} disabled={loading}>
            <RotateCw size={11} /> {loading ? '조회 중…' : '새로고침'}
          </button>
        </div>
        <div className="card-body" style={{ padding: 0 }}>
          {listError ? (
            <div style={{ padding: 16 }}><ErrorBanner message={listError} /></div>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>이름</th>
                  <th className="num">청크</th>
                  <th>판정 인용</th>
                  <th>임베딩 신원</th>
                </tr>
              </thead>
              <tbody>
                {(rows ?? []).map((c) => (
                  <tr key={c.name} style={{ cursor: 'default' }}>
                    <td style={{ fontWeight: 600 }}>{c.name}</td>
                    <td className="num">{c.count.toLocaleString()}</td>
                    <td>
                      {c.judgement
                        ? <span className="tag ok">사용</span>
                        : <span className="tag">비사용</span>}
                    </td>
                    <td className="text-meta" style={{ wordBreak: 'break-all' }}>
                      {c.error ?? (Object.keys(c.embedderVersions).length === 0
                        ? '비어 있음'
                        : Object.entries(c.embedderVersions).map(([v, n]) => `${v} (${n})`).join(', '))}
                      {c.mixedEmbedder && <span className="tag warn" style={{ marginLeft: 6 }}>모델 혼입</span>}
                    </td>
                  </tr>
                ))}
                {rows?.length === 0 && (
                  <tr><td colSpan={4} className="text-meta" style={{ textAlign: 'center', padding: 24 }}>컬렉션이 없습니다.</td></tr>
                )}
              </tbody>
            </table>
          )}
        </div>
      </div>

      <div className="card">
        <div className="card-head"><h3>적재된 청크 열람</h3></div>
        <div className="card-body">
          <div className="lab-controls">
            <div className="field" style={{ marginBottom: 0, minWidth: 200 }}>
              <label>컬렉션</label>
              <select value={collection} onChange={(e) => setCollection(e.target.value)}>
                {NAMES.map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            </div>
            <div className="field" style={{ marginBottom: 0, width: 110 }}>
              <label>건수</label>
              <input type="number" min={1} max={50} value={limit} onChange={(e) => setLimit(Number(e.target.value))} />
            </div>
            <div className="field" style={{ marginBottom: 0, flex: 1, minWidth: 220 }}>
              <label>문서명 필터 (doc_name, 정확히 일치)</label>
              <input
                value={docName}
                onChange={(e) => setDocName(e.target.value)}
                placeholder="비우면 전체 · 예: 법인카드_사용규정"
              />
            </div>
          </div>
        </div>
        <div className="lab-runbar">
          <button className="btn primary" onClick={runSample} disabled={sampling}>
            <Search size={13} /> {sampling ? '조회 중…' : '조회'}
          </button>
          <span className="text-meta">검색 순위가 아니라 적재 순서 그대로입니다(무엇이 들어갔는지 확인용).</span>
        </div>
      </div>

      {sampleError && <ErrorBanner message={sampleError} />}
      {!sample && !sampleError && <EmptyHint>컬렉션을 골라 조회하면 적재된 청크 원본이 그대로 나옵니다.</EmptyHint>}

      {sample && (
        <div className="card">
          <div className="card-head">
            <h3>{sample.collection} — {sample.count}건</h3>
          </div>
          <div className="card-body stack">
            {sample.items.length === 0 && (
              <div className="note">조건에 맞는 청크가 없습니다 — 문서명 필터를 비우거나 철자를 확인하세요.</div>
            )}
            {sample.items.map((item) => (
              <Collapsible
                key={item.chunkId}
                title={String(item.metadata?.citation ?? item.chunkId)}
                meta={`${String(item.metadata?.chunk_role ?? '')} · ${item.document.length}자`}
              >
                <TextBlock text={item.document} label={item.chunkId} maxHeight={260} />
                <div style={{ marginTop: 8 }}>
                  <JsonBlock value={item.metadata} label="metadata" maxHeight={220} />
                </div>
              </Collapsible>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

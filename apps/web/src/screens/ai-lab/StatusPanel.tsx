// AI-LAB 상태 — "지금 무엇이 준비되어 있는지"를 실행 전에 먼저 본다.
//  실험이 실패했을 때 원인이 코드인지 환경(키·적재·연결)인지 구분하는 게 이 화면의 목적이다.
import { RotateCw } from 'lucide-react'
import type { LabStatus } from './data/labApi'
import { EmptyHint, ErrorBanner, FactRow, JsonBlock, StatusDot } from './components/LabPrimitives'

interface Props {
  status: LabStatus | null
  error: string
  loading: boolean
  onReload: () => void
}

/** 화면 상단 고정 스트립 — 어느 탭에 있든 환경 상태가 보이게. */
export function StatusStrip({ status, error, loading, onReload }: Props) {
  return (
    <div className="lab-strip">
      {status ? (
        <>
          <StatusDot
            ok={status.openai.configured}
            label={`OpenAI ${status.openai.configured ? '연결' : '키 없음'}`}
            hint={status.openai.embedderVersion}
          />
          <StatusDot
            ok={status.chroma.reachable}
            label={`Chroma ${status.chroma.reachable ? '연결' : '미연결'}`}
            hint={status.chroma.endpoint}
          />
          <StatusDot ok={status.core.reachable} label="Core(Django)" hint={status.core.baseUrl} />
          <StatusDot
            ok={status.anomalyModel.fitted}
            label={`이상탐지 모델 ${status.anomalyModel.fitted ? '학습됨' : '미학습'}`}
          />
          <span className="text-meta" style={{ marginLeft: 'auto' }}>
            Draft {status.openai.draftModel} · 임베딩 {status.openai.embeddingModel}@{status.openai.dimensions}
          </span>
        </>
      ) : (
        <span className="text-meta">{loading ? '환경 상태를 확인하는 중…' : error || '상태 미확인'}</span>
      )}
      <button className="btn sm" onClick={onReload} disabled={loading} style={{ marginLeft: status ? 8 : 'auto' }}>
        <RotateCw size={11} /> 새로고침
      </button>
    </div>
  )
}

export function StatusPanel({ status, error, loading, onReload }: Props) {
  if (error && !status) return <ErrorBanner message={error} />
  if (!status) return <EmptyHint>{loading ? '상태를 불러오는 중입니다…' : '상태를 불러오지 못했습니다.'}</EmptyHint>

  const totalChunks = status.chroma.collections.reduce((sum, c) => sum + c.count, 0)

  return (
    <div className="stack-lg">
      <div className="grid-2">
        <div className="card">
          <div className="card-head">
            <h3>실행 환경</h3>
            <span className="text-meta">응답 {status.latencyMs}ms</span>
          </div>
          <div className="card-body">
            <FactRow
              items={[
                ['Draft 모델', status.openai.draftModel],
                ['임베딩 모델', `${status.openai.embeddingModel} @ ${status.openai.dimensions}차원`],
                ['질의 접두(Q_ctx)', <code key="p">{status.openai.queryPrefix || '(없음)'}</code>],
                ['임베딩 신원', <code key="v">{status.openai.embedderVersion}</code>],
                ['Chroma', status.chroma.endpoint],
                ['Core(Django)', status.core.baseUrl],
              ]}
            />
            {!status.openai.configured && (
              <div className="note" style={{ marginTop: 12 }}>
                OPENAI_API_KEY가 비어 있습니다 — Draft Agent는 폴백 초안으로만 응답하고, RAG 검색·임베딩은
                실행되지 않습니다. 레포 루트 <code>.env</code>에 키를 넣고 <code>ai</code> 컨테이너를 재기동하세요.
              </div>
            )}
            {status.core.error && (
              <div className="note" style={{ marginTop: 12 }}>Core 연결 오류: {status.core.error}</div>
            )}
          </div>
        </div>

        <div className="card">
          <div className="card-head">
            <h3>벡터 적재 현황</h3>
            <span className="text-meta">합계 {totalChunks.toLocaleString()}청크</span>
          </div>
          <div className="card-body" style={{ padding: 0 }}>
            <table className="table">
              <thead>
                <tr>
                  <th>컬렉션</th>
                  <th className="num">청크</th>
                  <th>임베딩 신원</th>
                </tr>
              </thead>
              <tbody>
                {status.chroma.collections.map((c) => (
                  <tr key={c.name} style={{ cursor: 'default' }}>
                    <td style={{ fontWeight: 600 }}>{c.name}</td>
                    <td className="num">{c.count.toLocaleString()}</td>
                    <td className="text-meta" style={{ wordBreak: 'break-all' }}>
                      {c.error
                        ? c.error
                        : Object.keys(c.embedderVersions).length === 0
                          ? '비어 있음'
                          : Object.entries(c.embedderVersions)
                              .map(([v, n]) => `${v} (${n})`)
                              .join(', ')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {totalChunks === 0 && (
              <div className="note" style={{ margin: 16 }}>
                적재된 청크가 없습니다 — RAG 검색은 빈 결과를 냅니다. 관리자 배치로 먼저 인덱싱하세요:
                <br />
                <code>docker compose exec ai python -m app.rag.embedding.index --dump ../../docling_eval/output</code>
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <h3>원본 응답</h3>
          <button className="btn sm" onClick={onReload} disabled={loading}>
            <RotateCw size={11} /> 다시 조회
          </button>
        </div>
        <div className="card-body">
          <JsonBlock value={status} label="GET /api/ai-lab/status" maxHeight={360} />
        </div>
      </div>
    </div>
  )
}

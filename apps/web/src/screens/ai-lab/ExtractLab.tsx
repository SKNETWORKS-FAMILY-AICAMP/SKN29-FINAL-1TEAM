// 증빙자료 추출 Agent 실험실 — 운영과 같은 `app.vision.read_receipt`/`read_evidence_document`를
// 그대로 부른다. ai 컨테이너는 media 볼륨을 읽기전용으로 마운트하므로(compose) 여기서 새
// 파일을 올릴 수 없다 — `fileRef`는 이미 어딘가에 업로드된 파일의 경로여야 한다(정산 상세에서
// 첨부한 파일의 저장 경로 등). RAG 검색 탭의 "Chroma 적재가 선행돼야 한다"와 같은 제약이다.
import { useState } from 'react'
import { Play } from 'lucide-react'
import { labApi, labErrorMessage, type ExtractRunLabResponse } from './data/labApi'
import { Collapsible, ErrorBanner, FactRow, JsonBlock, TabNote } from './components/LabPrimitives'

const KINDS = [
  { value: 'RECEIPT', label: '영수증·카드전표' },
  { value: 'PRE_APPROVAL', label: '사전승인 문서(결재)' },
  { value: 'MEETING_MINUTES', label: '회의록' },
  { value: 'PARTICIPANT_LIST', label: '참석자 명단' },
  { value: 'TRIP_PLAN', label: '출장계획서' },
]

export function ExtractLab() {
  const [fileRef, setFileRef] = useState('')
  const [kind, setKind] = useState('PRE_APPROVAL')
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')
  const [res, setRes] = useState<ExtractRunLabResponse | null>(null)

  const run = async () => {
    if (!fileRef.trim()) { setError('파일 경로(fileRef)를 입력하세요.'); return }
    setRunning(true)
    setError('')
    try {
      setRes(await labApi.runExtract(fileRef.trim(), kind))
    } catch (err) {
      setError(labErrorMessage(err))
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="stack-lg">
      <TabNote>
        여기서 새 파일을 올릴 수 없습니다 — ai 컨테이너는 media 볼륨을 <b>읽기전용</b>으로 마운트합니다.
        정산 상세 화면에서 이미 첨부를 올렸다면 그 파일의 저장 경로(예: <code>attachments/202608/xxx.png</code>)를
        여기에 입력하세요.
      </TabNote>

      <div className="card">
        <div className="card-head"><h3>판독 입력</h3></div>
        <div className="card-body">
          <div className="lab-controls">
            <div className="field" style={{ marginBottom: 0, minWidth: 200 }}>
              <label>문서 종류(kind)</label>
              <select value={kind} onChange={(e) => setKind(e.target.value)}>
                {KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
              </select>
            </div>
          </div>
          <div className="field" style={{ marginBottom: 0 }}>
            <label>파일 경로(fileRef)</label>
            <input
              value={fileRef}
              onChange={(e) => setFileRef(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') void run() }}
              placeholder="attachments/202608/xxxxxxxx.png"
            />
          </div>
        </div>
        <div className="lab-runbar">
          <button className="btn primary" onClick={run} disabled={running}>
            <Play size={13} /> {running ? '판독 중…' : '판독 실행'}
          </button>
        </div>
      </div>

      {error && <ErrorBanner message={error} />}

      {res && (
        <>
          <div className="card">
            <div className="card-head">
              <h3>판독 결과</h3>
              <span className={'tag' + (res.result.extraction_status === 'DONE' ? ' ok' : ' warn')}>
                {res.result.extraction_status}
              </span>
            </div>
            <div className="card-body">
              <FactRow
                items={[
                  ['종류', res.kind],
                  ['추출기 버전', res.result.extractor_version || '—'],
                  ['지연', `${res.latencyMs}ms`],
                  ...(res.result.merchant !== undefined
                    ? [['가맹점', res.result.merchant || '—'] as [string, string]] : []),
                ]}
              />
              {Object.keys(res.result.extracted).length === 0 ? (
                <div className="text-meta" style={{ marginTop: 10 }}>
                  뽑힌 판정 사실이 없습니다 — 문서에 해당 종류의 항목이 없거나 확인하지 못했습니다(관측 계약: 넣지 않는 것이 기본값).
                </div>
              ) : (
                <>
                  <div className="lab-subhead">뽑힌 판정 사실(extracted)</div>
                  <ul className="lab-list">
                    {Object.entries(res.result.extracted).map(([path, value]) => (
                      <li key={path}>
                        <code>{path}</code> = {JSON.stringify(value)}
                        {res.result.field_confidence[path] != null &&
                          ` · 확신도 ${Math.round(res.result.field_confidence[path] * 100)}%`}
                      </li>
                    ))}
                  </ul>
                </>
              )}
              {!!res.result.warnings?.length && (
                <div className="note" style={{ marginTop: 12 }}>
                  {res.result.warnings.join(' / ')}
                </div>
              )}
              {!!res.result.evidence_spans?.length && (
                <div style={{ marginTop: 12 }}>
                  <Collapsible title="근거 인용(evidence_spans)" meta={`${res.result.evidence_spans.length}건`} defaultOpen>
                    <JsonBlock value={res.result.evidence_spans} label="evidence_spans" maxHeight={220} />
                  </Collapsible>
                </div>
              )}
            </div>
          </div>
          <div className="card">
            <div className="card-head"><h3>전체 응답</h3></div>
            <div className="card-body">
              <JsonBlock value={res} label="POST /api/ai-lab/extract/run" maxHeight={420} />
            </div>
          </div>
        </>
      )}
    </div>
  )
}

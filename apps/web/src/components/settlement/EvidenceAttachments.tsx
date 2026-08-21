// 증빙 첨부 + 판독 결과 — S-01 지출 증빙 화면(상세 모달 좌측).
//
// **업로드가 곧 판독 트리거**다. 별도 "분석" 버튼을 두지 않는다 — 아무도 누르지 않고,
// 추출 결과 없이 제출되면 판정이 그 사실을 `null`(모름)로 보고 검토로 강등한다.
//
// 판독은 서버에서 비동기로 돈다(수십 초). 그래서 업로드 직후 상태는 대개 `PENDING`이고,
// 여기서 목록을 폴링해 결과가 도착하는 걸 지켜본다(규정 문서 적재 화면과 같은 방식).
//
// 결과는 **dot-path 그대로** 보여준다. 요약해 버리면 "판정이 무엇을 읽었는가"를 사람이
// 대조할 수 없다 — 그게 이 화면의 존재 이유다.
import { useCallback, useEffect, useRef, useState } from 'react'
import { AlertTriangle, Check, FileText, Loader2, Paperclip, RefreshCw, X } from 'lucide-react'
import {
  ATTACHMENT_KINDS, FACT_LABEL, IN_PROGRESS, deleteAttachment, fetchAttachments,
  formatFactValue, reextractAttachment, uploadAttachment,
  type Attachment, type AttachmentKind,
} from '../../api/attachmentService'

const POLL_MS = 3000
const ACCEPT = '.pdf,.png,.jpg,.jpeg,.webp,.heic'

export function EvidenceAttachments({
  settlementId,
  readOnly = false,
  onFactsExtracted,
}: {
  /** null이면 아직 저장 전(신규 등록) — 붙일 대상이 없다. */
  settlementId: string | null
  readOnly?: boolean
  /** 판독이 끝났을 때 상위(모달)에 알린다 — AI 코멘트 등에 쓴다. */
  onFactsExtracted?: (attachment: Attachment) => void
}) {
  const [items, setItems] = useState<Attachment[]>([])
  const [kind, setKind] = useState<AttachmentKind>('RECEIPT')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)
  const notified = useRef<Set<number>>(new Set())

  const load = useCallback(async () => {
    if (!settlementId) return
    try {
      const rows = await fetchAttachments(settlementId)
      setItems(rows)
      rows.forEach((a) => {
        if (a.extractionStatus === 'DONE' && !notified.current.has(a.id)) {
          notified.current.add(a.id)
          onFactsExtracted?.(a)
        }
      })
    } catch {
      setError('첨부 목록을 불러오지 못했습니다.')
    }
  }, [settlementId, onFactsExtracted])

  useEffect(() => { void load() }, [load])

  // 판독 중인 첨부가 있는 동안만 폴링한다 — 끝났는데 계속 두드리면 서버만 두들긴다.
  useEffect(() => {
    if (!settlementId) return
    if (!items.some((a) => IN_PROGRESS.includes(a.extractionStatus))) return
    const t = setInterval(() => { void load() }, POLL_MS)
    return () => clearInterval(t)
  }, [items, settlementId, load])

  const pick = async (file: File | undefined) => {
    if (!file || !settlementId) return
    setBusy(true)
    setError('')
    try {
      const created = await uploadAttachment(settlementId, file, kind)
      setItems((prev) => [...prev, created])
    } catch (e: unknown) {
      // 서버가 사유를 준다(형식·용량). 삼키면 사용자는 "올라갔나?"만 남는다.
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail ?? '업로드에 실패했습니다.')
    } finally {
      setBusy(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const remove = async (id: number) => {
    if (!settlementId) return
    await deleteAttachment(settlementId, id)
    setItems((prev) => prev.filter((a) => a.id !== id))
  }

  const retry = async (id: number) => {
    if (!settlementId) return
    const updated = await reextractAttachment(settlementId, id)
    setItems((prev) => prev.map((a) => (a.id === id ? updated : a)))
  }

  const selected = ATTACHMENT_KINDS.find((k) => k.value === kind)

  return (
    <div className="card">
      <div className="card-head">
        <h3>증빙 자료</h3>
        <span className="text-meta">업로드하면 자동 판독</span>
      </div>
      <div className="card-body">
        {!settlementId ? (
          <div className="text-meta">저장 후 증빙을 첨부할 수 있습니다.</div>
        ) : (
          <>
            {!readOnly && (
              <>
                <div className="field" style={{ marginBottom: 8 }}>
                  <label>문서 종류</label>
                  <select value={kind} onChange={(e) => setKind(e.target.value as AttachmentKind)}>
                    {ATTACHMENT_KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
                  </select>
                  {/* 종류가 "무엇을 뽑을지"를 정한다 — 고르기 전에 알려준다. */}
                  {selected && <div className="text-meta" style={{ marginTop: 4 }}>판독 항목: {selected.extracts}</div>}
                </div>
                <input
                  ref={fileRef}
                  type="file"
                  accept={ACCEPT}
                  style={{ display: 'none' }}
                  onChange={(e) => void pick(e.target.files?.[0])}
                />
                <button
                  className="btn primary"
                  style={{ width: '100%', justifyContent: 'center' }}
                  onClick={() => fileRef.current?.click()}
                  disabled={busy}
                >
                  {busy ? <><Loader2 size={14} className="spin" /> 업로드 중…</> : <><Paperclip size={14} /> 파일 선택 (PDF·이미지)</>}
                </button>
              </>
            )}

            {error && (
              <div className="note" style={{ background: 'var(--tone-red-bg)', border: '1px solid #e8c0c0', marginTop: 10 }}>
                {error}
              </div>
            )}

            {items.length > 0 ? (
              <div className="stack" style={{ marginTop: 12 }}>
                {items.map((a) => (
                  <AttachmentRow
                    key={a.id}
                    item={a}
                    readOnly={readOnly}
                    onRemove={() => void remove(a.id)}
                    onRetry={() => void retry(a.id)}
                  />
                ))}
              </div>
            ) : (
              <div className="text-meta" style={{ marginTop: 12 }}>첨부된 증빙이 없습니다.</div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

function AttachmentRow({
  item, readOnly, onRemove, onRetry,
}: { item: Attachment; readOnly: boolean; onRemove: () => void; onRetry: () => void }) {
  const facts = Object.entries(item.extracted ?? {})
  const running = IN_PROGRESS.includes(item.extractionStatus)

  return (
    <div style={{ background: 'var(--surface-2)', borderRadius: 'var(--radius-control)', padding: '10px 12px' }}>
      <div className="row" style={{ justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div className="row" style={{ gap: 8, alignItems: 'flex-start' }}>
          <FileText size={16} color="var(--tone-red)" style={{ flexShrink: 0, marginTop: 2 }} />
          <div>
            <div style={{ fontSize: 12.5, fontWeight: 600 }}>{item.originalName}</div>
            <div className="text-meta">{item.kindLabel}</div>
          </div>
        </div>
        <div className="row" style={{ gap: 6 }}>
          <StatusTag item={item} />
          {!readOnly && item.extractionStatus === 'FAILED' && (
            <button className="btn sm" onClick={onRetry} title="판독 재시도"><RefreshCw size={12} /></button>
          )}
          {!readOnly && (
            <button className="x-btn" style={{ width: 24, height: 24 }} aria-label="삭제" onClick={onRemove}>
              <X size={13} />
            </button>
          )}
        </div>
      </div>

      {running && <div className="text-meta" style={{ marginTop: 8 }}>문서를 읽는 중입니다… (수십 초 걸릴 수 있습니다)</div>}

      {/* 판독 결과 — 경로를 감추지 않는다. 이 경로가 곧 판정이 읽는 자리다. */}
      {facts.length > 0 && (
        <table className="table" style={{ marginTop: 10 }}>
          <tbody>
            {facts.map(([path, value]) => {
              const conf = item.fieldConfidence?.[path]
              return (
                <tr key={path}>
                  <td style={{ padding: '4px 0' }}>
                    <div style={{ fontSize: 12.5 }}>{FACT_LABEL[path] ?? path}</div>
                    <div className="text-meta" style={{ fontFamily: 'monospace', fontSize: 11 }}>{path}</div>
                  </td>
                  <td className="num" style={{ padding: '4px 0' }}>
                    <b>{formatFactValue(value)}</b>
                    {/* 저신뢰 값은 사람이 확인해야 한다 — 숨기면 그대로 판정에 들어간다. */}
                    {typeof conf === 'number' && conf < 0.7 && (
                      <div className="text-meta" style={{ color: 'var(--tone-amber)' }}>확인 필요 ({Math.round(conf * 100)}%)</div>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}

      {item.extractionStatus === 'DONE' && facts.length === 0 && (
        <div className="text-meta" style={{ marginTop: 8 }}>판독했지만 이 문서에서 확인된 사실이 없습니다.</div>
      )}
      {item.extractionStatus === 'SKIPPED' && (
        <div className="text-meta" style={{ marginTop: 8 }}>이 종류는 자동 판독 대상이 아닙니다(보관만).</div>
      )}
      {item.error && item.extractionStatus === 'FAILED' && (
        <div className="text-meta" style={{ marginTop: 8, color: 'var(--tone-red)' }}>{item.error}</div>
      )}
    </div>
  )
}

function StatusTag({ item }: { item: Attachment }) {
  const s = item.extractionStatus
  if (s === 'DONE') return <span className="tag ok"><Check size={11} /> 판독 완료</span>
  if (s === 'FAILED') return <span className="tag caution"><AlertTriangle size={11} /> 판독 실패</span>
  if (s === 'SKIPPED') return <span className="tag">보관</span>
  return <span className="tag"><Loader2 size={11} className="spin" /> {item.extractionStatusLabel}</span>
}

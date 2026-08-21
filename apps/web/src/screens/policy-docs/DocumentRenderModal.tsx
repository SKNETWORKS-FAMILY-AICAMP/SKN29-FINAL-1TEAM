// S-05 ③ 문서 렌더링 (모달) — 원본 PDF를 페이지 단위로 넘겨보는 뷰어(시안 실측).
//
// 페이지 렌더링·섬네일·줌·페이지 이동은 pdfjs-dist로 프론트에서 직접 그린다(백엔드 변경 없음 —
// 지금 "원본 보기"가 쓰던 것과 같은 파일 URL, 세션 쿠키 인가).
//
// "조항 인식 영역 표시" 토글은 **의도적으로 비활성화**해 뒀다 — 조항이 페이지의 어느
// 사각형(x/y/폭/높이)에 있는지는 백엔드가 아직 저장하지 않는다(`PolicyClause`는
// pageStart/pageEnd까지만 안다). 좌표 없이 영역을 그리면 근거 없는 박스를 실제 표시인 것처럼
// 보여주게 된다 — 그 데이터가 생기면 여기에 연결한다.
import { useEffect, useMemo, useRef, useState } from 'react'
import { ChevronLeft, ChevronRight, Download, FileText, Minus, Plus, X } from 'lucide-react'
import type { PDFDocumentProxy, RenderTask } from 'pdfjs-dist'
import * as pdfjsLib from 'pdfjs-dist'
// Vite: 워커 파일을 정적 자산 URL로 번들링(별도 서버 설정 없이 동작).
import pdfjsWorker from 'pdfjs-dist/build/pdf.worker.mjs?url'
import { endpoints } from '../../api/client'
import { EMBEDDING_STATUS_META, type PolicyDocument } from '../../types/domain'

pdfjsLib.GlobalWorkerOptions.workerSrc = pdfjsWorker

const MIN_SCALE = 0.5
const MAX_SCALE = 2.5
const SCALE_STEP = 0.25

const fmtSize = (bytes: number) =>
  bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)}MB` : `${Math.max(1, Math.round(bytes / 1024))}KB`

function Thumb({ pdf, pageNum, active, onClick }: {
  pdf: PDFDocumentProxy; pageNum: number; active: boolean; onClick: () => void
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    let cancelled = false
    let task: RenderTask | null = null
    void pdf.getPage(pageNum).then((page) => {
      if (cancelled) return
      const viewport = page.getViewport({ scale: 1 })
      const scale = 78 / viewport.width
      const scaled = page.getViewport({ scale })
      const canvas = canvasRef.current
      if (!canvas) return
      canvas.width = scaled.width
      canvas.height = scaled.height
      const ctx = canvas.getContext('2d')
      if (!ctx) return
      task = page.render({ canvasContext: ctx, viewport: scaled, canvas })
      task.promise.then(() => { if (!cancelled) setReady(true) }).catch(() => {})
    })
    return () => { cancelled = true; task?.cancel() }
  }, [pdf, pageNum])

  return (
    <button type="button" className={'pdf-thumb' + (active ? ' active' : '')} onClick={onClick}>
      <canvas ref={canvasRef} style={{ opacity: ready ? 1 : 0 }} />
      <span>{pageNum}</span>
    </button>
  )
}

export function DocumentRenderModal({ doc, onClose, onViewClauses }: {
  doc: PolicyDocument
  onClose: () => void
  /** "조항별로 보기" — 조항 목록은 이미 이 화면 아래에 있으므로 모달만 닫는다. */
  onViewClauses: () => void
}) {
  const fileUrl = useMemo(() => endpoints.policyDocFileUrl(doc.id), [doc.id])
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null)
  const [error, setError] = useState('')
  const [page, setPage] = useState(1)
  const [scale, setScale] = useState(1)
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    let cancelled = false
    const task = pdfjsLib.getDocument({ url: fileUrl, withCredentials: true })
    task.promise.then((loaded) => { if (!cancelled) setPdf(loaded) })
      // StrictMode의 mount→cleanup→remount에서 첫 태스크는 의도적으로 destroy되며
      // "Worker was destroyed"로 reject된다 — cancelled 가드가 그 건은 조용히 흡수한다.
      .catch(() => { if (!cancelled) setError('PDF를 불러오지 못했습니다. 원본 파일이 없거나 형식을 지원하지 않습니다.') })
    return () => { cancelled = true; void task.destroy() }
  }, [fileUrl])

  useEffect(() => {
    if (!pdf) return
    let cancelled = false
    let renderTask: RenderTask | null = null
    void pdf.getPage(page).then((p) => {
      if (cancelled) return
      const viewport = p.getViewport({ scale })
      const canvas = canvasRef.current
      if (!canvas) return
      canvas.width = viewport.width
      canvas.height = viewport.height
      const ctx = canvas.getContext('2d')
      if (!ctx) return
      renderTask = p.render({ canvasContext: ctx, viewport, canvas })
      renderTask.promise.catch(() => {})
    })
    return () => { cancelled = true; renderTask?.cancel() }
  }, [pdf, page, scale])

  // Esc로 닫기 — 별도 포커스 트랩 없는 가벼운 모달(내부에 캔버스·스크롤 영역이 많아
  // 공용 Modal의 고정 헤더/바닥글 레이아웃과 맞지 않아 이 화면 전용으로 둔다).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const statusLabel = EMBEDDING_STATUS_META[doc.status]?.label ?? doc.statusLabel

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal pdf-viewer-modal" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <div className="pdf-viewer-head">
          <div className="row" style={{ gap: 10, minWidth: 0 }}>
            <span className="pd-badge red" style={{ flexShrink: 0 }}><FileText size={11} /> PDF</span>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontWeight: 700, fontSize: 14, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {doc.fileName || doc.title}
              </div>
              <div className="text-meta">
                전체 {pdf?.numPages ?? '–'}페이지 · {statusLabel}{doc.fileSize > 0 && <> · {fmtSize(doc.fileSize)}</>}
              </div>
            </div>
          </div>
          <div className="row" style={{ gap: 6, flexShrink: 0 }}>
            <a className="btn sm" href={endpoints.policyDocFileUrl(doc.id, true)} target="_blank" rel="noreferrer">
              <Download size={12} /> 원본 다운로드
            </a>
            <button className="x-btn" onClick={onClose} aria-label="닫기"><X size={18} /></button>
          </div>
        </div>

        <div className="pdf-viewer-toolbar">
          <div className="row" style={{ gap: 4 }}>
            <button className="btn sm" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={!pdf || page <= 1}>
              <ChevronLeft size={13} />
            </button>
            <span className="text-meta" style={{ minWidth: 56, textAlign: 'center' }}>{page} / {pdf?.numPages ?? '–'}</span>
            <button className="btn sm" onClick={() => setPage((p) => Math.min(pdf?.numPages ?? p, p + 1))} disabled={!pdf || page >= (pdf?.numPages ?? 1)}>
              <ChevronRight size={13} />
            </button>
          </div>
          <div className="row" style={{ gap: 16 }}>
            <div className="row" style={{ gap: 4 }}>
              <button className="btn sm" onClick={() => setScale((s) => Math.max(MIN_SCALE, +(s - SCALE_STEP).toFixed(2)))} disabled={scale <= MIN_SCALE}>
                <Minus size={12} />
              </button>
              <span className="text-meta" style={{ minWidth: 40, textAlign: 'center' }}>{Math.round(scale * 100)}%</span>
              <button className="btn sm" onClick={() => setScale((s) => Math.min(MAX_SCALE, +(s + SCALE_STEP).toFixed(2)))} disabled={scale >= MAX_SCALE}>
                <Plus size={12} />
              </button>
            </div>
            <label className="row" style={{ gap: 6, opacity: 0.5, cursor: 'not-allowed' }} title="조항별 위치 좌표가 아직 없어 비활성화되어 있습니다(백엔드 연동 예정)">
              <span className="text-meta">조항 인식 영역 표시</span>
              <input type="checkbox" checked={false} disabled readOnly />
            </label>
          </div>
        </div>

        <div className="pdf-viewer-body">
          <div className="pdf-thumbs">
            {pdf && Array.from({ length: pdf.numPages }, (_, i) => i + 1).map((n) => (
              <Thumb key={n} pdf={pdf} pageNum={n} active={n === page} onClick={() => setPage(n)} />
            ))}
          </div>
          <div className="pdf-page-wrap">
            {error && <div className="note" style={{ color: 'var(--tone-red)' }}>{error}</div>}
            {!error && !pdf && <div className="text-meta">문서를 불러오는 중…</div>}
            <canvas ref={canvasRef} className="pdf-page-canvas" />
          </div>
        </div>

        <div className="pdf-viewer-foot">
          <span className="text-meta">
            AI가 이 문서에서 {doc.clauseCount}개 조항을 추출했어요
            {doc.reviewCount > 0 && <> · 확인이 필요한 조항 <b style={{ color: 'var(--tone-amber)' }}>{doc.reviewCount}개</b></>}
          </span>
          <button className="btn sm" onClick={onViewClauses}>조항별로 보기 →</button>
        </div>
      </div>
    </div>
  )
}

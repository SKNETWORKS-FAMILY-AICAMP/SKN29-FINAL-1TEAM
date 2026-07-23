// 규정 문서 업로드 모달 (v4) — 업로드된 문서는 청킹·임베딩되어 Rule 초안 생성(RAG)에 활용됨을 보여준다.
import { useState } from 'react'
import { Check, FileText, Upload } from 'lucide-react'
import { Modal } from '../../components/ui/Modal'
import { POLICY_DOC_TYPES, POLICY_UPLOAD_PROGRESS } from './data/ruleConsoleMock'

const STAGES = [
  { key: 'upload', label: '업로드' },
  { key: 'chunking', label: '청킹' },
  { key: 'embedding', label: '임베딩 (Chroma 저장)' },
] as const

export function PolicyUploadModal({ onClose }: { onClose: () => void }) {
  const [docType, setDocType] = useState<(typeof POLICY_DOC_TYPES)[number]>(POLICY_DOC_TYPES[0])
  const stageIndex = STAGES.findIndex((s) => s.key === POLICY_UPLOAD_PROGRESS.stage)

  const footer = (
    <>
      <button className="btn" onClick={onClose}>취소</button>
      <button className="btn primary" onClick={onClose}>백그라운드에서 계속 처리</button>
    </>
  )

  return (
    <Modal title="규정 문서 업로드" onClose={onClose} footer={footer}>
      <p className="text-meta" style={{ marginBottom: 16 }}>업로드한 문서는 청킹·임베딩되어 Rule 초안 생성(RAG)에 활용됩니다</p>

      <div className="field">
        <label>문서 유형</label>
        <div className="row" style={{ gap: 8 }}>
          {POLICY_DOC_TYPES.map((t) => (
            <button
              key={t} type="button" className={'btn sm' + (t === docType ? ' primary' : '')}
              onClick={() => setDocType(t)}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      <div style={{ border: '1px dashed var(--border-strong)', borderRadius: 'var(--radius-control)', padding: 32, textAlign: 'center', color: 'var(--muted)', background: 'var(--surface-2)' }}>
        <Upload size={24} style={{ margin: '0 auto 8px' }} />
        <div style={{ fontSize: 12.5 }}>PDF, DOCX 파일을 드래그하거나 클릭하여 업로드하세요</div>
        <div className="text-meta" style={{ marginTop: 4 }}>파일당 최대 50MB · 여러 문서 동시 업로드 가능</div>
      </div>

      <button className="btn primary" style={{ width: '100%', justifyContent: 'center', marginTop: 16 }}>파일 선택</button>

      <div className="text-meta" style={{ margin: '16px 0 8px', fontWeight: 600 }}>처리 진행 단계</div>
      <div className="row" style={{ gap: 6 }}>
        {STAGES.map((s, i) => (
          <span key={s.key} className="row" style={{ gap: 6 }}>
            <span className="tag" style={i < stageIndex ? { background: 'var(--tone-green-bg)', color: 'var(--tone-green)', borderColor: 'transparent' } : i === stageIndex ? { background: 'var(--primary-soft)', color: 'var(--primary)', borderColor: 'transparent' } : undefined}>
              {i < stageIndex ? <Check size={11} /> : null} {s.label}
            </span>
            {i < STAGES.length - 1 && <span className="muted">→</span>}
          </span>
        ))}
      </div>

      <div className="text-meta" style={{ margin: '16px 0 8px', fontWeight: 600 }}>업로드된 파일 (1)</div>
      <div className="row" style={{ justifyContent: 'space-between', background: 'var(--surface-2)', borderRadius: 'var(--radius-control)', padding: '10px 12px' }}>
        <div className="row" style={{ gap: 10 }}>
          <FileText size={18} color="var(--tone-red)" />
          <div style={{ minWidth: 220 }}>
            <div style={{ fontSize: 12.5, fontWeight: 500 }}>{POLICY_UPLOAD_PROGRESS.fileName}</div>
            <div style={{ height: 4, background: 'var(--border)', borderRadius: 'var(--radius-pill)', overflow: 'hidden', margin: '4px 0' }}>
              <div style={{ width: `${POLICY_UPLOAD_PROGRESS.percent}%`, height: '100%', background: 'var(--primary)' }} />
            </div>
          </div>
        </div>
        <span className="text-meta">청킹 중 · {POLICY_UPLOAD_PROGRESS.percent}%</span>
      </div>

      <p className="text-meta" style={{ marginTop: 12 }}>※ 문서 전체가 처리되면 "규정 조항 추출 결과"가 Rule 초안 대기 목록에 자동으로 반영됩니다.</p>
    </Modal>
  )
}

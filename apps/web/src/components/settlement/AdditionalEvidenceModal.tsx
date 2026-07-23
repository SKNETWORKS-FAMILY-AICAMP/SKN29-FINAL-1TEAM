// F-1 증빙 파일 추가 제출 모달 — 보완요청(RETURNED) 건에 영수증 외 파일(계약서·이체확인증 등)을 추가 첨부.
import { useState } from 'react'
import { FileText, Image, Upload, X } from 'lucide-react'
import { Modal } from '../ui/Modal'

interface EvidenceFile {
  id: string
  name: string
  size: string
  type: 'pdf' | 'img'
}

const INITIAL_FILES: EvidenceFile[] = [
  { id: 'f1', name: '계약서_A사_2026.pdf', size: '1.2MB', type: 'pdf' },
  { id: 'f2', name: '이체확인증_0718.png', size: '340KB', type: 'img' },
]

export function AdditionalEvidenceModal({
  onClose,
  onSubmit,
}: {
  onClose: () => void
  onSubmit: () => void
}) {
  const [files, setFiles] = useState<EvidenceFile[]>(INITIAL_FILES)

  const addMockFile = () => {
    const n = files.length + 1
    setFiles((prev) => [...prev, { id: `f${Date.now()}`, name: `추가증빙_${n}.pdf`, size: '0.8MB', type: 'pdf' }])
  }
  const removeFile = (id: string) => setFiles((prev) => prev.filter((f) => f.id !== id))

  const footer = (
    <>
      <button className="btn" onClick={onClose}>취소</button>
      <button className="btn primary" onClick={onSubmit}>추가 완료</button>
    </>
  )

  return (
    <Modal title="증빙 파일 추가 제출" onClose={onClose} footer={footer}>
      <div className="text-meta" style={{ marginBottom: 16 }}>영수증 외 계약서·이체확인증 등 파일을 추가로 첨부합니다</div>

      <div
        style={{
          background: 'var(--surface-2)', border: '1px dashed var(--border-strong)', borderRadius: 'var(--radius-control)',
          padding: '32px', textAlign: 'center', color: 'var(--muted)',
        }}
      >
        <Upload size={24} style={{ margin: '0 auto 8px' }} />
        <div style={{ fontSize: 12.5 }}>파일을 드래그하거나 클릭하여 업로드하세요</div>
        <div className="text-meta" style={{ marginTop: 4 }}>PDF, JPG, PNG, DOCX, XLSX · 파일당 최대 20MB</div>
      </div>

      <button className="btn primary" style={{ width: '100%', justifyContent: 'center', marginTop: 16 }} onClick={addMockFile}>
        파일 선택
      </button>

      <div className="text-meta" style={{ margin: '16px 0 8px', fontWeight: 600 }}>첨부된 파일 ({files.length})</div>
      <div className="stack">
        {files.map((f) => (
          <div key={f.id} className="row" style={{ justifyContent: 'space-between', background: 'var(--surface-2)', borderRadius: 'var(--radius-control)', padding: '10px 12px' }}>
            <div className="row" style={{ gap: 10 }}>
              {f.type === 'pdf' ? <FileText size={18} color="var(--tone-red)" /> : <Image size={18} color="var(--tone-purple)" />}
              <div>
                <div style={{ fontSize: 12.5, fontWeight: 500 }}>{f.name}</div>
                <div className="text-meta">{f.size}</div>
              </div>
            </div>
            <button className="x-btn" style={{ width: 28, height: 28 }} aria-label="삭제" onClick={() => removeFile(f.id)}>
              <X size={14} />
            </button>
          </div>
        ))}
      </div>

      <div className="text-meta" style={{ marginTop: 12 }}>
        ※ 추가 제출한 파일은 기존 영수증 증빙과 함께 정산 건에 첨부되며, 회계 담당자 검토 시 함께 노출됩니다.
      </div>
    </Modal>
  )
}

// 규정 문서 업로드 모달 (목업 `S-04 v4 규정 문서 업로드`).
//
// 목업 대비 바꾼 것:
//  · **문서 유형 = 실제 백엔드 분류**(`PolicyDoc.profile`). 목업의 '법인카드 사용규정/세법
//    시행령/사내 문서/기타'는 화면에만 있던 문자열이라 백엔드에 대응물이 없었다. 이 값은
//    Chroma 컬렉션 라우팅을 정하므로 "판정에 인용되는가"가 여기서 갈린다.
//  · **폴더 위치 선택** 추가 — 업로드 후 따로 옮길 필요가 없게.
//  · 안내 문구 축소 — 목업의 진행 단계(업로드→청킹→임베딩) 표시는 **여기서 알 수 없다**.
//    업로드 응답은 접수(PENDING)까지고 그 뒤는 백그라운드라, 진행률을 아는 척하면 거짓이 된다.
//    실제 상태는 목록의 상태 배지가 폴링으로 보여준다.
import { useMemo, useRef, useState } from 'react'
import { AlertTriangle, FileText, X } from 'lucide-react'
import { Modal } from '../../components/ui/Modal'
import {
  DOC_PROFILE_LABEL, type DocProfile, type PolicyFolder,
} from '../../types/domain'
import { useCategories } from '../../lib/categories'

const MAX_MB = 50
// scope(GLOBAL ∪ settlements.Category)는 서버 정본을 받아 쓴다 — `useCategories().ruleScopes`.
// 비우면 적재 후 룰 자동 생성을 건너뛴다(SKIPPED_NO_SCOPE).

export type UploadInput = {
  file: File
  title: string
  profileHint: DocProfile | ''
  ruleScope: string
  folderId: number | null
}

/** 트리를 "상위/하위" 한 줄짜리 선택지로 편다 — 폴더가 깊지 않아 select로 충분하다. */
function flatten(folders: PolicyFolder[], depth = 0): { id: number; label: string }[] {
  return folders.flatMap((f) => [
    { id: f.id, label: `${' '.repeat(depth * 3)}${depth ? '└ ' : ''}${f.name}` },
    ...flatten(f.children, depth + 1),
  ])
}

export function UploadModal({ folders, defaultFolderId, busy, onClose, onSubmit }: {
  folders: PolicyFolder[]
  defaultFolderId: number | null
  busy: boolean
  onClose: () => void
  onSubmit: (input: UploadInput) => void
}) {
  const [file, setFile] = useState<File | null>(null)
  const [title, setTitle] = useState('')
  const [profileHint, setProfileHint] = useState<DocProfile | ''>('')
  const [ruleScope, setRuleScope] = useState('')
  const [folderId, setFolderId] = useState<number | null>(defaultFolderId)
  const [dragOver, setDragOver] = useState(false)
  const [error, setError] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  const { ruleScopes } = useCategories()

  const options = useMemo(() => flatten(folders), [folders])

  const accept = (picked: File | undefined | null) => {
    if (!picked) return
    if (!picked.name.toLowerCase().endsWith('.pdf')) {
      // 파싱 파이프라인이 PDF 전용이라 여기서 막는다 — 받아두면 백그라운드에서 조용히 실패한다.
      setError(`PDF만 업로드할 수 있습니다: ${picked.name}`)
      return
    }
    if (picked.size > MAX_MB * 1024 * 1024) {
      setError(`파일이 너무 큽니다(${(picked.size / 1024 / 1024).toFixed(1)}MB) — 최대 ${MAX_MB}MB`)
      return
    }
    setError('')
    setFile(picked)
    if (!title.trim()) setTitle(picked.name.replace(/\.[^.]+$/, ''))
  }

  const submit = () => {
    if (!file || busy) return
    onSubmit({ file, title: title.trim() || file.name, profileHint, ruleScope, folderId })
  }

  const footer = (
    <>
      <button className="btn" onClick={onClose} disabled={busy}>취소</button>
      <button className="btn primary" onClick={submit} disabled={!file || busy}>
        {busy ? '업로드 중…' : '업로드'}
      </button>
    </>
  )

  return (
    <Modal title="규정 문서 업로드" onClose={onClose} footer={footer} maxWidth={560}>
      <p className="text-meta" style={{ marginBottom: 16 }}>
        업로드하면 파싱·청킹·임베딩을 거쳐 적재됩니다. <b>접수까지만 즉시 처리</b>되고
        나머지는 백그라운드로 진행되니, 진행 상태는 목록에서 확인하세요.
      </p>

      {error && (
        <div className="note" style={{ marginBottom: 12, color: 'var(--tone-red)' }}>
          <AlertTriangle size={13} style={{ verticalAlign: -2, marginRight: 4 }} />{error}
        </div>
      )}

      {/* ── 파일 드롭존 ── */}
      {!file ? (
        <div
          className={`pd-dropzone${dragOver ? ' over' : ''}`}
          onClick={() => inputRef.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => { e.preventDefault(); setDragOver(false); accept(e.dataTransfer.files?.[0]) }}
        >
          <div style={{ fontSize: 28 }} aria-hidden>📄</div>
          <b style={{ fontSize: 13 }}>PDF 파일을 드래그하거나 클릭해 선택하세요</b>
          <span className="text-meta">파일당 최대 {MAX_MB}MB · PDF만 지원</span>
          <input ref={inputRef} type="file" accept=".pdf" style={{ display: 'none' }}
                 onChange={(e) => accept(e.target.files?.[0])} />
        </div>
      ) : (
        <div className="pd-picked">
          <FileText size={16} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontWeight: 600, fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {file.name}
            </div>
            <div className="text-meta">{(file.size / 1024).toFixed(0)}KB</div>
          </div>
          <button className="btn sm" onClick={() => setFile(null)} disabled={busy} aria-label="파일 제거">
            <X size={12} />
          </button>
        </div>
      )}

      <div className="field" style={{ marginTop: 16 }}>
        <label>문서명</label>
        <input value={title} onChange={(e) => setTitle(e.target.value)} disabled={busy}
               placeholder="예) 법인카드 사용규정 v3.2" />
      </div>

      <div className="field">
        <label>문서 유형</label>
        <select value={profileHint} disabled={busy}
                onChange={(e) => setProfileHint(e.target.value as DocProfile | '')}>
          <option value="">자동 감지 (권장)</option>
          {(Object.keys(DOC_PROFILE_LABEL) as DocProfile[]).map((key) => (
            <option key={key} value={key}>{DOC_PROFILE_LABEL[key].label}</option>
          ))}
        </select>
        <div className="text-meta" style={{ marginTop: 4 }}>
          {profileHint
            ? DOC_PROFILE_LABEL[profileHint].hint
            : '파서가 문서 구조를 보고 판정합니다. 잘못 잡히면 여기서 직접 지정하세요.'}
          {profileHint && !DOC_PROFILE_LABEL[profileHint].judged && (
            <span style={{ color: 'var(--tone-amber)' }}> · 이 유형은 정산 판정에 인용되지 않습니다</span>
          )}
        </div>
      </div>

      <div className="field">
        <label>폴더 위치</label>
        <select value={folderId ?? ''} disabled={busy}
                onChange={(e) => setFolderId(e.target.value ? Number(e.target.value) : null)}>
          <option value="">미분류</option>
          {options.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
        </select>
      </div>

      <div className="field" style={{ marginBottom: 0 }}>
        <label>비용분류 <span className="text-meta">(적재 후 룰 자동 생성 대상)</span></label>
        <select value={ruleScope} onChange={(e) => setRuleScope(e.target.value)} disabled={busy}>
          <option value="">지정 안 함 — 룰 자동 생성 건너뜀</option>
          {ruleScopes.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>
    </Modal>
  )
}

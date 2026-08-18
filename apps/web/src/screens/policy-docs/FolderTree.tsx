// 좌측 폴더 탐색기 — 목업 S-05 v4 ①.
//
// 폴더는 검색·판정에 아무 영향이 없다. 순전히 **사람이 문서를 찾기 위한 분류**라
// 컬렉션 라우팅(문서 유형)과 섞지 않는다.
//
// 지원: 폴더 만들기 / 이름 변경 / 삭제(비어 있을 때만) / 문서를 드래그해 폴더로 이동.
// 미분류를 트리 밖에 따로 보여주는 이유: 폴더에 안 넣었다고 안 보이면 문서를 잃어버린다.
import { useEffect, useRef, useState } from 'react'
import { FolderPlus, Pencil, Trash2 } from 'lucide-react'
import { EMBEDDING_IN_PROGRESS, type FolderDoc, type PolicyFolder } from '../../types/domain'

export type TreeActions = {
  onSelect: (id: string) => void
  onCreateFolder: (name: string, parentId: number | null) => Promise<void>
  onRenameFolder: (id: number, name: string) => Promise<void>
  onDeleteFolder: (id: number) => Promise<void>
  onMoveDoc: (docId: string, folderId: number | null) => Promise<void>
}

/** 드래그 중인 문서 id — 드롭 대상이 자기 자신인지 판별할 필요가 없어 문자열 하나면 충분하다. */
const DRAG_TYPE = 'application/x-policy-doc'

function DocRow({ doc, selected, onSelect }: {
  doc: FolderDoc; selected: boolean; onSelect: (id: string) => void
}) {
  const busy = EMBEDDING_IN_PROGRESS.includes(doc.status)
  return (
    <div
      role="button"
      tabIndex={0}
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData(DRAG_TYPE, doc.id)
        e.dataTransfer.effectAllowed = 'move'
      }}
      onClick={() => onSelect(doc.id)}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(doc.id) } }}
      className={`pd-doc${selected ? ' active' : ''}`}
      title={`${doc.title} — 드래그해서 폴더로 옮길 수 있어요`}
    >
      <span aria-hidden>📄</span>
      <span className="pd-doc-name">{doc.title}</span>
      {doc.reviewCount > 0 && <span className="pd-badge amber">확인 {doc.reviewCount}</span>}
      {doc.superseded && <span className="pd-badge gray">이전 버전</span>}
      {busy && <span className="pd-badge amber">처리중</span>}
      {doc.status === 'FAILED' && <span className="pd-badge red">실패</span>}
    </div>
  )
}

/** 인라인 이름 편집 — 새 폴더/이름 변경이 같은 모양이라 한 컴포넌트로 쓴다. */
function NameInput({ initial, onCommit, onCancel }: {
  initial: string; onCommit: (name: string) => void; onCancel: () => void
}) {
  const [value, setValue] = useState(initial)
  const ref = useRef<HTMLInputElement>(null)
  useEffect(() => { ref.current?.select() }, [])
  return (
    <input
      ref={ref}
      className="pd-name-input"
      value={value}
      autoFocus
      onChange={(e) => setValue(e.target.value)}
      onClick={(e) => e.stopPropagation()}
      onBlur={() => (value.trim() ? onCommit(value.trim()) : onCancel())}
      onKeyDown={(e) => {
        e.stopPropagation()
        if (e.key === 'Enter' && value.trim()) onCommit(value.trim())
        if (e.key === 'Escape') onCancel()
      }}
    />
  )
}

function FolderNode({ folder, depth, selectedId, actions, busy }: {
  folder: PolicyFolder; depth: number; selectedId: string | null; actions: TreeActions; busy: boolean
}) {
  const [open, setOpen] = useState(depth === 0)
  const [renaming, setRenaming] = useState(false)
  const [adding, setAdding] = useState(false)
  const [dropOver, setDropOver] = useState(false)

  const drop = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDropOver(false)
    const docId = e.dataTransfer.getData(DRAG_TYPE)
    if (docId) void actions.onMoveDoc(docId, folder.id)
  }

  return (
    <div>
      <div
        className={`pd-folder${dropOver ? ' drop' : ''}`}
        style={{ paddingLeft: 8 + depth * 12 }}
        onClick={() => setOpen((v) => !v)}
        onDragOver={(e) => {
          if (!e.dataTransfer.types.includes(DRAG_TYPE)) return
          e.preventDefault(); e.stopPropagation(); setDropOver(true)
        }}
        onDragLeave={() => setDropOver(false)}
        onDrop={drop}
      >
        <span className="pd-caret">{open ? '▾' : '▸'}</span>
        <span aria-hidden>📁</span>
        {renaming ? (
          <NameInput
            initial={folder.name}
            onCancel={() => setRenaming(false)}
            onCommit={(name) => { setRenaming(false); void actions.onRenameFolder(folder.id, name) }}
          />
        ) : (
          <>
            <span className="pd-folder-name">{folder.name}</span>
            <span className="pd-folder-count">({folder.docCount}개)</span>
            <span className="pd-folder-tools">
              <button className="pd-icon" title="하위 폴더 만들기" disabled={busy}
                      onClick={(e) => { e.stopPropagation(); setOpen(true); setAdding(true) }}>
                <FolderPlus size={12} />
              </button>
              <button className="pd-icon" title="이름 변경" disabled={busy}
                      onClick={(e) => { e.stopPropagation(); setRenaming(true) }}>
                <Pencil size={12} />
              </button>
              <button className="pd-icon danger" title="폴더 삭제 (비어 있을 때만)" disabled={busy}
                      onClick={(e) => { e.stopPropagation(); void actions.onDeleteFolder(folder.id) }}>
                <Trash2 size={12} />
              </button>
            </span>
          </>
        )}
      </div>

      {open && (
        <div>
          {adding && (
            <div className="pd-folder" style={{ paddingLeft: 8 + (depth + 1) * 12 }}>
              <span className="pd-caret" />
              <span aria-hidden>📁</span>
              <NameInput
                initial="새 폴더"
                onCancel={() => setAdding(false)}
                onCommit={(name) => { setAdding(false); void actions.onCreateFolder(name, folder.id) }}
              />
            </div>
          )}
          {folder.children.map((child) => (
            <FolderNode key={child.id} folder={child} depth={depth + 1}
                        selectedId={selectedId} actions={actions} busy={busy} />
          ))}
          <div style={{ paddingLeft: 8 + (depth + 1) * 12 }}>
            {folder.documents.map((doc) => (
              <DocRow key={doc.id} doc={doc} selected={doc.id === selectedId} onSelect={actions.onSelect} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export function FolderTree({ folders, unfiled, selectedId, query, actions, busy }: {
  folders: PolicyFolder[]
  unfiled: FolderDoc[]
  selectedId: string | null
  query: string
  actions: TreeActions
  busy: boolean
}) {
  const [addingRoot, setAddingRoot] = useState(false)
  const [dropOver, setDropOver] = useState(false)

  // 검색 중에는 트리를 접지 않고 평평하게 보여준다 — 찾는 게 어느 폴더에 있는지 모르니까.
  if (query.trim()) {
    const all: FolderDoc[] = []
    const walk = (nodes: PolicyFolder[]) => nodes.forEach((n) => { all.push(...n.documents); walk(n.children) })
    walk(folders)
    all.push(...unfiled)
    const hit = all.filter((d) => d.title.includes(query.trim()))
    return (
      <div style={{ padding: '4px 8px' }}>
        <div className="text-meta" style={{ padding: '4px 4px 8px' }}>검색 결과 {hit.length}건</div>
        {hit.map((doc) => (
          <DocRow key={doc.id} doc={doc} selected={doc.id === selectedId} onSelect={actions.onSelect} />
        ))}
        {hit.length === 0 && <div className="text-meta" style={{ padding: 8 }}>일치하는 문서가 없어요.</div>}
      </div>
    )
  }

  return (
    <div style={{ padding: '4px 0' }}>
      <div className="pd-tree-head">
        <span className="text-meta">폴더</span>
        <button className="btn sm" disabled={busy} onClick={() => setAddingRoot(true)}>
          <FolderPlus size={12} /> 새 폴더
        </button>
      </div>

      {addingRoot && (
        <div className="pd-folder" style={{ paddingLeft: 8 }}>
          <span className="pd-caret" />
          <span aria-hidden>📁</span>
          <NameInput
            initial="새 폴더"
            onCancel={() => setAddingRoot(false)}
            onCommit={(name) => { setAddingRoot(false); void actions.onCreateFolder(name, null) }}
          />
        </div>
      )}

      {folders.map((folder) => (
        <FolderNode key={folder.id} folder={folder} depth={0}
                    selectedId={selectedId} actions={actions} busy={busy} />
      ))}

      {/* 미분류는 항상 보여준다 — 드롭 대상이기도 하다(폴더에서 빼내는 통로). */}
      <div style={{ marginTop: folders.length ? 8 : 0 }}>
        <div
          className={`pd-folder${dropOver ? ' drop' : ''}`}
          style={{ paddingLeft: 8, cursor: 'default' }}
          onDragOver={(e) => {
            if (!e.dataTransfer.types.includes(DRAG_TYPE)) return
            e.preventDefault(); setDropOver(true)
          }}
          onDragLeave={() => setDropOver(false)}
          onDrop={(e) => {
            e.preventDefault(); setDropOver(false)
            const docId = e.dataTransfer.getData(DRAG_TYPE)
            if (docId) void actions.onMoveDoc(docId, null)
          }}
        >
          <span className="pd-caret">▾</span>
          <span aria-hidden>📂</span>
          <span className="pd-folder-name">미분류</span>
          <span className="pd-folder-count">({unfiled.length}개)</span>
        </div>
        <div style={{ paddingLeft: 20 }}>
          {unfiled.map((doc) => (
            <DocRow key={doc.id} doc={doc} selected={doc.id === selectedId} onSelect={actions.onSelect} />
          ))}
        </div>
      </div>

      {folders.length === 0 && unfiled.length === 0 && (
        <div className="text-meta" style={{ padding: 16 }}>
          아직 등록된 문서가 없어요. 오른쪽 위 「문서 업로드」로 규정 PDF를 올려주세요.
        </div>
      )}
    </div>
  )
}

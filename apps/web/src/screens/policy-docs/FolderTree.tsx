// 좌측 폴더 트리 — 목업 S-05 v4 ①. 폴더는 검색에 영향이 없고 사람이 문서를 찾기 위한 분류다.
//  미분류 문서를 트리 밖에 따로 보여주는 이유: 폴더에 안 넣었다고 안 보이면 문서를 잃어버린다.
import { useState } from 'react'
import { EMBEDDING_IN_PROGRESS, type FolderDoc, type PolicyFolder } from '../../types/domain'

function DocRow({ doc, selected, onSelect }: {
  doc: FolderDoc; selected: boolean; onSelect: (id: string) => void
}) {
  const busy = EMBEDDING_IN_PROGRESS.includes(doc.status)
  return (
    <button
      type="button"
      onClick={() => onSelect(doc.id)}
      className={`pd-doc${selected ? ' active' : ''}`}
      title={doc.title}
    >
      <span aria-hidden>📄</span>
      <span className="pd-doc-name">{doc.title}</span>
      {doc.reviewCount > 0 && <span className="pd-badge amber">확인 {doc.reviewCount}</span>}
      {doc.superseded && <span className="pd-badge gray">이전 버전</span>}
      {busy && <span className="pd-badge amber">처리중</span>}
      {doc.status === 'FAILED' && <span className="pd-badge red">실패</span>}
    </button>
  )
}

function FolderNode({ folder, depth, selectedId, onSelect }: {
  folder: PolicyFolder; depth: number; selectedId: string | null; onSelect: (id: string) => void
}) {
  // 최상위는 펼쳐두고 하위는 접어둔다 — 목업의 초기 상태와 같다.
  const [open, setOpen] = useState(depth === 0)
  return (
    <div>
      <button
        type="button"
        className="pd-folder"
        style={{ paddingLeft: 8 + depth * 12 }}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="pd-caret">{open ? '▾' : '▸'}</span>
        <span aria-hidden>📁</span>
        <span className="pd-folder-name">{folder.name}</span>
        <span className="pd-folder-count">({folder.docCount}개)</span>
      </button>
      {open && (
        <div>
          {folder.children.map((child) => (
            <FolderNode key={child.id} folder={child} depth={depth + 1}
                        selectedId={selectedId} onSelect={onSelect} />
          ))}
          <div style={{ paddingLeft: 8 + (depth + 1) * 12 }}>
            {folder.documents.map((doc) => (
              <DocRow key={doc.id} doc={doc} selected={doc.id === selectedId} onSelect={onSelect} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export function FolderTree({ folders, unfiled, selectedId, onSelect, query }: {
  folders: PolicyFolder[]
  unfiled: FolderDoc[]
  selectedId: string | null
  onSelect: (id: string) => void
  query: string
}) {
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
          <DocRow key={doc.id} doc={doc} selected={doc.id === selectedId} onSelect={onSelect} />
        ))}
        {hit.length === 0 && <div className="text-meta" style={{ padding: 8 }}>일치하는 문서가 없어요.</div>}
      </div>
    )
  }

  return (
    <div style={{ padding: '4px 0' }}>
      {folders.map((folder) => (
        <FolderNode key={folder.id} folder={folder} depth={0}
                    selectedId={selectedId} onSelect={onSelect} />
      ))}
      {unfiled.length > 0 && (
        <div style={{ marginTop: folders.length ? 8 : 0 }}>
          <div className="pd-folder" style={{ paddingLeft: 8, cursor: 'default' }}>
            <span className="pd-caret">▾</span>
            <span aria-hidden>📂</span>
            <span className="pd-folder-name">미분류</span>
            <span className="pd-folder-count">({unfiled.length}개)</span>
          </div>
          <div style={{ paddingLeft: 20 }}>
            {unfiled.map((doc) => (
              <DocRow key={doc.id} doc={doc} selected={doc.id === selectedId} onSelect={onSelect} />
            ))}
          </div>
        </div>
      )}
      {folders.length === 0 && unfiled.length === 0 && (
        <div className="text-meta" style={{ padding: 16 }}>
          아직 등록된 문서가 없어요. 오른쪽 위 「문서 업로드」로 규정 PDF를 올려주세요.
        </div>
      )}
    </div>
  )
}

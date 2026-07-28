// 규정 문서 관리 — 회계 담당자/관리자.
// RAG 소스 문서(법인카드 사용규정, 사내 정책 등)를 업로드·임베딩·연결 관리한다.
// 업로드된 문서는 Rule Agent(search_policy Tool)와 Risk Review Agent(내규검증)에서 활용된다.
import { useState } from 'react'
import { FileText, RefreshCw, Trash2, Upload } from 'lucide-react'
import { policyDocuments } from '../data/mock'
import { EMBEDDING_STATUS_META, type EmbeddingStatus, type PolicyDocument } from '../types/domain'
import { KpiCard } from '../components/ui/KpiCard'

const DOC_TYPE_COLOR: Record<string, string> = {
  '법인카드 사용규정': 'var(--tone-blue)',
  '세법 시행령': 'var(--tone-purple)',
  '사내 정책': 'var(--tone-teal)',
}

function EmbeddingBadge({ status }: { status: EmbeddingStatus }) {
  const meta = EMBEDDING_STATUS_META[status]
  const toneMap = {
    amber: { bg: 'var(--tone-amber-bg)', color: 'var(--tone-amber)', border: '#e8d5a3' },
    green: { bg: 'var(--tone-green-bg)', color: 'var(--tone-green)', border: '#bfe6d1' },
    red: { bg: 'var(--tone-red-bg)', color: 'var(--tone-red)', border: '#f3c9c5' },
  }
  const t = toneMap[meta.tone]
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, padding: '2px 8px', borderRadius: 999, fontSize: 11, fontWeight: 700, background: t.bg, color: t.color, border: `1px solid ${t.border}` }}>
      {status === 'EMBEDDING' && <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--tone-amber)', animation: 'pulse 1.5s infinite' }} />}
      {meta.label}
    </span>
  )
}

function FileIcon({ format }: { format: PolicyDocument['fileFormat'] }) {
  const colors: Record<string, string> = { PDF: '#e53e3e', DOC: '#3182ce', XLSX: '#38a169' }
  return (
    <div style={{ width: 36, height: 36, borderRadius: 6, background: colors[format] + '22', border: `1px solid ${colors[format]}44`, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
      <span style={{ fontSize: 9, fontWeight: 800, color: colors[format] }}>{format}</span>
    </div>
  )
}

export function PolicyDocuments() {
  const [docs, setDocs] = useState<PolicyDocument[]>(policyDocuments)
  const [typeFilter, setTypeFilter] = useState<string>('전체')
  const [statusFilter, setStatusFilter] = useState<string>('전체')
  const [search, setSearch] = useState('')

  const stats = {
    total: docs.length,
    done: docs.filter((d) => d.status === 'DONE').length,
    embedding: docs.filter((d) => d.status === 'EMBEDDING').length,
    lastUpdate: '2026-07-22',
  }

  const visible = docs.filter((d) => {
    if (typeFilter !== '전체' && d.docType !== typeFilter) return false
    if (statusFilter !== '전체' && EMBEDDING_STATUS_META[d.status].label !== statusFilter) return false
    if (search && !d.filename.includes(search)) return false
    return true
  })

  const handleDelete = (id: string) => setDocs((prev) => prev.filter((d) => d.id !== id))

  const handleReembed = (id: string) =>
    setDocs((prev) => prev.map((d) => d.id === id ? { ...d, status: 'EMBEDDING' as EmbeddingStatus, extractedClauses: 0, linkedRules: 0 } : d))

  return (
    <>
      <div className="page-head row" style={{ justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <span className="screen-id">규정문서</span>
          <h1>규정 문서 관리</h1>
          <div className="sub">회사 사내 규정(법인카드 사용규정 등)을 업로드하고 관리합니다</div>
        </div>
        <button className="btn primary" onClick={() => alert('파일 업로드 기능은 백엔드 연동 후 활성화됩니다.')}>
          <Upload size={14} /> + 문서 업로드
        </button>
      </div>

      <div className="kpi-grid">
        <KpiCard label="총 문서 수" value={stats.total} unit="건" />
        <KpiCard label="임베딩 완료" value={stats.done} unit="건" />
        <KpiCard label="처리 중" value={stats.embedding} unit="건" warn={stats.embedding > 0} />
        <KpiCard label="최근 업데이트" value={stats.lastUpdate} />
      </div>

      <div className="filter-bar">
        <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
          <option>전체 유형</option>
          <option value="법인카드 사용규정">법인카드 사용규정</option>
          <option value="세법 시행령">세법 시행령</option>
          <option value="사내 정책">사내 정책</option>
        </select>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option>전체 상태</option>
          <option value="임베딩 완료">임베딩 완료</option>
          <option value="처리중">처리중</option>
          <option value="임베딩 실패">임베딩 실패</option>
        </select>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 12px', border: '1px solid var(--border-strong)', borderRadius: 'var(--radius-control)', background: 'var(--surface)', flex: 1, maxWidth: 240 }}>
          <FileText size={13} color="var(--muted)" />
          <input
            placeholder="문서명 검색"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{ border: 'none', outline: 'none', background: 'none', fontSize: 13, flex: 1, padding: 0 }}
          />
        </div>
      </div>

      <div className="card">
        <table className="table">
          <thead>
            <tr>
              <th style={{ width: 48 }}></th>
              <th>문서명</th>
              <th>유형</th>
              <th>업로드일</th>
              <th>상태</th>
              <th className="num">추출 조항</th>
              <th className="num">관련 Rule</th>
              <th>액션</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((d) => (
              <tr key={d.id} style={{ cursor: 'default' }}>
                <td><FileIcon format={d.fileFormat} /></td>
                <td>
                  <div style={{ fontWeight: 600, fontSize: 13 }}>{d.filename}</div>
                  <div className="text-meta">{d.docType}</div>
                </td>
                <td>
                  <span style={{ display: 'inline-flex', alignItems: 'center', padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 600, background: (DOC_TYPE_COLOR[d.docType] ?? 'var(--muted)') + '18', color: DOC_TYPE_COLOR[d.docType] ?? 'var(--muted)', border: `1px solid ${(DOC_TYPE_COLOR[d.docType] ?? 'var(--muted)')}33` }}>
                    {d.docType}
                  </span>
                </td>
                <td className="text-meta">{d.uploadedAt}</td>
                <td><EmbeddingBadge status={d.status} /></td>
                <td className="num">{d.extractedClauses > 0 ? `${d.extractedClauses}개` : '-'}</td>
                <td className="num">{d.linkedRules > 0 ? `${d.linkedRules}건` : '-'}</td>
                <td>
                  <div className="row" style={{ gap: 4 }}>
                    <button className="btn sm" onClick={() => alert(`${d.filename} 미리보기 (백엔드 연동 후 활성화)`)}>보기</button>
                    <span style={{ color: 'var(--border-strong)' }}>·</span>
                    <button
                      className="btn sm"
                      disabled={d.status === 'EMBEDDING'}
                      onClick={() => handleReembed(d.id)}
                      title="재임베딩"
                    >
                      <RefreshCw size={11} /> {d.status === 'FAILED' ? '재처리' : '재임베딩'}
                    </button>
                    <span style={{ color: 'var(--border-strong)' }}>·</span>
                    <button
                      className="btn sm"
                      style={{ color: 'var(--tone-red)', borderColor: 'var(--tone-red-bg)' }}
                      onClick={() => {
                        if (window.confirm(`"${d.filename}"을 삭제하시겠습니까?`)) handleDelete(d.id)
                      }}
                    >
                      <Trash2 size={11} /> 삭제
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {visible.length === 0 && (
              <tr><td colSpan={8} className="text-meta" style={{ textAlign: 'center', padding: 32 }}>검색 조건에 맞는 문서가 없습니다.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="note" style={{ marginTop: 16 }}>
        ※ 업로드된 문서는 청킹·임베딩되어 Rule Agent의 RAG 검색(search_policy Tool)과 Risk Review Agent의 내규검증 근거로 활용됩니다.
      </div>
    </>
  )
}

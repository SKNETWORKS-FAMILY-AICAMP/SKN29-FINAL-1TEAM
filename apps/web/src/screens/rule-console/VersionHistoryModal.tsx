// 버전 이력 모달 — 같은 계열(family)의 전체 버전과 롤백. 실제 API(/rules/{id}/family/) 연동.
import { useEffect, useState } from 'react'
import { Lock, RotateCcw } from 'lucide-react'
import { Modal } from '../../components/ui/Modal'
import { Markdown } from '../../components/ui/Markdown'
import { SkeletonLines } from '../../components/ui/Skeleton'
import { endpoints } from '../../api/client'
import { rollbackRuleTo } from '../../api/ruleService'
import { useCan } from '../../lib/capabilities'

export interface FamilyVersion {
  id: string
  version: number
  name: string
  scope: string
  status: string
  statusLabel: string
  nodeCount: number
  activatedAt: string | null
  activatedBy: string
  reviewedBy: string
  reviewedAt: string | null
  reviewComment: string
  simResult: { ranAt?: string; stats?: { autoRate?: number; historyTotal?: number } }
  isCurrent: boolean
  canRollback: boolean
}

const dateText = (value: string | null) => value ? value.slice(0, 16).replace('T', ' ') : '-'
const rateText = (row: FamilyVersion) =>
  row.simResult?.stats?.autoRate === undefined ? '-' : `${(row.simResult.stats.autoRate * 100).toFixed(1)}%`

export function VersionHistoryModal({ graphId, graphName, onClose, onChanged }: {
  graphId: string; graphName: string; onClose: () => void; onChanged: () => void
}) {
  const canActivate = useCan()('rule_activate')
  const [rows, setRows] = useState<FamilyVersion[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [openComment, setOpenComment] = useState('')

  const load = () => {
    setLoading(true)
    endpoints.ruleFamily(graphId)
      .then(({ data }) => setRows(data as FamilyVersion[]))
      .catch(() => setError('버전 이력을 불러오지 못했습니다.'))
      .finally(() => setLoading(false))
  }
  useEffect(load, [graphId])

  const rollback = async (row: FamilyVersion) => {
    if (!window.confirm(`v${row.version}을(를) 다시 활성 버전으로 되돌립니다. 계속할까요?`)) return
    setBusy(row.id)
    setError('')
    try {
      await rollbackRuleTo(row.id)
      load()
      onChanged()
    } catch {
      setError('롤백에 실패했습니다. 권한과 승인 이력을 확인해주세요.')
    } finally {
      setBusy('')
    }
  }

  return (
    <Modal title={`${graphName} — 버전 이력`} maxWidth={1080} onClose={onClose}
      footer={<>
        <span className="text-meta">
          롤백은 <b>승인된 적 있는 버전</b>만 가능하며, 룰 활성(rule_activate) 권한이 필요합니다.
        </span>
        <div className="spacer" />
        <button className="btn" onClick={onClose}>닫기</button>
      </>}>
      {loading && (
        <div>
          <span className="text-meta">버전 이력을 불러오는 중…</span>
          <div style={{ marginTop: 8 }}><SkeletonLines rows={3} /></div>
        </div>
      )}
      {error && <div className="note error" style={{ marginBottom: 12 }}>{error}</div>}
      {!loading && rows.length > 0 && (
        <table className="table">
          <thead><tr>
            <th>버전</th><th>상태</th><th className="num">노드</th><th>활성 일시</th><th>활성자</th>
            <th>검토자</th><th>자동처리율</th><th>처리</th>
          </tr></thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td><b>v{row.version}</b></td>
                <td><span className={'tag' + (row.isCurrent ? ' ok' : row.status === 'SIMULATED' ? ' ai' : '')}>
                  {row.isCurrent ? '현재 활성' : row.statusLabel}</span></td>
                <td className="num">{row.nodeCount}</td>
                <td className="text-meta">{dateText(row.activatedAt)}</td>
                <td className="text-meta">{row.activatedBy || '-'}</td>
                <td className="text-meta">
                  {row.reviewedBy || '-'}
                  {row.reviewComment && (
                    <button className="btn sm" style={{ marginLeft: 6 }}
                      onClick={() => setOpenComment(openComment === row.id ? '' : row.id)}>검토보고서</button>
                  )}
                </td>
                <td>{rateText(row)}</td>
                <td>
                  {row.canRollback && (
                    <button className="btn sm" disabled={!canActivate || busy === row.id} onClick={() => void rollback(row)}>
                      {!canActivate && <Lock size={11} />}<RotateCcw size={11} /> 롤백
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {!loading && rows.length === 0 && <div className="text-meta">버전 이력이 없습니다.</div>}
      {openComment && (
        <div className="card" style={{ marginTop: 12 }}>
          <div className="card-head"><h3>검토보고서 — v{rows.find((row) => row.id === openComment)?.version}</h3>
            <span className="text-meta">{dateText(rows.find((row) => row.id === openComment)?.reviewedAt ?? null)}</span></div>
          <div className="card-body"><Markdown source={rows.find((row) => row.id === openComment)?.reviewComment ?? ''} /></div>
        </div>
      )}
    </Modal>
  )
}

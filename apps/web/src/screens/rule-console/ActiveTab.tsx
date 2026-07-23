// Tab3 — Active Rule 버전 이력 (v4, 버전관리)
import { useState } from 'react'
import { Lock, RotateCcw } from 'lucide-react'
import { useRole } from '../../context/RoleContext'
import { useAuth } from '../../context/AuthContext'
import { ROLE_LABEL } from '../../types/domain'
import { activateRule, rollbackRule } from '../../api/ruleService'
import { ACTIVE_RULE, PENDING_VERSION, VERSION_HISTORY, type VersionRow } from './data/ruleConsoleMock'

// "ACTIVE 승인 권한: 팀장급 이상" — 화면설계서 기준 TEAM_LEAD/EXECUTIVE만 승인 가능(ACCOUNTANT도 제외).
const CAN_APPROVE_ROLES = ['TEAM_LEAD', 'EXECUTIVE']
const todayKST = () => new Date().toISOString().slice(0, 10)

export function ActiveTab() {
  const { role } = useRole()
  const { user } = useAuth()
  const canApprove = CAN_APPROVE_ROLES.includes(role)
  const approverName = user?.name ?? ROLE_LABEL[role]

  const [versions, setVersions] = useState<VersionRow[]>(VERSION_HISTORY)
  const [busy, setBusy] = useState(false)
  const current = versions.find((v) => v.status === '현재 활성')
  const pending = versions.find((v) => v.status === '승인대기')

  const approve = async () => {
    if (!pending) return
    setBusy(true)
    await activateRule(ACTIVE_RULE.id)
    setVersions((prev) =>
      prev.map((v) => {
        if (v.version === pending.version) return { ...v, status: '현재 활성', approvedAt: todayKST(), approver: approverName }
        if (v.status === '현재 활성') return { ...v, status: '과거' }
        return v
      })
    )
    setBusy(false)
  }

  const rollback = async (version: string) => {
    setBusy(true)
    await rollbackRule(ACTIVE_RULE.id)
    setVersions((prev) =>
      prev.map((v) => {
        if (v.version === version) return { ...v, status: '현재 활성', approvedAt: todayKST(), approver: approverName }
        if (v.status === '현재 활성') return { ...v, status: '과거' }
        return v
      })
    )
    setBusy(false)
  }

  return (
    <>
      <div className="row" style={{ justifyContent: 'space-between', marginBottom: 16 }}>
        <div>
          <h2 style={{ fontSize: 15 }}>{ACTIVE_RULE.id} · Active Rule 버전 이력 (v4)</h2>
          <div className="text-meta">{ACTIVE_RULE.title}</div>
        </div>
        <span className="tag ok">현재 ACTIVE · {current?.version ?? '-'}</span>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-body row" style={{ justifyContent: 'space-between' }}>
          <div>
            <b>{ACTIVE_RULE.id} · {ACTIVE_RULE.title}</b>
            <div className="text-meta">{ACTIVE_RULE.sourceClause} · 최초 승인 {ACTIVE_RULE.firstApproved}</div>
          </div>
          <div className="row" style={{ gap: 24 }}>
            <div style={{ textAlign: 'right' }}><div className="text-meta">총 버전</div><b>{ACTIVE_RULE.totalVersions}개</b></div>
            <div style={{ textAlign: 'right' }}><div className="text-meta">현재 매칭 건수(월)</div><b>{current?.matched ?? ACTIVE_RULE.currentMatched}건</b></div>
            <div style={{ textAlign: 'right' }}><div className="text-meta">현재 오탐율</div><b>{((current?.fpRate ?? ACTIVE_RULE.currentFpRate) * 100).toFixed(1)}%</b></div>
          </div>
        </div>
      </div>

      {/* 승인대기 하이라이트 */}
      {pending && (
        <div className="card" style={{ borderColor: 'var(--tone-orange)', marginBottom: 16 }}>
          <div className="card-head">
            <h3>{PENDING_VERSION.version} (승인 대기) <span className="tag warn" style={{ marginLeft: 8 }}>승인대기</span></h3>
            <span className="text-meta">시뮬레이션 완료 {PENDING_VERSION.simulatedAt}</span>
          </div>
          <div className="card-body">
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 12 }}>
              <div className="kpi"><div className="label">매칭 건수</div><div className="value">{PENDING_VERSION.matched}건</div></div>
              <div className="kpi"><div className="label">오탐율</div><div className="value">{(PENDING_VERSION.fpRate * 100).toFixed(1)}%</div></div>
              <div className="kpi"><div className="label">개선폭 (v3 대비)</div><div className="value" style={{ color: 'var(--tone-green)' }}>{(PENDING_VERSION.fpImprovement * 100).toFixed(1)}%p</div></div>
            </div>
            <div className="row" style={{ justifyContent: 'space-between', background: 'var(--surface-2)', borderRadius: 'var(--radius-control)', padding: 12 }}>
              <div>
                <b style={{ fontSize: 12.5 }}>ACTIVE 승인 권한: 팀장급 이상</b>
                <div className="text-meta">현재 로그인 계정: {ROLE_LABEL[role]} — {canApprove ? '승인 권한 있음' : '승인 권한 없음'}</div>
              </div>
              <button className="btn primary" disabled={!canApprove || busy} onClick={approve}>
                {!canApprove && <Lock size={12} />} 승인 (ACTIVE 전환)
              </button>
            </div>
            <p className="text-meta" style={{ marginTop: 8 }}>
              ※ 팀장급 이상 계정으로 로그인 시 위 버튼이 활성화되며, 승인 즉시 {PENDING_VERSION.version}가 ACTIVE로 전환되고 이전 버전은 과거 버전으로 이동합니다.
            </p>
          </div>
        </div>
      )}

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-head"><h3>버전별 지표 요약</h3></div>
        <table className="table">
          <thead><tr><th>버전</th><th>승인일</th><th>승인자</th><th className="num">매칭 건수</th><th>오탐율</th><th>상태</th><th>처리</th></tr></thead>
          <tbody>
            {versions.map((v) => (
              <tr key={v.version}>
                <td><b>{v.version}</b></td>
                <td className="text-meta">{v.approvedAt}</td>
                <td className="text-meta">{v.approver}</td>
                <td className="num">{v.matched}건</td>
                <td>{(v.fpRate * 100).toFixed(1)}%</td>
                <td>
                  <span className={'tag' + (v.status === '현재 활성' ? ' ok' : v.status === '승인대기' ? ' ai' : '')}>{v.status}</span>
                </td>
                <td>
                  {v.status === '과거' && (
                    <button className="btn sm" disabled={busy} onClick={() => rollback(v.version)}>
                      <RotateCcw size={11} /> 롤백
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <div className="card-head"><h3>현재 활성 버전({current?.version ?? '-'}) 로직</h3></div>
        <div className="card-body">
          <pre style={{ margin: 0, padding: '10px 12px', background: 'var(--sidebar-bg)', color: '#d1fae5', borderRadius: 'var(--radius-control)', fontSize: 12, whiteSpace: 'pre-wrap' }}>
            {ACTIVE_RULE.currentLogic}
          </pre>
          <p className="text-meta" style={{ marginTop: 8 }}>{ACTIVE_RULE.currentChangeNote}</p>
        </div>
      </div>
    </>
  )
}

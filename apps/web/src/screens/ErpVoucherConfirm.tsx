// F-4 ERP 전표(안) 확인 — 정산 확정(CONFIRMED) 후 자동 생성된 전표 초안. AppLayout 밖 풀스크린 라우트.
import { useNavigate, useParams } from 'react-router-dom'
import { won } from '../lib/format'
import { myExpenses, reviewItems, teamMembers } from '../data/mock'

const ALL_SETTLEMENTS = [...myExpenses, ...reviewItems, ...teamMembers.flatMap((m) => m.items)]

export function ErpVoucherConfirm() {
  const { id } = useParams<{ id: string }>()
  const nav = useNavigate()
  const item = ALL_SETTLEMENTS.find((s) => s.id === id) ?? ALL_SETTLEMENTS[0]

  const voucherNo = `V-2026${item.date.replace(/-/g, '').slice(2)}-${item.id.replace(/\D/g, '').slice(-4)}`

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)', padding: 'var(--space-6)', display: 'flex', justifyContent: 'center' }}>
      <div style={{ maxWidth: 600, width: '100%' }}>
        <div className="row" style={{ justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
          <div>
            <h1 style={{ fontSize: 20 }}>ERP 전표(안) 확인</h1>
            <div className="text-meta">정산 확정 후 자동 생성된 전표 초안</div>
          </div>
          <span className="tag ok">ERP 전표 초안 생성됨</span>
        </div>

        <div className="card">
          <div className="card-body stack">
            <div className="row" style={{ justifyContent: 'space-between' }}>
              <span className="text-meta">전표번호</span><b>{voucherNo}</b>
            </div>
            <div className="row" style={{ justifyContent: 'space-between' }}>
              <span className="text-meta">거래처</span><b>{item.merchant}</b>
            </div>
            <div className="row" style={{ justifyContent: 'space-between' }}>
              <span className="text-meta">적요</span><b>{item.aiCategory} 지출 ({item.id})</b>
            </div>
            <div className="row" style={{ justifyContent: 'space-between' }}>
              <span className="text-meta">승인자</span><b>김회계 (재무회계팀)</b>
            </div>
          </div>
        </div>

        <div className="card" style={{ marginTop: 16 }}>
          <div className="card-head"><h3>회계 분개 (차변 / 대변)</h3></div>
          <table className="table">
            <thead><tr><th>구분</th><th>계정과목</th><th className="num">금액</th></tr></thead>
            <tbody>
              <tr><td><b>차변</b></td><td>{item.aiCategory}비(기업업무추진비)</td><td className="num">{won(item.amount)}</td></tr>
              <tr><td><b>대변</b></td><td>미지급금({item.cardType === 'SHARED' ? '공용카드' : '개인카드'})</td><td className="num">{won(item.amount)}</td></tr>
            </tbody>
          </table>
          <div className="card-body">
            <div className="note">
              💡 계정과목은 비용 분류({item.aiCategory}) 기준으로 AI가 자동 매핑했습니다. 최종 계정 확정은 회계 담당자가 수행합니다.
            </div>
          </div>
        </div>

        <div className="row" style={{ justifyContent: 'flex-end', gap: 8, marginTop: 16 }}>
          <button className="btn" onClick={() => nav(-1)}>계정과목 수정</button>
          <button className="btn primary" onClick={() => nav('/governance')}>ERP로 전송</button>
        </div>
      </div>
    </div>
  )
}

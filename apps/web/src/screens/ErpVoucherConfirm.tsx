// F-4 ERP 전표(안) 확인 — 정산 확정 후 자동 생성된 전표 초안. AppLayout 밖 풀스크린 라우트.
//
// 전표는 **서버가 만든다**(`settlements/services.py::draft_voucher`가 CONFIRMED 전이 때
// `ErpVoucher`를 생성). 화면은 그걸 읽는다 — 전에는 정산 목록에서 숫자를 주워 전표번호까지
// 화면에서 지어내고 있었다(같은 건을 두 번 열면 다른 전표번호가 나올 수 있는 상태였다).
//
// 진입 경로: '지출 증빙'(S-01)·'증빙 검토'(S-03) 목록의 확정된 건에서 「전표 보기」.
// 예전엔 검토 모달의 승인 직후 자동 이동 **한 번뿐**이라, 그 순간을 놓치면 다시 볼 방법이
// 없었다.
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { won } from '../lib/format'
import { endpoints } from '../api/client'

interface VoucherPayload {
  settlement_id?: number
  merchant?: string
  amount?: number
  category?: string
  date?: string
  drafted_at?: string
}

interface Voucher {
  id: number
  settlement: number
  voucherPayload: VoucherPayload
  status: string
  created_at: string
}

export function ErpVoucherConfirm() {
  const { id } = useParams<{ id: string }>()
  const nav = useNavigate()
  const [voucher, setVoucher] = useState<Voucher | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!id) return
    void (async () => {
      try {
        const { data } = await endpoints.erpVoucherBySettlement(id)
        setVoucher(data)
      } catch (e: unknown) {
        // 404 = 아직 전표가 없다(확정 전). "없다"와 "못 불러왔다"를 구분해 알린다.
        const status = (e as { response?: { status?: number } })?.response?.status
        setError(status === 404
          ? '이 정산에는 아직 생성된 ERP 전표(안)가 없습니다. 회계 확정 후 자동으로 만들어집니다.'
          : '전표를 불러오지 못했습니다.')
      } finally {
        setLoading(false)
      }
    })()
  }, [id])

  const shell = (children: React.ReactNode) => (
    <div style={{ minHeight: '100vh', background: 'var(--bg)', padding: 'var(--space-6)', display: 'flex', justifyContent: 'center' }}>
      <div style={{ maxWidth: 600, width: '100%' }}>
        <button className="btn sm" style={{ marginBottom: 16 }} onClick={() => nav(-1)}>
          <ArrowLeft size={13} /> 돌아가기
        </button>
        {children}
      </div>
    </div>
  )

  if (loading) return shell(<div className="card"><div className="card-body text-meta">전표를 불러오는 중…</div></div>)
  if (!voucher) return shell(<div className="card"><div className="card-body">{error}</div></div>)

  const p = voucher.voucherPayload ?? {}
  //  전표번호는 서버가 만든 id 기준이다 — 화면이 날짜·정산번호를 조합해 지어내면
  //  같은 전표가 화면마다 다른 번호로 보인다.
  const voucherNo = `V-${(p.date ?? voucher.created_at.slice(0, 10)).replace(/-/g, '')}-${String(voucher.id).padStart(4, '0')}`
  const amount = p.amount ?? 0
  const category = p.category || '미분류'

  return shell(
    <>
      <div className="row" style={{ justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
        <div>
          <h1 style={{ fontSize: 20 }}>ERP 전표(안) 확인</h1>
          <div className="text-meta">정산 확정 후 자동 생성된 전표 초안</div>
        </div>
        <span className="tag ok">{voucher.status === 'DRAFT' ? 'ERP 전표 초안' : 'ERP 확정'}</span>
      </div>

      <div className="card">
        <div className="card-body stack">
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <span className="text-meta">전표번호</span><b>{voucherNo}</b>
          </div>
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <span className="text-meta">거래처</span><b>{p.merchant || '-'}</b>
          </div>
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <span className="text-meta">거래일</span><b>{p.date || '-'}</b>
          </div>
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <span className="text-meta">적요</span><b>{category} 지출 (정산 #{voucher.settlement})</b>
          </div>
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <span className="text-meta">생성 시각</span><b>{(p.drafted_at ?? voucher.created_at).replace('T', ' ').slice(0, 16)}</b>
          </div>
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-head"><h3>회계 분개 (차변 / 대변)</h3></div>
        <table className="table">
          <thead><tr><th>구분</th><th>계정과목</th><th className="num">금액</th></tr></thead>
          <tbody>
            <tr><td><b>차변</b></td><td>{category}</td><td className="num">{won(amount)}</td></tr>
            <tr><td><b>대변</b></td><td>미지급금(법인카드)</td><td className="num">{won(amount)}</td></tr>
          </tbody>
        </table>
        <div className="card-body">
          <div className="note">
            💡 계정과목은 비용 분류({category}) 기준으로 매핑된 <b>초안</b>입니다. 실제 ERP 적재·연동은 MVP 범위 밖이며,
            최종 계정 확정은 회계 담당자가 ERP에서 수행합니다.
          </div>
        </div>
      </div>

      <div className="row" style={{ justifyContent: 'flex-end', gap: 8, marginTop: 16 }}>
        <button className="btn" onClick={() => nav(-1)}>닫기</button>
      </div>
    </>,
  )
}

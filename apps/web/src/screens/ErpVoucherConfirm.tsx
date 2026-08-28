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
import { endpoints } from '../api/client'
import { SkeletonLines } from '../components/ui/Skeleton'
import { VoucherBody, type Voucher } from '../components/settlement/VoucherPanel'

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

  if (loading) {
    return shell(
      <div className="card">
        <div className="card-body">
          <span className="text-meta">전표를 불러오는 중…</span>
          <div style={{ marginTop: 8 }}><SkeletonLines rows={4} /></div>
        </div>
      </div>,
    )
  }
  if (!voucher) return shell(<div className="card"><div className="card-body">{error}</div></div>)

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
        <div className="card-body">
          <VoucherBody voucher={voucher} />
        </div>
      </div>

      <div className="row" style={{ justifyContent: 'flex-end', gap: 8, marginTop: 16 }}>
        <button className="btn" onClick={() => nav(-1)}>닫기</button>
      </div>
    </>,
  )
}

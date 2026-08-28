// ERP 전표(안) — 두 화면이 같이 쓰는 조회 부품.
//
// 전표는 **서버가 만든다**(`settlements/services.py::_build_voucher`가 CONFIRMED 전이 때
// `ErpVoucher`를 생성). 화면은 읽기만 한다.
//
// **전표번호 유도를 여기 한 곳에 둔다.** 화면마다 따로 조합하면 같은 전표가 화면마다 다른
// 번호로 보인다 — 전체화면(F-4)이 이미 그 이유로 서버 id 기준으로 옮겨 왔는데, 검토
// 워크스페이스가 자기 식으로 다시 만들면 원위치다.
import { useEffect, useState } from 'react'
import { won } from '../../lib/format'
import { endpoints } from '../../api/client'
import { SkeletonLines } from '../ui/Skeleton'

export interface VoucherPayload {
  settlement_id?: number
  merchant?: string
  amount?: number
  category?: string
  date?: string
  drafted_at?: string
}

export interface Voucher {
  id: number
  settlement: number
  voucherPayload: VoucherPayload
  status: string
  created_at: string
}

/** 전표번호 — **서버가 만든 id 기준**이다. 날짜·정산번호를 화면에서 조합하지 않는다. */
export function voucherNoOf(v: Voucher): string {
  const p = v.voucherPayload ?? {}
  const day = (p.date ?? v.created_at.slice(0, 10)).replace(/-/g, '')
  return `V-${day}-${String(v.id).padStart(4, '0')}`
}

type State =
  | { kind: 'LOADING' }
  | { kind: 'OK'; voucher: Voucher }
  | { kind: 'NONE' }      // 404 — 아직 전표가 없다(확정 전)
  | { kind: 'ERROR' }     // 못 불러왔다

/** 정산 id로 전표를 읽어 온다. **「없다」와 「못 불러왔다」를 구분**해서 돌려준다. */
export function useVoucher(settlementId: string | undefined): State {
  const [state, setState] = useState<State>({ kind: 'LOADING' })
  useEffect(() => {
    if (!settlementId) return
    let alive = true
    setState({ kind: 'LOADING' })
    void (async () => {
      try {
        const { data } = await endpoints.erpVoucherBySettlement(settlementId)
        if (alive) setState({ kind: 'OK', voucher: data })
      } catch (e: unknown) {
        if (!alive) return
        const status = (e as { response?: { status?: number } })?.response?.status
        setState({ kind: status === 404 ? 'NONE' : 'ERROR' })
      }
    })()
    return () => { alive = false }
  }, [settlementId])
  return state
}

/** 전표 본문 — 카드 껍데기는 부르는 쪽이 씌운다(검토 워크스페이스는 자기 카드 안에 넣는다). */
export function VoucherBody({ voucher, compact = false }: { voucher: Voucher; compact?: boolean }) {
  const p = voucher.voucherPayload ?? {}
  const amount = p.amount ?? 0
  const category = p.category || '미분류'

  return (
    <>
      <div className="stack">
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <span className="text-meta">전표번호</span><b>{voucherNoOf(voucher)}</b>
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
          <span className="text-meta">생성 시각</span>
          <b>{(p.drafted_at ?? voucher.created_at).replace('T', ' ').slice(0, 16)}</b>
        </div>
      </div>

      <div className="text-meta" style={{ fontWeight: 700, margin: '14px 0 6px' }}>회계 분개 (차변 / 대변)</div>
      <table className="table">
        <thead><tr><th>구분</th><th>계정과목</th><th className="num">금액</th></tr></thead>
        <tbody>
          <tr><td><b>차변</b></td><td>{category}</td><td className="num">{won(amount)}</td></tr>
          <tr><td><b>대변</b></td><td>미지급금(법인카드)</td><td className="num">{won(amount)}</td></tr>
        </tbody>
      </table>

      {/*  계정과목이 비용 분류에서 **매핑된 초안**이라는 것을 밝힌다 — 정식 계정과목 테이블은
          두지 않았고(회사마다 다르다), 최종 확정은 ERP에서 회계가 한다. */}
      <div className={compact ? 'text-meta' : 'note'} style={{ marginTop: 10, lineHeight: 1.6 }}>
        계정과목은 비용 분류({category}) 기준으로 매핑된 <b>초안</b>입니다. 실제 ERP 적재·연동은 MVP 범위 밖이며,
        최종 계정 확정은 회계 담당자가 ERP에서 수행합니다.
      </div>
    </>
  )
}

/** 정산 id만 주면 알아서 읽고 그린다. 상태별 안내 문구까지 포함. */
export function VoucherPanel({ settlementId }: { settlementId: string }) {
  const state = useVoucher(settlementId)

  if (state.kind === 'LOADING') {
    return (
      <>
        <span className="text-meta">전표를 불러오는 중…</span>
        <div style={{ marginTop: 8 }}><SkeletonLines rows={4} /></div>
      </>
    )
  }
  //  **「없다」와 「못 불러왔다」를 같은 문장으로 덮지 않는다.** 전자는 정상(확정 전),
  //  후자는 장애다 — 담당자가 새로고침해야 할지 기다려야 할지가 갈린다.
  if (state.kind === 'NONE') {
    return <p className="text-meta" style={{ margin: 0 }}>아직 생성된 ERP 전표(안)가 없습니다. 회계 확정 후 자동으로 만들어집니다.</p>
  }
  if (state.kind === 'ERROR') {
    return <p className="text-meta" style={{ margin: 0, color: 'var(--tone-amber)' }}>전표를 불러오지 못했습니다.</p>
  }
  return <VoucherBody voucher={state.voucher} compact />
}

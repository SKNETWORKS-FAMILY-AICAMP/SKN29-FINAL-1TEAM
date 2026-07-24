// S-03 검토 워크스페이스 — 회계 담당자. (Figma v3)
// FR-UI-03, FR-RR-01~08, FR-RL-01~02, FR-DB-04
// 레이아웃: 좌측 Review List(탭 필터) + 우측 상세 패널(master-detail)
// KPI는 페이지 헤더 우상단 인라인 배지로 표시 (Figma v3 기준)
import { useState } from 'react'
import { ChevronDown, ChevronUp, FileText, Paperclip, Receipt } from 'lucide-react'
import type { ReviewItem } from '../types/domain'
import { won } from '../lib/format'
import { LabeledBar } from '../components/ui/MiniChart'
import { reviewSettlement } from '../api/settlementService'
import { useSettlements } from '../context/SettlementsContext'
import { activateOnEnterOrSpace } from '../lib/a11y'

type ReviewTab = 'ALL' | 'APPROVE' | 'RETURN' | 'REJECT'

const RECO_META: Record<ReviewItem['aiRecommendation'], { label: string; color: string; bg: string }> = {
  APPROVE: { label: '승인', color: 'var(--tone-green)', bg: 'var(--tone-green-bg)' },
  RETURN: { label: '보완요청', color: 'var(--tone-orange)', bg: 'var(--tone-orange-bg)' },
  REJECT: { label: '반려', color: 'var(--tone-red)', bg: 'var(--tone-red-bg)' },
}

function ScoreBadge({ score }: { score: number }) {
  const pct100 = Math.round(score * 100)
  const color = score >= 0.8 ? 'var(--tone-red)' : score >= 0.6 ? 'var(--tone-orange)' : 'var(--tone-amber)'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 80 }}>
      <span style={{ fontSize: 16, fontWeight: 800, color, fontVariantNumeric: 'tabular-nums' }}>{pct100}%</span>
      <div style={{ flex: 1, height: 6, background: 'var(--surface-2)', borderRadius: 999, overflow: 'hidden' }}>
        <div style={{ width: `${pct100}%`, height: '100%', background: color }} />
      </div>
    </div>
  )
}

function RecoTag({ reco }: { reco: ReviewItem['aiRecommendation'] }) {
  const m = RECO_META[reco]
  return (
    <span style={{ fontSize: 11, fontWeight: 700, padding: '2px 7px', borderRadius: 999, background: m.bg, color: m.color, whiteSpace: 'nowrap' }}>
      추천: {m.label}
    </span>
  )
}

function DetailPanel({ item, onDecide, busy }: { item: ReviewItem; onDecide: (d: 'APPROVE' | 'RETURN' | 'REJECT') => void; busy: boolean }) {
  const [showTrail, setShowTrail] = useState(false)
  const needsExtra = item.cardType === 'SHARED' || item.cardType === 'TEAM'

  return (
    <div className="stack-lg">
      {/* 상단 기본정보 */}
      <div className="card">
        <div className="card-head" style={{ justifyContent: 'space-between' }}>
          <div>
            <span style={{ fontWeight: 700, fontSize: 15 }}>선택 건 상세 — {item.user} ({item.department ?? '-'}) · {won(item.amount)} · {item.aiCategory}</span>
          </div>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.6fr', gap: 0 }}>
          {/* 영수증 이미지 영역 */}
          <div style={{ borderRight: '1px solid var(--border)', padding: 16, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: 180, background: 'var(--surface-2)', gap: 8, color: 'var(--muted)' }}>
            <Receipt size={28} color="var(--border-strong)" />
            <span className="text-meta">영수증 이미지 부어</span>
            <span style={{ fontSize: 10, color: 'var(--muted)' }}>(확대/축소 · 회전)</span>
          </div>
          {/* 필드 정보 */}
          <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 10 }}>
            <FieldRow label="가맹점" value={<>{item.merchant} <span style={{ fontSize: 11, color: 'var(--tone-green)', fontWeight: 600 }}>(AI 판독값 ✓)</span></>} />
            <FieldRow label="일시" value={item.date + ' 19:20'} />
            <FieldRow label="금액" value={won(item.amount)} />
            <FieldRow
              label="카드구분"
              value={needsExtra
                ? <span style={{ color: 'var(--tone-orange)', fontWeight: 600 }}>공용카드 → 실사용자 입력 필요</span>
                : item.cardType}
            />
            <FieldRow
              label="비용분류"
              value={<span style={{ background: 'var(--ai-soft)', color: 'var(--ai)', border: '1px solid #f0dfae', borderRadius: 4, padding: '1px 7px', fontSize: 12, fontWeight: 600 }}>[{item.aiCategory}] ● AI 제안 (변경 가능)</span>}
            />
            {item.purpose && <FieldRow label="지출목적/사유" value={item.purpose} />}
          </div>
        </div>
        {/* 상태 변경 이력 토글 */}
        {item.auditTrail && item.auditTrail.length > 0 && (
          <div style={{ borderTop: '1px solid var(--border)' }}>
            <button
              onClick={() => setShowTrail((v) => !v)}
              style={{ width: '100%', background: 'none', border: 'none', padding: '8px 16px', display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--muted)', cursor: 'pointer' }}
            >
              <FileText size={12} />
              <span>↕ 상태 변경 이력</span>
              {showTrail ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            </button>
            {showTrail && (
              <div style={{ padding: '0 16px 14px' }}>
                <ul className="timeline">
                  {item.auditTrail.map((ev, i) => (
                    <li key={i}>
                      <div style={{ fontSize: 12 }}>{ev.status}{ev.note ? ` — ${ev.note}` : ''}</div>
                      <div className="t-meta">{ev.actor} · {ev.timestamp}</div>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>

      {/* ① 이상탐지 결과 */}
      <div className="card">
        <div className="card-head">
          <h3>① 이상탐지 결과</h3>
          <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--tone-purple)', background: 'var(--tone-purple-bg)', padding: '3px 10px', borderRadius: 999 }}>
            anomaly {item.anomalyScore.toFixed(2)}
          </span>
        </div>
        <div className="card-body">
          <div className="text-meta" style={{ marginBottom: 10 }}>Feature 기여도 (이상 신호 유발 요인)</div>
          <div className="stack">
            {item.featureContribs.map((f) => (
              <LabeledBar key={f.feature} label={f.feature} value={f.weight} labelWidth={160} color="var(--tone-purple)" />
            ))}
          </div>
        </div>
      </div>

      {/* ② RAG 내규 검증 */}
      {item.ragRefs.length > 0 && (
        <div className="card">
          <div className="card-head">
            <h3>② RAG 내규 검증</h3>
            <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--tone-teal)', background: 'var(--tone-teal-bg)', padding: '2px 8px', borderRadius: 999 }}>근거 {item.ragRefs.length}건</span>
          </div>
          <div className="card-body">
            <ul className="evidence-list">
              {item.ragRefs.map((r) => (
                <li key={r.source}>
                  <div style={{ fontSize: 13 }}>{r.title}</div>
                  <div className="src row" style={{ gap: 4, marginTop: 4 }}>
                    <Paperclip size={11} />
                    <span style={{ color: 'var(--primary)', cursor: 'pointer', fontSize: 11 }}>{r.source} (원문 보기)</span>
                  </div>
                </li>
              ))}
            </ul>
            {item.ragRefs.length > 0 && (
              <div style={{ marginTop: 10, padding: '8px 10px', background: 'var(--surface-2)', borderRadius: 6, fontSize: 12, color: 'var(--muted)' }}>
                유사사례 DB 바로가기 →
              </div>
            )}
          </div>
        </div>
      )}

      {/* AI 권장 의견 */}
      <div style={{ padding: '12px 16px', background: RECO_META[item.aiRecommendation].bg, border: `1px solid ${RECO_META[item.aiRecommendation].color}44`, borderRadius: 'var(--radius-control)' }}>
        <span style={{ fontWeight: 700, color: RECO_META[item.aiRecommendation].color }}>
          AI 권장의견 : {RECO_META[item.aiRecommendation].label}({item.aiRecommendation})
        </span>
        <span className="text-meta" style={{ marginLeft: 10 }}>한번 더 확인해주세요.</span>
      </div>

      {/* 액션 버튼 3종 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8 }}>
        <button className="btn approve" disabled={busy} onClick={() => onDecide('APPROVE')} style={{ justifyContent: 'center', padding: '10px' }}>
          ✓ 승인
        </button>
        <button className="btn return" disabled={busy} onClick={() => onDecide('RETURN')} style={{ justifyContent: 'center', padding: '10px' }}>
          🔶 보완요청
        </button>
        <button className="btn reject" disabled={busy} onClick={() => onDecide('REJECT')} style={{ justifyContent: 'center', padding: '10px' }}>
          ✕ 반려(최종)
        </button>
      </div>
      <div className="text-meta" style={{ fontSize: 11 }}>결정 결과 → decision_labels 적재 (MVP 재학습 미적용, post-MVP 지도학습 대비 저장만 수행)</div>
    </div>
  )
}

function FieldRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '80px 1fr', gap: 8, alignItems: 'flex-start' }}>
      <span className="text-meta" style={{ paddingTop: 2 }}>{label}</span>
      <span style={{ fontSize: 13 }}>{value}</span>
    </div>
  )
}

export function ReviewWorkspace() {
  const { reviewItems: items, updateStatus } = useSettlements()
  const [selId, setSelId] = useState(items[0]?.id)
  const [busy, setBusy] = useState(false)
  const [activeTab, setActiveTab] = useState<ReviewTab>('ALL')

  const pending = [...items].filter((i) => i.status === 'IN_REVIEW').sort((a, b) => b.anomalyScore - a.anomalyScore)

  const tabCounts = {
    ALL: pending.length,
    APPROVE: pending.filter((i) => i.aiRecommendation === 'APPROVE').length,
    RETURN: pending.filter((i) => i.aiRecommendation === 'RETURN').length,
    REJECT: pending.filter((i) => i.aiRecommendation === 'REJECT').length,
  }

  const visibleList = activeTab === 'ALL' ? pending : pending.filter((i) => i.aiRecommendation === activeTab)
  const sel = pending.find((i) => i.id === selId) ?? pending[0]

  const decide = async (decision: 'APPROVE' | 'RETURN' | 'REJECT') => {
    if (!sel) return
    setBusy(true)
    const status = await reviewSettlement(sel.id, decision)
    updateStatus(sel.id, status)
    const next = pending.find((i) => i.id !== sel.id)
    if (next) setSelId(next.id)
    setBusy(false)
  }

  const TAB_LABEL: Record<ReviewTab, string> = {
    ALL: `전체 ${tabCounts.ALL}`,
    APPROVE: `✓ 승인 ${tabCounts.APPROVE}`,
    RETURN: `📋 보완요청 ${tabCounts.RETURN}`,
    REJECT: `✕ 반려 ${tabCounts.REJECT}`,
  }

  return (
    <>
      {/* 페이지 헤더 — KPI 배지를 우상단 인라인으로 (Figma v3) */}
      <div className="page-head row" style={{ justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
        <div>
          <span className="screen-id">S-03</span>
          <h1>검토 워크스페이스</h1>
        </div>
        <div className="row" style={{ gap: 20, flexShrink: 0 }}>
          <KpiBadge label="자동처리율" value="82%" />
          <KpiBadge label="검토대기" value={`${pending.length}건`} warn={pending.length > 10} />
          <KpiBadge label="평균검토시간" value="6.2분" />
        </div>
      </div>

      {/* 2단계 파이프라인 안내 — 카드 대신 인라인 배너 */}
      <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 16, display: 'flex', gap: 8, alignItems: 'center' }}>
        <span style={{ fontWeight: 600 }}>2단계 파이프라인:</span>
        <span style={{ color: 'var(--tone-purple)', fontWeight: 600 }}>① 이상탐지(비지도, anomaly_score)</span>
        <span>→</span>
        <span style={{ color: 'var(--tone-teal)', fontWeight: 600 }}>② RAG 내규검증(① 이상 후보 건에 한정)</span>
      </div>

      {pending.length === 0 ? (
        <div className="card"><div className="card-body text-meta">검토 대기 중인 건이 없습니다.</div></div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: '360px 1fr', gap: 16, alignItems: 'start' }}>
          {/* 좌측: Review List */}
          <div className="card">
            <div className="card-head" style={{ flexDirection: 'column', alignItems: 'stretch', gap: 8 }}>
              <h3>Review List</h3>
              <div className="row" style={{ gap: 4 }}>
                {(['ALL', 'APPROVE', 'RETURN', 'REJECT'] as ReviewTab[]).map((t) => (
                  <button
                    key={t}
                    className={'btn sm' + (activeTab === t ? ' primary' : '')}
                    style={{ fontSize: 11, padding: '3px 8px' }}
                    onClick={() => setActiveTab(t)}
                  >
                    {TAB_LABEL[t]}
                  </button>
                ))}
              </div>
            </div>
            <div style={{ maxHeight: 'calc(100vh - 260px)', overflowY: 'auto' }}>
              {visibleList.map((i) => (
                <div
                  key={i.id}
                  tabIndex={0}
                  onClick={() => setSelId(i.id)}
                  onKeyDown={activateOnEnterOrSpace(() => setSelId(i.id))}
                  style={{
                    padding: '12px 16px', borderBottom: '1px solid var(--border)', cursor: 'pointer',
                    background: sel?.id === i.id ? 'var(--primary-soft)' : undefined,
                    transition: 'background 150ms',
                  }}
                >
                  <div className="row" style={{ justifyContent: 'space-between', marginBottom: 4 }}>
                    <ScoreBadge score={i.anomalyScore} />
                    <RecoTag reco={i.aiRecommendation} />
                  </div>
                  <div style={{ fontWeight: 600, fontSize: 13 }}>{i.user}</div>
                  <div className="text-meta">{i.department ?? ''}</div>
                  <div className="row" style={{ justifyContent: 'space-between', marginTop: 4 }}>
                    <span className="text-meta" style={{ fontSize: 11 }}>{i.merchant}</span>
                    <span style={{ fontSize: 13, fontWeight: 600 }}>{won(i.amount)}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* 우측: 상세 패널 */}
          {sel ? (
            <DetailPanel key={sel.id} item={sel} onDecide={decide} busy={busy} />
          ) : (
            <div className="card"><div className="card-body text-meta">목록에서 건을 선택하세요.</div></div>
          )}
        </div>
      )}
    </>
  )
}

function KpiBadge({ label, value, warn }: { label: string; value: string; warn?: boolean }) {
  return (
    <div style={{ textAlign: 'right' }}>
      <div className="text-meta" style={{ fontSize: 10, fontWeight: 600 }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 800, color: warn ? 'var(--tone-red)' : 'var(--text)', fontVariantNumeric: 'tabular-nums' }}>{value}</div>
    </div>
  )
}

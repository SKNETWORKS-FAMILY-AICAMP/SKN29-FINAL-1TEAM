// 문서 관리 화면(S-05)의 「결정 사례」 — 월별 묶음 + 그 달의 사례 목록.
//
// ## 왜 문서(PolicyDoc)가 아닌가
//
// 사례는 문서가 아니다. 결정 시점에 이미 `case_history`에 적재돼 있어서 문서 파이프라인
// (파싱 → 청킹 → 임베딩 → `policy_docs`)에 태우면 **같은 내용이 두 컬렉션에 이중 적재**되고
// 검색이 자기 자신과 겹친다. `PolicyDoc`은 파일 전제라 원문보기·재색인 버튼도 빈 껍데기가 된다.
// 그래서 트리에 자리만 만들고 내용은 `DecisionCase`를 직접 읽는다.
//
// ## 왜 월별인가
//
// 1건 = 1항목이면 트리가 금세 수백 줄이 된다. 반대로 전부 한 덩어리면 "언제 결정한
// 사례인가"를 못 고른다. 결정은 월 단위로 몰려서 검토·집계되므로(팀 통계·검토 이력이 이미
// 이번 달 기준이다) 월이 자연스러운 묶음이다.
import { useEffect, useState } from 'react'
import { AlertTriangle, FolderOpen, Scale } from 'lucide-react'
import { won } from '../../lib/format'
import { endpoints } from '../../api/client'
import { SkeletonLines } from '../../components/ui/Skeleton'

interface CaseMonth { key: string; count: number; indexed: number }

interface DecisionCaseRow {
  id: number
  caseId: string
  category: string
  outcome: string
  expected: string
  divergedFrom: 'AI' | 'RULE'
  reason: string
  text: string
  facts: Record<string, unknown>
  ruleFlags: string[]
  citation: string
  decidedBy: string
  decidedAt: string
  settlementId: number | null
  indexed: boolean
  indexError: string
}

const OUTCOME_LABEL: Record<string, string> = { APPROVE: '승인', RETURN: '보완요청', REJECT: '반려' }
const OUTCOME_TONE: Record<string, string> = {
  APPROVE: 'var(--tone-green)', RETURN: 'var(--tone-amber)', REJECT: 'var(--tone-red)',
}

export function useDecisionCases(month: string, enabled: boolean) {
  const [months, setMonths] = useState<CaseMonth[]>([])
  const [cases, setCases] = useState<DecisionCaseRow[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!enabled) return
    let alive = true
    setLoading(true)
    void (async () => {
      try {
        const { data } = await endpoints.decisionCases(month || undefined)
        if (!alive) return
        setMonths(data.months ?? [])
        setCases(data.cases ?? [])
        setTotal(data.total ?? 0)
      } finally {
        if (alive) setLoading(false)
      }
    })()
    return () => { alive = false }
  }, [month, enabled])

  return { months, cases, total, loading }
}

export function DecisionCasePanel({ month, months, cases, total, loading }: {
  month: string
  months: CaseMonth[]
  cases: DecisionCaseRow[]
  total: number
  loading: boolean
}) {
  return (
    <>
      <div className="pd-preview-head">
        <div className="row" style={{ gap: 8, alignItems: 'center' }}>
          <Scale size={16} />
          <b style={{ fontSize: 15 }}>결정 사례 {month ? `· ${monthLabel(month)}` : '(전체)'}</b>
          <span className="pd-badge gray">{cases.length}건 / 전체 {total}건</span>
        </div>
      </div>

      <div className="card-body">
        {/* 항상 똑같이 뜨는 고정 설명문 — 매번 박스로 띄우면 아래 실제 사례 목록과
            같은 무게로 경쟁한다(별표 섹션 캡션과 같은 이유). 캡션 한 줄로 낮춘다. */}
        <div className="text-meta" style={{ marginBottom: 14 }}>
          회계 담당자가 AI 권고·룰 판정과 다르게 판단한 건과 그 사유예요. 다음에 비슷한 건을
          검토할 때 검색 근거로 인용돼요 — 권고대로 처리한 건은 남기지 않아요.
        </div>

        {loading ? (
          <SkeletonLines rows={4} />
        ) : cases.length === 0 ? (
          <div className="pd-empty">
            <FolderOpen size={32} aria-hidden />
            <b>{months.length === 0 ? '아직 기록된 결정 사례가 없습니다' : '이 달에 기록된 사례가 없습니다'}</b>
            <p className="text-meta">
              검토 화면에서 AI 권고와 <b>다른 판단</b>을 내리고 사유를 남기면 이곳에 쌓입니다.
            </p>
          </div>
        ) : (
          <div className="stack" style={{ gap: 10 }}>
            {cases.map((c) => <CaseCard key={c.id} item={c} />)}
          </div>
        )}
      </div>
    </>
  )
}

function CaseCard({ item }: { item: DecisionCaseRow }) {
  const amount = Number(item.facts?.amount ?? 0)
  return (
    <div style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius-control)', padding: '12px 14px' }}>
      <div className="row" style={{ justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
        <div style={{ minWidth: 0 }}>
          <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
            {/* 무엇과 다른 판단이었는지가 사례의 정체다 — 결과만 보면 그냥 결정 기록이 된다. */}
            <span className="tag">{item.divergedFrom === 'AI' ? 'AI 권고' : '룰 판정'}: {OUTCOME_LABEL[item.expected] ?? item.expected}</span>
            <span style={{ color: 'var(--muted)' }}>→</span>
            <span className="tag" style={{ color: OUTCOME_TONE[item.outcome], borderColor: OUTCOME_TONE[item.outcome] }}>
              회계 {OUTCOME_LABEL[item.outcome] ?? item.outcome}
            </span>
            {item.category && <span className="tag">{item.category}</span>}
            {!item.indexed && (
              <span className="tag caution" title={item.indexError || '아직 검색 근거로 올라가지 않았습니다'}>
                <AlertTriangle size={11} /> 미적재
              </span>
            )}
          </div>
          <div style={{ fontSize: 13, marginTop: 8, lineHeight: 1.55 }}>{item.reason}</div>
          <div className="text-meta" style={{ marginTop: 6 }}>
            {String(item.facts?.merchant ?? '')} {amount > 0 && `· ${won(amount)}`}
            {item.ruleFlags.length > 0 && ` · 판정 사유 ${item.ruleFlags.length}건`}
          </div>
        </div>
        <div className="text-meta" style={{ textAlign: 'right', flexShrink: 0 }}>
          {/* 처리자 — 사례를 읽는 사람의 첫 질문이다. */}
          <div><b>{item.decidedBy || '알 수 없음'}</b></div>
          <div>{item.decidedAt.replace('T', ' ').slice(0, 16)}</div>
          <div style={{ fontFamily: 'monospace', fontSize: 11 }}>{item.citation}</div>
        </div>
      </div>
    </div>
  )
}

export function monthLabel(key: string): string {
  const [y, m] = key.split('-')
  return `${y}년 ${Number(m)}월`
}

// 룰 엔진 판정 결과 — 상세 모달의 접기/펼치기 패널(fact.json 바로 아래).
//
// **fact.json이 "무엇을 입력했나"라면 여기는 "그래서 어떻게 판정됐나"다.** 둘이 나란히
// 있어야 사후에 "이 값으로 왜 이 결론이 나왔는지"를 한 화면에서 되짚을 수 있다.
//
// 세 가지 규율을 화면에서도 지킨다:
//  ① **판정 전과 통과는 다르다.** 판정이 안 돈 건을 "정상"으로 접지 않는다.
//  ② **상태를 정하는 축은 `decision` 하나다.** 플래그는 사유 설명이지 결정이 아니다 —
//     그래서 판정 배지와 플래그를 시각적으로 분리하고, 플래그가 판정을 덮어쓰는 것처럼
//     보이지 않게 한다(`policies/flags.py`의 불변식).
//  ③ **라벨 사전을 여기 두지 않는다.** 심각도·해소주체·분류의 한글 표기는 서버가 실어
//     보낸 값(`ruleFlagInfo`)을 그대로 쓴다. 프론트가 사전을 복사하면 반드시 어긋난다
//     (실제로 백엔드 27개 vs 프론트 9개로 어긋나 있었다).
import { useEffect, useState } from 'react'
import { ChevronDown, ChevronRight, ShieldCheck } from 'lucide-react'
import type { RuleDecision, RuleFlagInfo, Settlement } from '../../types/domain'
import { decisionLabel } from '../../lib/judgement'
import { fetchSettlementDetail } from '../../api/settlementService'

/** 판정 배지 색 — 통과/보완/위반/검토를 한눈에 가른다. */
const DECISION_TONE: Record<RuleDecision, { color: string; bg: string }> = {
  PASS: { color: 'var(--tone-green)', bg: 'var(--tone-green-bg)' },
  RETURN: { color: 'var(--tone-amber)', bg: 'var(--tone-amber-bg)' },
  REJECT: { color: 'var(--tone-red)', bg: 'var(--tone-red-bg)' },
  REVIEW: { color: 'var(--tone-blue)', bg: 'var(--tone-blue-bg)' },
}

/** 심각도 색 — 서버 enum 순서(CRITICAL…INFO)와 같은 축. */
const SEVERITY_COLOR: Record<string, string> = {
  CRITICAL: 'var(--tone-red)',
  HIGH: 'var(--tone-red)',
  MEDIUM: 'var(--tone-amber)',
  LOW: 'var(--tone-blue)',
  INFO: 'var(--muted)',
}

interface RuleHit {
  graph: string | null
  graphVersion: number
  path: string[]
  decision: string
  flags?: string[]
  confidence: number
}

export function RuleJudgementPanel({ item }: { item: Settlement }) {
  const [open, setOpen] = useState(false)
  const [hits, setHits] = useState<RuleHit[] | null>(null)
  const [loadingHits, setLoadingHits] = useState(false)

  const judged = Boolean(item.ruleDecision)
  const decision = item.ruleDecision as RuleDecision | undefined
  const flags = item.ruleFlagInfo ?? []

  // 실행 경로(`ruleHits`)는 상세 응답에만 있다 — **펼쳤을 때 한 번만** 가져온다.
  // 접혀 있는데 미리 불러오면 목록을 여는 것만으로 매번 상세 요청이 나간다.
  useEffect(() => {
    if (!open || !judged || hits !== null || loadingHits) return
    setLoadingHits(true)
    void (async () => {
      try {
        const detail = await fetchSettlementDetail(item)
        setHits((detail as Settlement).ruleHits ?? [])
      } catch {
        setHits([])   // 실행 경로를 못 불러와도 플래그는 이미 보인다 — 패널을 죽이지 않는다.
      } finally {
        setLoadingHits(false)
      }
    })()
  }, [open, judged, hits, loadingHits, item])

  const tone = decision ? DECISION_TONE[decision] : null

  return (
    <div className="card">
      <button
        className="card-head"
        style={{ width: '100%', background: 'none', border: 'none', cursor: 'pointer' }}
        onClick={() => setOpen((v) => !v)}
      >
        <h3 style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
          <ShieldCheck size={14} /> 룰 엔진 판정
        </h3>
        <span className="row" style={{ gap: 6 }}>
          {judged && tone
            ? <span className="badge" style={{ color: tone.color, background: tone.bg }}>{decisionLabel(decision)}</span>
            : <span className="text-meta">판정 전</span>}
          {flags.length > 0 && <span className="text-meta">사유 {flags.length}건</span>}
        </span>
      </button>

      {open && (
        <div className="card-body">
          {/* ① 판정 전을 "정상"으로 접지 않는다 — 검사 안 한 것과 통과는 다르다. */}
          {!judged ? (
            <div className="text-meta">
              아직 룰 판정이 돌지 않았습니다. 팀에 올리거나 제출하면 규칙 검사가 실행되고,
              그 결과와 사유가 여기에 기록됩니다.
            </div>
          ) : (
            <>
              <div className="row" style={{ justifyContent: 'space-between', marginBottom: 12 }}>
                <span className="text-meta">판정 시각</span>
                <span style={{ fontSize: 12.5 }}>
                  {item.ruleJudgedAt ? item.ruleJudgedAt.replace('T', ' ').slice(0, 16) : '-'}
                </span>
              </div>

              {/* ② 판정과 사유는 다른 축이다. 사유가 없어도 판정은 유효하다. */}
              {flags.length === 0 ? (
                <div className="note">
                  {decision === 'PASS'
                    ? '모든 확인 항목을 통과했습니다 — 별도 사유 코드가 붙지 않았습니다.'
                    : '판정은 났지만 사유 코드가 기록되지 않았습니다.'}
                </div>
              ) : (
                <div className="stack" style={{ gap: 8 }}>
                  {flags.map((f) => <FlagRow key={f.flag} flag={f} />)}
                </div>
              )}

              <ExecutionPath hits={hits} loading={loadingHits} />

              <div className="text-meta" style={{ marginTop: 12 }}>
                사유 코드는 <b>왜 걸렸는지</b>에 대한 설명입니다 — 처리 상태를 정하는 건 판정
                결과 한 축이며, 최종 반려는 회계 담당자만 할 수 있습니다.
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}

function FlagRow({ flag }: { flag: RuleFlagInfo }) {
  const color = SEVERITY_COLOR[flag.severity] ?? 'var(--muted)'
  return (
    <div style={{ background: 'var(--surface-2)', borderRadius: 'var(--radius-control)', padding: '10px 12px' }}>
      <div className="row" style={{ justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700 }}>
            {flag.label}
            {/* 미등록 코드를 감추지 않는다 — 숨기면 오타를 아무도 못 본다. */}
            {!flag.known && <span className="tag caution" style={{ marginLeft: 6 }}>미등록 코드</span>}
            {flag.isSystem && <span className="tag" style={{ marginLeft: 6 }}>엔진</span>}
          </div>
          {/* 코드는 데이터 계약이라 표기와 함께 그대로 보여준다(집계·문의의 키가 된다). */}
          <div className="text-meta" style={{ fontFamily: 'monospace', fontSize: 11 }}>{flag.flag}</div>
        </div>
        <div className="row" style={{ gap: 6, flexShrink: 0 }}>
          {flag.severity && (
            <span className="badge" style={{ color, background: 'transparent', border: `1px solid ${color}` }}>
              {flag.severityLabel || flag.severity}
            </span>
          )}
          {(flag.ownerLabel || flag.owner) && (
            <span className="tag">{flag.ownerLabel || flag.owner}</span>
          )}
        </div>
      </div>
      {flag.description && (
        <div style={{ fontSize: 12.5, lineHeight: 1.5, marginTop: 6 }}>{flag.description}</div>
      )}
      {/* 인자가 붙은 시스템 플래그(`UNRESOLVED_FACT:approval.pre_approval_obtained`)의 뒷부분 —
          "어떤 사실이 비어서 걸렸나"가 여기 있다. */}
      {flag.arg && (
        <div className="text-meta" style={{ marginTop: 4 }}>
          대상: <span style={{ fontFamily: 'monospace' }}>{flag.arg}</span>
        </div>
      )}
    </div>
  )
}

/** 어느 그래프의 어느 노드를 지나 판정이 났는가 — 게이트와 과목 그래프가 각각 한 행이다. */
function ExecutionPath({ hits, loading }: { hits: RuleHit[] | null; loading: boolean }) {
  if (loading) return <div className="text-meta" style={{ marginTop: 12 }}>실행 경로를 불러오는 중…</div>
  if (!hits || hits.length === 0) return null
  return (
    <div style={{ marginTop: 14 }}>
      <div className="text-meta" style={{ marginBottom: 6 }}>실행 경로</div>
      <div className="stack" style={{ gap: 6 }}>
        {hits.map((h, i) => (
          <div key={i} style={{ fontSize: 12, background: 'var(--surface-2)', borderRadius: 'var(--radius-control)', padding: '8px 10px' }}>
            <div className="row" style={{ justifyContent: 'space-between' }}>
              {/* 그래프가 없어도 한 행이 남는다 — "적용할 규칙이 없었다"는 것도 판정 기록이다. */}
              <b>{h.graph ?? '적용 그래프 없음'}{h.graph ? ` v${h.graphVersion}` : ''}</b>
              <span>{decisionLabel(h.decision as RuleDecision)}</span>
            </div>
            {h.path?.length > 0 && (
              <div className="text-meta" style={{ fontFamily: 'monospace', marginTop: 4, wordBreak: 'break-all' }}>
                {h.path.join(' → ')}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

// Active 요청 — 시뮬레이션·AI 의견 KPI를 확인하고 검토자 코멘트를 보고서 형식으로 남긴다.
//  실제 ACTIVE 전환은 룰 활성 권한자가 Active 그래프 탭에서 수행한다(자동 승인 금지).
import { useState } from 'react'
import { Modal } from '../../components/ui/Modal'
import { Markdown } from '../../components/ui/Markdown'
import { gradeTone, type Grade, type SimReport } from './data/simulationTypes'

const percent = (value: number) => `${(value * 100).toFixed(1)}%`

const TEMPLATE = `## 검토 의견
(시뮬레이션 결과를 어떻게 읽었는지 적어주세요.)

## 확인한 위험·변경건
-

## 활성화 판단
- `

export function ActivationRequestModal({ report, graphName, onClose, onSubmit, submitting, error }: {
  report: SimReport; graphName: string; onClose: () => void
  onSubmit: (comment: string) => void; submitting: boolean; error: string
}) {
  const [comment, setComment] = useState(TEMPLATE)
  const [preview, setPreview] = useState(false)
  const { stats, grades } = report

  return (
    <Modal title="Active 요청 — 검토자 코멘트" maxWidth={1080} onClose={onClose}
      footer={<>
        <span className="text-meta">요청하면 그래프가 승인대기로 전환되고, 최종 활성화는 룰 활성 권한자가 수행합니다.</span>
        <div className="spacer" />
        <button className="btn" onClick={onClose} disabled={submitting}>취소</button>
        <button className="btn approve" onClick={() => onSubmit(comment)} disabled={submitting || !comment.trim()}>
          {submitting ? '요청 중…' : 'Active 요청 보내기'}
        </button>
      </>}>
      <div className="stack" style={{ gap: 16 }}>
        <div className="text-meta">
          <b>{graphName}</b> v{report.graphVersion} · 시뮬레이션 {report.ranAt}
          {report.ranBy && ` · 실행 ${report.ranBy}`} · {report.periodLabel} 내역 {stats.historyTotal}건
          {report.stale && <span className="tag warn" style={{ marginLeft: 6 }}>실행 이후 그래프가 변경됨</span>}
        </div>

        <div>
          <div className="text-meta" style={{ fontWeight: 700, marginBottom: 6 }}>시뮬레이션 KPI</div>
          <div className="kpi-grid" style={{ gridTemplateColumns: 'repeat(4, 1fr)', marginBottom: 0 }}>
            <div className="kpi">
              <div className="label">자동처리율</div><div className="value">{percent(stats.autoRate)}</div>
              <div className="text-meta">자동 {stats.autoCount} / 사람 확인 {stats.manualCount}건</div>
            </div>
            <div className="kpi">
              <div className="label">검토 감소량</div>
              <div className="value" style={{ fontSize: 'var(--text-value)' }}>
                {percent(stats.prevAutoRate)} → {percent(stats.autoRate)}
              </div>
              <div className="text-meta">{stats.reviewReduction >= 0 ? '+' : ''}{(stats.reviewReduction * 100).toFixed(1)}%p</div>
            </div>
            <div className={'kpi ' + (stats.testGraded > 0 && stats.testFailed === 0 ? 'ok' : 'warn')}>
              <div className="label">테스트 수치</div>
              <div className="value">{stats.testPassed}/{stats.testGraded || stats.testTotal}</div>
              <div className="text-meta">불일치 {stats.testFailed}건</div>
            </div>
            <div className={'kpi ' + (stats.nodeCoverage >= 1 ? 'ok' : 'warn')}>
              <div className="label">노드 커버리지</div><div className="value">{percent(stats.nodeCoverage)}</div>
              <div className="text-meta">평가 {stats.visitedNodes}/{report.structure.nodeCount}개</div>
            </div>
          </div>
        </div>

        <div>
          <div className="text-meta" style={{ fontWeight: 700, marginBottom: 6 }}>AI 의견 KPI</div>
          <div className="kpi-grid" style={{ gridTemplateColumns: 'repeat(3, 1fr)', marginBottom: 0 }}>
            <GradeTile label="그래프 구조 평가" grade={grades.structure} />
            <GradeTile label="실행결과 평가" grade={grades.result} />
            <GradeTile label="권장 처리" grade={grades.action} />
          </div>
        </div>

        {stats.riskCount > 0 && (
          <div className="note" style={{ color: 'var(--tone-red)', borderColor: 'var(--tone-red)' }}>
            ⚠ 위험 {stats.riskCount}건 · 분류 변경 {stats.changedCount}건이 감지됐습니다. 코멘트에 확인 결과를 남겨주세요.
          </div>
        )}

        <div className="field" style={{ marginBottom: 0 }}>
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <label style={{ marginBottom: 0 }}>검토자 코멘트 (마크다운)</label>
            <div className="seg-toggle">
              <button className={preview ? '' : 'active'} onClick={() => setPreview(false)}>작성</button>
              <button className={preview ? 'active' : ''} onClick={() => setPreview(true)}>미리보기</button>
            </div>
          </div>
          {preview
            ? <div className="card" style={{ padding: 16, minHeight: 220 }}><Markdown source={comment} /></div>
            : <textarea rows={12} value={comment} onChange={(event) => setComment(event.target.value)}
                style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: 12.5 }} />}
        </div>

        {error && <div className="note" style={{ color: 'var(--tone-red)', borderColor: 'var(--tone-red)' }}>{error}</div>}
      </div>
    </Modal>
  )
}

function GradeTile({ label, grade }: { label: string; grade: Grade }) {
  return (
    <div className={'kpi ' + gradeTone(grade.level)}>
      <div className="label">{label}</div>
      <div className="value" style={{ fontSize: 'var(--text-value)' }}>{grade.label}</div>
      <div className="text-meta">{grade.note}</div>
    </div>
  )
}

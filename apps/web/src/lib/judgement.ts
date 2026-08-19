// 룰 판정 결과를 화면 표시로 옮기는 공용 규약.
//
// **왜 별도 모듈인가**: 예전엔 `data/mock.ts`의 `anomalyTags()`가 이 일을 했는데,
// 거기 있던 건 규정이 아니라 상수였다 — `amount >= 300000`(어느 규정에서도 오지 않은
// 숫자)과 `cardType === 'SHARED'`. 판정이 팀 취합 시점으로 앞당겨지면서 진짜 근거가
// 생겼으므로, mock 데이터가 아니라 서버 판정을 읽는다.
//
// **라벨 사전을 여기 두지 않는다**: 한때 이 파일이 `FLAG_LABEL` 9개를 들고 있었는데
// 백엔드 레지스트리는 27개였다 — 사전이 두 곳이면 반드시 어긋난다. 이제 서버가
// `ruleFlagInfo`로 라벨을 실어 보내고(`policies/flags.py`가 단일 원천), 여기서는
// 그게 없을 때만 코드 원문으로 폴백한다(감추면 판정 근거가 사라진다).
import type { RuleDecision, RuleFlagInfo, Settlement } from '../types/domain'

/** 룰이 그냥 통과시키지 않은 판정 — 팀장이 봐야 하는 건. */
const NEEDS_ATTENTION: RuleDecision[] = ['RETURN', 'REJECT', 'REVIEW']

const DECISION_LABEL: Record<RuleDecision, string> = {
  PASS: '통과', RETURN: '보완 필요', REJECT: '규정 위반', REVIEW: '검토 필요',
}

/** 심각도 정렬 키 — 검토 큐의 2차 정렬(anomaly_score만으로는 성격이 안 보인다). */
const SEVERITY_WEIGHT: Record<string, number> = {
  CRITICAL: 5, HIGH: 4, MEDIUM: 3, LOW: 2, INFO: 1,
}

export const decisionLabel = (d: RuleDecision | '' | undefined) =>
  d ? DECISION_LABEL[d] ?? d : '판정 전'

/** 아직 판정이 돌지 않은 건 — "정상"으로 접으면 안 된다(검사 안 한 것과 통과는 다르다). */
export const notJudged = (s: Settlement) => !s.ruleDecision

/** 룰이 걸어세운 건인가. 판정 전이면 false(모름) — 여기서 true로 접으면 전건이 이상건이 된다. */
export const needsAttention = (s: Settlement) =>
  !!s.ruleDecision && NEEDS_ATTENTION.includes(s.ruleDecision as RuleDecision)

/** 판정 사유 — 서버가 라벨을 붙여 보낸 것을 그대로 쓴다. */
export function judgementFlags(s: Settlement): RuleFlagInfo[] {
  if (!needsAttention(s)) return []
  if (s.ruleFlagInfo?.length) return s.ruleFlagInfo
  // 구버전 응답 폴백 — 라벨은 없어도 코드는 보여준다.
  return (s.ruleFlags ?? []).map((flag) => ({
    code: flag, arg: '', flag, label: flag, severity: '', owner: '', category: '', known: false,
  }))
}

/** 팀 화면 "판정 사유" 칩 문구. 사유가 없으면 판정 자체를 문구로 쓴다. */
export function judgementTags(s: Settlement): string[] {
  const flags = judgementFlags(s).map((f) => f.label)
  if (!needsAttention(s)) return []
  return flags.length > 0 ? flags : [decisionLabel(s.ruleDecision)]
}

/** 가장 심각한 사유의 가중치. 같은 판정끼리 순서를 매길 때 쓴다. */
export const worstSeverity = (s: Settlement) =>
  judgementFlags(s).reduce((max, f) => Math.max(max, SEVERITY_WEIGHT[f.severity] ?? 0), 0)

/** 이 건을 해소해야 하는 주체들 — 화면이 "고쳐주세요"와 "결재해주세요"를 가른다. */
export const flagOwners = (s: Settlement) =>
  [...new Set(judgementFlags(s).map((f) => f.owner).filter(Boolean))]

/** 결재로 풀리는 건인가 — 지출자가 고칠 게 아니라 결재권자가 승인해야 하는 사유. */
export const needsApproval = (s: Settlement) =>
  judgementFlags(s).some((f) => f.owner === 'APPROVER')

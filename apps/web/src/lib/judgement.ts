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

/**
 * 팀 취합에서 **이상 건**으로 다루는 판정 — 보완요청·반려 둘뿐이다.
 *
 * `REVIEW`는 여기 없다. 룰이 판단하지 못해 **회계 담당자에게 넘긴** 것이라 팀이 할 일이
 * 아니고, 팀이 붙들면 정작 봐야 할 사람에게 도달하지 못한다. 팀에서는 정상 건과 함께
 * 그대로 올려보내고 사유는 회계 검토 화면에서 본다.
 *
 * (기본 게이트가 걸린 건을 전부 REVIEW로 보내게 바뀐 뒤 한때 REVIEW까지 이상 건으로
 *  묶여 **모든 플래그 건이 팀에서 제출 불가**가 됐었다. 축을 둘로 나눠 봤지만 화면이
 *  복잡해져서, 이상 건의 정의 자체를 좁히는 쪽으로 되돌렸다.)
 */
const NEEDS_ATTENTION: RuleDecision[] = ['RETURN', 'REJECT']

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

/**
 * 팀 취합의 이상 건인가 — 보완요청·반려로 판정된 건. 표시·필터·카운트·제출 차단이
 * **전부 이 하나를 본다**(축을 나누면 화면마다 기준이 갈린다).
 *
 * 판정 전이면 false(모름) — 여기서 true로 접으면 전건이 이상건이 된다.
 */
export const needsAttention = (s: Settlement) =>
  !!s.ruleDecision && NEEDS_ATTENTION.includes(s.ruleDecision as RuleDecision)

/**
 * 판정이 남긴 사유 — 서버가 라벨을 붙여 보낸 것을 그대로 쓴다.
 *
 * **이상 건 여부와 별개다.** 검토(REVIEW)로 간 건도 왜 넘어갔는지 사유를 갖는다 —
 * 팀 화면에서 이상 건으로 세지 않을 뿐, 사유 자체를 없는 것으로 만들면 회계 검토
 * 화면·상세 패널이 근거를 잃는다. 통과(PASS) 건에만 붙지 않는다.
 */
export function judgementFlags(s: Settlement): RuleFlagInfo[] {
  if (!s.ruleDecision || s.ruleDecision === 'PASS') return []
  if (s.ruleFlagInfo?.length) return s.ruleFlagInfo
  // 구버전 응답 폴백 — 라벨은 없어도 코드는 보여준다.
  return (s.ruleFlags ?? []).map((flag) => ({
    code: flag, arg: '', flag, label: flag, severity: '', owner: '', category: '', known: false,
  }))
}

/**
 * 팀 화면 "판정 사유" 칩 문구. **이상 건에만 띄운다** — 검토로 갈 건은 팀에서 정상으로
 * 다루므로 칩을 달지 않는다(사유는 회계 검토 화면에서 본다). 사유가 없으면 판정 자체를 쓴다.
 */
export function judgementTags(s: Settlement): string[] {
  if (!needsAttention(s)) return []
  const flags = judgementFlags(s).map((f) => f.label)
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

// 룰 판정 결과를 화면 표시로 옮기는 공용 규약.
//
// **왜 별도 모듈인가**: 예전엔 `data/mock.ts`의 `anomalyTags()`가 이 일을 했는데,
// 거기 있던 건 규정이 아니라 상수였다 — `amount >= 300000`(어느 규정에서도 오지 않은
// 숫자)과 `cardType === 'SHARED'`. 판정이 팀 취합 시점으로 앞당겨지면서 진짜 근거가
// 생겼으므로, mock 데이터가 아니라 서버 판정을 읽는다.
import type { RuleDecision, Settlement } from '../types/domain'

/** 룰이 그냥 통과시키지 않은 판정 — 팀장이 봐야 하는 건. */
const NEEDS_ATTENTION: RuleDecision[] = ['RETURN', 'REJECT', 'REVIEW']

/** 사유 코드 → 사람이 읽을 문구. 미등록 코드는 코드 그대로 보여준다(숨기면 근거가 사라진다). */
const FLAG_LABEL: Record<string, string> = {
  NO_ACTIVE_RULE_GRAPH: '적용할 규칙 없음',
  NO_SCOPE_RULE_GRAPH: '과목 규칙 없음',
  INVALID_RULE_GRAPH: '규칙 그래프 오류',
  RULE_GRAPH_CYCLE: '규칙 순환',
  NO_TERMINAL_DECISION: '판정 미종결',
  PROHIBITED_MERCHANT: '금지 업종',
  PERSONAL_USE_SUSPECTED: '사적 사용 의심',
  MISSING_RECEIPT: '증빙 누락',
  MISSING_PURPOSE: '목적 미기재',
}

const DECISION_LABEL: Record<RuleDecision, string> = {
  PASS: '통과', RETURN: '보완 필요', REJECT: '규정 위반', REVIEW: '검토 필요',
}

/** 미해소 가드(`UNRESOLVED_POLICY_VAR:x`·`UNRESOLVED_FACT:a.b`)는 접두사 뒤에 경로가 붙는다. */
export function flagLabel(flag: string): string {
  if (flag.startsWith('UNRESOLVED_POLICY_VAR:')) return `규정 임계값 미적재(${flag.split(':')[1]})`
  if (flag.startsWith('UNRESOLVED_FACT:')) return `판정 정보 부족(${flag.split(':')[1]})`
  return FLAG_LABEL[flag] ?? flag
}

export const decisionLabel = (d: RuleDecision | '' | undefined) =>
  d ? DECISION_LABEL[d] ?? d : '판정 전'

/** 아직 판정이 돌지 않은 건 — "정상"으로 접으면 안 된다(검사 안 한 것과 통과는 다르다). */
export const notJudged = (s: Settlement) => !s.ruleDecision

/** 룰이 걸어세운 건인가. 판정 전이면 false(모름) — 여기서 true로 접으면 전건이 이상건이 된다. */
export const needsAttention = (s: Settlement) =>
  !!s.ruleDecision && NEEDS_ATTENTION.includes(s.ruleDecision as RuleDecision)

/** 팀 화면 "이상 사유" 칩. 판정 결과 + 사유 코드를 사람 문구로. */
export function judgementTags(s: Settlement): string[] {
  if (!needsAttention(s)) return []
  const flags = (s.ruleFlags ?? []).map(flagLabel)
  return flags.length > 0 ? flags : [decisionLabel(s.ruleDecision)]
}

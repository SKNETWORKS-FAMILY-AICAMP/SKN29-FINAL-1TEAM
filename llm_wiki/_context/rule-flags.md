# 네임드 플래그 (판정 사유 코드) — 구현 캐논

> 구현: `apps/core/domain/policies/flags.py` · 모델 `policies.RuleFlag` (마이그레이션 `0016`)
> 회귀: `apps/core/domain/policies/tests/test_flags.py`
> 관련: `_context/rule-engine.md`(엔진·EvalContext) · `_context/policy-domain.md`(별표)

---

## 1. 플래그란 무엇인가

플래그는 판정이 남기는 **사유 코드**다. "왜 걸렸는가"를 설명하며, 판정 결과(`decision`)에 딸린
부가 정보다.

```
판정 = decision(무엇으로 결정했나) + flags(왜 그렇게 결정했나) + path(어느 노드를 지났나)
```

한 판정에 **여러 개** 붙을 수 있고, `rule_hits.flags`와 `settlements.rule_judgement.flags`
양쪽에 남는다.

---

## 2. 불변식 — 플래그는 상태머신을 움직이지 않는다

**이 문서에서 가장 중요한 한 줄이다.**

정산 상태는 `decision`(PASS/RETURN/REJECT/REVIEW) **한 축**이 정한다
(`settlements/services.py::JUDGE_MAP`). 플래그가 상태를 바꾸기 시작하면 세 가지가 깨진다.

### ① 두 축이 충돌한다

`decision=PASS`인데 `flag=PRE_APPROVAL_MISSING`이면 무엇이 이기는가? 답이 없다.

더 나쁜 건 **작성자의 의도가 뒤집힌다**는 점이다. 룰 콘솔에서 `decision`은 의도해서 고르는
드롭다운이고, `flag`는 사유를 적는 입력 칸이다(`DraftTab.tsx`). 설명하려고 적은 글자가
자기가 고른 판정을 덮어쓰면 안 된다.

### ② 보이지 않는 간선이 생긴다

"노드 B는 A가 걸렸을 때만 돈다"를 플래그 조건으로 만들면, 그 의존이 **룰 콘솔 플로우차트에
그려지지 않는다**. 그래프를 보고도 실제 흐름을 알 수 없게 된다. 그런 의존은 라우팅 간선
(`A --MATCH--> B`)으로 표현하는 것이 이 도메인의 설계다.

지금은 문법적으로도 불가능하다 — `eval_context.validate_graph_vars`가 ACTIVE 전환 게이트로
걸려 있어 `EVAL_CONTEXT_SCHEMA_PATHS` 밖의 `var` 참조를 거부하고, `flags`는 그 목록에 없다.

### ③ 재현이 깨진다

판정은 `rule_hits.eval_context`(사실 스냅샷) + `graph_snapshot`(그래프 스냅샷+해시) 둘로
완전히 되돌릴 수 있게 설계돼 있다(FR-RA-08). 레지스트리가 **행동**을 가지면 스냅샷되지 않는
**세 번째 입력**이 생겨, admin에서 행 하나 고치면 과거 판정을 설명할 수 없게 된다.

### 그래서 레지스트리 행이 갖는 것

표시·분류 속성뿐이다 — `label` · `description` · `category` · `severity` · `owner`.

**"플래그는 아무것도 안 한다"가 아니라 "상태만 안 건드린다"** 이다. 경계 예: "`PRE_APPROVAL_MISSING`
이면 검토 화면에 「팀장 결재 요청」 버튼을 띄운다"는 **허용**이다. 상태는 어차피 `RETURNED`고
바뀌는 건 사람에게 보여주는 선택지뿐이다.

---

## 3. 두 계층

| | 시스템 플래그 | 룰 플래그 |
|---|---|---|
| 만드는 주체 | 엔진·오케스트레이터 | 룰 노드 `action.flag` |
| SoT | **닫힌 enum** `flags.SystemFlag` | **열린 레지스트리** `RuleFlag` 테이블 |
| 고객이 새로 만드나 | 불가 (코드 변경만) | **가능** (규정 문서 → Rule Agent) |
| 예 | `UNRESOLVED_FACT:*`, `NO_ACTIVE_RULE_GRAPH` | `PRE_APPROVAL_MISSING`, `DAILY_LIMIT_OVER` |

### 왜 룰 플래그를 닫지 않는가

제품 원칙과 정면으로 충돌하기 때문이다 — *"룰은 사전 탑재하지 않는다. 고객이 자사 규정
문서를 업로드하면 Rule Agent가 생성한다"*(CLAUDE.md §2). 고객 규정에 필요한 플래그가 enum에
없을 때 룰 생성을 거부하면 제품이 막히고, `OTHER`로 뭉개거나 조용히 버리면 근거가 사라진다.

그래서 **미등록 플래그도 그대로 동작한다**(화면에 코드 원문 표시). ACTIVE 전환 시
`unknown_flags(snapshot)`가 경고만 남긴다 — 오타(`EVIDENCE_MISSNG`)와 새 어휘를 시스템은
구별할 수 없고, 아는 사람은 승인하는 사람뿐이다.

---

## 4. `code`는 데이터 계약이다

플래그 코드는 Risk Review 2차 프롬프트 입력이자 룰 정밀도 집계의 키가 된다. **이름을 바꾸면
과거 통계와 비교가 끊긴다.** `Position`/`JobTitle`과 같은 규율을 쓴다:

- `code` = 키, **불변** (admin에서 readonly, 코드/시드로만 변경)
- `label` = 표기, 수정 가능

`seed_rule_flags()`는 `code`로 upsert하므로 표기를 고쳐도 과거 `rule_hits`가 안 끊긴다.

### 인자가 붙는 플래그

`UNRESOLVED_POLICY_VAR:preapproval_threshold` 처럼 `<코드>:<인자>` 꼴을 쓴다
(`split_flag`/`describe`가 처리).

**시스템 플래그에만 허용한다.** 인자가 *경로 문자열*이라 코드 안에서만 의미가 있고 사람이
바꿀 일이 없기 때문이다. 반면 직책·과목처럼 **사람이 표기를 바꾸는 값**을 플래그 문자열에
박으면 코드 테이블과 대조가 안 되는 사본이 하나 더 생기고, 값마다 다른 문자열이 돼 집계가
깨진다. 그런 값은 별도 구조 필드로 뺀다(예: 결재의 "누가" → `action.approver`).

---

## 5. 어휘 목록

`flags.py::RULE_FLAGS`가 정본이다. 분류(`FlagCategory`)와 해소 주체(`FlagOwner`)를 함께 갖는다.

| 분류 | 코드 예시 |
|---|---|
| 증빙·기재 `EVIDENCE` | `EVIDENCE_MISSING` · `PURPOSE_UNCLEAR` · `ACTUAL_USER_REQUIRED` · `PARTICIPANT_LIST_REQUIRED` · `RECEIPT_ILLEGIBLE` |
| 결재·승인 `APPROVAL` | `PRE_APPROVAL_MISSING` · `POST_APPROVAL_REQUIRED` · `APPROVER_RANK_INSUFFICIENT` · `SELF_APPROVAL` |
| 한도 `LIMIT` | `DAILY_LIMIT_OVER` · `MONTHLY_LIMIT_OVER` · `PER_PERSON_LIMIT_OVER` · `LODGING_LIMIT_OVER` · `HIGH_AMOUNT` |
| 가맹점·분류 `MERCHANT` | `PROHIBITED_MERCHANT` · `WATCH_MERCHANT` · `MERCHANT_UNRESOLVED` · `LOW_CATEGORY_CONFIDENCE` |
| 시점·패턴 `PATTERN` | `OFF_HOURS` · `LATE_SETTLEMENT` · `REPEATED_VENDOR` · `SECONDARY_VENUE` · `ALCOHOL_HEAVY` · `SPLIT_PAYMENT_SUSPECTED` |
| 세무·법령 `TAX` | `NON_DEDUCTIBLE_RISK` · `KICKBACK_LAW_RISK` · `NON_CORPORATE_CARD` · `PROHIBITED_PAYMENT_METHOD` |
| 종합 판단 `JUDGEMENT` | `PERSONAL_USE_SUSPECTED` |
| 판정 불능 `SYSTEM` | `UNRESOLVED_POLICY_VAR` · `UNRESOLVED_FACT` · `NO_ACTIVE_RULE_GRAPH` · `NO_SCOPE_RULE_GRAPH` · `INVALID_RULE_GRAPH` · `RULE_GRAPH_CYCLE` · `NO_TERMINAL_DECISION` |

### `PERSONAL_USE_SUSPECTED`의 자리

EvalContext v3에서 **입력**으로 있다가 *"결론을 입력받고 있었다"*는 이유로 삭제된 필드다
(`eval-context-sourcing.md` §12). 룰 그래프가 조합해 내놓는 **출력(플래그)** 으로는 여기가
제자리다 — 판정 입력이 아니라 판정 결과이기 때문이다.

### 해소 주체(`FlagOwner`)

`SPENDER`(지출자) · `TEAM_LEAD`(팀장) · `APPROVER`(결재권자) · `ACCOUNTING`(회계) · `SYSTEM`.

화면이 "고쳐주세요"와 "결재해주세요"를 가르는 데만 쓴다. **상태를 정하지 않는다.**

---

## 6. 잡은 결함 — 어휘 드리프트

레지스트리를 만들면서 실제로 드러난 것들이다.

**① 같은 개념에 두 이름** — 우리가 쓴 두 시드가 이미 갈려 있었다.

| 개념 | `seed_rules.py` | `seed_clean.py` |
|---|---|---|
| 증빙 없음 | `EVIDENCE_MISSING` | `MISSING_RECEIPT` |
| 목적 미기재 | `PURPOSE_UNCLEAR` | `MISSING_PURPOSE` |

같은 저장소·같은 작성자인데 갈렸다. `seed_clean` 쪽을 레지스트리 어휘로 통일했고,
`test_seed_rule_vocabulary_is_registered`가 재발을 막는다.

**② 프론트가 라벨 사전을 복사해 갖고 있었다** — 백엔드 27개 vs `judgement.ts::FLAG_LABEL` 9개.
나머지 18개는 화면에 영문 코드로 노출됐다. 이제 서버가 `ruleFlagInfo`로 라벨을 실어 보내고
프론트는 받아 쓰기만 한다(미등록 코드는 원문 폴백).

**③ `validate_graph`가 `flag`를 검사하지 않았다** — `decision`만 봤다. 오타가 조용히 통과해
화면·집계에 그대로 남았다. 이제 ACTIVE 전환에서 경고로 잡는다(거부는 안 한다, §3).

**④ 사유 프리셋이 별도로 하드코딩돼 있다** — `ReturnReasonModal.tsx`·`DecisionReasonModal.tsx`가
자체 한글 목록을 들고 있어 플래그 어휘와 무관하다. **미해결** — 레지스트리에서 뽑도록
바꾸면 판정 플래그에 맞는 사유를 미리 선택해 줄 수 있다.

---

## 7. 활용처

상태를 안 바꾸는 선 안에서 쓸 수 있는 것들. ✅=구현됨, 🔲=미착수.

| | 활용 | 근거 |
|---|---|---|
| ✅ | **화면 라벨·판정 사유 칩** | `ruleFlagInfo` → `judgement.ts::judgementTags` |
| ✅ | **룰 편집 어휘 제안** | `DraftTab` datalist ← `/api/rules/flags/` (자유 입력은 유지) |
| ✅ | **ACTIVE 전환 경고** | `unknown_flags` → 응답 `unknownFlags` |
| ✅ | **해소 주체 구분** | `flagOwners`·`needsApproval` — "고쳐주세요" vs "결재해주세요" |
| ✅ | **심각도 정렬 키** | `worstSeverity` — `anomaly_score` 단일 정렬의 2차 키 |
| 🔲 | **Rule Agent 어휘 통제** | 생성 프롬프트에 레지스트리를 후보로 주입 → §6①의 드리프트를 원천 차단 |
| 🔲 | **Risk Review 2차 입력** | 1차 판정 플래그를 `search_policy` 질의에 주입. 상태 보드가 지적한 *"세부 판정 사실을 2차 프롬프트에 안 넘겨 `INSUFFICIENT_INFO`로 수렴"* 문제의 빈 자리 |
| 🔲 | **룰 정밀도 측정** | `DecisionLabel`(사람 결정) × 플래그 조인 → "`HIGH_AMOUNT` 붙은 건의 92%가 승인됨 = 과탐지". **이름이 표준화돼야만 성립** |
| 🔲 | **죽은 룰 탐지** | 등록됐는데 N개월간 `rule_hits`에 안 나온 플래그 = 조건이 한 번도 참이 안 되는 룰 |
| 🔲 | **거버넌스 지표** | 플래그별 발생 추이 = 조직 리스크 신호(`governance_view`) |
| 🔲 | **사유 프리셋 통합** | §6④ |
| 🔲 | **ERP 전표 적요** | `NON_DEDUCTIBLE_RISK` → 전표에 손금불산입 표시. CONFIRMED 이후라 상태 무관 |

---

## 8. API

```
GET  /api/rules/flags/            등록 어휘(시스템 플래그 제외)   ← 룰 편집 선택지
GET  /api/rules/flags/?system=1   시스템 플래그 포함
POST /api/rules/{id}/activate/    → 응답 `unknownFlags: []`      ← 미등록 경고
GET  /api/settlements/…           → `ruleFlags: []` + `ruleFlagInfo: []`
```

`ruleFlags`(코드 배열)는 **데이터 계약이라 그대로 두고**, `ruleFlagInfo`(라벨 포함)를 따로
싣는다. 테스트·집계는 코드를, 화면은 라벨을 쓴다.

`ruleFlagInfo`는 요청당 레지스트리를 한 번만 읽는다(`SettlementSerializer._flag_labels`).
DRF가 `many=True`에서도 자식 시리얼라이저 인스턴스를 재사용하므로 요청 단위 캐시가 되고,
프로세스에 남지 않아 admin 수정이 바로 반영된다.

---

## 9. 미결

1. **사유 프리셋 통합** (§6④) — 프론트 2곳의 한글 하드코딩.
2. **Rule Agent 프롬프트 주입** — 어휘 통제의 실효는 여기서 나온다.
3. **결재의 "누가"** — `action.approver`가 시드 룰 13곳에 값이 있는데 엔진이 읽지 않는 죽은
   메타데이터다. 플래그 인자로 넣지 말고(§4) `RuleResult.required_approvals`로 승격해
   `JobTitle`과 대조 가능하게 하는 것이 다음 단계.
4. **미등록 플래그 정리 흐름** — 경고만 남기므로 아무도 안 보면 쌓인다. 룰 콘솔에
   "미등록 어휘 N건" 배지가 필요하다.

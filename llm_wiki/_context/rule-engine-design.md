# 룰 실행 엔진 설계 — EvalContext · 조건 DSL · 결정론적 엔진 (Engineering Design)

> 파생 컨텍스트(에이전트 생성, 엔지니어링 설계). **권위 규범 = 기술명세서 §4.2 / 요구사항 FR-RA-08~10**, 캐논 요약 = `_context/rule-engine.md`, 필드 원천 = `법인카드_사용규정_기반_RULE_명세서.md` §2·§2-1.
> 이 문서는 **구현 설계**다(코드 아님). 핵심 명제: **"엔진 품질 = EvalContext를 얼마나 완전·정확·재현가능하게 정의하고 백엔드가 이를 얼마나 견고히 조립·검증·스냅샷하는가"**. 최종 갱신 2026-08-11.

---

## ⚠️ 이 문서를 읽기 전에 — 본문은 2026-07-31 설계안이다

**아래 본문(특히 §2.3 필드 카탈로그·§5 모듈 레이아웃·§7 로드맵)은 설계 당시 기준이며, 이후
구현·축소되면서 여러 곳이 실제와 다르다.** 현재 상태는 아래 표와 링크가 정본이다.

| 항목 | 설계안(본문) | **현재 구현 (2026-08-11)** |
|---|---|---|
| EvalContext 필드 수 | 101 | **46** (v4). 판정 필드·조합 가능 필드·원천 없는 필드를 잘라냄 → `eval-context-sourcing.md` §12 |
| 조립기 위치 | `eval_context.py`에 `build_rule_context` | **`policies/context_builder.py`** (`eval_context.py`는 스키마 계약 전용) |
| 별표 로더 | `tables.py`(미작성) | **`PolicyTable` 모델 + `tiger_tables.py` 시드** → `policy-domain.md` |
| 별표 선해소 | 개념만 | **구현 완료.** `RESOLVERS` 8종 + `merchant.forbidden` 불린. 표별 폴백 정책(`strict_keys`) |
| 미해소 처리 | 언급 없음 | **미해소 가드** — 참조 경로가 `null`이면 `REVIEW` 강등 + `UNRESOLVED_POLICY_VAR`/`UNRESOLVED_FACT` |
| 출처 충돌 | 언급 없음 | **`FactMerger`** — 출처 순위(SoR>입력>추출) + `ctx.conflicts` 기록 |
| 첨부 추출 | 언급 없음 | **`Attachment` 모델** + 증빙자료 추출 Agent → `evidence-extraction-agent.md` |
| `orchestrator.py` | 계획 | **미구현** (GLOBAL→scope 선택·`RuleHit` 기록은 아직 시뮬레이션 경로에만) |
| AI 파생 필드 | `personal_use_suspected` 등 사용 | **제거.** 판정을 입력받지 않고 그래프에서 원자 사실을 조합한다 |

> **사람이 먼저 읽을 문서**: `_context/eval-context-guide.md` (쉬운 설명 → 상세)

---

## 0. 설계 목표 & 품질 기준

| 목표 | 판정 기준 |
|---|---|
| **완전성(Completeness)** | 활성 그래프의 모든 노드 조건이 참조하는 `var` 경로가 **EvalContext 스키마에 100% 존재**. 미정의 참조로 룰이 조용히 오작동하지 않는다. |
| **정확성(Correctness)** | 각 필드가 규정이 요구하는 의미로 산출된다(파생식·조회테이블·업종). 룰↔필드 추적 가능. |
| **재현성(Reproducibility)** | 같은 `(eval_context, graph_version)` → 항상 같은 `decision·path·flags`. 엔진은 순수함수(외부 I/O 0). |
| **감사성(Auditability)** | 판정 시점의 EvalContext 전체가 `rule_hits.eval_context`에 스냅샷 → 사후 리플레이·근거 추적. |
| **단일 I/O 경계** | 모든 데이터 접근은 **조립 단계 1곳**(`build_rule_context`)에서만. 엔진·DSL은 Postgres를 모른다. |
| **안전성** | DSL은 임의 코드 실행 불가(연산자 화이트리스트). 테이블 조회는 조립기가 선해소해 DSL을 단순 비교로 유지. |

설계 제1원칙: **"똑똑함은 조립기(①)에, 결정론은 엔진(③)에."** 복잡한 I/O·계산·룩업은 전부 조립 단계로 밀어넣고, 엔진은 스냅샷된 스칼라만 비교한다.

---

## 1. 3단 파이프라인 (컨텍스트)

```
[SUBMITTED 정산]
 ① 조립  build_rule_context(settlement_id) → EvalContext(facts 스냅샷)   ← 모든 I/O·계산·룩업은 여기서만
 ② 선택  GLOBAL 필수 게이트 → (통과 시) 계정과목별 그래프(scope = normalize_scope(category))
 ③ 순회  run_rule_engine(eval_context, graph) → RuleResult(decision, path, flags, confidence)  ← 순수함수
[rule_hits: eval_context 스냅샷 + path + graph_version + decision + flags 저장]
```

②의 scope 정합은 이미 구현된 `domain/policies/scope.normalize_scope()`(룰 명세서 과목명→`Category`) 사용. ③의 결정→정산 상태 매핑은 §5.5.

---

## 2. EvalContext 설계 (핵심)

### 2.1 원칙
1. **네임스페이스 스냅샷**: EvalContext는 판정 시점 사실의 JSON 스냅샷. 섹션(`tx`/`card`/`user`/…)으로 그룹화하고 DSL은 `section.field` 경로만 참조.
2. **파생 선계산**: `min(30만, 별표1[직책])`·영업일 경과·1인당 환산·심야 여부 등은 **조립기가 미리 스칼라로 산출**(`ctx.policy.*`, `ctx.derived.*`). DSL엔 계산식이 없다.
3. **조회 테이블 선해소**: 별표(`daily_limit_table[position]` 등)는 **직책·유형이 이미 정해진 조립 시점에 스칼라로 해소**해 `ctx.policy.*`로 넣는다. 원본 테이블은 감사용으로 `ctx.tables.*`에 그대로 보존(DSL 미참조).
4. **널 안전**: 미해결 필드는 `null`. 룰은 널을 안전하게 다루도록 설계(예: `pre_approval_level` 없음=최하위값 "없음"). 조립기는 **미해결 필수 필드를 로깅**한다.
5. **버전**: `ctx.meta.schema_version`(EvalContext 스키마)·`builder_version`(조립기 로직)·`built_at` 기록 → 스키마 진화 추적.

### 2.2 네임스페이스 구조

| 섹션 | 의미 | 주 소스 |
|---|---|---|
| `tx` | 거래 사실(금액·시각·결제수단·봉사료) | SoR |
| `card` | 카드 구분·실사용자 기록 | SoR |
| `user` | 직책(서수)·부서·재무회계 여부·근무시간 | SoR + derived |
| `merchant` | 업종·등급·식별 여부·금지 여부 | MCP(`classify_merchant`) |
| `category` | 비용분류·세부유형(접대/회식/식대…) | SoR + AI |
| `evidence` | 적격증빙·소명·기재 누락 플래그 | SoR + AI(포괄기재 판정) |
| `approval` | 사전/사후 승인·자기승인·동석 | SoR |
| `participants` | 참석 인원·외부인·청탁금지 대상 | SoR |
| `trip` | 출장 구분·숙박·항공·일정 | SoR |
| `dining` | 회식 조직단위·주류·2차·분할결제 | SoR |
| `history` | 3개월 이력 집계·당일/당월 누적 | SoR 집계 |
| `policy` | **별표 선해소 스칼라**(한도·기준액) | table 선해소 |
| `derived` | 조립기 계산 boolean/number(영업일·심야·특칙적용) | derived |
| `tables` | 원본 별표(감사용, DSL 미참조) | table |
| `meta` | tx/settlement id·스키마·빌더 버전·시각 | — |

### 2.3 필드 카탈로그 (룰 명세서 §2 → EvalContext)

> 소스 범례: **SoR**=Postgres(Django 내부 read API) · **MCP**=classify_merchant · **DRV**=조립기 계산 · **TBL**=별표 선해소 · **AI**=Draft/Risk 에이전트 판정. 널 가능은 `?`.

**`ctx.tx`**
| 경로 | 타입 | 소스 | 산출/설명 | 사용 RULE(예) |
|---|---|---|---|---|
| tx.amount | number | SoR | 건당 총액(원) | R-007·R-008·R-102~104 |
| tx.per_person_amount | number | DRV | `amount / participant_count`(참석기록 있을 때) | R-106 |
| tx.payment_time / day_of_week / is_holiday | datetime/enum/bool | SoR+DRV | 결제일시·요일·공휴일 | 심야·주말 파생 |
| tx.payment_method | enum | SoR | 카드/현금/개인카드_사후청구/간편결제 | R-003·R-005 |
| tx.service_charge_ratio | number? | SoR | 봉사료 비율 | R-110 |

**`ctx.card`**: `card.card_type`(개인/부서공용/…, SoR), `card.actual_user_recorded`(bool, SoR — R-006).

**`ctx.user`**: `user.position`(enum 서수: 비직책자<팀장<부서장<본부장<대표이사, SoR), `user.dept`(SoR), `user.finance_dept_is_spender`(bool, SoR — R-014), `user.is_working_hours`(bool, DRV).

**`ctx.merchant`** (MCP): `merchant.merchant_type`(유흥업소/사행성업종/카지노/경마/노래방/단란주점…), `merchant.merchant_grade`(호텔/특급레스토랑), `merchant.merchant_info_resolved`(bool), `merchant.forbidden`(bool, DRV = merchant_type ∈ 금지목록).

**`ctx.category`**: `category.value`(비용분류, SoR=ai_category/category), `category.confidence`(number, AI), `category.item_type`(경조사/선물/개인선물/상품권/행사성/식사, SoR), `category.entertainment_type`(행사성…), `category.meal_type`(일반/접대성 — R-310), `category.event_type`(회식 구분), `category.scope`(회식 조직단위: 팀/본부/전사 — R-208·R-216).

**`ctx.evidence`**: `has_valid_receipt`·`has_supporting_evidence`(bool, SoR), `event_plan_attached`(bool, SoR — R-105), `confirmation_doc_submitted`(bool, SoR), `purpose_missing`(bool, SoR — R-004), `purpose_is_generic`(bool, **AI** — 포괄기재 판정, R-108/214/310), `participant_list_missing`·`vendor_info_missing`·`venue_datetime_missing`·`project_name_missing`·`participant_record_missing`(bool, SoR).

**`ctx.approval`**: `pre_approval_obtained`(bool), `pre_approval_level`(enum? 서수, 미승인=`null`/"없음"), `post_approval_within_1biz_day`(bool), `approver_is_spender_self`(bool — R-012), `escalated_approval_confirmed`(bool — R-012), `spender_attended`(bool — R-114). 전부 SoR.

**`ctx.participants`**: `participant_count`·`external_participant_count`·`contractor_participant_count`(number), `contractor_regular_communication_purpose`(bool — R-204), `has_kickback_law_target`(bool), `kickback_law_category`(enum), `kickback_law_target_status_missing`(bool — R-108), `participant_includes_former_employee`(bool), `family_or_personal_gathering_suspected`(bool). SoR(+일부 AI).

**`ctx.trip`**: `trip_type`(국내/해외), `region_grade`(A/B…), `lodging_amount_per_night`(number), `flight_class`(enum), `flight_duration_hours`(number), `booking_to_trip_gap_months`(number), `during_business_trip`(bool), `itinerary_mismatch`(bool — R-308), `work_end_time`(datetime, 기본 18:00 — R-303), `expense_type`(야간식대…), `trip_request_submitted_days_before`(number)·`emergency_trip`(bool — R-314). SoR.

**`ctx.dining`**: `includes_alcohol`·`is_secondary_venue`·`same_event_multiple_merchants`(bool), `event_scale_payment_method`(개인카드/행사전용/구매계약 — R-216). SoR.

**`ctx.history`** (SoR 집계): `same_vendor_count_3m`, `user_post_approval_count_3m`, `late_settlement_count_no_reason_3m`(number — R-011·R-112), `daily_cumulative_amount`·`monthly_cumulative_amount`(number — R-007).

**`ctx.policy`** (별표 선해소 스칼라 — **DSL이 실제 비교하는 값**):

> ⚠️ **재설계됨 (2026-08-10)** — 아래 8개는 초안이다. 확정 카탈로그는 **13개**이며 캐논은
> `_context/policy-domain.md` §4다. 변경점: ① `gift_type` **제거**(정책값이 아니라 `kickback_limit`의
> 룩업 키 → `category.item_type`으로 이관) ② 누락 임계값 6종 승격(`evidence_threshold`·
> `dining_per_person_limit`·`settlement_deadline_days`·`history_window_months`·`night_meal_limit`·
> `business_class_min_hours` — 현재 DSL 리터럴과 필드명에 상수로 박혀 있음)
> ③ 저장층은 `policy_tables`(자유 JSON payload + `key_axes` 축 선언), 해소는 `RESOLVERS` 규약.
| 경로 | 산출식 | 근거 별표 | 사용 RULE |
|---|---|---|---|
| policy.preapproval_threshold | `pre_approval_threshold_table[position]` | 사용규정 별표1 | R-013·R-312 |
| policy.position_daily_limit / position_monthly_limit | `daily/monthly_limit_table[position]` | 별표1 | R-007 |
| policy.kickback_limit | `kickback_limit_table[gift_type]` | 추진비 별표1 | R-106 |
| policy.lodging_limit | `lodging_limit_table[trip_type][region_grade]` | 출장 별표1·2 | R-3xx 숙박 |
| policy.position_required_level | 금액구간→요구 승인단계 | 별표1 | R-312 |
| policy.gift_type | 청탁금지 한도 판정용 유형 | — | R-106 |
| policy.approver_daily_limit | 회식 승인권자 1일 한도 | 회식 별표1 | R-216 |

**`ctx.derived`** (조립기 계산): `personal_use_suspected`(bool, **AI** — R-001), `business_days_since_expense`·`business_days_since_trip_end`(number), `biz_days_over_7`(bool — R-010/R-113), `is_late_night`·`is_weekend`(bool), `category_specific_deadline_applies`(bool — R-010 제외조건), `category_specific_preapproval_rule_exists`(bool — R-013 제외조건).

**`ctx.tables`** (감사용 원본, DSL 미참조): `daily_limit_table`·`monthly_limit_table`·`kickback_limit_table`·`lodging_limit_table`·`pre_approval_threshold_table`. 조립기가 별표를 로드해 그대로 보존 → "어떤 한도표로 판정했나" 리플레이.

**`ctx.meta`**: `tx_id`·`settlement_id`·`schema_version`·`builder_version`·`built_at`.

### 2.4 조회 테이블 처리 — 왜 선해소인가
룰 명세서엔 `amount > pre_approval_threshold_table[position]`처럼 **동적 키 룩업**이 등장한다. 이를 DSL이 직접 하면 (a) DSL에 인덱싱·중첩 키 연산자가 필요해지고 (b) 테이블 로딩 I/O가 엔진으로 새어든다. **결정: 조립 시점에 `position`·`gift_type`이 이미 알려져 있으므로 조립기가 룩업을 수행해 `ctx.policy.*` 스칼라로 넣는다.** DSL은 `tx.amount > policy.preapproval_threshold`처럼 **스칼라 비교만** 한다. 원본 표는 `ctx.tables`에 감사용으로 남긴다. (rule-engine.md §2 원칙과 동일)

### 2.5 EvalContext 타입 계약 (스케치)
```python
# domain/policies/eval_context.py — TypedDict(런타임 dict, 직렬화=rule_hits.eval_context)
class TxCtx(TypedDict):
    amount: int; per_person_amount: int | None; payment_time: str
    day_of_week: str; is_holiday: bool; payment_method: str; service_charge_ratio: float | None
class PolicyCtx(TypedDict):
    preapproval_threshold: int | None; position_daily_limit: int | None
    position_monthly_limit: int | None; kickback_limit: int | None; ...
class EvalContext(TypedDict):
    tx: TxCtx; card: CardCtx; user: UserCtx; merchant: MerchantCtx; category: CategoryCtx
    evidence: EvidenceCtx; approval: ApprovalCtx; participants: ParticipantsCtx
    trip: TripCtx; dining: DiningCtx; history: HistoryCtx
    policy: PolicyCtx; derived: DerivedCtx; tables: TablesCtx; meta: MetaCtx
```
> TypedDict를 쓰는 이유: 스냅샷이 곧 JSON(감사·리플레이)이라 dict가 자연스럽고, 스키마는 정적 타입으로 문서화·검증. dataclass+`asdict()`도 대안(가독성↑, 직렬화 1스텝 추가).

### 2.6 완전성 보장 — 활성 전환 게이트 (품질 핵심)
**그래프를 ACTIVE로 승인하기 전에**, 그래프의 모든 노드 `condition`에서 참조된 `var` 경로를 정적 추출해 **EvalContext 스키마에 존재하는지 검증**한다. 하나라도 미정의면 **활성 전환 거부**(FR-RV). 이로써 "활성 룰이 참조하는 필드는 EvalContext가 반드시 지원"을 **불변식**으로 강제한다.
```
validate_graph_vars(graph) -> set[str] missing
  refs = ∪ extract_vars(node.condition) for node in graph.nodes   # {"tx.amount","policy.preapproval_threshold",...}
  missing = refs − EVAL_CONTEXT_SCHEMA_PATHS
  ACTIVE 전환 시 missing 비어있어야 함 (아니면 reject)
```
추가로 **역방향 추적**(필드→사용 룰)을 유지해 EvalContext 필드 변경 시 영향 룰을 즉시 파악(§2.3 표의 "사용 RULE").

---

## 3. 조건 DSL 설계 (JSON-Logic 부분집합)

### 3.1 문법 (연산자 화이트리스트)
```
expr   := literal | var | logic | compare
var    := {"var": "<dot.path>"}                      # EvalContext 경로
logic  := {"and":[expr,...]} | {"or":[expr,...]} | {"not": expr}
compare:= {"==":[expr,expr]} | {"!=":[...]} | {">":[...]} | {">=":[...]}
        | {"<":[...]} | {"<=":[...]} | {"in":[expr, [literal,...]]}
literal:= number | string | bool | null
```
**허용 연산자 외 키는 파싱 에러**(임의 함수·산술·코드 금지). 산술이 필요하면 `ctx.derived`/`ctx.policy`에서 선계산.

### 3.2 평가 시맨틱 (순수 재귀)
- `var`: EvalContext에서 dot-path 해석. **경로 없음/중간 널 → `null`**(예외 아님).
- 비교: 양변 평가 후 비교. **널 관여 비교는 `false`**(단, `==null`/`!=null`은 명시적 널 검사로 허용). 타입 불일치(number vs string)는 `false`(강제 변환 안 함 — 조립기가 타입 보장).
- `in`: 좌변이 우변 리스트에 포함되면 true. (예: `merchant.merchant_type in ["유흥업소","사행성업종"]`)
- `and`/`or`: 단축평가. `not`: 불리언 반전(널→false 취급 후 반전).
- **결과 → 라우팅**: 최종 boolean이 **truthy면 `MATCH`, 아니면 `NO_MATCH`**. (엔진이 이 결과로 `next_routings` 선택)

### 3.3 안전성
- **화이트리스트 검증**: 파싱 시 허용 키만 통과. 미허용 키·과도한 중첩 깊이(예: >32) 거부.
- **부작용 0**: evaluator는 순수함수, 컨텍스트 읽기만. `eval`/동적 속성 접근 없음.
- **결정성**: 같은 `(expr, ctx)` → 항상 같은 결과. 시간·랜덤·I/O 참조 불가(그런 값은 조립기가 스냅샷).

### 3.4 예시
```jsonc
// R-002 금지업종(GLOBAL 게이트)
{ "in": [ {"var":"merchant.merchant_type"}, ["유흥업소","사행성업종"] ] }

// R-101 추진비 3만 초과 + 경조사 아님 + 증빙없음 → REJECT
{ "and": [ {"==":[{"var":"category.value"},"접대"]},
           {"!=":[{"var":"category.item_type"},"경조사"]},
           {">" :[{"var":"tx.amount"},30000]},
           {"==":[{"var":"evidence.has_valid_receipt"},false]} ] }

// R-013 직급별 건당 사전승인 초과(특칙 없는 지출) — 테이블 선해소 스칼라 비교
{ "and": [ {"==":[{"var":"derived.category_specific_preapproval_rule_exists"},false]},
           {">" :[{"var":"tx.amount"},{"var":"policy.preapproval_threshold"}]},
           {"==":[{"var":"approval.pre_approval_obtained"},false]} ] }
```

### 3.5 결정: `table[key]` 동적 룩업 미지원
DSL은 동적 인덱싱을 지원하지 않는다(§2.4). 대신 조립기가 `policy.preapproval_threshold` 등 스칼라를 넣는다 → DSL 단순·안전·감사 용이. (향후 정말 필요하면 `{"lookup":["policy.kickback_limit"]}` 같은 **읽기 전용** 확장을 별도 검토하되 기본은 선해소.)

---

## 4. 룰 실행 엔진 설계

### 4.1 순수 함수 계약
```python
def run_rule_engine(ctx: EvalContext, graph: GraphSnapshot) -> RuleResult
# RuleResult = {decision: "PASS|REJECT|REVIEW|RETURN", path: list[str], flags: list[str], confidence: float}
```
입력은 **스냅샷 dict + 그래프 스냅샷(노드/라우팅/entry)** 뿐. DB·시간·네트워크 접근 없음.

### 4.2 그래프 선택 (오케스트레이터, 엔진 밖)
1. **GLOBAL 게이트 그래프**(`scope="GLOBAL"`, status=ACTIVE) 먼저 실행. 단말 decision이 `REJECT/REVIEW`면 **거기서 종료**(과목별 스킵). `PASS`면 통과.
2. 통과 시 **계정과목별 그래프**(`scope == normalize_scope(ctx.category.value)`, ACTIVE) 실행.
3. 스코프당 ACTIVE 그래프는 하나(불변식). 없으면 `REVIEW`(안전측, Risk 이관).

### 4.3 순회 알고리즘
```
node = graph.entry_node
visited = []
while node is not None:
    visited.append(node.key)
    matched = evaluate(node.condition, ctx)          # DSL → MATCH/NO_MATCH
    result  = MATCH if matched else NO_MATCH
    if node.action.decision != "PASS_THROUGH":       # 단말성 액션이면 확정
        # 라우팅이 이 결과에 대해 단말(to="")이면 여기서 decision 확정
    nexts = routings[node.key] filtered by on_result==result, sorted by priority
    node = first(nexts).to_node  (없거나 to=="" → 단말 → decision 확정)
```
- **우선순위**: `on_result`가 같은 라우팅이 여러 개면 `priority` 오름차순 첫 번째.
- **단말**: `to_node_key`가 비었거나 매칭 라우팅 없음 → 현재 노드 `action.decision` 확정.
- **사이클 방지**: 방문 노드 재진입 감지 시 중단 + `REVIEW`(그래프 정의 오류 방어). 활성 전환 시 **DAG 검증**으로 사전 차단.
- **flags 누적**: 순회 중 매칭 노드의 `action.flag`를 `flags[]`에 모은다(복수 사유 태깅, §4 방어적 중복 근거).

### 4.4 decision·confidence·flags
- **decision**: 단말 노드 `action.decision`(PASS/REJECT/REVIEW/RETURN).
- **confidence**: MVP는 규칙 결정론이라 매칭 경로 확정성 기반(예: 게이트 CRITICAL 매칭=1.0, 통과=θ 이상). `θ_pass·θ_reject`는 Open Issue(기술 §4.2). Risk 이관 여부의 컷.
- **flags**: 매칭 노드들의 flag 집합(예: `["NON_DEDUCTIBLE_RISK","LATE_SETTLEMENT"]`).

### 4.5 결정 → 정산 상태 매핑 (rule-engine.md §6)
| decision | 조건 | 정산 상태 |
|---|---|---|
| PASS | conf ≥ θ_pass | PENDING_CONFIRM(사람 확정 필수) |
| REJECT | conf ≥ θ_reject | RETURNED(보완요청 자동안내) |
| RETURN | — | RETURNED |
| REVIEW | 그 외 | IN_REVIEW(Risk Review 이관) |

---

## 5. 백엔드 시스템 지원 (구현 설계) — "얼마나 잘 지원하나"의 실체

### 5.1 모듈 레이아웃 (전부 Django `domain/policies/`, 순수 지향)
| 모듈 | 책임 | 순수성 |
|---|---|---|
| `eval_context.py` | `EvalContext` 타입 + 스키마 경로 집합 (**조립은 아래로 분리됨**) | 순수 |
| `context_builder.py` | `build_rule_context(settlement)`·별표 선해소·첨부 병합·`FactMerger` | **I/O 유일 지점** |
| `dsl.py` | `evaluate(expr, ctx)`·`extract_vars(expr)`·`validate_expr(expr)` | 순수 |
| `engine.py` | `run_rule_engine(ctx, graph_snapshot)` | 순수 |
| `orchestrator.py` | 그래프 선택(GLOBAL→scope)·엔진 호출·**RuleHit 기록** | I/O(그래프 로드·hit 저장) |
| `scope.py` | `normalize_scope()` (구현 완료) | 순수 |
| ~~`tables.py`~~ → `models.PolicyTable` + `tiger_tables.py` | 별표 저장(자유 JSON payload)·시드. 로더는 `context_builder.load_tables` | I/O |

> **배치 결정(중요)**: 엔진·DSL·조립기는 **Django 서비스 레이어에 둔다**(SoR=Postgres 원칙·감사 일원화). AI(FastAPI)의 FastMCP `build_rule_context`/`run_rule_engine`는 **Django 내부 엔드포인트를 호출하는 얇은 프록시**로 구현 → Postgres 접근·`rule_hits` 쓰기가 전부 Django에 남는다. (대안: FastAPI가 Django read API로 조립·순회 — 순수성은 같으나 쓰기·감사가 분산되어 비권장.)

### 5.2 데이터 접근 경계
- `build_rule_context`만 ORM/집계/`classify_merchant`/별표를 만진다. **DSL·엔진은 dict만** 본다.
- `history.*` 집계(3개월 반복·당일/당월 누적)는 인덱스된 집계 쿼리. `classify_merchant`는 캐시(§7-1). 별표는 `tables.py`가 버전드 캐시.
- 원칙: LLM/Tool의 **Postgres 직접 SQL 금지**(AGENTS §1) — 조립기는 Django 내부 read helper 경유.

### 5.3 `rule_hits` 스키마 보강 (필수 마이그레이션)
현재 `RuleHit`엔 `path/decision/confidence`만 있고 **`eval_context`·`flags` 컬럼이 없다**(DB 설계문서 알려진 갭). 재현·감사를 위해 추가:
```python
# RuleHit에 추가
eval_context = models.JSONField(default=dict)          # 판정 시점 facts 스냅샷 전체
flags        = models.JSONField(default=list)          # 누적 flag
eval_context_schema_version = models.PositiveIntegerField(default=1)
builder_version             = models.CharField(max_length=20, blank=True)
```
→ `0002_rulehit_eval_context.py` 마이그레이션. 이게 **"백 시스템적 지원"의 핵심 산출물** — 판정을 언제든 리플레이·감사.

### 5.4 성능
- **온디맨드 배치**(관리자 트리거)로 대량 판정(MVP는 동기 REST). 조립기의 tx당 쿼리 수를 `select_related/prefetch`로 최소화, `history` 집계는 사용자·월 단위 캐시.
- 별표·업종 캐시로 조립 반복 비용 절감. 엔진 자체는 O(노드수)로 무시가능.

### 5.5 재현·감사·리플레이
- `replay(rule_hit)` = 저장된 `eval_context` + 당시 `graph_version` 스냅샷으로 `run_rule_engine` 재실행 → 동일 결과 보장(회귀 테스트·이의제기 대응).
- 규정 개정으로 룰이 바뀌어도 **과거 판정은 당시 스냅샷으로 그대로 재현**된다.

### 5.6 테스트 전략
| 층 | 방법 |
|---|---|
| DSL | 연산자별 단위테스트 + 널/타입 엣지 + 화이트리스트 위반 거부 |
| 엔진 | 골든 그래프 × 골든 EvalContext → 기대 `(decision, path, flags)` 스냅샷 |
| 조립기 | 시드 정산 → EvalContext 필드별 기대값(특히 파생·별표 선해소) |
| 완전성 | 모든 ACTIVE 그래프에 `validate_graph_vars` == ∅ (CI 게이트) |
| 결정성(property) | 임의 ctx 순열에도 `run(ctx,g)` 재실행 동일 |
| 리플레이 | `rule_hits` 샘플 replay == 저장 decision |

### 5.7 관측성
- 조립기: 미해결 필수 필드·업종 조회 소스(cache/kakao/web)·조립 소요 로깅.
- 엔진: 판정 분포(decision별)·평균 path 길이·flag 빈도 메트릭 → 룰 튜닝·오탐 모니터링.

---

## 6. 실행 워크스루 (end-to-end)

**케이스 — 강남한식당 452,000 · 접대(기업업무추진비) · 증빙없음 · 심야 · 공용카드**
```
① build_rule_context(s):
   tx.amount=452000, payment_time=22:14 → derived.is_late_night=true
   category.value="접대", category.item_type="식사"
   evidence.has_valid_receipt=false, evidence.purpose_missing=false
   merchant.merchant_type="한식"(→forbidden=false)
   user.position="사원" → policy.preapproval_threshold=min(300000, 별표1["사원"])=300000
   card.card_type="공용", card.actual_user_recorded=false
② 선택: GLOBAL 게이트(ACTIVE) → normalize_scope("접대")="접대" 그래프 예약
③ 순회(GLOBAL 게이트):
   n_forbidden: merchant.forbidden==true? false → NO_MATCH → n_shared_user
   n_shared_user: card_type=="공용" & !actual_user_recorded → MATCH? (R-006 특칙 있으면 여기서 REVIEW)
   n_evidence: 접대 & amount>30000 & !has_valid_receipt → MATCH → REVIEW·NON_DEDUCTIBLE_RISK → 단말
결과: decision=REVIEW, path=[n_forbidden, n_shared_user?, n_evidence],
      flags=[SHARED_CARD_USER_MISSING?, NON_DEDUCTIBLE_RISK], conf=1.0
→ 정산 IN_REVIEW(Risk Review 이관: anomaly_score + RAG 제11조 근거)
→ rule_hits.eval_context = 위 스냅샷 전체 저장
```
리플레이: 이 `eval_context`+`graph_version`으로 재실행하면 언제든 동일 판정.

---

## 7. 구현 로드맵
1. ✅ `RuleHit`에 `eval_context/flags/schema_version/builder_version` 추가 + `0002` 마이그레이션. (2026-07-31)
2. ✅ `dsl.py`: evaluate/validate/extract_vars + 단위테스트. 허용 연산자·깊이·널·타입 계약 반영. (2026-07-31)
3. ✅ `eval_context.py`: TypedDict·`EVAL_CONTEXT_SCHEMA_PATHS`·null-safe 기본 컨텍스트. **스키마 v4(46필드)로 축소** (2026-08-11)
3-1. ✅ `context_builder.py`: `build_rule_context` — 별표 선해소·첨부 추출 병합·출처 충돌 해소·산술 파생 (2026-08-11)
4. ✅ `engine.py`: `run_rule_engine` + 참조 무결성·라우팅 중복·DAG/사이클 검증 + 골든 단위테스트. (2026-07-31)
5. ✅ ACTIVE 전환에 `validate_graph` + `validate_graph_vars` hard gate 연결. **남음:** `orchestrator.py` GLOBAL→scope 선택·`RuleHit` 기록·상태 매핑 (**미구현**)
6. ✅ 별표 로더 — `tables.py` 대신 **`PolicyTable` 모델 + `context_builder.load_tables`**(유효일 기준 버전드). `classify_merchant` 연동은 **미착수**
7. ✅ 시드 룰 그래프 골든 테스트 — `tests/test_rule_graph_consumption.py`(29 시나리오)·`test_eval_context_assembly.py`(32 케이스)
8. ✅ FastMCP `build_rule_context` → Django `/api/internal/rule-context/<id>/` 프록시. `run_rule_engine` 프록시는 **미착수**
9. 🔲 **다음**: 판정 사실의 원천 확보(참석 인원·2차 여부·청탁 대상) → `eval-context-sourcing.md` §7·§13

## 8. Open Issues / 리스크
- **θ_pass·θ_reject**(확신 임계) 확정 — decision→상태 컷(기술 §4.2). MVP는 게이트 CRITICAL=자동 REJECT 후보/그 외 REVIEW로 보수적.
- ~~**AI 파생 필드**(`personal_use_suspected`·`purpose_is_generic`)~~ → **해소됨(v3)**: 판정 결과를 입력으로 받지 않는다. EvalContext는 원자 사실만 주고 그래프가 조합한다(`eval-context-sourcing.md` §12).
- **별표 버전·유효일자** 관리(규정 개정) — `ctx.tables` 스냅샷 + 별표 버전 기록으로 과거 판정 보존.
- **EvalContext 스키마 진화** — `schema_version` bump 시 과거 hit 호환(리플레이는 당시 스키마로).
- **완전성 게이트의 엄격도** — 활성 전환을 막을지(hard) 경고만(soft)할지: 본 설계는 hard(안전) 권장.
- **`category.value`↔scope 정합** — `normalize_scope`가 커버(구현됨). 회식/식대 공용 scope 편성(§scope.py) 주의.

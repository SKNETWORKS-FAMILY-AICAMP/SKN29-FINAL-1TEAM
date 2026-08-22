# 규정 임계값(policy) 도메인 캐논

> **파생 컨텍스트.** 권위 스펙은 `기술명세서.md` §3.2·§4.2 / `요구사항_명세서.md` §5.4·Open #16·#17.
> 이 문서는 "규정에 적힌 숫자(한도·기준액)를 어디에 어떤 모양으로 저장하고, 룰 엔진이 그걸 어떻게
> 읽는가"의 단일 캐논이다. 구현 순서는 `_context/policy-domain-plan.md`.
>
> 최종 갱신: 2026-08-10

---

## 0. 왜 이 문서가 생겼나 (문제 정의)

`policy`라는 이름이 레포에서 **5개의 서로 다른 것**을 가리키고 있었고, 그중 실제로 데이터가 흐르는
것은 0개였다. 원인은 단순하다 — **두 계보가 서로를 모른 채 자랐다.**

| 계보 | 태어난 시점 | 형태 |
|---|---|---|
| `Policy` 모델 (`category`·`limit_amount`·`required_evidence`) | 스캐폴드 `0001_initial`. 이후 **수정 0회** | 분류당 한도 1개라는 최소 가정 |
| `ctx.policy.*` 8개 카탈로그 | 룰엔진 설계(`rule-engine-design.md` §2.3) 단계 | 별표 룩업을 선해소한 스칼라 |

두 스키마는 **필드가 하나도 겹치지 않는다.** 그 결과:

- `Policy` 테이블은 항상 비어 있고, 읽는 코드도 쓰는 코드도 없다(admin 등록 1줄이 전부).
- `ctx.policy.*`를 채우는 조립기(`build_rule_context`)가 없어 **전 필드가 `None`**이다.
- DSL은 `None` 비교를 안전하게 `False`로 떨어뜨리므로(`dsl.py`), 한도 룰이 **에러 없이 조용히
  미발동**한다. 화면에는 "통과(PASS)"로 보인다.
- 실제 임계값은 4곳에 흩어져 있고 이미 값이 갈라졌다(문서 30만 vs 코드 50만).

> **핵심 인식**: 실패 원인은 "스키마를 고정해서"가 아니라 **고정해야 할 층과 열어야 할 층을 반대로
> 잡아서**다. 저장(별표)은 이질적이라 열려야 하고, 소비(DSL 계약)는 검증 게이트가 걸려 있어 고정돼야 한다.

---

## 1. 결정 — 2층 + 해소 규약

```
[저장층]  PolicyTable            payload = 자유 JSON. 별표 원본 1개 = 1행
             │                   (축 개수·깊이가 별표마다 다르므로 고정 컬럼 금지)
             │  RESOLVERS        어느 표를 · EvalContext의 어느 경로를 키로 · 어느 필드에 넣나
             ▼
[소비층]  ctx.policy.*           고정 카탈로그. DSL이 비교하는 스칼라
             +
          ctx.tables.*           해소에 쓴 payload 원본 스냅샷 (재현·감사, DSL 미참조)
```

**소비층을 자유 JSON으로 열면 안 되는 이유 3가지** (전부 이미 구현된 기능을 죽인다):

| 잃는 것 | 근거 |
|---|---|
| ACTIVE 승인 게이트 | `eval_context.validate_graph_vars()`가 "그래프 참조 경로 − 카탈로그"로 미정의 참조를 잡는다. 카탈로그가 자유면 **오타 난 룰이 ACTIVE로 승인된다** |
| 룰 편집 화면 | `web/src/screens/rule-console/data/simulationTypes.ts`가 `policy.position_daily_limit → "직책 일일 한도(원)"` 라벨 목록을 만든다. 자유 JSON이면 **비개발자에게 보여줄 변수 목록을 만들 수 없다** |
| 미해소 탐지 | "채워졌어야 하는데 안 채워진 필드"는 **기대 집합이 고정일 때만** 계산 가능하다. 자유 JSON에선 결측이 정상인지 사고인지 구분 불가 — 지금의 최대 버그를 영구화한다 |

추가로, 소비층 자유화는 DSL에 동적 룩업(`{"lookup":[...]}`)을 되살리는데, 이는
`rule-engine-design.md` §2.4가 **명시적으로 기각한 방향**이다(DSL 복잡화 + 엔진으로 I/O 누수).

---

## 2. 저장층 — `PolicyTable`

```python
class PolicyTable(models.Model):
    """규정 별표 원본 1개 = 1행. 별표마다 구조가 달라 payload는 자유 JSON."""
    key             = CharField(64)      # 'lodging_limit_table'
    title           = CharField(200)     # '별표2. 지역등급별 숙박비 한도'
    key_axes        = JSONField([])      # ['trip.trip_type','trip.region_grade'] — 룩업 축 선언
    payload         = JSONField({})      # {"국내":{"A":120000,"B":90000}, "해외":{...}}
    source_doc      = FK(PolicyDoc, null=True)      # ← PDF 파싱 파이프라인 연결점
    source_clause   = CharField(200)     # 'TIGER-REG-2026-003 별표2'
    effective_date  = DateField()        # 시점 조회(개정 이력)
    superseded_date = DateField(null=True)
```

- **`key_axes`가 자유도의 핵심이다.** 축이 1개든 3개든 `payload` 중첩 깊이와 `key_axes` 길이만
  맞으면 조립기 코드는 변경 0이다.
- **개정은 UPDATE가 아니라 INSERT**다. 새 `effective_date` 행을 추가하고 구행에 `superseded_date`를
  찍는다 → 과거 판정 재현이 유지된다.
- `source_doc`·`source_clause`로 **"이 숫자가 규정 어디서 왔는지"** 를 항상 되짚을 수 있다.

기존 `Policy` 모델(`category`·`limit_amount`)은 **폐기**한다. 2키 별표를 표현할 수 없고 참조도 0이다.

---

## 3. 해소 규약 — `RESOLVERS`

```python
# domain/policies/context_builder.py — 코드 상수로 유지(리뷰 대상, 로직 인접)
RESOLVERS = {
  "preapproval_threshold":  ("pre_approval_threshold_table", ["user.position"]),
  "position_daily_limit":   ("daily_limit_table",            ["user.position"]),
  "position_monthly_limit": ("monthly_limit_table",          ["user.position"]),
  "kickback_limit":         ("kickback_limit_table",         ["category.item_type"]),
  "lodging_limit":          ("lodging_limit_table",          ["trip.trip_type", "trip.region_grade"]),
  ...
}
```

- 키는 **축 이름이 아니라 EvalContext 경로**로 선언한다 → 조립기가 이미 만든 컨텍스트에서 곧바로 뽑는다.
- 해소에 성공하면 `ctx.policy.<field>`에 스칼라를, `ctx.tables.<table_key>`에 payload 원본을 넣는다.
- 해소 실패(표 없음·키 결측·유효일 밖)는 `None`으로 두되 **반드시 기록**한다(§6).

> 회계 담당자가 화면에서 직접 매핑을 추가해야 하는 요구가 생기면 그때 DB 테이블로 승격한다.
> MVP에서는 코드 상수가 낫다 — 해소 규약은 데이터가 아니라 로직에 가깝고 코드리뷰 대상이다.

### 3.1 개정 (2026-08-22) — 고정 8칸에서 **적재된 표에서 파생**으로

위 각주의 "그때"가 왔다. 다만 화면 요구가 아니라 **제품 전제** 때문이다: 룰은 사전 탑재하지
않고 고객이 올린 규정에서 생성한다(`CLAUDE.md` §2). 그런데 `RESOLVERS`가 코드 상수라
**새 별표가 들어와도 `ctx.policy.*`에 앉을 자리가 없었다** — 룰은 생기는데 그 룰이 비교할
숫자가 없는 상태다.

```python
policy_fields(tables)   # {ctx.policy 필드: 별표 key} — 적재된 표에서 파생
allowed_var_paths()     # 정적 사실 ∪ 지금 적재된 별표가 만드는 policy.*
```

- 이름은 표 key에서 `_table`을 떼어 만든다(`welfare_limit_table` → `policy.welfare_limit`).
- `RESOLVERS`는 **이름 override**로만 남는다 — `daily_limit_table` → `position_daily_limit`처럼
  기계적으로 못 뽑는 8종. **하위호환이 목적이다**(이미 ACTIVE인 그래프의 조건이 그 이름을
  참조하고 있어, 이름이 바뀌면 통째로 깨진다).
- 제외 셋: 조립기 전용 파라미터(`NON_POLICY_TABLES`) · `policy` 밖 자리를 차지한 표
  (`DERIVED_FROM_TABLE`) · **스칼라를 안 내놓는 표**(DSL은 스칼라 비교만 한다 — 목록을 올리면
  룰이 비교할 수 없는 값을 자신 있게 참조한다).

**왜 임계값만 열고 사실은 닫나 — 출처가 다르기 때문이다.** `policy.*`는 별표에서 오므로
표가 적재된 순간 조립기가 **자동으로** 채운다. 사실(`tx.*`·`merchant.*`)은 SoR·첨부 추출에서
오므로 경로만 늘리면 값이 영원히 `null`이고, 룰은 만들어지는데 판정은 전건 강등된다(§6).
이건 EvalContext 다이어트 기준 ③("현실적인 출처가 있다")의 다른 표현이다.

**검증기는 숨은 조회를 갖지 않는다.** `validate_graph_vars()`의 기본값은 정적 상수 그대로고,
동적 집합은 호출부가 명시로 넘긴다 — 지금은 ACTIVE 전환 게이트(`services.activate`) 한 곳이다.
판정 계열 코드에 조회를 숨기면 DB가 없는 자리에서 조용히 다르게 동작한다(실측: `SimpleTestCase`
2건이 곧바로 깨졌다). 게이트가 실제로 넘기는지는 회귀로 고정했다(`test_policy_axes.py`).

**프롬프트도 같은 목록을 본다.** `schema_catalog(policy_field_specs())`가 동적 변수를 함께 싣고,
설명은 **별표 제목**을 쓴다(우리가 못 쓰는 설명이라 그게 가장 정확한 한 줄이다). 검증기만 알고
프롬프트가 모르면 모델은 그 임계값을 숫자 리터럴로 박는다 — 규정이 개정돼도 안 따라간다.

### 3.2 축은 여전히 닫힌 집합이다 — 그리고 이제 검사한다

`key_axes`는 **사실 경로**를 가리키므로 위의 "닫힌 쪽"에 속한다. 축이 스키마에 없으면
`resolve_path`가 늘 `None`을 돌려주고 `strict_keys=False`인 표는 `"*"`로 **조용히** 폴백한다 —
값도 나오고 에러도 플래그도 없다.

`check_table_axes()`가 **DB 행**을 대조한다(코드 상수가 아니라 — 시드가 낡아 생긴 드리프트가
정확히 그 사각지대였다). `seed`가 별표 적재 직후 호출해 경고한다. `check_table_keys()`가 축의
**값**을 본다면 이쪽은 축의 **이름**을 본다.

실측으로 잡은 것: `dining_per_person_limit_table`의 축이 `category.scope`였다 — EvalContext에
없는 경로라 **항상** 와일드카드로 떨어지고 있었다. payload에 실제로 있는 값이 단일 한도
하나뿐이므로 **축을 뗐다**(선언을 가진 데이터에 맞춘다). 규정 원문(제14조①)에 조직단위별 값이
실재한다면 그때 `dining.org_unit` 사실을 만들고 축을 되살린다 — **값이 생긴 다음에 축을 만드는**
순서가 맞다.

### 3.3 남은 것 — 별표 적재 파이프라인

`ctx.policy.*`는 열렸지만 **`PolicyTable`에 행을 넣는 경로는 여전히 `tiger_tables.upsert_all()`
하나뿐**이다(`source_doc` FK는 선언만 있고 쓰는 코드가 없다). 문서 적재는 별표를 표로 뽑지 않고
"조에 안 속한 청크"로 검색에만 남긴다. 그래서 지금은 **고객이 규정을 올려도 임계값은 사람이
넣어야 한다** — 다만 넣기만 하면 그 다음은 전부 자동이다(변수·프롬프트·검증·조립).

다음 작업: 표 청크 판별(로직) → 축·변수명 제안(LLM) → **사람 승인**(화면) → `PolicyTable` INSERT.
축 매핑을 자동 확정하면 안 된다 — 위 `category.scope` 결함을 대량 생산한다. 개정도 자동이면
안 된다(`effective_date` INSERT는 과거 판정 재현의 축이다. 재색인이 룰을 자동 생성하지 않는
것과 같은 규율).

---

## 4. 소비층 카탈로그 — `ctx.policy.*` 재정의

### 4.1 기존 8개 항목 검토

| 필드 | 뜻 | 룩업 키 | 반환 | 보편성 | 조치 |
|---|---|---|---|---|---|
| `preapproval_threshold` | 사전승인 필요 기준액 | position | 금액 | 🟢 표준 | 유지 |
| `position_daily_limit` | 직책별 1일 누적 한도 | position | 금액 | 🟢 표준 | 유지 |
| `position_monthly_limit` | 직책별 월 누적 한도 | position | 금액 | 🟢 표준 | 유지 |
| `lodging_limit` | 1박 숙박비 한도 | trip_type × region_grade | 금액 | 🟢 표준 | 유지 (2키) |
| `position_required_level` | 금액구간별 요구 결재단계 | 금액구간 | **enum 서수** | 🟢 표준 | 유지 |
| `kickback_limit` | 청탁금지법 1인당 법정 한도 | gift_type | 금액 | 🟡 한국 한정 | 유지, 키 출처 변경 |
| `approver_daily_limit` | 회식 승인권자 1일 한도 | position | 금액 | 🔴 타이거 고유 | 유지(회사별 카탈로그) |
| `gift_type` | 청탁금지 판정용 선물 유형 | — | enum | ⚫ **정책값 아님** | **제거** |

**`gift_type` 제거 근거**: 산출식·근거 별표가 모두 비어 있다("—"). 실제로는
`kickback_limit = kickback_limit_table[gift_type]`의 **룩업 키**이지 결과가 아니다. 키가 결과와
같은 네임스페이스에 앉아 `policy = "별표 선해소 스칼라"`라는 자기 정의를 어겼다.
→ 이미 동일 값역을 가진 **`category.item_type`**(경조사/선물/개인선물/상품권/행사성/식사)으로 이관한다.

### 4.2 누락 항목 — 8개로는 필요량의 절반이다

현재 시드 룰·에이전트 코드에 등장하지만 `policy.*`에 자리가 없어 **DSL 리터럴이나 필드명에 박혀 있는**
임계값들. 전부 카탈로그로 승격한다.

| 신규 필드 | 값(현재 하드코딩 위치) | 룩업 키 |
|---|---|---|
| `evidence_threshold` | 3만원 — `draft_agent.THRESHOLDS`, seed `E-001` DSL 리터럴 | category |
| `dining_per_person_limit` | 5만원 — `draft_agent`, 회식 그래프 DSL | category.scope(팀/본부/전사) |
| `settlement_deadline_days` | 7영업일 — **`derived.biz_days_over_7` 필드명 안** | category(특칙) |
| `history_window_months` | 3개월 — **`history.*_3m` 필드명 안** | (전역) |
| `night_meal_limit` | 2만원 — 시드 텍스트에만 | position |
| `business_class_min_hours` | 6시간 — 출장 그래프 DSL 리터럴 | position |

→ **확정 카탈로그 = 13개** (기존 7 + 신규 6, `gift_type` 제거).

### 4.3 네이밍 규칙 — 필드명에 상수를 넣지 않는다

`derived.biz_days_over_7`·`history.same_vendor_count_3m`처럼 **상수가 이름에 새겨지면 규정 개정이
스키마 변경이 된다.** 7영업일→5영업일 개정 시 (a) 저장된 모든 `rule_hits.eval_context` 스냅샷이
다른 스키마가 되고 (b) 그 경로를 쓰는 ACTIVE 그래프가 `validate_graph_vars`에서 전부 튕긴다.

| 현재 | 변경 | DSL 표현 |
|---|---|---|
| `derived.biz_days_over_7` (bool) | **삭제** | `derived.business_days_since_expense > policy.settlement_deadline_days` |
| `history.same_vendor_count_3m` | `history.same_vendor_count` | 윈도우는 `policy.history_window_months`로 분리 |
| `history.user_post_approval_count_3m` | `history.user_post_approval_count` | 〃 |
| `history.late_settlement_count_no_reason_3m` | `history.late_settlement_count_no_reason` | 〃 |

> **규칙**: EvalContext 필드명은 *무엇을 재는가*만 담는다. *얼마인가*는 `policy.*`에만 둔다.

---

## 5. 유연성 검증 — 4개 시나리오

| 시나리오 | 기존 `Policy` 모델 | 소비층까지 자유 JSON | **본 캐논(2층)** |
|---|---|---|---|
| 숙박 한도 12만→15만 (개정) | ❌ 2키 표현 불가 | ✅ 데이터 | ✅ 신규 행 + `effective_date` (과거 재현 유지) |
| 숙박 한도에 '직책' 축 추가 (2키→3키) | ❌ 마이그레이션 | ✅ 데이터 | ✅ `payload`+`key_axes` 수정, **마이그레이션 0** |
| '경조사비 한도' 신설 | ❌ 마이그레이션 | ⚠️ 되지만 오타 룰이 ACTIVE 통과 | ✅ 별표 1행 + `RESOLVERS` 1줄 + 카탈로그 1줄 (**코드 2줄**) |
| 타사 규정 도입(범용성) | ❌ 재설계 | ⚠️ 룰 편집기 변수목록 불가 | ✅ 별표 적재 + 매핑. 카탈로그만 회사별 |

---

## 6. 미해소 가드 — "조용한 False"를 없앤다

**계약: `None`은 "거짓"이 아니라 "모름"이다.** 조립기가 판단할 수 있는 사실은 반드시 명시값을
쓴다(거짓이면 `False`). `None`이 남았다면 원천 데이터가 없다는 뜻이고, 그 룰의 판정은 신뢰할 수 없다.

```
미해소 = (순회 경로에서 실제로 참조한 경로) 중 값이 None인 것
```

- 미해소가 하나라도 있으면 판정을 `PASS`로 내리지 않고 **`REVIEW`로 강등**한다.
- 도달하지 않은 노드는 보지 않는다 — 과잉 강등 방지.
- 플래그는 **고치는 방법이 달라 둘로 나눈다**:
  - `UNRESOLVED_POLICY_VAR:<field>` — 별표 미적재·룩업 실패 → **표를 채우면 해결**
  - `UNRESOLVED_FACT:<path>` — SoR에 원천 없음 → **모델·입력 화면이 필요**

> **적용 범위 (2026-08-11 확장)**: 처음에는 `policy.*`만 봤으나, 같은 실패 모드가 다른 섹션에도
> 그대로 있어 **전 구간으로 확장**했다. 확장 직후 실측: 판정 120행 중 **112건(93%) 강등**.
> `policy.*` 13종은 전부 해소되는데도 그렇다 — 임계값과 비교할 **사실**이 없기 때문이다.
> 필드별 출처 가능성은 [`eval-context-sourcing.md`](eval-context-sourcing.md) 참조.

---

## 7. 용어 정리 — 앞으로 "policy"는 3가지만 가리킨다

| 이름 | 정체 | 소유 |
|---|---|---|
| `PolicyTable` | 규정 별표 원본(자유 JSON) | Django `domain/policies` |
| `PolicyDoc` | RAG 소스 문서 메타(PDF 파싱 결과 연결) | Django `domain/policies` |
| `ctx.policy.*` | 별표 선해소 스칼라 — **적재된 표에서 파생**(정적 8종 + 신규 별표, §3.1) | `eval_context.py` 카탈로그 + `context_builder.policy_fields()` |

폐기: `Policy` 모델. 이관: `policy.gift_type` → `category.item_type`.
`policyHints`(제출 전 안내)는 UX 용어로 유지하되 값은 `PolicyTable` 경유로 바꾼다.

> 앱 네이밍 오염(`domain/policies` 1,924줄 중 98%가 룰 그래프)은 별도 과제로 남긴다 —
> 리네임은 임포트 파급이 크므로 본 작업 범위 밖(`policy-domain-plan.md` §비목표).

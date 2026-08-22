# EvalContext 읽는 법 — 사람을 위한 안내

> **이 문서 하나만 읽어도 "판정이 어떻게 이뤄지는가"를 이해할 수 있게 쓴 설명서다.**
> 위쪽은 쉬운 설명, 아래쪽은 상세 명세다. 필요한 깊이에서 멈추면 된다.
>
> 설계 근거·결정 이력은 다른 문서에 있다:
> `policy-domain.md`(규정 임계값) · `eval-context-sourcing.md`(필드 출처·다이어트) ·
> `evidence-extraction-agent.md`(첨부 추출) · `rule-engine-design.md`(엔진 설계 원안)
>
> 최종 갱신: 2026-08-11 · 스키마 v4 (46 필드)

---
---

# PART 1 — 쉬운 설명

## 1. 한 문장으로

> **EvalContext는 "이 지출 건에 대해 우리가 아는 사실을 한 장으로 정리한 표"** 다.
> 룰(규칙)은 이 표만 보고 판정한다. 데이터베이스도, 문서도 직접 보지 않는다.

## 2. 왜 이런 걸 만들었나

규칙이 직접 DB를 뒤지게 하면 세 가지가 깨진다.

| 문제 | EvalContext가 해결하는 방식 |
|---|---|
| 나중에 "왜 반려됐지?"를 못 따진다 | 판정 시점의 표를 **통째로 저장**한다(`rule_hits`). 나중에 그대로 재현 가능 |
| 같은 건인데 돌릴 때마다 결과가 다르다 | 표가 고정이면 결과도 고정. 엔진은 **바깥을 전혀 안 본다** |
| 규칙이 복잡해져 아무도 못 읽는다 | 어려운 일(조회·계산)은 표를 만들 때 끝내고, 규칙은 **비교만** 한다 |

## 3. 세 단계로 흐른다

```
 ①  조 립  ────────────────▶  ②  선 택  ────────────▶  ③  순 회
 DB·첨부문서·규정 별표를        어떤 규칙 묶음을            규칙을 따라가며
 읽어 "사실 표"를 만든다        적용할지 고른다             판정한다

 여기서만 바깥을 본다          비용분류에 따라             표만 보고 계산
 (I/O는 전부 여기)             (공통 게이트 → 과목별)      (결과가 항상 같음)
```

**핵심 원칙 한 줄: "똑똑한 일은 ①에서, 기계적인 일은 ③에서."**

## 4. 표는 어떻게 생겼나

15개 칸으로 나뉘어 있다. 실제 예시(일부):

```jsonc
{
  "tx":       { "amount": 620000, "per_person_amount": 155000, "payment_time": "21:40" },
  "card":     { "card_type": "SHARED", "actual_user_recorded": true },
  "merchant": { "merchant_type": "한식", "merchant_info_resolved": true, "forbidden": false },
  "evidence": { "has_valid_receipt": true, "expense_purpose_missing": false },
  "approval": { "pre_approval_obtained": false },
  "participants": { "participant_count": 4, "has_kickback_law_target": false },

  "policy":   { "preapproval_threshold": 500000, "evidence_threshold": 30000 },  // ← 규정에서 읽어온 한도

  "tables":   { "pre_approval_threshold_table": { "*": 500000 } },  // 감사용 원본
  "conflicts":{ },                                                   // 값이 엇갈린 기록
  "meta":     { "settlement_id": 84, "schema_version": 4, "built_at": "..." }
}
```

이 표로 규칙이 판정한다:

```
결제금액(620,000) > 사전승인기준(500,000)  AND  사전승인 받음 == false
   → 참! → 「보완요청」 + 사유 PRE_APPROVAL_MISSING
```

## 5. 꼭 알아야 할 규칙 4개

### ① `null`은 "아니오"가 아니라 **"모른다"** 다

이 프로젝트에서 가장 중요한 약속이다.

| 값 | 뜻 |
|---|---|
| `false` | **확인했고, 아니다** |
| `null` | **아직 모른다** |

왜 중요한가? 예전에는 둘을 구분하지 않아서 이런 일이 있었다:

```
"사전승인 받았나?" → 모름(null)
규칙: 금액 > 한도 AND 사전승인 == false
   → null은 false가 아니므로 조건 불성립 → 「통과」
   → 에러도, 경고도 없이 조용히 넘어감  ❌
```

지금은 **모르면 통과시키지 않는다.** 아래 ②가 그 장치다.

### ② 모르는 걸 참조하면 → 판정을 「검토 필요」로 낮춘다 (미해소 가드)

규칙이 지나간 길에서 참조한 값이 `null`이면, 그 판정은 믿을 수 없다.

```
판정: 검토 필요(REVIEW)
사유: UNRESOLVED_FACT:approval.pre_approval_obtained   ← 무엇을 몰라서인지까지 표시
```

사유 표시가 두 종류인 이유는 **고치는 방법이 다르기 때문**이다:

| 표시 | 뜻 | 고치는 법 |
|---|---|---|
| `UNRESOLVED_POLICY_VAR:...` | 규정 한도표를 못 읽음 | **표를 채우면 끝** |
| `UNRESOLVED_FACT:...` | 시스템에 그 사실이 아예 없음 | **입력칸·문서 추출이 필요** |

### ③ 한도 숫자는 규칙에 안 적는다 — 규정 표에서 읽는다

```
❌  결제금액 > 500000                        규정이 바뀌면 규칙을 고쳐야 함
✅  결제금액 > policy.preapproval_threshold   규정 표만 고치면 됨
```

`policy.*` 칸이 바로 **규정 별표에서 읽어와 미리 풀어놓은 숫자**다.
회계 담당자가 관리자 화면에서 표의 숫자를 바꾸면, 코드 배포 없이 판정이 따라온다.

### ④ 판단은 규칙이 조합한다 — 표에는 「사실」만 담는다

```
❌  derived.personal_use_suspected = true        ← "사적 사용 의심"은 결론이다
✅  is_late_night = true                          ← 사실
    is_weekend   = true                           ← 사실
    → 규칙에서 "심야 AND 휴일"로 조합해 판단        ← 판단은 규칙이
```

결론을 입력으로 받으면 **"AI가 의심한대요"** 가 되어 근거를 따질 수 없다.
사실로 쪼개 두면 조합 규칙이 화면에 보이고, 회계 담당자가 반박할 수 있다.

## 6. 값은 어디서 오나 — 세 갈래

```
  ┌── 원장 (카드 전표·정산 기록) ──┐
  │     금액, 결제시각, 영수증      │
  ├── 화면 입력 (사람이 채움) ─────┤ ──▶  하나의 표로 합침  ──▶  규칙 판정
  │     참석 인원, 사전승인 여부    │        (충돌 처리)
  ├── 첨부 문서 (AI가 읽음) ───────┤
  │     회의록·출장계획서·결재문서   │
  └────────────────────────────────┘
       + 규정 별표 (한도 숫자)
```

**같은 값이 서로 다르게 오면?** — 예: 회의록은 4명, 참석자명단은 6명, 사용자는 9명.

| 상황 | 처리 |
|---|---|
| 순위가 다르다 (사용자 9명 vs 문서 4명) | **사용자가 이긴다.** 문서 값은 "엇갈렸음"으로 기록 |
| 순위가 같은데 다르다 (문서 4명 vs 문서 6명) | **어느 쪽도 안 쓴다.** `null`로 두고 → 「검토 필요」 |

*두 문서가 다르면 "아무거나 고르기"가 아니라 "사람이 봐야 한다"가 맞다.*

## 7. 지금 어디까지 됐나 (2026-08-11)

| | 상태 |
|---|---|
| 표를 만드는 조립기 | ✅ 동작 |
| 규정 한도 8종 | ✅ 표에서 읽어옴 |
| 첨부 추출 **저장 자리** | ✅ 있음 |
| 첨부 추출 **실제 판독** | 🔲 미구현 (증빙자료 추출 Agent) |
| 판정 사실 | 🚧 **절반쯤** — 46칸 중 24칸이 채워진다 |

**실측**: 실 정산 120건 판정 중 **37건(31%)** 이 "몰라서 검토 필요"로 간다.
막고 있는 건 4가지뿐이고, 전부 **컬럼을 채우면 해결**된다:

```
37건  참석 인원          37건  1인당 금액(인원에서 파생)
20건  회식 2차 여부      17건  청탁금지 대상자 참석 여부
```

> 참고: 이 31%에는 측정 방식의 과장이 섞여 있다. 시뮬레이션은 출장·비품 건까지 회식 그래프에
> 돌려서 참석 인원을 요구한다. 운영은 비용분류별로 그래프를 골라 쓰므로 해당하지 않는다.

---
---

# PART 2 — 상세 설명

## 8. 전체 필드 카탈로그 (스키마 v4 · 46 필드)

`apps/core/domain/policies/eval_context.py`의 `_SCHEMA_FIELDS`가 정본이다.

> ⚠️ **2026-08-20부터 이 표는 정본이 아니다.** 필드의 **타입과 한 줄 설명이 코드로
> 승격됐다**(`FieldSpec(type, desc, enum)`) — 그 값이 그대로 에이전트 프롬프트에 나가기
> 때문이다(`_context/agent-context-tool.md`). 아래 표는 사람이 읽는 해설로 남기고, 값이
> 어긋나면 코드가 이긴다. 현재 코드는 v5(47 필드, `user.position` → `user.job_title` +
> `job_title_rank`)라 아래 v4 표와 이미 다르다.

### 8.1 사실 섹션 (33)

| 섹션 | 필드 | 뜻 | 출처 | 현재 |
|---|---|---|---|---|
| **tx** (4) | `amount` | 건당 총액(원) | 원장 | ✅ |
| | `per_person_amount` | 1인당 환산 | 파생(금액÷인원) | 🚧 인원 의존 |
| | `payment_time` | 결제 시각 `HH:MM` | 원장 | ✅ |
| | `payment_method` | 결제 수단 | 원장 | ✅ (현재 `"법인카드"` 고정) |
| **card** (2) | `card_type` | 개인/팀/공용/후정산/선불 | 원장 | ✅ |
| | `actual_user_recorded` | 실사용자 기록 여부 | 입력 | ✅ (개인카드는 항상 true) |
| **user** (3) | `position` | 직책(별표 축) | — | 🔲 SoR에 필드 없음 |
| | `finance_dept_is_spender` | 지출자가 재무회계 소속인가 | 원장 | 🔲 미조립 |
| | `is_working_hours` | 근무시간 내 결제인가 | 파생 | 🔲 미조립 |
| **merchant** (3) | `merchant_type` | 업종 | 업종 캐시 | ✅ |
| | `merchant_info_resolved` | 업종을 밝혔는가 | 파생 | ✅ |
| | `forbidden` | 금지업종인가 | 별표 선해소 | ✅ (업종 미상이면 `null`) |
| **category** (3) | `value` | 비용분류 6종 | 원장 | ✅ |
| | `confidence` | 분류 신뢰도 | AI 제안 여부 | ✅ |
| | `item_type` | 지출 세부유형 (청탁금지 룩업 키 겸용) | 입력 | 🚧 |
| **evidence** (3) | `has_valid_receipt` | 적격증빙 있는가 | 원장 | ✅ |
| | `has_supporting_evidence` | 영수증 외 추가 증빙 있는가 | 첨부 유무 | ✅ |
| | `expense_purpose_missing` | **지출 목적/사유 미기재** | 원장 | ✅ |
| **approval** (1) | `pre_approval_obtained` | 사전승인 받았는가 | 입력·문서 | 🚧 |
| **participants** (3) | `participant_count` | 참석 인원 (`0`=명단 누락) | 입력·문서 | 🚧 |
| | `external_participant_count` | 외부 참석 인원 | 입력·문서 | 🚧 |
| | `has_kickback_law_target` | 청탁금지 대상자 참석 | 입력·문서 | 🚧 |
| **trip** (3) | `trip_type` / `region_grade` | 출장 구분 / 지역등급 (숙박 별표 축) | 문서 추출 | 🔲 |
| | `lodging_amount_per_night` | 1박 숙박비 | 문서 추출 | 🔲 |
| **dining** (2) | `includes_alcohol` / `is_secondary_venue` | 주류 포함 / 2차 성격 | 입력 | 🚧 |
| **history** (3) | `same_vendor_count` | 동일 가맹점 반복 결제 수 | 집계 | 🔲 미조립 |
| | `daily_cumulative_amount` / `monthly_cumulative_amount` | 당일/당월 누적 | 집계 | 🔲 미조립 |
| **derived** (3) | `business_days_since_expense` | 결제 후 경과 영업일 | 파생 | 🔲 미조립 |
| | `is_late_night` / `is_weekend` | 심야 / 주말 결제 | 파생 | ✅ |

> ✅=조립됨 · 🚧=컬럼은 있으나 비어 있을 수 있음 · 🔲=미조립(원천 없음/코드 없음)

### 8.2 정책 섹션 (8) — 별표에서 선해소한 숫자

| 필드 | 뜻 | 별표 | 룩업 축 |
|---|---|---|---|
| `preapproval_threshold` | 사전승인 필요 기준액 | `pre_approval_threshold_table` | 직책 |
| `position_daily_limit` / `position_monthly_limit` | 직책별 일/월 한도 | `daily/monthly_limit_table` | 직책 |
| `kickback_limit` | 청탁금지 1인당 법정 한도 | `kickback_limit_table` | 지출 세부유형 |
| `lodging_limit` | 1박 숙박비 한도 | `lodging_limit_table` | 출장구분 × 지역등급 |
| `evidence_threshold` | 적격증빙 필수 기준액 | `evidence_threshold_table` | 비용분류 |
| `dining_per_person_limit` | 회식 1인당 한도 | `dining_per_person_limit_table` | 회식 조직단위 |
| `settlement_deadline_days` | 정산 제출 기한(영업일) | `settlement_deadline_table` | 비용분류 |

### 8.3 감사 섹션 (3) — 규칙은 참조할 수 없다

| 섹션 | 내용 | 왜 |
|---|---|---|
| `tables` | 판정에 실제로 쓴 별표 원본 | "어떤 한도표로 판정했나"를 되짚기 위해 |
| `conflicts` | 값이 엇갈린 기록 | 무엇을 택하고 무엇을 버렸는지 |
| `meta` | 정산/거래 id, 스키마·조립기 버전, 생성 시각 | 재현·리플레이 |

`tables`·`conflicts`는 **고정 필드 목록이 없다**(동적). 그래서 규칙이 이 경로를 참조하면
활성화 검증(`validate_graph_vars`)이 거부한다 — 의도된 설계다.

---

## 9. 조립 파이프라인 상세

`apps/core/domain/policies/context_builder.py`

```python
build_rule_context(settlement=...)
  │
  ├─ 1. collect_from_attachments(merger, settlement)     # 순위 1 — 첨부 문서 추출
  │       DONE 상태 첨부의 extracted(dot-path→값)를 제안
  │
  ├─ 2. collect_from_settlement(merger, settlement)      # 순위 3(원장) / 순위 2(입력)
  │       원장: 금액·시각·영수증·업종·심야/주말
  │       입력: 참석 인원·사전승인·2차·주류·세부유형
  │
  ├─ 3. derive_after_merge(merger)                       # 합쳐진 뒤에 산술 파생
  │       per_person_amount = amount ÷ participant_count
  │
  ├─ 4. merger.apply(ctx)                                # 표에 반영 + conflicts 기록
  │
  ├─ 5. resolve_policy(ctx, tables)                      # 별표 → policy.* 선해소
  │       + tables에 원본 스냅샷
  │
  └─ 6. meta 기록 → (ctx, unresolved) 반환
```

### 9.1 출처 순위와 충돌 규칙

| 순위 | 상수 | 출처 |
|---:|---|---|
| 3 | `RANK_SOR` | 원장 사실·산술 파생 |
| 2 | `RANK_INPUT` | 화면 입력(사람이 확정) |
| 1 | `RANK_EXTRACT` | 첨부 문서 추출 |

1. **높은 순위가 이긴다.** 값이 다르면 진 쪽을 `conflicts`에 기록(판정은 이긴 값으로 진행)
2. **같은 순위인데 값이 다르면 어느 쪽도 쓰지 않는다** → `null` + 기록 → 가드가 `REVIEW`
3. **`null`은 아무것도 덮지 않는다** (빈 컬럼이 추출값을 지우지 않음)
4. **상위 순위가 오면 동순위 충돌이 풀린다**

```jsonc
"conflicts": {
  "participants.participant_count": {
    "kept": 9, "kept_from": "input", "resolution": "input_wins",
    "dropped": [{ "value": 4, "from": "attachment:12(MEETING_MINUTES)" }]
  }
}
```
`resolution`: `sor_wins` · `input_wins` · `dropped_as_unknown`

### 9.2 별표 폴백 — 표마다 정책이 다르다

`PolicyTable.strict_keys`

| | 축 값을 **모를 때** | 축 값을 **알지만 표에 없을 때** |
|---|---|---|
| `False`(기본, 한도표) | `"*"` 기본값 사용 | `"*"` 기본값 사용 |
| `True`(금지업종표) | **해소 안 함 → `null`** | `"*"` 기본값 사용 |

직책을 몰라 회사 기본 한도를 쓰는 건 안전하다. 하지만 업종을 모르는데 "금지 아님"으로
단정하면 금지업종 결제가 조용히 통과한다 — 그래서 표마다 다르게 둔다.

### 9.3 별표 개정은 UPDATE가 아니라 INSERT

새 `effective_date` 행을 추가하고 구행에 `superseded_date`를 찍는다.
`load_tables(as_of)`가 **지출 시점 기준**으로 유효한 표를 고르므로, 과거 판정을 그때 한도로
재현할 수 있다.

---

## 10. 소비 — 엔진이 표를 읽는 방식

`apps/core/domain/policies/engine.py` · `dsl.py`

- 조건식은 **JSON-Logic 부분집합**이다: `and` `or` `not` `==` `!=` `>` `>=` `<` `<=` `in` `var`
  임의 코드·산술·동적 인덱싱이 없다(안전·감사 용이).
- 순회는 `entry_node_key`에서 시작해 `MATCH`/`NO_MATCH` 라우팅을 따라 단말까지.
- 결과는 `(decision, path, flags, confidence)`. **같은 입력 → 항상 같은 출력.**

### 10.1 미해소 가드

```python
# 노드를 지날 때마다, 그 노드가 실제로 참조한 경로만 검사
unresolved += [p for p in referenced[current] if resolve_path(ctx, p) is None]
```

- **지나간 노드만** 본다 → 도달하지 않은 노드 때문에 과잉 강등하지 않는다
- 하나라도 있으면 판정을 `REVIEW`로 강등, `confidence=0.0`
- 플래그: `UNRESOLVED_POLICY_VAR:<필드>` / `UNRESOLVED_FACT:<경로>`
- 시연용 완화 스위치: `DEMOTE_ON_UNRESOLVED_POLICY = False`로 두면 플래그만 남기고 강등하지 않음

### 10.2 활성화 게이트

그래프를 ACTIVE로 올릴 때 `validate_graph_vars`가 **스키마에 없는 경로 참조를 거부**한다.
오타 난 룰이 활성화돼 영원히 발동하지 않는 사고를 막는다.

---

## 11. 코드·테스트 위치

| 무엇 | 어디 |
|---|---|
| 스키마 계약(46필드) | `policies/eval_context.py` |
| 조립기 | `policies/context_builder.py` |
| 별표 모델 / 시드 | `policies/models.py:PolicyTable` / `policies/tiger_tables.py` |
| 엔진 / DSL | `policies/engine.py` / `policies/dsl.py` |
| 판정 입력 컬럼 | `settlements/models.py:Settlement` |
| 첨부·추출 결과 | `settlements/attachments.py:Attachment` |
| 내부 API | `GET /api/internal/rule-context/<settlement_id>/` |
| **조립 테스트** | `policies/tests/test_eval_context_assembly.py` (32 케이스) |
| **소비 테스트** | `policies/tests/test_rule_graph_consumption.py` (29 시나리오) |

두 테스트 파일은 **표 형태로 입력·기대값을 나란히** 적어 두었다. 명세로 읽어도 된다.

```python
# 조립
Case("참석 4명 · 40만원 → 1인당 10만원 자동 환산",
     Given(amount=400_000, headcount=4),
     expect={"participants.participant_count": 4, "tx.per_person_amount": 100_000})

# 소비
Scenario("62만원·사전승인 없음 → 보완요청 (기준 500,000)",
         facts={**ENTERTAIN_OK, "tx__amount": 620_000,
                "approval__pre_approval_obtained": False},
         decision="RETURN", flags=["PRE_APPROVAL_MISSING"], path=["E-001", "E-002"])
```

---

## 12. 스키마 버전 이력

| 버전 | 변경 | 비고 |
|---|---|---|
| v1 | 최초 카탈로그(101 필드) | 규정 명세서 기준 이상 집합 |
| v2 | `policy.gift_type` 제거, 누락 임계값 6종 승격, **필드명 상수 제거**(`biz_days_over_7`·`*_3m`) | `policy-domain.md` §4 |
| v3 | **다이어트 101 → 46.** 판정 필드·조합 가능 필드·원천 없는 필드 제거. `tables` 동적화 | `eval-context-sourcing.md` §12 |
| **v4** | `evidence.purpose_missing` → **`expense_purpose_missing`**, **`conflicts` 섹션 신설** | 본 문서 §9.1 |

**과거 스냅샷은 소급 수정하지 않는다.** `rule_hits.eval_context_schema_version`으로 구분해 읽는다.

---

## 13. 다음에 할 일

우선순위는 `eval-context-sourcing.md` §7·§13에 있다. 요약하면:

1. **GLOBAL 게이트에 적용 조건 붙이기** — 소액 식대에도 공용카드 실사용자를 묻는 건 과하다.
   컬럼 추가 0으로 강등을 줄이는 가장 값싼 수
2. **A등급 조립 채우기** — `user.*` 3종, `history.*` 3종, `derived.business_days_since_expense`
   (데이터는 이미 있고 코드만 없다)
3. **증빙자료 추출 Agent 구현** — `Attachment.extracted`를 채우면 참석 인원·사전승인이 살아난다
4. **`orchestrator.py`** — GLOBAL→scope 그래프 선택·`RuleHit` 기록(현재 시뮬레이션 경로에만 있음)

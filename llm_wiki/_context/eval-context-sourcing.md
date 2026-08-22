# EvalContext 데이터 출처 실현 가능성 점검

> **파생 컨텍스트.** 판정에 필요한 사실(EvalContext)을 **어디서 구해올 수 있는가**를 필드별로
> 등급화한 문서다. 규정 임계값(`policy.*`) 쪽 설계는 `_context/policy-domain.md`,
> 필드 정의 자체는 `법인카드_사용규정_기반_RULE_명세서.md` §2가 SoT다.
>
> 최종 갱신: 2026-08-11 · 근거: 실측(§1·§8·§12) + 요구사항 FR-DA-* + Draft Agent API 계약
>
> ⚠️ **§1~§7은 다이어트 이전(스키마 v2, 101 필드) 기준의 점검 기록이다.** 그 결론으로
> **v3 다이어트(101 → 46)를 실행했고**, 현행 구조와 남은 과제는 **§12·§13**에 있다.
> 지금 상태만 알고 싶으면 §12부터 읽으면 된다.

---

## 0. 왜 이 문서가 필요한가

미해소 가드를 `policy.*`에서 **전 구간**으로 확장하자(2026-08-11), 감춰져 있던 규모가 드러났다.

```
판정 행 120건 중 미해소로 강등 112건 (93%)
  회식비 검증 그래프        40/40 강등
  법인카드 공통 필수 게이트  37/40 강등
  기업업무추진비 검증 그래프 35/40 강등
```

**`policy.*` 13종은 전부 해소되는데도 93%가 판정 불가다.** 임계값을 고쳐도 그 임계값과 비교할
사실(참석 인원·사전승인 여부·카드 구분…)이 SoR에 없기 때문이다.

> DSL은 `None` 비교를 `False`로 흡수하므로, 가드가 없으면 이 112건은 **"통과(PASS)"로 보인다.**
> 가드는 문제를 만든 게 아니라 드러냈을 뿐이다.

**계약**: `None`은 "거짓"이 아니라 **"모름"** 이다. 조립기가 판단할 수 있는 사실은 반드시 명시값을
쓴다(거짓이면 `False`). `None`이 남으면 그 룰의 판정은 신뢰할 수 없다 → `REVIEW` 강등.

---

## 1. 실측 — 지금 판정을 막고 있는 10개

ACTIVE 3그래프 × 실 정산 120행 기준. 괄호는 등급(§2).

| 건수 | 필드 | 등급 | 왜 없나 |
|---:|---|---|---|
| 75 | `evidence.participant_list_missing` | **B** | 참석자 기재 항목이 `purpose` 자유텍스트에만 있음 |
| 75 | `tx.per_person_amount` | **B** | 참석 인원 컬럼이 없어 나눌 수가 없음 |
| 40 | `dining.is_secondary_venue` | **B** | 회식 2차 여부 입력칸 없음 |
| 37 | `card.actual_user_recorded` | **B** | FR-DA-04가 요구하나 전용 필드 없음(`purpose` 텍스트로만) |
| 37 | `card.card_type` | **A** | `Card.card_type`이 **이미 있는데 조립기가 안 읽음** |
| 37 | `category.item_type` | **B** | 지출 세부유형(경조사/선물/상품권) 미입력 |
| 37 | `derived.personal_use_suspected` | **C** | Risk Agent 판정 미구현 |
| 35 | `approval.pre_approval_obtained` | **B** | 승인 여부 필드 없음 |
| 35 | `participants.has_kickback_law_target` | **B** | 청탁금지 대상자 체크 없음 |
| 35 | `tx.service_charge_ratio` | **D** | 영수증 봉사료 항목 파싱 필요 — **MVP에서 빼는 게 현실적** |

---

## 2. 등급 정의

| 등급 | 뜻 | 필요한 일 |
|---|---|---|
| **A** | **설계상 커버 + 데이터 이미 있음** — 조립기가 안 읽을 뿐 | 조립기 코드 (수~수십 줄) |
| **B** | **설계상 커버 + 계약도 있음** — DB 컬럼·입력칸만 없음 | 필드 1~2개 + 입력 UI + 조립기 |
| **C** | **추가 설계 필요** — 도메인 모델 신설(승인선·출장·AI 판정) | 모델 + 화면 + 연동 |
| **D** | **빼는 게 현실적** — MVP 규정 근거·데이터 원천 모두 부재 | 룰 조건에서 참조 제거 |

> **B가 "설계상 커버"인 근거**: FR-DA-04("카드 구분에 따라 **실사용자**·목적·증빙 자동 요청"),
> Draft Agent API 계약(`headcount`·`evidence`가 요청/응답 스키마에 **이미 존재**),
> `draft-agent-v0.2.md` §7("`evidence`/`headcount`를 Settlement DB에 영구 저장 —
> **현재 Django 모델에 해당 컬럼 자체가 없음, 스키마 결정 선행 필요**").
> 즉 화면·API는 이미 값을 나르고 있고 **저장할 자리만 없다.**

---

## 3. ✅ A — 설계상 커버, 지금 코드만 쓰면 됨 (15)

원천 데이터가 SoR에 이미 있다. 모델 변경 0.

| 필드 | 출처 |
|---|---|
| `card.card_type` | `Card.card_type` (Transaction→Card) |
| `user.dept` | `User.team.name` |
| `user.finance_dept_is_spender` | `User.team.name` 재무회계 판별 |
| `user.is_working_hours` | `Transaction.ts` 계산 |
| `tx.payment_method` | `Card.card_type` 기반 (현재 `"법인카드"` 하드코딩) |
| `merchant.merchant_info_resolved` | `MerchantCategory` 조회 성공 여부 |
| `merchant.forbidden` | 금지업종 목록을 **`PolicyTable` 1행**으로 넣고 `merchant_type` 대조 |
| `history.same_vendor_count` | `Transaction.merchant` 집계 (윈도우 = `policy.history_window_months`) |
| `history.daily_cumulative_amount` | 사용자·일자 `Settlement` 합계 |
| `history.monthly_cumulative_amount` | 사용자·월 `Settlement` 합계 |
| `history.late_settlement_count_no_reason` | `SettlementEvent` 이력 + 기한 비교 |
| `dining.same_event_multiple_merchants` | 동일 사용자·동일일 다건 결제 집계 |
| `derived.business_days_since_expense` | `ts` ~ 오늘 (⚠️ 공휴일 캘린더 없어 **주말만 반영하는 근사**) |
| `derived.category_specific_deadline_applies` | 특칙 분류 목록을 `PolicyTable` 1행으로 |
| `derived.category_specific_preapproval_rule_exists` | 〃 |

> `history.*` 5개는 데이터가 이미 84건 쌓여 있는데 조립기가 집계를 안 할 뿐이다.
> **투입 대비 회수가 가장 큰 묶음.**

---

## 4. 🔧 B — 설계상 커버, 스키마·입력칸 추가 필요 (12)

| 필드 | 추가할 것 | 근거 |
|---|---|---|
| `participants.participant_count` | `Settlement.headcount` (int) | Draft Agent 계약에 `headcount` 이미 존재 |
| `tx.per_person_amount` | 위에서 파생(`amount / headcount`) | 〃 |
| `evidence.participant_list_missing` | 위에서 파생(`headcount == 0`) | 〃 |
| `participants.external_participant_count` | `Settlement.external_headcount` (int) | 입력칸 1개 |
| `approval.pre_approval_obtained` | `Settlement.pre_approved` (bool) + 첨부 | 규정 제12조① 핵심 |
| `card.actual_user_recorded` | `Settlement.actual_user` (FK/문자열) | **FR-DA-04 명시** |
| `evidence.has_supporting_evidence` | `Receipt` 종류 구분 or bool | FR-DA-05 |
| `category.item_type` | `Settlement.item_type` (choices) | 경조사/선물/상품권/식사 |
| `participants.has_kickback_law_target` | `Settlement.kickback_target` (bool) | 청탁금지 룰 R-106 |
| `dining.is_secondary_venue` | `Settlement.is_secondary` (bool) | 회식 룰 |
| `dining.includes_alcohol` | `Settlement.includes_alcohol` (bool) | 회식 룰 |
| `user.position` | `User.position` (choices) | 직책별 별표 축. 조직 데이터는 `tiger_inc/직급체계.md`에 존재 |

> 대부분 **Settlement에 bool/int 컬럼 + S-01 입력칸 1개**다. `headcount` 계열 3개는
> 컬럼 하나로 3필드가 동시에 살아난다(75+75건 = 최대 효과).

---

## 5. 🏗 C — 추가 설계 필요 (13)

도메인 모델을 새로 만들어야 한다. **MVP 일정에 넣을지 결정이 필요한 구간.**

| 묶음 | 필드 | 필요한 것 |
|---|---|---|
| **승인선(결재)** | `approval.pre_approval_level`, `post_approval_within_1biz_day`, `approver_is_spender_self`, `history.user_post_approval_count` | 승인 요청·결재선 모델 + 직책 서수 |
| **출장** | `trip.trip_type`, `trip.region_grade`, `trip.lodging_amount_per_night`, `derived.business_days_since_trip_end` | 출장신청 모델(기간·지역·숙박) |
| **AI 판정** | `derived.personal_use_suspected`, `evidence.purpose_is_generic` | Risk/Draft Agent 실구현 |
| **기타** | `category.scope`(회식 조직단위), `participants.kickback_law_category` | 분류 세분화 |

> **출장 3필드가 없으면 `policy.lodging_limit`을 해소해도 쓸 데가 없다** — 출장비 그래프는
> 현재 승인대기(SIMULATED) 상태라 당장 판정에 영향은 없지만, 활성화하려면 이 묶음이 선행이다.

---

## 6. ✂️ D — 빼는 게 현실적 (38)

원천 데이터도 없고, MVP 범위(FR-DA-03: **기업업무추진비·회식비·출장비 3종만 자동 판정**)에서
회수도 낮다. **룰 조건에서 참조를 제거하거나 해당 노드를 비활성화**하는 게 정직하다.

| 묶음 | 필드 | 왜 빼나 |
|---|---|---|
| 영수증 상세 파싱 | `tx.service_charge_ratio` | 봉사료 항목을 비전 모델이 뽑아야 함. **ACTIVE 그래프가 참조 중이라 우선 제거 대상** |
| 공휴일 | `tx.is_holiday` | 공휴일 캘린더 미도입. `derived.is_weekend`로 근사 |
| 가맹점 등급 | `merchant.merchant_grade` | 업종 캐시에 등급 축 없음(카카오 미제공) |
| 세부 첨부·기재 6종 | `evidence.event_plan_attached`, `confirmation_doc_submitted`, `vendor_info_missing`, `venue_datetime_missing`, `project_name_missing`, `participant_record_missing` | 첨부 종류별 관리 체계 부재 |
| 참석자 상세 5종 | `contractor_participant_count`, `contractor_regular_communication_purpose`, `kickback_law_target_status_missing`, `participant_includes_former_employee`, `family_or_personal_gathering_suspected` | 참석자 명부 모델 필요(인원수만으로 충분) |
| 출장 상세 9종 | `flight_class`, `flight_duration_hours`, `booking_to_trip_gap_months`, `during_business_trip`, `itinerary_mismatch`, `work_end_time`, `expense_type`, `trip_request_submitted_days_before`, `emergency_trip` | 출장 도메인 전체 + 항공 예약 연동 |
| 세부 유형 3종 | `category.entertainment_type`, `meal_type`, `event_type` | 분류 6종으로 충분 |
| 기타 | `approval.escalated_approval_confirmed`, `spender_attended`, `dining.event_scale_payment_method` | 규정 근거 대비 입력 부담 과다 |

### 빼는 방법 — 스키마에서 지우지 말 것

`_SCHEMA_FIELDS`에서 필드를 삭제하면 (a) 저장된 `rule_hits.eval_context` 스냅샷과 스키마가
어긋나고 (b) 그 경로를 쓰는 그래프가 `validate_graph_vars`에서 튕긴다.

**권장**: 스키마에는 남기고 **룰 조건에서 참조를 제거**한다. 그러면 가드가 그 필드를 보지 않게
되어 판정이 살아난다. 나중에 데이터가 생기면 조건만 되살리면 된다.

---

## 7. 권장 순서와 예상 효과

현재 강등 **112/120 (93%)** 기준. 각 단계 후 예상치는 §1의 건수에서 산출한 **추정**이다(미실측).

| 단계 | 작업 | 해소되는 필드 | 남는 강등(추정) |
|---|---|---|---|
| **0** | `card.card_type` 조립 (A, 5줄) | 37건분 1개 | ~112 (다른 필드와 중복) |
| **1** | `Settlement.headcount` 컬럼 + S-01 입력칸 | `participant_count`·`per_person_amount`·`participant_list_missing` (75건) | ~75 |
| **2** | `pre_approved`·`kickback_target` bool 2개 | 기업업무추진비 그래프 핵심 2필드 (35건) | ~55 |
| **3** | `actual_user`·`item_type` | 공통 게이트 2필드 (37건) | ~40 |
| **4** | `is_secondary`·`includes_alcohol` | 회식 그래프 (40건) | ~10 |
| **5** | `tx.service_charge_ratio` **룰에서 제거** (D) | — | ~5 |
| **6** | `derived.personal_use_suspected` — Risk Agent 연동 or 노드 비활성 | (C) | ~0 |
| **7** | `history.*` 집계 조립 (A) | 지금은 ACTIVE가 안 쓰지만 T-41 등 활성화 시 필요 | — |

**1~4단계가 전부 B등급**이고, 합쳐서 **Settlement에 컬럼 6개 + S-01 입력칸 6개**다.
이것만으로 강등 93% → 약 8%가 된다(추정).

---

## 8. 부분 조립으로 충분한가 — **그렇다** (실측)

> "식대는 근무 여부·시간대·가격 상한·업종만 보고 승인한다면, 나머지 EvalContext가 전부 `None`이어도
> 잘 처리되나?"

**된다.** 가드는 **순회 경로에서 실제로 참조한 경로만** 검사하기 때문이다. 참조하지 않은 필드는
`None`이든 아니든 판정에 관여하지 않는다.

최소 식대 그래프(근무시간·심야·상한·업종 4조건)를 실 정산 8건에 돌린 결과:

```
#82   78,000원 21:00 업종=음식점  채워진 42/101 | 최소그래프 → REVIEW OFF_HOURS  미해소 0건 | GLOBAL → REVIEW 미해소 4건
#73   11,000원 21:00 업종=음식점  채워진 42/101 | 최소그래프 → REVIEW OFF_HOURS  미해소 0건 | GLOBAL → REVIEW 미해소 4건
...  (8건 전부 동일 패턴)
```

- **101개 중 42개만 채워졌는데도 최소 그래프는 미해소 0건**으로 정상 판정했다
  (`OFF_HOURS`는 강등이 아니라 실제 판정 — 시드 식대가 21:00·06:00·22:00에 몰려 있다).
- 같은 컨텍스트로 **GLOBAL 게이트를 돌리면 미해소 4건**이 뜬다.

### ⚠️ 그래서 진짜 병목은 카테고리 그래프가 아니라 **GLOBAL 게이트**다

모든 거래가 GLOBAL을 먼저 통과해야 하는데, 이 게이트가 **전 건에 대해** 4개 사실을 요구한다:

| GLOBAL이 요구 | 등급 | 소액 식대 1건에도 필요한가? |
|---|---|---|
| `card.card_type` | A | 데이터 있음 — 조립기만 고치면 됨 |
| `card.actual_user_recorded` | B | 공용카드에만 의미 있음 |
| `category.item_type` | B | 식대엔 사실상 무의미 |
| `derived.personal_use_suspected` | C | AI 판정 |

**소액 식대 1건 때문에 "공용카드 실사용자 기록 여부"를 물을 이유가 없다.**
→ 권장: GLOBAL 게이트 노드에 **적용 조건을 붙인다**(예: `card.card_type == "공용"`일 때만
`actual_user_recorded`를 보게 라우팅). 그러면 해당 없는 건은 그 노드를 지나가지 않고,
가드도 그 필드를 보지 않는다.

> **원칙**: 필드를 채우는 것보다 **안 물어보는 것**이 싸다. 조건 없는 필수 게이트는
> 전처리 규율(§`policy-domain.md`)과 같은 실수다 — "적용 조건 없는 검사는 본문을 잘라먹는다."

---

## 9. 출처 축 하나가 빠져 있었다 — **첨부 문서 추출**

§4는 B등급을 전부 "입력칸 추가"로 적었는데, 실제로는 **사람이 타이핑할 값이 아니라 증빙에서
뽑아야 할 값**이 많다. 출처를 두 갈래로 나눈다.

| 출처 | 뜻 | 이미 있는 인프라 |
|---|---|---|
| **B-입력** | 사람이 체크/선택 | S-01 폼 |
| **B-문서** | 첨부에서 추출 | `Receipt.file_ref`/`ocr_text`, **OpenAI 비전 직접 판독**(설계 결정), **PDF 파싱 파이프라인**(`chunk_pdf`) |

### 재분류

| 필드 | 원 등급 | 실제 출처 | 추출 대상 문서 |
|---|---|---|---|
| `approval.pre_approval_obtained` | B | **B-문서** | 사전승인 결재 캡처/PDF |
| `approval.pre_approval_level` | C | **C-문서** | 〃 (결재선 파싱) |
| `evidence.participant_list_missing` | B | **B-문서** | 회의록·참석자 명단 |
| `participants.participant_count` | B | B-입력 **또는** B-문서 | 회의록에서 추출 가능 |
| `evidence.has_supporting_evidence` | B | **B-문서** | 첨부 종류 판별 |
| `trip.trip_type`·`region_grade`·`lodging_amount_per_night` | C | **C-문서** | 출장계획서 |
| `tx.service_charge_ratio` | D | **B-문서** | 영수증 상세(봉사료 항목) |

**`chunk_pdf` 파이프라인이 이미 있다** — 규정 문서용으로 만들었지만 출장계획서·회의록 PDF에
그대로 쓸 수 있다. 새로 만들 게 아니라 **연결**하면 된다.

### 빠진 조각: 첨부의 "종류"

현재 `Receipt`는 `file_ref`·`ocr_text`·`status`만 있고 **종류(kind) 필드가 없다.**
영수증·회의록·사전승인서·출장계획서를 구분할 수 없어 "어느 문서에서 무엇을 뽑을지"를 정할 수 없다.
→ `Receipt.kind`(choices) 추가 또는 `Attachment` 모델 분리가 선행이다.

### 추출값에 적용할 계약 — "관측했는데 없음" vs "안 물어봄"

§0의 `None`=모름 계약을 추출에도 확장한다.

| 상황 | 써야 할 값 | 이유 |
|---|---|---|
| 영수증을 읽었고 봉사료 항목이 **없었다** | `service_charge_ratio = 0.0` | 부재를 **관측**했으므로 사실이다 |
| 영수증 첨부 자체가 없다 | `None` | 관측하지 않았으므로 모른다 |
| 회의록을 읽었고 참석자가 3명이었다 | `participant_count = 3` | — |
| 회의록을 첨부받지 않는다 | `None` | — |

**"관측했고 부재를 확인했으면 명시값(0/False), 관측 자체를 안 했으면 `None`."**
이 구분만 지키면 추출로 채우는 필드가 늘수록 미해소가 자연히 줄어든다.
추출값은 `parse_confidence`를 함께 남겨 저신뢰 건을 사람이 볼 수 있게 한다.

---

## 10. 스키마를 축소해 재설계할 것인가 — **아니오, 그래프를 축소한다**

> "핵심 '단어'로만 축소해서 아예 재설계하는 게 오히려 작업이 더 많아지려나?"

**목표는 옳다. 하지만 스키마 재설계는 비용이 크고 효과가 없다.**

### 왜 효과가 없나 — 스키마는 비용을 만들지 않는다

`empty_eval_context()`가 만드는 101개 `None`은 런타임 비용이 0이다. 실제 비용은 전부
**다른 층**에서 발생한다:

```
스키마(어휘 사전)  ← 커도 무해. 안 쓰는 단어는 비용 0
그래프(실제 문장)  ← 여기서 참조하는 순간 비용 발생 (모델·입력·추출)
```

**필드 100개를 20개로 줄여도, "어떤 룰을 유지할지" 결정은 똑같이 해야 한다.** 그 결정이 곧
"어떤 필드를 소싱할지"이므로, 스키마를 줄이는 작업은 순수한 추가 비용이다.

### 재설계 시 되돌려야 하는 자산

| 자산 | 규모 |
|---|---|
| `법인카드_사용규정_기반_RULE_명세서.md` | **58 RULE — 권위 문서(SoT)** 전면 재작성 |
| 시드 그래프 | 9그래프 (TEST만 노드 17·라우팅 28) 조건 재작성 |
| `rule_hits.eval_context` 스냅샷 | 스키마 v3 — 기존 감사 기록과 3중 분기 |
| 룰 편집 UI 변수 목록 | `simulationTypes.ts` |
| 테스트 | 35개 중 상당수 |

### 값싼 대안 — **MVP 코어 프로파일 선언**

> **후속(2026-08-11)**: 아래 제안 대신 **스키마 자체를 46필드로 줄이는 쪽을 택했다**(§12).
> 남은 필드가 곧 코어 프로파일 역할을 하므로 별도 `MVP_CORE_PATHS` 선언은 두지 않았다.
> 아래는 그 결정에 이른 비교 근거로 남긴다.

스키마는 그대로 두고, **"이번 MVP에서 실제로 소싱하기로 한 경로 집합"** 을 선언한 뒤
ACTIVE 전환 게이트에서 검증한다.

```python
# eval_context.py — 스키마(어휘)와 별개로 "이번에 쓰기로 한 단어" 선언
MVP_CORE_PATHS = frozenset({
    "tx.amount", "tx.payment_time", "tx.per_person_amount",
    "card.card_type", "user.is_working_hours",
    "merchant.merchant_type", "merchant.forbidden",
    "category.value", "evidence.has_valid_receipt", "evidence.expense_purpose_missing",
    "approval.pre_approval_obtained", "participants.participant_count",
    "derived.is_late_night", "derived.is_weekend", "derived.business_days_since_expense",
    "history.daily_cumulative_amount", "history.same_vendor_count",
    *(f"policy.{f}" for f in _SCHEMA_FIELDS["policy"]),
})
```

- 그래프를 ACTIVE로 올릴 때 **코어 밖 경로를 참조하면 경고**(또는 차단).
  → `validate_graph_vars`와 같은 자리에 한 줄 추가.
- 룰 편집 UI 변수 목록도 이 집합으로 필터 → 회계 담당자가 **못 채울 필드를 애초에 못 고른다.**
- 나중에 출장 도메인이 생기면 **프로파일만 넓히면 된다.** 스키마는 손대지 않는다.

### 비용 비교

| 방안 | 작업량 | 얻는 것 |
|---|---|---|
| 스키마 전면 재설계 | 권위 문서 + 그래프 + 스냅샷 + UI + 테스트 | 어휘가 작아짐 (**기능 이득 0**) |
| **코어 프로파일 + 룰 축소** | `frozenset` 1개 + 게이트 1곳 + 룰 조건 정리 | 못 채울 룰이 **활성화 자체가 안 됨** |

**결론: 축소는 하되 스키마가 아니라 그래프에서 한다.** 가드가 이미 "못 채우는 룰"을 실시간으로
알려주므로, 그 목록(§1의 10개)을 보고 룰에서 참조를 빼면 그게 곧 축소다.

---

## 12. 스키마 v3 다이어트 실행 기록 (2026-08-11)

§10에서 "스키마가 아니라 그래프를 축소하자"고 결론냈지만, 실제로 남은 필드를 훑어보니
**스키마 자체에도 애초에 있으면 안 되는 것**이 섞여 있었다. 판정 결과를 입력으로 받는 필드다.

### 삭제 기준 — **EvalContext는 '단어', 그래프는 '문장'**

필드가 남으려면 셋 다 만족해야 한다:
① 관찰(observation)이지 판정(verdict)이 아니다 ② 다른 필드로부터 DSL 연산자로 조합할 수 없다
③ 현실적인 출처가 있다.

| 사유 | 삭제한 것 | 대체 |
|---|---|---|
| **(a) 판정 필드** — 결론을 입력받고 있었다 | `derived.personal_use_suspected`, `derived.category_specific_*`, `evidence.purpose_is_generic` | **그래프에서 조합한다** |
| **(b) 조합 가능** — 중복 | `evidence.participant_list_missing` 등 `*_missing` 계열 7종 | 대상 필드의 값으로 판정 (`participant_count == 0`) |
| **(c) 원천 없고 부차적** | `tx.service_charge_ratio`, `tx.is_holiday`, `merchant.merchant_grade`, `tx.day_of_week`, `user.dept` | — (제거) |
| **(d) 과세분화** | 출장 상세 9종·참석자 상세 5종·승인 상세 5종·세부유형 3종·집계 2종 | 원천(모델) 확보 후 되살린다 |

**대표 사례** — `derived.personal_use_suspected`(GLOBAL R-006):

```jsonc
// before — 「사적사용 의심」이라는 결론을 그대로 입력받았다
{"and": [{"==": [{"var": "derived.is_late_night"}, true]},
         {"==": [{"var": "derived.personal_use_suspected"}, true]}]}

// after — 확인 가능한 사실 3개의 조합으로 바꿨다
{"and": [{"==": [{"var": "derived.is_late_night"}, true]},
         {"or": [{"==": [{"var": "derived.is_weekend"}, true]},
                 {"==": [{"var": "merchant.merchant_info_resolved"}, false]}]}]}
```

조합 규칙이 룰 화면에 그대로 보이므로 **회계 담당자가 근거를 따질 수 있다.** 판정 필드로 두면
"AI가 의심한다더라"가 되어 감사할 수 없다.

### 결과 — 101 → 46 필드

| 섹션 | v2 → v3 | 섹션 | v2 → v3 |
|---|---|---|---|
| tx | 7 → **4** | trip | 12 → **3** |
| card | 2 → 2 | dining | 4 → **2** |
| user | 4 → **3** | history | 5 → **3** |
| merchant | 4 → **3** | policy | 13 → **8** |
| category | 7 → **3** | derived | 7 → **3** |
| evidence | 11 → **3** | tables | 5 → **동적** |
| approval | 6 → **1** | meta | 5 → 5 |
| participants | 9 → **3** | | |

- `tables`는 **고정 목록을 없앴다** — 감사용 원본이라 DSL이 참조하지 않으므로, 조립기가 실제
  사용한 별표만 동적으로 담는다. 별표가 늘어도 스키마 변경이 없다.
- `policy` 8종: 비교 대상이 함께 남아 있는 것만 유지(`business_class_min_hours`·`night_meal_limit`·
  `approver_daily_limit`·`position_required_level`은 짝이 사라져 제거). `history_window_months`는
  DSL 비교 대상이 아니라 조립기 파라미터라 `ctx`에서 뺐다.
- 새 별표 1종 추가: `forbidden_merchant_table` — 금지업종 **목록**을 DSL `in` 리터럴로 박으면
  규정 개정을 못 따라가므로, `merchant.forbidden` 불린으로 선해소한다(policy와 같은 패턴).

### 함께 정리한 룰 그래프 (시드는 예시이므로 자유롭게 조정)

| 그래프 | 변경 |
|---|---|
| GLOBAL v3 `R-006` | 판정 필드 → 사실 3개 조합으로 재작성 |
| 기업업무추진비 v2 | `E-005`(봉사료 10%) **노드 삭제** — 원천 확보 불가 |
| 회식 v2 초안 | `M-004`(분할결제 의심) **노드 삭제** — 패턴 탐지는 이상탐지(Risk) 영역 |
| 출장 v1 | `T-101`·`T-103`·`T-104` **삭제**, 숙박 한도(`T-102`)만 유지 — 출장 도메인 부재 |
| 접대·회식 참석자 노드 | `participant_list_missing` → `participant_count == 0` |
| TEST `T-22` | `purpose_is_generic` 제거 → `purpose_missing`만 |

### 다이어트 후 실측 — 강등률은 그대로, **그러나 성격이 달라졌다**

```
조립 커버리지   34/101 (34%)  →  24/46 (52%)
판정 강등        112/120 (93%) →  112/120 (93%)   ← 변화 없음
막는 필드          10개        →   9개
```

**강등률이 안 줄어든 것이 정상이다.** 삭제한 필드는 대부분 ACTIVE 그래프가 애초에 참조하지 않던
것들이고, 참조하던 2개(`service_charge_ratio`·`personal_use_suspected`)는 노드째 정리했다.

**진짜 성과는 남은 9개의 등급 구성이다:**

| 다이어트 전 (10개) | 다이어트 후 (9개) |
|---|---|
| A 1 · **B 7 · C 1 · D 1** | **A 2 · B 7 · C 0 · D 0** |

C(AI 판정 대기)·D(원천 없음)가 **사라졌다.** 이제 막고 있는 것이 전부
**"컬럼을 추가하면 해결되는 것"** 뿐이다 — 언제 해결될지 모르는 항목이 없다.

| 건수 | 필드 | 등급 |
|---:|---|---|
| 75 | `participants.participant_count` | B |
| 75 | `tx.per_person_amount` | B(위에서 파생) |
| 40 | `dining.is_secondary_venue` | B |
| 37 | `card.card_type` | **A — 즉시** |
| 37 | `card.actual_user_recorded` | B |
| 37 | `category.item_type` | B |
| 37 | `merchant.merchant_info_resolved` | **A — 즉시** |
| 35 | `approval.pre_approval_obtained` | B |
| 35 | `participants.has_kickback_law_target` | B |

---

## 12a. 조립 충돌 해소 규칙 (2026-08-11 구현)

같은 경로에 **서로 다른 값이 도착한다.** 회의록은 4명, 참석자명단은 6명, 사용자는 9명.
예전 구현은 나중 값이 조용히 이겼다 — 조용한 손실이다. 지금은 출처 순위와 기록으로 처리한다.

### 출처 순위

| 순위 | 출처 | 예 |
|---:|---|---|
| 3 | **`RANK_SOR`** — 원장 사실·산술 파생 | 카드 전표 금액, 결제 시각, 영수증 매칭 여부, 1인당 환산 |
| 2 | **`RANK_INPUT`** — 화면 입력(사람이 확정) | `Settlement.headcount`·`pre_approved` 등 |
| 1 | **`RANK_EXTRACT`** — 첨부 문서 추출 | `Attachment.extracted` |

### 규칙

1. **높은 순위가 이긴다.** 값이 다르면 진 쪽을 충돌로 기록한다(판정은 이긴 값으로 진행).
2. **같은 순위에서 값이 다르면 어느 쪽도 쓰지 않는다.** `None`으로 남기고 충돌을 기록한다
   → 미해소 가드가 `REVIEW`로 보낸다.
   *두 문서가 4명/6명이라면 "둘 중 아무거나"가 아니라 "사람이 봐야 한다"가 맞다.*
3. **`None`(모름)은 아무것도 덮지 않는다.** 빈 컬럼이 추출값을 지우지 않는다.
4. **상위 순위가 오면 동순위 충돌이 해소된다.** 사용자가 7명이라고 확정하면 문서 4/6 충돌은 풀린다.

### 기록

`ctx["conflicts"]`(감사용 동적 섹션, DSL 미참조)에 남아 `rule_hits` 스냅샷으로 보존된다.

```jsonc
"conflicts": {
  "participants.participant_count": {
    "kept": 9, "kept_from": "input", "resolution": "input_wins",
    "dropped": [{ "value": 4, "from": "attachment:12(MEETING_MINUTES)" }]
  }
}
```

`resolution`: `sor_wins` · `input_wins` · `dropped_as_unknown`

### 함께 고친 결함 — 파생 순서

`tx.per_person_amount`를 정산 컬럼에서 미리 계산하면, 인원이 **첨부에서만** 온 경우 `None`으로
덮어써 추출값을 지웠다. 지금은 **합쳐진 인원으로 병합 이후에** 파생한다(`derive_after_merge`).

> **미해결로 남긴 것**: `Attachment.field_confidence`를 아직 쓰지 않는다. 동순위 충돌을
> 신뢰도로 가릴지(높은 쪽 채택) 지금처럼 보수적으로 버릴지는 §13 #9 참조.

---

## 12b. 별표 폴백 — 표마다 다르다 (`strict_keys`)

`user.position`이 SoR에 없어 직책별 한도가 와일드카드(`"*"`)로 떨어지는 건 **괜찮다**
(회사 기본 한도가 의미 있다). 하지만 **업종을 모르는데 `merchant.forbidden = False`** 로 떨어지면
금지업종 결제를 조용히 통과시킨다. 같은 폴백이 표에 따라 안전하기도, 위험하기도 하다.

| `PolicyTable.strict_keys` | 축 값을 **모를 때** | 축 값을 **알지만 표에 없을 때** | 쓰는 표 |
|---|---|---|---|
| `False` (기본) | `"*"` 폴백 | `"*"` 폴백 | 한도표 — 기본값이 의미 있다 |
| `True` | **해소 안 함(`None`)** | `"*"` 폴백 | 금지업종표 — 모르면 단정 못 한다 |

"알지만 목록에 없음"은 두 모드 모두 `"*"`로 폴백한다 — **금지 목록에 없는 업종 = 금지 아님**은
관측 결과이므로 단정해도 된다.

---

## 13. 추가로 판단이 필요한 것 (미결)

다이어트 과정에서 **결정을 미룬** 항목들이다. 사람이 정해야 한다.

| # | 쟁점 | 선택지 | 지금 상태 |
|---|---|---|---|
| 1 | **GLOBAL 게이트의 무조건 요구** — 소액 식대 1건에도 공용카드 실사용자·품목유형을 묻는다 | (a) 노드에 적용 조건 부착(`card_type == 공용`일 때만) (b) 그대로 두고 컬럼을 채운다 | (a) 권장, 미적용 |
| 2 | **`participant_count == 0` vs `None`** — "0명"과 "안 물어봄"을 화면이 구분해 보낼 수 있는가 | 입력칸을 비워두면 `None`, 0을 명시 입력하면 0 | 컬럼 신설 시 함께 결정 |
| 3 | **`merchant.forbidden` 미상 처리** — 업종을 모를 때 `"*": False`(금지 아님)로 떨어진다 | 현재는 `merchant_info_resolved`로 별도 포착. 아니면 `None`으로 두고 강등 | 현행 유지 중 |
| 4 | **`user.position` 원천** — `role`(권한)과 직책은 다르다 | 조직 데이터(`tiger_inc/직급체계.md`)로 시드 vs 입력 | 미결. 지금은 별표가 전부 `"*"` 폴백 |
| 5 | **첨부 종류(`Receipt.kind`)** — 영수증·회의록·사전승인서 구분 | `Receipt.kind` 추가 vs `Attachment` 모델 분리 | 미결 (§9) |
| 6 | **삭제한 38종의 복귀 기준** | 원천(모델/추출) 확보 → 필드 추가 → 룰 조건 복원 **순서 고정** | 규약만 정함 |
| ~~7~~ | ~~58 RULE 명세서와의 간극~~ | — | ✅ **해소(2026-08-11)**: 명세서 최상단에 «참고용 예시» 배너 추가 — 제품 기본 제공은 `DEFAULT GATE` 1개, 세부 룰은 문서 업로드 시 생성. 필드 간극도 의도된 것으로 명기 |
| 8 | **`tx.payment_method` 하드코딩** — 조립기가 `"법인카드"` 고정 | `Card.card_type` 기반 산출 |
| 9 | **동순위 충돌에 신뢰도를 쓸지** (§12a) — 지금은 보수적으로 버려 `REVIEW`로 보낸다 | (a) 현행 유지 (b) `field_confidence`가 높은 쪽 채택 + 충돌 기록. (b)는 편하지만 저신뢰 오추출이 자동 통과를 만들 수 있다 |
| 10 | **`evidence.expense_purpose_missing`의 의미** — 현재는 **지출 목적/사유 미기재**(`Settlement.purpose`)다. "영수증 미첨부에 대한 소명 사유 없음"은 **별개 개념**이며 지금 스키마에 없다 | 필요하면 `evidence.missing_receipt_reason_absent`를 신설(원천: 사유 입력칸 또는 소명 문서 추출) |

> 특히 **#7**: `법인카드_사용규정_기반_RULE_명세서.md`는 룰 시드의 SoT인데 삭제한 필드를 그대로
> 쓰고 있다. 코드는 "구현 가능한 것"으로 좁혔고 명세서는 "규정이 요구하는 것"을 담고 있어
> **의도적인 간극**이지만, 문서에 표기하지 않으면 다음 사람이 혼란스럽다.

---

## 14. 결론

- **조립기 코드는 완성돼 있다.** 못 채우는 건 코드 문제가 아니라 **SoR에 원천이 없어서**다.
- 막고 있는 10개 중 **A 1개 · B 6개 · C 1개 · D 1개**(+1개는 B 파생) — **대부분 컬럼 하나짜리**다.
- **모든 필드가 채워질 필요는 없다**(§8 실측). 42/101만 채워져도 최소 그래프는 정상 판정한다.
  진짜 병목은 **조건 없이 4개 사실을 요구하는 GLOBAL 게이트**다 — 필드를 채우는 것보다
  **적용 조건을 붙여 안 물어보는 것**이 싸다.
- 많은 값은 입력칸이 아니라 **첨부 문서에서 추출**해야 한다(§9). `chunk_pdf`·비전 판독 인프라는
  이미 있고, 빠진 건 **첨부의 종류(kind) 구분**이다. 추출엔 "관측했고 부재 확인 → 명시값 /
  관측 안 함 → `None`" 계약을 적용한다.
- **스키마 축소 재설계는 하지 않는다**(§10). 스키마는 어휘 사전이라 커도 무해하고, 실제 비용은
  그래프가 참조하는 순간 발생한다. 축소는 **`MVP_CORE_PATHS` 선언 + ACTIVE 게이트**로 얻는다.
- D 38개는 스키마에 남기되 룰에서 참조를 빼는 게 정직하다 — 안 그러면 영원히 REVIEW로 쌓인다.

---

## 15. 실측 감사 + 조립 보강 (2026-08-22)

시드 DB 정산 **87건 전건**을 `build_rule_context`에 태우고, 룰 노드 49개가 참조하는 경로를
세어 47경로의 상태를 갈랐다. 추측이 아니라 그 수치가 아래 조치의 근거다.

### 15.1 드러난 것 — "원천이 없다"와 "조립 코드가 없다"는 다르다

가장 큰 발견은 **데이터가 있는데 조립기가 안 읽는 필드**였다. `history.*` 3종은 원천이
없는 게 아니라, `transactions/features.py::build_tx_features`가 **이미 같은 종류의 집계를
하고 있는데**(ML 서빙용) 조립기가 그 자리를 비워 둔 것이었다. 룰 3곳이 참조하는데 전건
미해소 → 그 룰들은 항상 REVIEW로 강등되고 있었다.

### 15.2 조립을 채운 것 (모델 변경 0)

| 경로 | 전 | 후 | 원천 |
|---|---:|---:|---|
| `history.daily_cumulative_amount` | 0% | 100% | Settlement 집계 |
| `history.monthly_cumulative_amount` | 0% | 100% | 〃 |
| `history.same_vendor_count` | 0% | 100% | 〃 (윈도우는 `history_window_table`) |
| `derived.business_days_since_expense` | 0% | 100% | `tx.ts` ↔ 오늘 |
| `user.is_working_hours` | 0% | 100% | `tx.ts` |

**이력 집계 주체는 카드가 아니라 사람**(실사용자, 없으면 지출자)이다. 비교 대상인
`policy.position_*_limit`이 직책 축이라 사람이어야 뜻이 맞고, 한 사람이 개인·공용 카드를
섞어 쓰면 카드 기준 합계는 한도와 무관한 숫자가 된다. `build_tx_features`가 카드 기준인
것과 기준이 다른데, 그쪽은 **카드 이상탐지**가 목적이라 그게 맞다.

주인을 모르는 건(공용카드 미등록)은 **집계하지 않고 `None`으로 남긴다** — 0으로 채우면
"하루에 한 푼도 안 썼다"가 되어 한도 판정이 그대로 틀린다.

### 15.3 새로 올린 사실 8종

| 경로 | 왜 |
|---|---|
| `user.team` · `user.bu` | v3에서 뺐던 `dept`와 다르다 — 그때 근거는 "부서명을 비교하는 룰이 없다"였는데, **별표 축**(본부별 한도)으로는 실제로 쓰인다. 이름 비교가 아니라 룩업 키가 용도다 |
| `card.actual_user_is_spender` | 「지출자 ≠ 실사용자」를 물을 수 있다. 미기록이면 `None`(모름) — `False`면 "다른 사람이 썼다"로 읽힌다 |
| `merchant.industry_confidence` | `merchant_info_resolved`만 보면 「확실한 업종」과 「가까스로 찍은 업종」이 같아 보인다 |
| `evidence.has_meeting_minutes` 외 3종 | `has_supporting_evidence` 하나로는 "참석자 명단이 필요한 지출인데 명단이 있는가"를 못 묻는다. **DSL의 `in`은 좌변이 스칼라**라 목록 포함을 표현하지 못하므로 종류별 불린이어야 한다 |

### 15.4 인원이 0으로 채워지던 이유 — 화면에 입력칸이 없었다

서버는 `headcount`를 받을 준비가 돼 있었는데(`views.py` PATCH 매핑) **S-01 모달에 입력칸이
없었다.** 유일하게 보내는 자리가 AI 초안 수정 payload의 `headcount: 0` **하드코딩**이었다 —
안 적은 건을 "인원 0명"이라고 Agent에게 단정해 알려주던 셈이다.

이게 조용히 번졌다: 스키마 계약이 「`0`=명단 없음 / `null`=모름」인데 0을 보내면 확인한
것으로 단정되고, `derive_after_merge`가 `if amount is not None and count:`로 0을 falsy
처리해 **`tx.per_person_amount`가 영영 안 만들어졌다**. 1인당 한도 룰이 전건 미해소였던
직접 원인이다.

→ 입력칸을 만들고(빈 문자열=모름, 0=해당 없음을 화면 문구로 구분) 하드코딩을 지웠다.
1인당 환산액을 입력 즉시 미리 보여준다 — 그 숫자가 판정에 쓰인다는 걸 적는 사람이 알아야 한다.

### 15.5 남은 것

- `trip.*` 3종 — **첨부 추출(`TRIP_PLAN`)은 이미 뽑는다.** 화면 입력칸만 없어 0%다.
  출장계획서를 올리면 채워지므로 "원천 없음"이 아니다
- `user.finance_dept_is_spender` — `Team`에 재무 표시가 없다(시드가 `name="재무회계팀"`
  **문자열 관례**로만 구분). `Team.is_finance` 플래그가 있어야 되살아난다
- `merchant.forbidden` — 59% 채워지는데 **참조 0**이다. 금지업종 별표를 선해소한 불린인데
  게이트가 `merchant_type in [리터럴]`로 직접 비교한다 → 규정 개정 추종이라는 선해소의
  목적이 사라졌다. 게이트를 고치거나 선해소를 빼거나 **둘 중 하나를 정해야 한다**
- `policy.position_monthly_limit` — 이제 비교 대상(`monthly_cumulative_amount`)이 생겼다.
  월 한도 룰을 만들 수 있다
- 결재선(승인자·직책) — `pre_approved` 불린만으로는 "누가 승인했나"·"부서장 이상인가"를
  못 묻는다. 규정이 실제로 요구하는 축이다


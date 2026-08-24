# 테스트 케이스 — DEFAULT GATE (룰엔진, 식대/회의/비품)

> 대상: `apps/core/domain/policies/orchestrator.py` GLOBAL 게이트(`seed_clean.py: default_gate_spec()`).
> 식대(MEAL)·회의(MEETING)·비품(SUPPLIES) 3개 카테고리는 전용 scope 룰그래프가 없어 **GLOBAL DEFAULT GATE 단독**으로만 판정된다(PASS 또는 REVIEW 둘 중 하나 — 게이트는 RETURN/REJECT를 내지 않음. 최종 RETURN/REJECT는 회계 담당자의 사람 결정).
>
> 근거: `PolicyTable`(`tiger_tables.py`) 임계값, `IndustryCode`(15종), `default_gate_spec()` 노드 순서, `decision_reasons.py`. 값 중 일부(청탁금지·숙박·회식·기한)는 문서 주석상 "규정 원문 미검증"으로 표시되어 있어 재확인 필요.
>
> 실행 방법: `POST /api/settlements/` (사전 로그인) → `/api/settlements/{id}/judge/` 또는 제출 경로에서 자동 판정 → 응답 상태(`PENDING_CONFIRM`=PASS 계열, `IN_REVIEW`=REVIEW 계열)와 `ruleHits`/`judgementFlags` 비교.
>
> **✅ 실측 검증 완료(2026-08-24, main 풀 이후)**: 2026-08-22 최초 설계 시점엔 `n_actual_user`가
> `card.actual_user_recorded`를 값 비교로만 처리해 두 가지 결함이 있었다 — ① `False`(명시적
> 미등록)인데 `PASS`가 나는 문제(MEAL-15류 영향) ② `None`(모름)인데 `UNRESOLVED_FACT` +
> confidence 0으로 떨어지는 문제. **`domain/policies/tests/test_seed_clean.py::DefaultGateJudgementTests`
> 16/16 전체 통과로 두 결함 모두 수정 확인**(`n_actual_user_unknown`(`is_null`) 선분기 +
> 화이트리스트에 `actual_user_recorded == True` 명시). 아래 표의 MEAL-05·MEAL-15 기대판정은
> 그대로 유효하다. 상세: `llm_wiki/_context/default-gate.md` §4.1.

## 게이트 요약 (판정 로직)

| 순서 | 노드 | 조건 | 플래그 | 심각도 |
|---|---|---|---|---|
| 1 | `n_industry_known` | 업종 확인 여부 분기 | — | — |
| 2 | `n_forbidden` | 업종 ∈ {주점/유흥, 노래연습장, 사행성업종} | `PROHIBITED_MERCHANT` | CRITICAL |
| 3 | `n_industry_unresolved` | 업종 미확정 | `MERCHANT_UNRESOLVED` | LOW |
| 4 | `n_evidence` | `evidence.has_valid_receipt==False` | `EVIDENCE_MISSING` | HIGH |
| 5 | `n_purpose` | `expense_purpose_missing==True` | `PURPOSE_UNCLEAR` | MEDIUM |
| 6 | `n_category` | `category.value==None` | `CATEGORY_MISSING` | MEDIUM |
| 7 | `n_actual_user` | `card.actual_user_recorded==False` | `ACTUAL_USER_REQUIRED` | MEDIUM |
| 8 | `n_high_amount` | `tx.amount >= 300,000` | `HIGH_AMOUNT` | LOW |
| 9 | `n_auto_pass` | 증빙O ∧ 목적O ∧ 분류O ∧ 업종확인 ∧ 비위험업종 ∧ 금액<30만 | → `PASS` | — |
| — | 그 외 전부 | — | → `REVIEW` | — |

## A. 식대 (MEAL) — 30건

### A-1. 정상 — PASS 예상 (10건)

| ID | 시나리오 | 금액 | 업종 | 증빙/목적/분류 | 예상판정 |
|---|---|---|---|---|---|
| MEAL-01 | 평일 점심, 일반음식점, 팀 회의 겸 식사 | 4.5만 | 일반음식점 | O/O/O | PASS |
| MEAL-02 | 카페 업무 미팅 중 간단 식음료 | 1.2만 | 카페 | O/O/O | PASS |
| MEAL-03 | 평일 저녁 야근 식대(20시) | 2.8만 | 일반음식점 | O/O/O | PASS |
| MEAL-04 | 개인카드 후정산, 해외 출장 중 식사 대체 | 6만 | 일반음식점 | O/O/O | PASS |
| MEAL-05 | 팀 배정 법인카드, 실사용자 등록 완료 | 3.5만 | 일반음식점 | O/O/O(+actual_user=True) | PASS |
| MEAL-06 | 마트에서 회의용 다과 구입, "식대"로 분류 | 1.8만 | 마트/편의점 | O/O/O | PASS |
| MEAL-07 | 거래처 미팅 겸 점심(내부 인원만, 4인) | 9만 | 일반음식점 | O/O/O | PASS |
| MEAL-08 | 주말 근무 중 식사(사전 승인 有) | 3만 | 일반음식점 | O/O/O | PASS |
| MEAL-09 | 29.9만원 대량 식사, 조건 전부 충족 | 29.9만 | 일반음식점 | O/O/O | PASS |
| MEAL-10 | 편의점 간식 소액 반복 | 0.8만 | 마트/편의점 | O/O/O | PASS |

### A-2. 애매 — 경계값/미해소, REVIEW 예상 (10건)

| ID | 시나리오 | 금액 | 업종 | 결측/경계 | 예상판정 |
|---|---|---|---|---|---|
| MEAL-11 | 가맹점명 신규 브랜드, 업종 캐시/카카오 모두 미분류 | 3만 | 미확정 | 나머지 정상 | REVIEW(`MERCHANT_UNRESOLVED`) |
| MEAL-12 | 정확히 30만원(경계값) | 30.0만 | 일반음식점 | 나머지 정상 | REVIEW(`HIGH_AMOUNT`, `>=` 경계) |
| MEAL-13 | 29.99만 vs 30.0만 반올림 회귀 | 299,999 / 300,000 | 일반음식점 | 정상 | 경계 짝 비교용 |
| MEAL-14 | 목적란 "식사"만 기재(필드는 채워짐) | 2.5만 | 일반음식점 | purpose_missing=False | PASS(게이트 통과, 사람 판단은 별개) |
| MEAL-15 | 공용카드, 실사용자 미등록(미확인) | 3.2만 | 일반음식점 | actual_user_recorded=None | REVIEW(`ACTUAL_USER_REQUIRED`) |
| MEAL-16 | 분류 비움, AI 제안만 존재 | 2.8만 | 일반음식점 | category=None | REVIEW(`CATEGORY_MISSING`) |
| MEAL-17 | 심야 01시 결제, 나머지 정상 | 3.5만 | 일반음식점 | 정상 | PASS(게이트엔 심야조건 없음 — Risk Review 이상탐지 별도 검증 대상) |
| MEAL-18 | 동일 가맹점·금액 당일 2회 결제(분할/중복 의심) | 2.9만×2 | 일반음식점 | 각각 정상 | PASS 2건(게이트 통과, 회계 중복의심 별도 판단) |
| MEAL-19 | 회식성 지출을 "식대"로 등록해 1인당 한도 룰 우회 | 1인당 7만 | 일반음식점 | 정상 필드 | PASS(게이트만으론 미탐지 — scope 오분류 갭) |
| MEAL-20 | 영수증 판독 신뢰도 미달(FAILED) | 3.1만 | 일반음식점 | has_valid_receipt 판정 불가 | REVIEW(`EVIDENCE_MISSING`, 신뢰도 게이트 미해소) |

### A-3. 이상 — REVIEW 후 RETURN/REJECT 소지 (10건)

| ID | 시나리오 | 금액 | 업종 | 결함 | 예상판정 |
|---|---|---|---|---|---|
| MEAL-21 | 유흥주점 결제를 "식대"로 등록 | 8만 | 주점/유흥 | 금지업종 | REVIEW(`PROHIBITED_MERCHANT`, CRITICAL) |
| MEAL-22 | 노래연습장 결제 | 5만 | 노래연습장 | 금지업종 | REVIEW(`PROHIBITED_MERCHANT`) |
| MEAL-23 | 사행성업종 결제 | 4만 | 사행성업종 | 금지업종 | REVIEW(`PROHIBITED_MERCHANT`) |
| MEAL-24 | 5만원, 영수증 없음 | 5만 | 일반음식점 | 증빙 없음(3만 초과) | REVIEW(`EVIDENCE_MISSING`) |
| MEAL-25 | 지출목적 완전 공란 | 4만 | 일반음식점 | purpose_missing=True | REVIEW(`PURPOSE_UNCLEAR`) |
| MEAL-26 | 45만원 고액(증빙·목적 有) | 45만 | 일반음식점 | 고액 | REVIEW(`HIGH_AMOUNT`) |
| MEAL-27 | 심야+이·미용업종 복합 | 12만 | 이·미용 | 정책표는 forbidden=True이나 게이트 목록엔 없음 | PASS 예상(게이트 3종 미포함) — **정책표/게이트 불일치 검증 케이스** |
| MEAL-28 | 2인 이하 소규모, 1인당 15만 고액 | 30만(2인) | 일반음식점 | 참석자 적음+고액 | REVIEW(`HIGH_AMOUNT`) |
| MEAL-29 | 퇴사예정자 명의 카드 결제 | 5만 | 일반음식점 | owner 비활성 예정 | PASS 예상(게이트는 퇴사 여부 미검사) — 카드 관리 화면(회수 대상)과의 정합 확인용 |
| MEAL-30 | 동일 결제 중복 등록 시도(멱등성) | 3만 | 일반음식점 | external_id 충돌 | 2번째 요청 거부/무시(가드 확인) |

## B. 회의(MEETING) — 10건

| ID | 시나리오 | 금액 | 상태 | 근거 |
|---|---|---|---|---|
| MTG-01 | 회의실 대여+다과, 증빙·목적 완비 | 15만 | PASS | 화이트리스트 충족 |
| MTG-02 | 외부 회의장 대관료, 사전승인 완료(팀장) | 45만 | REVIEW | `HIGH_AMOUNT` |
| MTG-03 | 회의용 음료, 3만원 이하 | 2만 | PASS | 증빙기준 미만 |
| MTG-04 | 회의 다과 3.5만, 영수증 누락 | 3.5만 | REVIEW | `EVIDENCE_MISSING` |
| MTG-05 | 비직책자 35만 지출(사전승인기준 30만 초과) | 35만 | REVIEW | `HIGH_AMOUNT`(사전승인 소명은 R-013, 게이트 미검사) |
| MTG-06 | 팀장 45만 지출(사전승인기준 50만 이내) | 45만 | REVIEW | `HIGH_AMOUNT`(금액 자체는 30만 넘어 게이트 REVIEW) |
| MTG-07 | 회의 명목, 실제 업종 카페, 목적란 공란 | 6만 | REVIEW | `PURPOSE_UNCLEAR` |
| MTG-08 | 화상회의 구독료, 업종 미확정 | 5만 | REVIEW | `MERCHANT_UNRESOLVED` |
| MTG-09 | 회의비 명목, 실제 결제 업종 주점(위장 의심) | 20만 | REVIEW | `PROHIBITED_MERCHANT` |
| MTG-10 | 공용카드, 실사용자 미등록 | 4만 | REVIEW | `ACTUAL_USER_REQUIRED` |

## C. 비품(SUPPLIES) — 10건

| ID | 시나리오 | 금액 | 업종 | 상태 | 근거 |
|---|---|---|---|---|---|
| SUP-01 | 문구 구입, 영수증 완비 | 3만 | 문구/사무용품 | PASS | 정상 |
| SUP-02 | 모니터 구입, 사전승인 완료 | 25만 | 전자/가전 | PASS | 30만 미만 |
| SUP-03 | 노트북 구입 | 120만 | 전자/가전 | REVIEW | `HIGH_AMOUNT` |
| SUP-04 | 사무용품 3.2만, 증빙 없음 | 3.2만 | 문구/사무용품 | REVIEW | `EVIDENCE_MISSING` |
| SUP-05 | 35만 비품 구매, 사전승인 없음 | 35만 | 전자/가전 | REVIEW | `HIGH_AMOUNT` |
| SUP-06 | 55만 비품 구매(부서장 사전승인기준 60만 이내) | 55만 | 전자/가전 | REVIEW | `HIGH_AMOUNT`(게이트는 30만 기준이라 REVIEW) |
| SUP-07 | 면세점에서 "비품" 명목 결제(개인물품 의심) | 15만 | 면세점 | PASS 예상(게이트는 면세점 위험업종 미포함) | 업종-용도 불일치는 게이트 밖 — 회계 육안 |
| SUP-08 | 목적란 공란 | 4만 | 문구/사무용품 | REVIEW | `PURPOSE_UNCLEAR` |
| SUP-09 | 분류 미기재 | 6만 | 전자/가전 | REVIEW | `CATEGORY_MISSING` |
| SUP-10 | 골프용품을 "비품"으로 등록 | 30만 | 골프장/레저 | REVIEW | `HIGH_AMOUNT`(업종 자체는 금지 3종 아님이라 `PROHIBITED_MERCHANT` 미발동 — 갭 확인용) |

## 확인된 설계 갭 (테스트로 검증할 것)

1. **정책표 vs 게이트 금지업종 불일치**: `forbidden_merchant_table`(정책표)은 이·미용을 포함하나 게이트 `LEGAL_RISK_MERCHANT_TYPES`는 3종(주점/유흥·노래연습장·사행성업종)만 — MEAL-27로 확인.
2. **scope 오분류 우회**: 회식성 지출을 식대로 등록하면 GATHERING scope 룰(1인당 5만/8만)을 완전히 우회 — MEAL-19.
3. **업종-용도 불일치 미검사**: 면세점·골프용품 등 "비품" 명목의 업종 불일치는 게이트가 못 잡음 — SUP-07/SUP-10.
4. **퇴사예정자 카드**: 게이트는 카드 소유자 재직 상태를 보지 않음 — MEAL-29(카드관리 화면 "회수 대상" 파생 로직과의 정합은 별개 검증).

# QA 테스트 케이스 — Risk Review Agent (50건)

> 대상: `apps/ai/app/agents/risk_review_agent.py::run()` (`/lab/risk/run` 경유, 부작용 없음 — FastAPI는
> Postgres에 쓰지 않는다, `apps/ai/app/api/lab.py::risk_run` 독스트링 및 코드 확인).
> 실행 결과·지표는 `llm_wiki/_context/qa/risk-review-agent-test-report.md` 참조.
>
> **2026-08-24 v2 재검증**: main 대량 풀로 Risk Review Agent v2(`risk-review-agent-v2.md`)가
> 들어온 뒤 동일 Settlement 476~525에 대해 재실행했다(신규 데이터 생성 없음). **golden label 3건
> 정정**(qa39·41·47 — 아래 표 반영): "정보 부족→면제"가 아니라 "필수 기재사항 미기재/한도초과
> 자체가 위반"이 맞는 해석이었음을 재검증 과정에서 확인(근거는 리포트 §2-1). 나머지 golden은
> 그대로 유효.

## 데이터 생성 방법

`docker compose exec core python manage.py shell`로 ORM 스크립트를 실행해 `Settlement`+`Transaction`
50건을 신규 생성했다(기존 시드 데이터는 건드리지 않음). 전부 카드 41(`kim`의 개인 배정 카드, 영업팀),
`submitted_by=kim`, `team_id=13`에 귀속시켰고, `purpose` 필드 맨 앞에 `QA_RISK_TEST_<case_id>:` 태그를
붙여 식별·정리가 쉽게 했다. 상태는 `IN_REVIEW`로 두었다(값 자체는 `/lab/risk/run` 실행에 영향 없음 —
읽기 전용 조회이므로).

**생성된 신규 DB 행(정리 대상)**: `Settlement.id` 476~525 (50건), 대응 `Transaction.id` 728~777 (50건).
연결 스크립트: `/private/tmp/claude-501/.../scratchpad/create_qa_cases.py`(세션 스크래치패드,
레포 밖). 삭제는 하지 않았다(작업 지침에 따름) — 정리 필요 시 `Settlement.objects.filter(purpose__startswith="QA_RISK_TEST_").delete()`
(Transaction은 `on_delete=PROTECT`라 Settlement 삭제 후 별도 처리 필요).

## 설계 근거

- **판정 사실 스키마 한계 확인**: `Settlement` 모델의 판정 입력 필드는 `headcount`·`external_headcount`·
  `pre_approved`·`item_type`·`kickback_target`·`is_secondary_venue`·`includes_alcohol` 7종뿐이다. `RULE_명세서.md`
  R-2xx가 요구하는 `scope`(전사/본부 단위) · `family_or_personal_gathering_suspected` · `participant_includes_former_employee` ·
  `during_business_trip` · `payment_time`(야간/주말 판정) 등은 **구조화 필드로 존재하지 않는다** — EvalContext
  다이어트(101→46 필드)로 "과세분화" 항목이 정리되며 함께 빠졌다. 이 사실 자체가 테스트 대상이다: 해당
  규정을 구조화 필드 없이 `purpose`(자유서술) 텍스트만으로 LLM이 잡아내는지 확인한다.
- **`GET /api/internal/settlement-summary/<id>/` 응답에 거래 시각(`ts`)이 없다** — R-202(야간)·R-203(주말)은
  2차 LLM에 시각 정보 자체가 전달되지 않는다(자연어 질의도 `build_query`가 시각을 안 씀). 구조적으로 탐지가
  불가능할 것으로 예상 → qa14·qa15에서 실측 확인.
- **가맹점 업종 코드(`merchant_industry_code`)도 summary에 없다** — 2차 LLM은 가맹점 **이름 문자열**만 본다.
  그래서 R-208(금지업종) 테스트는 가맹점명 자체에 업종을 드러내는 이름(예: "블랙펄 노래연습장")을 썼다.

## 케이스 목록

범례: **risk_tier**는 anomaly 모델이 실제 학습 데이터 분포에 따라 산출하므로 구조화 사실만으로 정확한
등급을 강제할 수 없다(1차는 카드 사용 이력 기반 비지도 이상탐지) — "예상 방향"만 golden으로 표기하고,
실측값과의 정합은 리포트에서 정성 평가한다. **violation_verdict**는 R-2xx/GLOBAL 게이트에 명시된 규정
위반 패턴을 근거로 확정 golden label을 부여했다.

| # | case_id | settlement_id | 카테고리 | 금액 | 시나리오 요지 | golden risk_tier(예상) | golden violation_verdict | 근거 조항(예상 인용) |
|---|---|---|---|---|---|---|---|---|
| 1 | qa01 | 476 | 회식 | 180,000 | 5인, 주류 포함(36,000/인), 사전승인 완료 | LOW | NO_VIOLATION | — |
| 2 | qa02 | 477 | 회식 | 90,000 | 4인, 무알코올, 정상 회식 | LOW | NO_VIOLATION | — |
| 3 | qa03 | 478 | 식대 | 45,000 | 3인 야근 식대 | LOW | NO_VIOLATION | — |
| 4 | qa04 | 479 | 회의 | 60,000 | 6인 회의 다과 | LOW | NO_VIOLATION | — |
| 5 | qa05 | 480 | 회식 | 250,000 | 8인, 사전승인 완료, 신규입사자 환영회 | LOW | NO_VIOLATION | — |
| 6 | qa06 | 481 | 접대 | 280,000 | 외부인 2명, 사전승인 완료 거래처 미팅 | LOW | NO_VIOLATION | — |
| 7 | qa07 | 482 | 회식 | 150,000 | 5인 정기 회식(30만원 이하, 승인 불요) | LOW | NO_VIOLATION | — |
| 8 | qa08 | 483 | 비품 | 35,000 | 사무용품 구매 | LOW | NO_VIOLATION | — |
| 9 | qa09 | 484 | 회식 | 120,000 | 4인, 주류 포함(30,000/인) | LOW | NO_VIOLATION | — |
| 10 | qa10 | 485 | 식대 | 15,000 | 1인 개인 야근 식대(식대라 최소인원 룰 미적용) | LOW | NO_VIOLATION | — |
| 11 | qa11 | 486 | 회식 | 200,000 | 6인, 사전승인 완료 팀빌딩 | LOW | NO_VIOLATION | — |
| 12 | qa12 | 487 | 회의 | 50,000 | 4인 주간회의 다과 | LOW | NO_VIOLATION | — |
| 13 | qa13 | 488 | 회식 | 450,000 | 30만원 초과, `pre_approved=False` | MEDIUM+ | VIOLATION | R-201(회식 규정 제7조·제8조①) |
| 14 | qa14 | 489 | 회식 | 200,000 | 23:30 결제(야간) — **ts가 요약 API에 없어 LLM이 못 봄** | LOW/MEDIUM | INSUFFICIENT_INFO(예상, 시각 미전달) | R-202(제8조②) — 탐지 실패 예상 |
| 15 | qa15 | 490 | 회식 | 150,000 | 토요일 결제(주말) — purpose에 "토요일" 명시 | LOW | VIOLATION(purpose 텍스트로만 가능) 또는 INSUFFICIENT_INFO | R-203(제8조③) |
| 16 | qa16 | 491 | 회식 | 220,000 | 외부인 2명 참석(`external_headcount=2`) | LOW/MEDIUM | VIOLATION | R-204(제2조·제6조②, 업무추진비 재분류) |
| 17 | qa17 | 492 | 회식 | 500,000 | 호텔 레스토랑(가맹점명으로 신호) | MEDIUM | VIOLATION | R-205(제8조⑤) |
| 18 | qa18 | 493 | 회식 | 200,000 | 2인, 주류 포함, 1인당 100,000원(>80,000) | MEDIUM | VIOLATION | R-206(제8조⑥) |
| 19 | qa19 | 494 | 회식 | 80,000 | `headcount=1` | LOW/MEDIUM | VIOLATION | R-207(제6조①) |
| 20 | qa20 | 495 | 회식 | 100,000 | `headcount=2` | LOW/MEDIUM | VIOLATION | R-207(제6조①) |
| 21 | qa21 | 496 | 회식 | 300,000 | 노래연습장, `is_secondary_venue=True` | HIGH | VIOLATION | R-208(제5조·제9조, CRITICAL) |
| 22 | qa22 | 497 | 회식 | 400,000 | 유흥주점, `is_secondary_venue=True` | HIGH | VIOLATION | R-208 / GLOBAL 금지업종(공통 R-002) |
| 23 | qa23 | 498 | 회식 | 200,000 | `item_type=상품권` | MEDIUM | VIOLATION | R-209(제5조) |
| 24 | qa24 | 499 | 회식 | 150,000 | `item_type=선물`(개인 선물 명목) | MEDIUM | VIOLATION | R-209(제5조) |
| 25 | qa25 | 500 | 회식 | 180,000 | purpose "가족과 함께한 저녁식사" — 구조화 필드 없음 | LOW | VIOLATION(텍스트로만 가능) 또는 INSUFFICIENT_INFO | R-210(제6조③) |
| 26 | qa26 | 501 | 회식 | 200,000 | purpose "퇴사한 전 팀원 송별회", `pre_approved=False` — 구조화 필드 없음 | LOW/MEDIUM | VIOLATION(텍스트로만 가능) 또는 INSUFFICIENT_INFO | R-211(제6조④) |
| 27 | qa27 | 502 | 회식 | 9,000,000 | 40인 전사 단합대회, `pre_approved=False`, purpose에 "전사" 명시 — `scope` 필드 없음 | HIGH | VIOLATION(텍스트로만 가능) 또는 INSUFFICIENT_INFO | R-213(제4조·제8조⑧) |
| 28 | qa28 | 503 | 회식 | 150,000 | `headcount=None`, purpose 공란 | LOW/MEDIUM | VIOLATION 또는 INSUFFICIENT_INFO | R-214(제10조, 기록 누락) |
| 29 | qa29 | 504 | 회식 | 120,000 | `headcount=5`(있음)이나 purpose 공란(목적 누락만) | LOW | VIOLATION 또는 INSUFFICIENT_INFO | R-214(제10조) |
| 30 | qa30 | 505 | 회식 | 60,000 | purpose "2차로 카페 추가 결제(분할결제)" — `same_event_multiple_merchants` 필드 없음 | LOW | VIOLATION(텍스트로만 가능) 또는 INSUFFICIENT_INFO | R-215(제5조 단서) |
| 31 | qa31 | 506 | 회식 | 12,000,000 | 30인 본부 대규모 회식, 개인카드 결제 — `scope`/`approver_daily_limit` 필드 없음 | HIGH | VIOLATION(텍스트로만 가능) 또는 INSUFFICIENT_INFO | R-216(제4조) |
| 32 | qa32 | 507 | 접대 | 500,000 | 카지노(가맹점명) — 사행성업종 | HIGH | VIOLATION | GLOBAL 금지업종 게이트(공통 R-002) |
| 33 | qa33 | 508 | 회식 | 150,000 | 인원·승인·주류 전부 `None`, purpose만 "팀 회식" | LOW/MEDIUM | INSUFFICIENT_INFO | — |
| 34 | qa34 | 509 | 회식 | 350,000 | 30만원 초과인데 승인여부·인원 전부 `None` | MEDIUM | INSUFFICIENT_INFO | R-201 근거는 있으나 사실 미확정 |
| 35 | qa35 | 510 | 회식 | 90,000 | 전 필드 `None`, 가맹점명도 무의미("이름없는분식") | LOW | INSUFFICIENT_INFO 또는 NO_VIOLATION | — |
| 36 | qa36 | 511 | 접대 | 280,000 | 외부인·승인 여부 `None` | LOW/MEDIUM | INSUFFICIENT_INFO | — |
| 37 | qa37 | 512 | 회식 | 500,000 | 전 필드 `None` + purpose 공란 + 고액 | MEDIUM/HIGH | INSUFFICIENT_INFO | — |
| 38 | qa38 | 513 | 출장 | 200,000 | 출장 중 식사(출장 세부 필드 자체가 스키마에 없음) | LOW | INSUFFICIENT_INFO | — |
| 39 | qa39 | 514 | 회식 | 180,000 | "세부사항 미기재" 명시, 전 필드 `None` | LOW | ~~INSUFFICIENT_INFO~~ → **VIOLATION(정정, 2026-08-24)**: 참석자 명단 등 필수 기재사항 자체가 없는 것은 R-214(제10조 필수증빙) 기록누락 위반이지 정보부족이 아님 | 회식_운영규정 제10조 |
| 40 | qa40 | 515 | 회식 | 220,000 | `headcount=4`(있음)이나 승인·2차·주류 `None` | LOW/MEDIUM | INSUFFICIENT_INFO | — |
| 41 | qa41 | 516 | 접대 | 600,000 | `kickback_target=None`(청탁금지 대상 여부 모름), 고액, `pre_approved=None` | MEDIUM | ~~INSUFFICIENT_INFO~~ → **VIOLATION(정정, 2026-08-24)**: 60만원은 사전승인 대상 금액인데 승인여부 확인 불가 자체가 결함(모름=면제 아님) | 회식_운영규정 제7조·업무추진비_사용규정 별표2 |
| 42 | qa42 | 517 | 회식 | 130,000 | `headcount=3`(있음)이나 주류·2차 `None` | LOW | NO_VIOLATION 또는 INSUFFICIENT_INFO | — |
| 43 | qa43 | 518 | 식대 | 3,000,000 | 이례적 고액 단건 | HIGH(이상탐지 방향) | NO_VIOLATION(규정 위반은 아님) | — |
| 44 | qa44 | 519 | 식대 | 3,000 | 매우 소액 | LOW | NO_VIOLATION | — |
| 45 | qa45 | 520 | 회식 | 999,999 | 6인, 사전승인 완료, 경계값 근접(100만원 미만) | MEDIUM(금액만으로) | NO_VIOLATION(승인 있음) | — |
| 46 | qa46 | 521 | 식대 | 50,000 | 새벽 3시 결제(식대라 회식 야간룰 미적용) | MEDIUM(이상탐지 방향) | NO_VIOLATION | — |
| 47 | qa47 | 522 | 회식 | 700,000 | 카드 첫 거래 가맹점명, 고액, `headcount=6`·`includes_alcohol=True`·`pre_approved=None` | HIGH(이상탐지 방향) | ~~NO_VIOLATION~~ → **VIOLATION(정정, 2026-08-24)**: 1인당 116,667원(=700,000/6)은 회식 1인당 권장한도(5만원)를 명백히 초과 — 최초 설계 시 1인당 금액을 계산하지 않은 실수 | 회식_운영규정 제7조(1인당 한도) |
| 48 | qa48 | 523 | 회식 | 400,000 | "당일 반복 결제" 텍스트, 사전승인 완료 | MEDIUM/HIGH(이상탐지 방향) | NO_VIOLATION(승인 있음) | — |
| 49 | qa49 | 524 | 회식 | 300,000 | R-201 경계값 — **정확히 30만원(초과 아님)**, `pre_approved=False` | LOW/MEDIUM | NO_VIOLATION(경계 미달) | — |
| 50 | qa50 | 525 | 회식 | 300,001 | R-201 경계값 — **30만원 초과 1원**, `pre_approved=False` | MEDIUM | VIOLATION | R-201(제7조·제8조①) |

## 그룹 요약

- **(a) 명백히 정상 (qa01~qa12, 12건)**: LOW / NO_VIOLATION 기대.
- **(b) 명백한 위반 (qa13~qa32, 20건)**: R-201·204·205·206·207·208(×2)·209(×2)·210·211·213·214(×2)·215·216
  + GLOBAL 금지업종(카지노) 커버. 이 중 **qa14·15·25·26·27·30·31 (7건)은 구조화 필드가 아예 없어 `purpose`
  자유서술 텍스트로만 위반 신호를 줬다** — RAG stage2가 텍스트만으로 규정을 연결할 수 있는지가 핵심 관찰점.
- **(c) 애매/정보부족 (qa33~qa42, 10건)**: 핵심 판정 필드를 의도적으로 `None`으로 남겨 `INSUFFICIENT_INFO`
  수렴 여부 확인.
- **(d) 이상탐지 임계값/이상치 (qa43~qa50, 8건)**: 고액·소액·새벽시각·첫거래가맹점·R-201 금액 경계값(정확히
  300,000 vs 300,001) 양쪽을 포함해 anomaly_score 분포 반응과 룰 경계 정확도를 함께 관찰.

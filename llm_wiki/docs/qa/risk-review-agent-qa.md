# Risk Review Agent QA — 테스트 케이스 + 실행 결과 (v1 2026-08-22 → v2 재검증 2026-08-24)

> 원본 DB 레코드(Settlement 476~525·Transaction 728~777)는 이미 삭제됨.
> `fixtures/qa_risk_review_settlements.json`+`qa_risk_review_transactions.json`로 `loaddata`
> 복원 가능(전제 조건은 `fixtures/README.md`).

## 1. 테스트 케이스 정의 (50건)

> 대상: `apps/ai/app/agents/risk_review_agent.py::run()` (`/lab/risk/run` 경유, 부작용 없음 — FastAPI는
> Postgres에 쓰지 않는다).
>
> **2026-08-24 v2 재검증**: main 대량 풀로 Risk Review Agent v2(`risk-review-agent-v2.md`)가
> 들어온 뒤 동일 Settlement 476~525에 대해 재실행했다(신규 데이터 생성 없음). **golden label 3건
> 정정**(qa39·41·47 — 아래 표 반영): "정보 부족→면제"가 아니라 "필수 기재사항 미기재/한도초과
> 자체가 위반"이 맞는 해석이었음을 재검증 과정에서 확인(근거는 §2.2). 나머지 golden은 그대로 유효.

### 데이터 생성 방법 (당시)

`docker compose exec core python manage.py shell`로 ORM 스크립트를 실행해 `Settlement`+`Transaction`
50건을 신규 생성했다(기존 시드 데이터는 건드리지 않음). 전부 카드 41(`kim`의 개인 배정 카드, 영업팀),
`submitted_by=kim`, `team_id=13`에 귀속시켰고, `purpose` 필드 맨 앞에 `QA_RISK_TEST_<case_id>:` 태그를
붙여 식별했다. 상태는 `IN_REVIEW`로 두었다(값 자체는 `/lab/risk/run` 실행에 영향 없음 — 읽기 전용 조회).

### 설계 근거

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

### 케이스 목록

범례: **risk_tier**는 anomaly 모델이 실제 학습 데이터 분포에 따라 산출하므로 구조화 사실만으로 정확한
등급을 강제할 수 없다(1차는 카드 사용 이력 기반 비지도 이상탐지) — "예상 방향"만 golden으로 표기하고,
실측값과의 정합은 §2에서 정성 평가한다. **violation_verdict**는 R-2xx/GLOBAL 게이트에 명시된 규정
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

### 그룹 요약

- **(a) 명백히 정상 (qa01~qa12, 12건)**: LOW / NO_VIOLATION 기대.
- **(b) 명백한 위반 (qa13~qa32, 20건)**: R-201·204·205·206·207·208(×2)·209(×2)·210·211·213·214(×2)·215·216
  + GLOBAL 금지업종(카지노) 커버. 이 중 **qa14·15·25·26·27·30·31 (7건)은 구조화 필드가 아예 없어 `purpose`
  자유서술 텍스트로만 위반 신호를 줬다** — RAG stage2가 텍스트만으로 규정을 연결할 수 있는지가 핵심 관찰점.
- **(c) 애매/정보부족 (qa33~qa42, 10건)**: 핵심 판정 필드를 의도적으로 `None`으로 남겨 `INSUFFICIENT_INFO`
  수렴 여부 확인.
- **(d) 이상탐지 임계값/이상치 (qa43~qa50, 8건)**: 고액·소액·새벽시각·첫거래가맹점·R-201 금액 경계값(정확히
  300,000 vs 300,001) 양쪽을 포함해 anomaly_score 분포 반응과 룰 경계 정확도를 함께 관찰.

---

## 2. 실행 결과 보고서 — Risk Review Agent v2 (2026-08-24 재검증)

동일한 50건·동일한 `POST /lab/risk/run` 엔드포인트로 v1(2026-08-22)·v2(2026-08-24) 두 차례 실행했다.
사전 절차: `docker compose exec core python manage.py migrate` 후 실행.

### 2.0 v1 → v2 핵심 변화 (실측에 영향)

- **등급 분기 신설**: LOW는 LLM 호출 없이 결정론적 APPROVE, MEDIUM은 `fast`(gpt-4o-mini), HIGH·미측정은
  `heavy`(gpt-5-mini). 이번 50건은 v1과 같은 카드 1개·순차 날짜 데이터라 여전히 47/50이 HIGH로 쏠려
  `heavy` 경로를 탔다(2/50 LOW, 1/50 MEDIUM) — **risk_tier 분포 자체는 이번에도 참고용**(카드 공유
  아티팩트, 신규 실행이 아니라 재사용 데이터라 동일 재현).
- **`violation_verdict`(VIOLATION/NO_VIOLATION/INSUFFICIENT_INFO)는 유지**되고 그 위에 `recommendation`
  (APPROVE/SUPPLEMENT/REJECT)이 신설됨 — 판정과 권고가 분리.
- **서버 측 대조 가드 신설**(`_validate_report`): 인용이 실제 검색결과에 없으면 버림, `INSUFFICIENT_INFO`인데
  `APPROVE`면 `SUPPLEMENT`로 자동 정정 등.
- 지연시간: heavy 경로 평균 **26.9초**/건(v1 대비 약 2.7배 — gpt-5-mini reasoning 비용). LOW 경로는
  50~수백ms(LLM 미호출).

### 2.1 핵심 결과 — false VIOLATION율 **68% → 17%**로 대폭 개선, 단 새 결함 1건 발견

| 지표 | v1(2026-08-22) | v2(2026-08-24) |
|---|---|---|
| 실행 성공 | 50/50 | 50/50 |
| golden과 일치(acceptable) | — | 38/50 (76%) |
| "위반 아님"이어야 할 30건 중 오탐(VIOLATION) | 21/31 (68%) | **5/30 (17%)** |
| R-201 경계값(정확히 30만원 vs 30만원+1원) 정확도 | 오류(`>=`로 오판) | **정확**(qa49 NO_VIOLATION / qa50 VIOLATION) |
| qa01 총액↔1인당 계산(180,000÷5) | 오류(390,000으로 역산) | **정확**(36,000원, report 요약에 명시) |
| 근거 인용 완전 창작 | 0건(v1도 0건) | 0건 |

**경계값 처리와 총액/1인당 산술 오류는 이번 재검증에서 재현되지 않았다** — v1이 권고했던
"산술 검산 규칙 프롬프트 추가" 방향과 일치하는 개선으로 보인다(v2 코드에 명시적 검산 규칙이
추가됐는지는 diff로 확인하지 않았음 — `gpt-5-mini`+heavy reasoning 자체의 개선 가능성도 배제 못 함).

### 2.2 남은 오탐 5건 재분석 — **3건은 골든 라벨이 틀렸고, 2건은 실제 버그**

5건을 근거 문구까지 열어본 결과, 오탐으로 셀 게 아닌 것과 진짜 결함이 섞여 있었다:

**골든 라벨이 틀렸던 3건 (모델이 오히려 맞았다)**

| case | 실제 필드 | 모델 판단 | 재평가 |
|---|---|---|---|
| qa41(516) | 접대, headcount=3, pre_approved=`None`, 60만원 | VIOLATION→SUPPLEMENT(사전승인 미확인+참석자 명단 불완전) | 60만원은 사전승인 대상 금액(30만원 초과)인데 `pre_approved`가 `None`(모름)이면 "모르니 통과"가 아니라 "승인 여부를 확인할 수 없다"는 결함이 맞다 — 골든이 이를 무조건 INSUFFICIENT_INFO로 접었던 게 과했다 |
| qa39(514) | 회식, 전 필드 `None` | VIOLATION→SUPPLEMENT(제10조 참석자 명단 필수증빙 누락) | "정보 없음"과 "필수 기재사항 자체가 없음(R-214 기록누락)"은 다른 사실 — 후자는 그 자체로 문서화된 위반 유형이다. 골든이 이 구분을 안 하고 뭉뚱그렸다 |
| qa47(522) | 회식, headcount=6, 70만원, 주류포함, pre_approved=`None` | VIOLATION→REJECT(1인당 116,667원 초과 + 사전승인 미확인) | 1인당 116,667원은 회식 1인당 권장한도(정책표 5만원)를 명백히 초과 — golden 설계 당시 "고액이지만 구조화 사실상 위반 아님"이라고 적었던 게 계산 실수였다(1인당 금액을 직접 안 나눠봤다) |

**실제 버그 2건 — 카테고리 스코프 누수: 회식 규정이 식대(MEAL) 거래에 적용됨**

| case | 실제 필드 | 모델 판단 | 문제 |
|---|---|---|---|
| qa44(519) | **식대(MEAL)**, headcount=1, 3,000원 | VIOLATION→REJECT: "회식_운영규정 제6조, 최소 참석 인원 3인 이상 원칙 위반" | `category="식대"`인데 **회식(GATHERING) 전용 최소인원 규정을 인용해 반려**했다. 3,000원짜리 개인 야근 식대에 회식 최소인원 룰을 적용하는 것은 명백한 오적용 |
| qa46(521) | **식대(MEAL)**, headcount=1, 50,000원, 새벽 3시 | VIOLATION→REJECT: 동일하게 "회식_운영규정 제6조" 인용 | 동일 결함 재현 — 우연이 아니라 **패턴**임을 확인 |

두 건 모두 `Settlement.category`는 정확히 "식대"로 저장돼 있음을 DB에서 직접 확인했다(모델 입력이
아니라 판정 로직 쪽 문제). **원인**: `search_policy` 검색이 정산의 `category` 필드로 문서를
스코프 필터링하지 않고 전체 규정을 대상으로 검색. Rule Agent의 "근거 없는 카테고리 질의 시 다른
카테고리 규정을 가져오는" 결함과 **같은 계열의 근본 원인**(두 에이전트가 검색 단계에서
카테고리/스코프를 강제하지 않는다는 공통점). **2026-08-24 후속: 이 원인은 `_summary.md` §수정 1의
RAG scope 필터로 실제 수정·라이브 재검증까지 완료됨**(qa44·46 재실행 시 더는 회식_운영규정을
인용하지 않고 공통 규정만 인용 확인).

### 2.3 그룹별 세부 결과

- **(a) 명백히 정상 qa01~12(12건)**: 12/12 중 11건 정확히 NO_VIOLATION, 1건(qa10)만 INSUFFICIENT_INFO로
  보수적 이탈(오판 아님, 과소평가 방향이라 안전한 실패).
- **(b) 명백한 위반 qa13~32(20건)**: VIOLATION 정확 11건 + INSUFFICIENT_INFO(허용 가능) 3건 = 14/20
  안전권. **실제 미탐지(false negative) 5건**: qa14(야간, ts 미전달 — 구조적 한계로 예상됐던 그대로)·
  qa15(주말, purpose 텍스트 신호를 못 잡음)·qa16(외부인 참석 R-204 미탐)·qa20(headcount=2 최소인원
  룰 미탐 — v1에서도 같은 케이스가 검색 비결정성으로 누락됐던 자리, 이번에도 재현)·qa29(목적 공란
  R-214 미탐, 다만 qa39는 같은 유형을 잡았다 — 일관성 문제).
- **(c) 애매/정보부족 qa33~42(10건)**: 8/10 정확(INSUFFICIENT_INFO), 2건(§2.2의 qa39·41)은 "정보
  부족"이 아니라 "필수사항 미기재=위반"으로 더 엄격하게 판단 — 골든 설계 오류로 재분류.
- **(d) 이상탐지 경계 qa43~50(8건)**: 경계값(qa49/50) 정확, §2.2의 카테고리 누수 버그 2건(qa44·46)
  제외하면 6/8 정확.

### 2.4 지연시간 · 비용

| 지표 | 값 |
|---|---|
| 실행 성공 | 50/50 |
| tier_path 분포 | heavy 47 · low 2 · fast 1 |
| 지연 평균(전체) | 26,949.9ms |
| 지연 평균(heavy만) | 약 28.5초 |
| 지연 최소/최대 | 50.9ms(LOW, LLM 미호출) / 39,733.8ms |
| 토큰/비용 | `/lab/risk/run` 응답에 여전히 토큰 사용량 노출 없음(v1과 동일 한계, N/A) |

### 2.5 근거 인용(citation) 타당성

새 서버 측 검증(`_validate_report`)이 "검색 결과에 없는 인용은 버린다"를 강제하므로 구조적으로
창작 인용 가능성이 낮아졌다. 5건 스팟체크(§2.2 표에 실은 사례)에서 인용된 조·항 번호가 실제
회식_운영규정/업무추진비_사용규정 문서 구조(제2장 제5~7조, 제4장 제10조, 별표2)와 일치했고, 완전
창작 조항은 발견되지 않았다.

### 2.6 남은 권고

1. R-207(최소인원) 계열의 검색 비결정성(qa20, v1·v2 양쪽에서 재현)은 여전히 미해결 — 같은 케이스
   n회 반복 실행으로 재현율 자체를 측정해 볼 가치가 있다.
2. 산술·경계값 오류가 이번엔 재현되지 않아 v1의 최우선 권고(산술 검산 규칙)는 효과가 있었거나
   이미 반영된 것으로 보인다 — 우선순위 하향.
3. ~~카테고리 스코프 필터 추가~~ — 완료(§2.2 후속 참조).
4. ~~골든 라벨셋 정정~~ — 완료(위 표에 반영).

# Rule Agent QA — 테스트 케이스 + 실행 결과 (2026-08-22, 코드 변경 영향 재확인 2026-08-24)

> 원본 DB 레코드(RuleGraph DRAFT 50~51건)는 이미 삭제됨. 재현하려면 아래 케이스 표로 다시 생성하거나
> `fixtures/qa_rule_agent_rulegraphs.json`+`qa_rule_agent_rulenodes.json`을 `loaddata`(전제 조건은
> `fixtures/README.md`).

## 1. 테스트 케이스 정의 (50건)

scope는 `apps/ai/app/agents/rule_agent_v0/api.py`의 `Scope` Literal 값(GLOBAL/회식/회의/식대/출장/접대/비품) 기준. golden은 `llm_wiki/docs/RULE_명세서.md` 기준 정답 조건/임계값.

| ID | scope | 목표 RULE | 질의(query) | Golden 기대값 |
|---|---|---|---|---|
| G01 | 회식 | R-201 | 회식비 사전승인 기준 금액(30만원 초과 시 사전승인 필요)에 대한 룰을 만들어줘 | amount > 300000, pre_approval_obtained == false |
| G02 | 회식 | R-202 | 회식 22시 이후 야간 결제에 대한 승인확인 룰을 생성해줘 | payment_time >= 22:00 |
| G03 | 회식 | R-203 | 회식비 주말·공휴일 결제 시 사후승인 확인이 필요하다는 룰을 만들어줘 | day_of_week IN (SAT,SUN) OR is_holiday==true |
| G04 | 회식 | R-204 | 회식에 외부인(거래처 등)이 1인 이상 참석하면 기업업무추진비로 재분류하는 룰을 만들어줘 | external_participant_count >= 1 → reclassify to 기업업무추진비 |
| G05 | 회식 | R-205 | 회식비를 호텔이나 특급레스토랑 같은 고급업종에서 결제한 경우에 대한 룰을 생성해줘 | merchant_grade IN (호텔,특급레스토랑) |
| G06 | 회식 | R-206 | 회식 시 주류를 포함해 1인당 식대가 8만원을 초과하는 경우 룰을 만들어줘 | includes_alcohol==true AND per_person_amount > 80000 |
| G07 | 회식 | R-207 | 회식 참석 인원이 카드 사용자 포함 2인 이하인 경우(개인 식사 추정) 룰을 만들어줘 | participant_count <= 2 |
| G08 | 회식 | R-208 | 회식 후 노래방·단란주점 등 2차 유흥업소에서 결제한 경우에 대한 반려 룰을 만들어줘 | merchant_type IN (노래방,단란주점,유흥업소) OR is_secondary_venue==true, CRITICAL |
| G09 | 회식 | R-209 | 회식비 명목으로 상품권이나 개인 선물을 구매한 경우 반려 룰을 만들어줘 | item_type IN (상품권,개인선물) |
| G10 | 회식 | R-210 | 회식 참석자가 전부 가족·지인 등 사적 관계로 추정되는 경우의 룰을 만들어줘 | family_or_personal_gathering_suspected == true |
| G11 | 회식 | R-211 | 퇴사한 사람이 회식에 참석했는데 부서장 승인이 없는 경우 룰을 만들어줘 | participant_includes_former_employee==true AND pre_approval_level < 부서장 |
| G12 | 회식 | R-212 | 출장 기간 중 발생한 회식에 대한 룰을 만들어줘 | during_business_trip == true |
| G13 | 회식 | R-213 | 전사 단위 회식은 금액과 무관하게 CEO 사전승인이 필요하다는 룰을 만들어줘 | scope == 전사 |
| G14 | 회식 | R-214 | 회식 참석자 명단·목적·장소일시 등 필수 기재사항이 누락된 경우 룰을 만들어줘 | participant_list_missing OR purpose_missing OR venue_datetime_missing 등 |
| G15 | 회식 | R-215 | 동일 회식 건이 2개 이상 가맹점으로 분할 결제된 경우(2차 유흥업소 제외)의 룰을 만들어줘 | same_event_multiple_merchants==true AND is_secondary_venue==false |
| G16 | 회식 | R-216 | 본부·전사 단위 대규모 회식이 승인권자 1일 한도를 초과할 것으로 예상되는데 개인카드로 결제한 경우 룰을 만들어줘 | scope IN (본부,전사) AND amount > approver_daily_limit AND event_scale_payment_method==개인카드 |
| T01 | 출장 | R-301 | 모든 해외출장은 금액과 무관하게 부서장 이상 사전승인이 필요하다는 룰을 만들어줘 | trip_type==해외 AND pre_approval_level < 부서장 |
| T02 | 출장 | R-302 | 출장 1박 숙박비가 등급별 상한(국내 15만원, 해외 A등급 25만원 등)을 초과하는 경우 룰을 만들어줘 | lodging_amount_per_night > lodging_limit_table[trip_type][region_grade] |
| T03 | 출장 | R-303 | 국내출장 야간식대 청구인데 근무종료시각(기본 18시) 이전 결제인 경우 룰을 만들어줘 | trip_type==국내 AND expense_type==야간식대 AND payment_time < work_end_time(18:00) |
| T04 | 출장 | R-304 | 출장 중 유흥업소·카지노·경마 등 사행성 업종에서 결제한 경우 반려 룰을 만들어줘 | merchant_type IN (유흥업소,사행성업종,카지노,경마), CRITICAL |
| T05 | 출장 | R-305 | 출장 중 이용업·미용업 등 업무관련성 낮은 업종 결제 시 부서장 승인 없으면 반려 권고하는 룰을 만들어줘 | merchant_type IN (이용업,미용업) AND pre_approval_level < 부서장 |
| T06 | 출장 | R-306 | 출장비 결제 시 봉사료가 10% 이상 포함된 경우 룰을 만들어줘 | service_charge_ratio >= 0.10 |
| T07 | 출장 | R-307 | 출장 종료일로부터 7영업일 초과해서 정산 등록한 경우 룰을 만들어줘 | business_days_since_trip_end > 7 |
| T08 | 출장 | R-308 | 항공권·숙박 예약과 출장일 사이 2개월 이상 시차가 있는데 확인서 미제출인 경우 룰을 만들어줘 | booking_to_trip_gap_months >= 2 AND (confirmation_doc_submitted==false OR itinerary_mismatch==true) |
| T09 | 출장 | R-309 | 간편결제로 결제해 원 가맹점 정보 확인이 어려운 경우 룰을 만들어줘 | payment_method==간편결제 AND merchant_info_resolved==false |
| T10 | 출장 | R-310 | 출장 중 접대성 식대인데 참석자 인원·소속 기록이 없는 경우 룰을 만들어줘 | meal_type==접대성 AND participant_record_missing==true |
| T11 | 출장 | R-311 | 해외출장 항공권이 이코노미 원칙을 위반하거나 프리미엄이코노미 요건(비행 8시간 이상, 본부장 이상)을 충족하지 못한 경우 룰을 만들어줘 | NOT flight_class IN (이코노미,프리미엄이코노미) OR (프리미엄이코노미 AND (flight_duration_hours<8 OR position<본부장)) |
| T12 | 출장 | R-312 | 출장비가 직책별 사전승인 기준금액(팀장 50만원/부서장 60만원/본부장 80만원/대표이사 100만원)을 초과하는데 승인이 없는 경우 룰을 만들어줘 | amount > pre_approval_threshold_table[position] AND pre_approval_level < position_required_level |
| T13 | 출장 | R-313 | 해외출장 항공+숙박 합산 예산이 500만원을 초과하는데 본부장 이상 승인이 없는 경우 룰을 만들어줘 | (flight_amount+lodging_amount) > 5000000 AND pre_approval_level < 본부장 |
| T14 | 출장 | R-314 | 출장 개시 3영업일 전까지 출장신청서를 제출하지 않은 경우(긴급출장 제외) 룰을 만들어줘 | trip_request_submitted_days_before < 3 AND emergency_trip==false |
| E01 | 접대 | R-101 | 기업업무추진비 3만원 초과 지출인데 적격증빙을 수취하지 못한 경우 룰을 만들어줘 | amount > 30000 AND has_valid_receipt==false |
| E02 | 접대 | R-102 | 기업업무추진비 30만원 초과 100만원 이하 구간에서 부서장 사전승인이 없는 경우 룰을 만들어줘 | 300000 < amount <= 1000000 AND pre_approval_level < 부서장 |
| E03 | 접대 | R-103 | 기업업무추진비 100만원 초과 300만원 이하 구간에서 본부장 이상 승인이 없는 경우 룰을 만들어줘 | 1000000 < amount <= 3000000 AND pre_approval_level < 본부장 |
| E04 | 접대 | R-104 | 기업업무추진비 300만원 초과 지출인데 대표이사 사전승인이 없는 경우 룰을 만들어줘 | amount > 3000000 AND pre_approval_level < 대표이사 |
| E05 | 접대 | R-105 | 골프 등 행사성 접대에서 부서장 이상 사전승인 또는 행사계획 첨부가 없는 경우 룰을 만들어줘 | entertainment_type==행사성 AND (pre_approval_level<부서장 OR event_plan_attached==false) |
| E06 | 접대 | R-106 | 청탁금지법 적용대상자에게 유형별 한도(음식물 5만원, 선물 5만원/농수산물 15만원, 경조사비 5만원/화환 10만원)를 초과 지급한 경우 룰을 만들어줘 | has_kickback_law_target==true AND per_person_amount[gift_type] > kickback_limit_table[gift_type] |
| E07 | 접대 | R-108 | 기업업무추진비 거래처명·참석자 정보·목적 기재가 누락되거나 포괄적으로만 기재된 경우 룰을 만들어줘 | vendor_info_missing OR participant_list_missing OR purpose_is_generic OR kickback_law_target_status_missing |
| E08 | 접대 | R-110 | 기업업무추진비 결제금액 중 봉사료가 10% 이상 포함된 경우 룰을 만들어줘 | service_charge_ratio >= 0.10 |
| E09 | 접대 | R-111 | 거래처 경조사 화환·조의금이 20만원을 초과하는데 소명자료가 없는 경우 룰을 만들어줘 | item_type==경조사 AND amount > 200000 AND has_supporting_evidence==false |
| E10 | 접대 | R-114 | 기업업무추진비 지출 결의자 본인이 접대 자리에 참석하지 않은 경우(선물 제외) 룰을 만들어줘 | spender_attended==false AND entertainment_type != 선물 |
| M01 | 회의 | NONE | 회의비 사용 시 지켜야 할 한도나 승인 규정을 알려주고 룰을 만들어줘 | no dedicated 회의 규정 exists — expect generic/공통 RULE or graceful no-match, NOT a fabricated specific threshold |
| M02 | 회의 | NONE | 회의비 1인당 식대 한도 초과 기준에 대한 룰을 만들어줘 | no such documented rule for 회의 category — watch for hallucinated specific won amount |
| M03 | 회의 | NONE | 회의 중 다과·음료 구매의 증빙 기준 룰을 만들어줘 | no dedicated source; only common R-008 (3만원 초과 적격증빙) could generically apply |
| M04 | 회의 | NONE | 외부 인사가 참석하는 회의비 지출에 대한 승인 절차 룰을 만들어줘 | no dedicated 회의 규정 — should not hallucinate a specific approval threshold |
| S01 | 비품 | R-013(공통) | 비품 구매 등 카테고리 특칙이 없는 지출이 직책별 사전승인 기준(대표이사 100만원/본부장 80만원/부서장 60만원/팀장 50만원/비직책자 30만원)을 초과하는 경우 룰을 만들어줘 | amount > pre_approval_threshold_table[position] AND pre_approval_level < position (공통 R-013) |
| S02 | 비품 | R-008(공통) | 비품 등 기업업무추진비 외 지출이 3만원을 초과하는데 적격증빙을 수취하지 못한 경우 룰을 만들어줘 | category != 기업업무추진비 AND amount > 30000 AND has_valid_receipt==false (공통 R-008) |
| S03 | 비품 | NONE | 비품 구매 시 특정 브랜드 제품 구매를 제한하는 룰을 만들어줘 | no such rule documented anywhere — pure hallucination trap, should decline/no-match |
| ML1 | 식대 | R-008(공통) | 식대 지출 3만원 초과인데 적격증빙을 수취하지 못한 경우 룰을 만들어줘 | category != 기업업무추진비 AND amount > 30000 AND has_valid_receipt==false (공통 R-008) |
| ML2 | 식대 | R-007(공통) | 식대 지출이 직책별 1일·1개월 사용한도(별표1)를 초과한 경우 룰을 만들어줘 | daily_cumulative_amount > daily_limit_table[position] OR monthly_cumulative_amount > monthly_limit_table[position] (공통 R-007) |
| ML3 | 식대 | NONE | 식대 지출 시 1인당 5만원을 초과하면 무조건 반려한다는 룰을 만들어줘 | no such specific 식대 5만원 cap documented anywhere — hallucination trap |

---

## 2. 실행 결과 보고서

50개 테스트 케이스를 실제 운영 경로(`POST /lab/rule/generate` → `rule_agent_v0.agent.generate()` → RAG(Chroma `policy_docs`, 103청크) → GPT-4o-mini 추출 → 결정론적 조립 → Django `RuleGraph(DRAFT)` 저장)로 전건 실행했다. 사전 확인: `GET /lab/status` — `policy_docs` count=103 (정상, RAG 대상 존재 확인).

### ⚠️ 2026-08-24 재확인 — main 풀(`0235fe5` 등) 영향 검토, 재실행은 보류

main에서 대량 풀(44커밋) 이후 `rule_agent_v0/agent.py`(121줄)·`django_client.py`(42줄)·`api.py`·`chat.py`가
바뀌었다. **`git diff`로 실제 변경 내용을 확인한 결과**, 이번 변경은 **어휘(파일 검증 카탈로그) 정합성
리팩터링**이다 — `EvalContext` 허용 경로·decision/severity·연산자 목록을 `app/context`(신규 공용
카탈로그, Draft Agent와 공유)로 일원화하고, `is_null` 연산자(「값이 없다」 vs 「모른다」 구분)를 새로
허용했다. **아래 §2.2의 두 핵심 발견(CRITICAL 룰이 topK 편향으로 검색에서 밀려남 / 근거 없는 카테고리
질의 시 83% 환각)을 겨냥한 변경은 이번 diff에 없다** — `search_policy` 호출부의 `top_k` 기본값(6)도
그대로고, scope-문서 불일치를 사전 차단하는 로직도 추가되지 않았다. 따라서 **§2.2의 findings는 여전히
유효할 가능성이 높다고 판단**해 이번 라운드에서는 50건 전체 재실행은 보류했다(같은 결함을 재확인만
하는 데 47초×50건의 비용을 쓰는 것보다, 검색 다양성·scope 가드가 실제로 들어간 뒤 재실행하는 편이
효율적). `is_null` 신규 지원은 이번 테스트셋의 목표 룰(R-2xx/T-xxx/E-xxx)에 해당 연산자가 필요한
케이스가 없어 이번 재확인 범위 밖이다.

**다음 재실행 트리거**: ① `search_policy` 검색 다양성(topK 확대 또는 조 단위 강제 샘플링) 추가 ②
생성 후 "인용 문서의 scope가 요청 scope와 일치하는가" 결정론적 검증 게이트 추가 — 둘 중 하나라도
들어오면 §2.1의 34%/83% 수치를 재측정할 가치가 있다.

### 2.0 실행 결과 개요

- **50/50 성공** — API 에러·타임아웃 없음. **50/50 DRAFT RuleGraph 생성**(그래프 id 89~138, 전부 `QA_RULE_<caseId>_<timestamp>` 이름으로 태깅 — 원본 레코드는 삭제됨, `fixtures/qa_rule_agent_rulegraphs.json` 참조).
- **지연시간**: 평균 47.8초, 최소 33.6초(T01), 최대 78.3초(E03). LLM 툴콜링 루프(멀티턴)가 케이스별로 조금씩 다른 시도 횟수를 쓰는 것으로 보인다.
- **토큰/비용**: `/lab/rule/generate` 응답에는 토큰 사용량 필드가 없다(다른 lab 엔드포인트와 달리 `usage` 미노출) — 이번 조사에서는 비용을 계량하지 못했다. 향후 계측하려면 `rule_agent_v0/agent.py` 쪽에 usage 로깅을 추가해야 한다.
- **DSL 유효성**: 268개 생성 노드 전부 유효한 JSON-Logic(`and/or/==/>/in/not`) 구조로 Postgres에 저장됨(파싱·제약조건 위반 0건) — 문법적 유효성은 100%.

### 채점 방법

각 케이스의 실제 `RuleNode.condition`(JSON-Logic)을 Postgres에서 직접 조회(`policies_rulenode`/`policies_rulegraph`, `docker compose exec db psql`)해 golden 조건과 **의미 단위로** 대조했다(자동 숫자-리터럴 매칭 + 수동 조건식 검토). 3단 판정:
- **HIT** — 목표 RULE의 핵심 조건(변수+임계값)이 그대로 또는 `policy.*` 참조 테이블로 정확히 구현됨.
- **PARTIAL** — 개념은 맞지만 조건이 느슨해짐(예: 직책별 테이블이 단일 고정 임계값으로 평탄화, 부가 조건 누락).
- **MISS** — 목표 RULE과 무관한 다른 규칙이 생성되었거나(질의를 사실상 무시), 해당 개념이 전혀 나타나지 않음.

### 2.1 임계값/조건 추출 정확도 (documented-rule 44케이스: G16+T14+E10+공통확장 4)

| 그룹 | HIT | PARTIAL | MISS |
|---|---|---|---|
| 회식 G01~16 | 6 | 2 | 8 |
| 출장 T01~14 | 6 | 3 | 5 |
| 접대 E01~10 | 2 | 2 | 6 |
| 공통 확장(S01·S02·ML1·ML2) | 1 | 1 | 2 |
| **합계** | **15/44 (34%)** | **8/44 (18%)** | **21/44 (48%)** |

**HIT+PARTIAL 합산 정확도 ≈ 52%**, **순수 HIT(정확 재현)만 보면 34%**. 절반에 가까운 케이스에서 명시적으로 요청한 규정 조항의 핵심 조건이 아예 반영되지 않았다.

### 2.2 핵심 발견 (findings)

**발견 1 — CRITICAL 규칙이 골라서 요청해도 생성되지 않는다.** 회식 R-208(2차 유흥업소 결제, CRITICAL/자동반려), R-209(금지품목), R-210(가족·사적모임), R-211(퇴사자 참석), R-215(분할결제)를 **각각 명시적으로 지목해 질의**했음에도(G08~G11, G15), 생성된 노드에는 해당 개념이 전혀 없고 대신 사전승인 금액(30만원)·주류 1인당(8만원)·외부인·야간·주말 같은 **제7조·제8조 계열의 동일한 6~8개 패턴이 케이스마다 거의 그대로 반복**됐다. `topK=6` 검색이 매번 같은 지배적 청크(제7조·제8조)를 상위로 뽑아, 제5조(2차·금지품목)·제6조(가족·퇴사자) 근거는 컨텍스트에 거의 밀려나는 것으로 보인다. **결과적으로 가장 위험도가 높은 CRITICAL 룰(R-208)이 정확히 그것을 요청한 케이스에서도 생성 실패**했다 — 이 시스템에서 가장 중요하게 잡아야 할 규칙이 가장 잘 빠지는 역설.

**발견 2 — "규정 없음" 카테고리에서 진짜 환각(hallucination)이 발생한다.** 회의(MEETING, M01~04)·식대(ML3)에는 RULE_명세서에 대응 조항이 없다. 정상적인 반응은 "근거 없음"으로 건너뛰거나 공통 RULE만 적용하는 것이지만, **6개 트랩 케이스 중 5개(M01~04, ML3)에서 회식_운영규정/업무추진비_사용규정의 조항·숫자(30만원·8만원·5만원 등)를 그대로 가져와 `scope="회의"`/`"식대"` 그래프에 저장**했다. 예: `M03`은 회식 규정을 근거로 REJECT/CRITICAL 노드를 "회의" 카테고리에 만들었고, `ML3`은 청탁금지법 한도(5만원, 원래 조건은 `has_kickback_law_target==true`가 필수)를 그 조건 없이 **모든 식대 1인당 5만원 초과 건에 무조건 적용**하는 노드를 만들었다(실사용 시 대상자 아닌 정상 식사도 대량 오탐). **`S03`(비품, 특정 브랜드 제한 트랩)만 유일하게 "근거 없음"으로 정직하게 건너뛰었다(`llm_skipped`)** — 나머지는 실패 신호 없이 조용히 저장됐다는 점이 더 위험하다(`status: DRAFT_SAVED`로 성공처럼 보인다).
→ **하드 트랩 6건 중 5건(83%) 환각**, 이는 별도 파이프라인 결함이 아니라 **RAG가 스코프 필터 없이 전체 규정 문서를 검색해 카테고리 불일치를 감지하지 못하는 구조적 문제**로 보인다. (2026-08-24 후속: 이 근본 원인은 `_summary.md` §수정 1의 RAG scope 필터로 실제 수정·재검증됨.)

**발견 3 — 직책별/구간별 테이블이 평탄화(flatten)된다.** R-102~104(30만~100만/100만~300만/300만↑ 구간별 승인권자), R-312(직책별 사전승인 테이블), R-313(500만원 합산)처럼 **구간·직책에 따라 값이 달라지는 규칙**은 (E02·E03처럼 잘 잡힌 경우도 있지만) T12·T13·E04에서 단일 고정 `policy.preapproval_threshold` 하나로 뭉개지거나, T13은 아예 R-302(숙박비 상한)를 재생성해 버렸다(질의 대상과 다른 규칙). `policy.*` 참조 자체는 설계상 올바른 패턴(정책 도메인 캐논)이지만, **다축(직책×금액) 구조를 단일 스칼라로 붕괴시키는 추출 오류**는 3건 이상에서 반복됐다.

**발견 4 — 인용(citation)은 문서·조 단위로는 대체로 맞지만 조 하위 항까지는 거칠다.** 정상 케이스(G01·G06·E02·E03·T04·T07 등) 15건 스팟체크 결과, `source_clause`가 올바른 문서명(회식_운영규정/출장비_사용규정/기업업무추진비_사용규정)과 대략적 조(제7조·제8조 등)는 대부분 일치했으나, 세부 항(①~⑧)까지 정확히 짚은 경우는 드물었다("제8조 제1~8호"처럼 범위로 뭉뚱그림). 환각 트랩(발견 2)에서는 **문서 자체가 틀렸다**(회의/식대 스코프인데 회식·업무추진비 규정을 인용).

### 2.3 요약 수치

| 지표 | 값 |
|---|---|
| 실행 성공률 | 50/50 (100%) |
| DRAFT RuleGraph 생성 | 50/50 (100%) |
| DSL 문법 유효성 | 268/268 노드 (100%) |
| 임계값 HIT (엄격) | 15/44 (34%) |
| 임계값 HIT+PARTIAL | 23/44 (52%) |
| 하드 트랩(무근거) 환각률 | 5/6 (83%) |
| 평균 지연시간 | 47.8초 (33.6~78.3초) |
| 토큰/비용 계측 | 불가 (엔드포인트 미노출) |

생성됐던 50건의 그래프id·이름 전체 목록은 원본 DB에서 이미 삭제됐다 — `fixtures/qa_rule_agent_rulegraphs.json`(원본 PK 89~138, 141)에 스냅샷으로 남아 있다.

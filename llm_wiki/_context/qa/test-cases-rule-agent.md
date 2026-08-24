# Rule Agent QA — 테스트 케이스 정의 (50건)

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

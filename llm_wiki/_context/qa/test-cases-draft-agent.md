# Draft Agent QA — 테스트 케이스 50건 (골든 라벨)

> 대상: `POST /lab/draft/run`(생성 모드, `apps/ai/app/api/lab.py::draft_run` → `app/agents/draft_agent.py::run`).
> 실행 결과·지표는 `draft-agent-test-report.md` 참조. 실행일 2026-08-22.
>
> **환경 제약(최초 실행, 2026-08-22 21:xx)**: 최초 실행 시점에는 `KAKAO_REST_API_KEY`가 설정되어
> 있지 않아(`apps/ai/app/merchant/classify.py` 경고 로그로 확인) 업종 분류 캐스케이드가
> **캐시 → (카카오 스킵) → 미확정**으로만 동작, 캐시된 3건(`스타벅스` 계열) 외 47건이 전부
> 미확정으로 귀결됐다.
>
> **✅ 카카오 키 추가 후 재검증 완료(2026-08-22 22:4x)**: `.env`에 `KAKAO_REST_API_KEY` 설정 →
> `docker compose up -d --force-recreate ai` → 동일 50건 재실행. 결과·정정 사항은
> `draft-agent-test-report.md` §11("카카오 활성화 재검증") 참조. 요지: **카카오 API 자체는
> 정상 동작 확인**(실 호출 200 OK 다수 관측)하지만, 이번 재검증에서 새로 드러난 사실은 —
> 이 테스트셋의 "미확정 기대(UNKNOWN)" 6건 외에도 **실존하지 않는 가상의 상호명(예: "삼겹살구이
> 대박당", "회의실렌탈 서울센터")은 카카오 실지도 검색에서 애초에 매치될 결과가 없어 미확정으로
> 남는다** — 이는 테스트 케이스가 가상 상호를 쓴 데서 오는 한계이지 코드 결함이 아니다. 반대로
> 실존 체인(GS25·이마트·신라호텔·오피스디포 등)은 카카오가 정확히 찾아내 업종이 확정됐다.

카테고리(6종): 회식(GATHERING)·회의(MEETING)·식대(MEAL)·출장(TRIP)·접대(ENTERTAIN)·비품(SUPPLIES)
업종코드(15종, `domain/transactions/industry.py`): RESTAURANT·CAFE·BAR_ENTERTAINMENT·KARAOKE·GAMBLING·LODGING·GOLF·LEISURE·MART·DUTY_FREE·PERSONAL_CARE·OFFICE_SUPPLIES·FUEL_TRANSPORT·ELECTRONICS·OTHER

`UNKNOWN` = 이 케이스는 정답이 하나로 고정되지 않는(모호/적대적) 케이스라는 뜻 — 실제 응답을 관찰 대상으로 삼는다.

| # | 가맹점 | 금액 | 카드구분 | 인원 | 기대 category | 기대 industry | 근거 |
|---|---|---|---|---|---|---|---|
| 1 | 김밥천국 강남점 | 8,000 | PERSONAL | 0 | 식대 | RESTAURANT | 분식 체인, 개인 소액 식사 |
| 2 | 맥도날드 신촌점 | 12,000 | PERSONAL | 0 | 식대 | RESTAURANT | 패스트푸드 개인 식사 |
| 3 | 본죽 여의도점 | 9,500 | PERSONAL | 0 | 식대 | RESTAURANT | 죽 전문점 개인 식사 |
| 4 | 스타벅스 을지로점 | 6,500 | PERSONAL | 0 | 식대 | CAFE | 소액 커피, 개인 음료 |
| 5 | 교촌치킨 판교점 | 25,000 | PERSONAL | 0 | 식대 | RESTAURANT | 치킨, 1인 야근식 규모 |
| 6 | 파리바게뜨 강남역점 | 15,000 | PERSONAL | 0 | 식대 | CAFE | 베이커리 간식/개인식사 |
| 7 | 설렁탕집 종로점 | 11,000 | PERSONAL | 0 | 식대 | RESTAURANT | 한식당 개인 식사 |
| 8 | 미가옥 우동전문점 | 10,500 | PERSONAL | 0 | 식대 | RESTAURANT | 일식 프랜차이즈 개인 식사 |
| 9 | 이자카야 준 강남점 | 180,000 | TEAM | 6 | 회식 | BAR_ENTERTAINMENT | 이자카야+대인원+고액=팀 회식 |
| 10 | 호프집 맥주와치킨 | 220,000 | TEAM | 8 | 회식 | BAR_ENTERTAINMENT | 호프집+대인원 |
| 11 | 삼겹살구이 대박당 | 350,000 | TEAM | 10 | 회식 | RESTAURANT | 구이 전문점+대인원+고액 |
| 12 | 노래방 신나라 | 150,000 | TEAM | 6 | 회식 | KARAOKE | 회식 2차 전형 패턴 |
| 13 | 포차 골목집 | 90,000 | TEAM | 4 | 회식 | BAR_ENTERTAINMENT | 포장마차 팀 회식 |
| 14 | 곱창집 만석당 | 280,000 | TEAM | 7 | 회식 | RESTAURANT | 구이류+대인원 |
| 15 | 토즈 강남점 모임공간 | 80,000 | TEAM | 5 | 회의 | OTHER | 모임공간 대여, 15종에 렌탈업 없음 |
| 16 | 회의실렌탈 서울센터 | 100,000 | TEAM | 8 | 회의 | OTHER | 회의실 대여 |
| 17 | 스터디룸 대여 강남 | 60,000 | TEAM | 4 | 회의 | OTHER | 스터디룸 대여 |
| 18 | 청년창업허브 세미나룸 | 50,000 | TEAM | 10 | 회의 | OTHER | 세미나룸 대여 |
| 19 | 스타벅스 회의동점 | 45,000 | TEAM | 5 | 회의 | CAFE | 카페+다수 인원, 회의 vs 식대 경계 |
| 20 | 대한항공 | 450,000 | PERSONAL | 0 | 출장 | OTHER | 항공사, 15종에 항공 카테고리 없음 |
| 21 | 신라호텔 부산 | 250,000 | PERSONAL | 0 | 출장 | LODGING | 호텔 숙박, 출장 전형(단 정보 부족 시 접대로도 해석 가능 — 보고서 참조) |
| 22 | KTX 코레일 | 45,000 | PERSONAL | 0 | 출장 | FUEL_TRANSPORT | 철도 이동 |
| 23 | 하나투어 출장예약센터 | 800,000 | PERSONAL | 0 | 출장 | OTHER | 여행사, 출장 패키지 |
| 24 | 메리어트호텔 서울 | 300,000 | PERSONAL | 0 | 출장 | LODGING | 호텔 체인 숙박 |
| 25 | 갤러리아백화점 선물세트 | 300,000 | TEAM | 0 | 접대 | OTHER | 거래처 선물(백화점은 15종에 없음, 비품과 혼동 가능성 — 보고서 참조) |
| 26 | 한우전문점 접대용 안심점 | 500,000 | TEAM | 4 | 접대 | RESTAURANT | 고가 한식당+거래처 동반 |
| 27 | 와인샵 셀러바인 | 200,000 | TEAM | 0 | 접대 | OTHER | 주류 소매점, 선물용 |
| 28 | 골프존카운티 라운딩 | 400,000 | TEAM | 4 | 접대 | GOLF | 골프 라운딩(주의업종) |
| 29 | 오피스디포 강남점 | 45,000 | PERSONAL | 0 | 비품 | OFFICE_SUPPLIES | 사무용품 전문점 |
| 30 | 다이소 사무용품코너 | 12,000 | PERSONAL | 0 | 비품 | OFFICE_SUPPLIES | 생활용품점, 사무용품 목적 명시 |
| 31 | 알파문구 센터점 | 30,000 | PERSONAL | 0 | 비품 | OFFICE_SUPPLIES | 문구 전문점 |
| 32 | 하이마트 전자제품매장 | 850,000 | PERSONAL | 0 | 비품 | ELECTRONICS | 가전 양판점 |
| 33 | 가나다라마바상사 | 20,000 | PERSONAL | 0 | UNKNOWN | 미확정 | 무의미 상호, 업종 신호 없음 → 미확정 유지가 정답 |
| 34 | ABC123유통 | 15,000 | PERSONAL | 0 | UNKNOWN | 미확정 | 일반 상사명, 업종 신호 없음 |
| 35 | 제이케이물류센터 | 50,000 | PERSONAL | 0 | UNKNOWN | 미확정 | 물류업, 15종 어휘에 없음 |
| 36 | 튼튼상회 | 8,000 | PERSONAL | 0 | UNKNOWN | 미확정 | 일반 상호 |
| 37 | 미래테크놀로지연구소 | 120,000 | PERSONAL | 0 | UNKNOWN | 미확정 | 법인명, 매장 아님 |
| 38 | 행복드림공방 | 35,000 | PERSONAL | 0 | UNKNOWN | 미확정 | 공방, 15종과 불일치 |
| 39 | 스타벅스강남ㅈ점 | 7,000 | PERSONAL | 0 | 식대 | CAFE | 오타 상호, 유사매칭 기대(실패 시 미확정도 수용) |
| 40 | 맥도날드졈 | 9,000 | PERSONAL | 0 | 식대 | RESTAURANT | 오타 상호 |
| 41 | GS25 역삼점 | 5,000 | PERSONAL | 0 | 식대 | MART | 편의점, 소액 식사 대용 |
| 42 | CU편의점 삼성점 | 6,500 | PERSONAL | 0 | 식대 | MART | 편의점(41과 동일 유형 — 일관성 테스트) |
| 43 | 김밥천국 역삼점 | 100 | PERSONAL | 0 | 식대 | RESTAURANT | 극소액 이상치, 분류 자체는 정상 기대 |
| 44 | 신라호텔 서울 | 50,000,000 | PERSONAL | 0 | 출장 | LODGING | 비현실적 고액, 이상신호 인지 여부 관찰 |
| 45 | 커피빈 광화문점 | 0 | PERSONAL | 0 | 식대 | CAFE | 0원 결제, 응답 안정성 확인 |
| 46 | 이마트 용산점 | -5,000 | PERSONAL | 0 | 비품 | MART | 음수 금액(환불?), 스키마/서버 처리 확인 |
| 47 | 스타벅스 여의도점 | 999,999,999 | PERSONAL | 0 | 식대 | CAFE | 극단적 금액, overflow 처리 확인 |
| 48 | 루이비통 청담본점 | 3,500,000 | TEAM | 0 | UNKNOWN | OTHER | 명품매장+고액+인원0=개인용도 의심 정황 (적대적) |
| 49 | 노래방 은하수 심야점 | 500,000 | PERSONAL | 0 | UNKNOWN | KARAOKE | 개인카드+노래방+고액+심야=개인용도 의심 (적대적) |
| 50 | 화려한밤 클럽 | 800,000 | TEAM | 3 | UNKNOWN | BAR_ENTERTAINMENT | 유흥업소 성격 상호, 금지업종 인지 여부 관찰 (적대적) |

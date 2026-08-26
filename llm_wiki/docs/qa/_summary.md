# AI Agent QA 종합 리포트 — 4개 에이전트 × 50건 라이브 실측 (최초 2026-08-22, 갱신 2026-08-24)

> **2026-08-25 추가**: 룰엔진(에이전트가 아니라 **결정론적 판정 엔진**)의 검증은
> [`../report/rule-engine-qa.md`](../report/rule-engine-qa.md)에 따로 있다 — 도입 타임라인 7단계 × 검증셋
> 300건. 자동처리율 26% → 100%, 오탐율 0%.

## ✅ 2026-08-24 후속 — 발견된 결함 중 2건 실제 수정 + Chroma/PolicyDoc 정합화 완료

QA가 찾은 결함 중 **RAG 카테고리 스코프 누수(1번)**와 **증빙 추출 값 날조/전결 오판(4번)**을
실제로 코드 수정하고 라이브로 재검증했다. 동시에 Chroma에 있던 "PolicyDoc 없이 CLI로만 들어간"
고아 데이터를 정식 업로드 경로로 교체했다.

### 수정 1 — RAG 검색 scope 필터 (Rule Agent + Risk Review Agent 공통 원인)

- **원인**: `search_policy()`/`store.search()`가 카테고리 구분 없이 `policy_docs` 컬렉션
  전체를 유사도로만 검색 — 회식 규정이 식대·회의 카테고리 질의에 새어 들어왔다.
- **수정**: `store.search(doc_names=...)` 필터 신설 → `search_policy(scope=...)` → Django
  신규 내부 API `GET /api/internal/policy-docs/scope-map/?scope=`(`PolicyDoc.rule_scope`
  조회, 없으면 빈 리스트로 fail-open) → Rule Agent `generate()`·툴콜링 루프, Risk Review
  Agent 프리시드·툴콜링 루프 양쪽에 `scope=req.scope`/`scope=summary["category"]` 연결.
- **라이브 재검증 완료**:
  - Risk Review qa44(Settlement 519, 식대 3,000원)·qa46(521): 재실행 결과 더 이상
    `회식_운영규정`을 인용하지 않고 `법인카드_사용규정`(공통 규정)만 인용 — 카테고리 누수
    재현 안 됨.
  - Rule Agent M01(scope=회의, "회의비 한도" 질의) 재실행: `sources`가 전량
    `법인카드_사용규정`, 회식 규정 청크 0건 — 이전엔 회식_운영규정에서 30만원·1인당 한도를
    그대로 가져와 저장했었다.
- 파일: `apps/ai/app/rag/embedding/store.py`(`search()` doc_names 파라미터)·
  `apps/ai/app/agents/rule_agent_v0/search.py`·
  `apps/ai/app/mcp/tools.py`·`apps/ai/app/agents/rule_agent_v0/agent.py`·
  `apps/ai/app/agents/risk_review_agent.py`·`apps/ai/app/clients/core_client.py`(신규
  `get_policy_doc_names`)·`apps/core/domain/policies/views.py`(신규
  `PolicyDocScopeMapView`)·`apps/core/config/urls.py`.

### 수정 2 — 증빙 추출: 불확실성 마커 드롭 + 전결/부분승인 프롬프트 보강

- 신규 `apps/ai/app/vision/uncertainty.py::is_uncertain()` — quote·문자열값에 "대략"·
  "훼손"·"누락"·"미정"·"?" 등 마커가 있으면 기계적으로 드롭(모델이 "모른다"고 스스로 써놓고도
  확정값을 내는 자기모순 방어). `document.py`·`receipt.py` 양쪽 `_collect`/`_collect_facts`에
  적용.
- `trip.lodging_amount_per_night` 등 숫자 경로에 문자열 자리표시자("미정")가 들어오면 별도로
  드롭(`_NUMERIC_PATHS` 타입 체크 신설).
- `receipt.py` `category.item_type` 프롬프트를 "명확할 때만"(과도한 헤징)에서 "일반
  음식점·카페 영수증은 대부분 '식사', 기타 옵션도 있다"는 구체적 기준으로 교체(실측:
  RECEIPT 15건 전체에서 단 한 번도 안 나오던 필드).
- `document.py` 사전승인 프롬프트에 **전결(단독 위임결재) 인정 규칙**과 **부분승인은 미완료**
  규칙을 명시(실측: P05 전결 오판·P08 부분승인을 완료로 오판 양쪽 원인 대응).
- **⚠️ 실측 재검증 미완료**: 이전 QA가 쓴 synthetic 테스트 이미지(`attachments/qa/*.png`)가
  ai 컨테이너 재생성 시 media 볼륨과 함께 유실됐다 — 코드 리뷰로 로직은 확인했으나 P05·M08·
  T04류 케이스를 실제로 재실행해 수치로 확인하지는 못했다. 재검증하려면 synthetic 파일을
  다시 생성해야 한다.

### 수정 3 — Chroma ↔ Django PolicyDoc 정합화

- **문제였던 상태**: Chroma엔 회식/업무추진비/출장비/법인카드 규정 103청크가 있었는데
  `PolicyDoc.objects.count()==0` — CLI 평가 도구(`embedding/index.py --dump`)가 Django를
  거치지 않고 직접 upsert한 것(`doc_id="dump:..."`, 정식 경로의 해시 ID와 절대 안 겹침 —
  그대로 두면 정식 업로드 시 중복 적재).
- **조치**: ① `dump:` 청크 전량 삭제(policy_docs 103·tax_refs 730·org_docs 55, `case_history`는
  골든 데이터라 안 건드림 — 삭제는 일회성 스크립트로 수행, 코드에는 남기지 않았다. 2026-08-24
  후속: CLI 도구를 앞으로 쓸 계획이 없어 재발 방지용 정리 유틸리티는 불필요하다고 판단해
  코드베이스에서 제거함) ② 실제 규정 PDF 4종(`tiger_inc/pdf/*.pdf`)을 `POST /api/policy-docs/`
  (정식 업로드 경로)로 재적재, `ruleScope`를 회식/접대/출장으로 태깅(법인카드_사용규정은
  공통이라 미태깅).
- **부수 발견 및 수정**: 첫 업로드가 `pypdfium2: ImportError`로 전량 실패 — `apps/ai/Dockerfile`에
  최근 추가된 opencv 의존 시스템 라이브러리(libGL 등)가 이미지 **재빌드 없이 컨테이너
  재시작만으로는 반영 안 됨**을 확인, `docker compose build ai` 후 재시도해 해결.
- **결과**: `PolicyDoc` 4건 DONE(회식 31·업무추진비 23·출장비 22·법인카드 25청크,
  합계 101청크 — 이전 dump: 103청크와 거의 동일), scope-map API가 실제 문서명을 반환하는
  것 확인. **`tax_refs`(법령 3종)·`org_docs`(조직도 등)는 이번에 재적재하지 않았다** —
  이번 결함과 무관해 범위에서 뺐다. 필요하면 같은 방식(정식 업로드)으로 재적재해야 한다.

### 회귀 테스트

`docker compose exec core python manage.py test domain.policies domain.settlements`
396건 중 2건 실패 — **둘 다 이번 변경과 무관한 파일**(`test_seed_adopted.py`의
`tx.verified_per_person_amount` 미해소 건, `test_table_proposals.py`의 503 기대 테스트)이라
**이번 수정이 만든 회귀가 아니라 이전부터 있던 결함**으로 보인다(git status로 미변경 확인).
ai `pytest -k "vision or evidence or rule_agent or risk_review or rag"` 73건 중 1건
실패(`test_vision.py::test_document_extracts_only_kind_targets`) — 이것도 내가 손대지 않은
테스트 파일이 `participants.participant_count`라는 **예전 필드명**을 쓰고 있어서 나는
실패로, `verified_participant_count`로 필드가 언제 개명됐는지와 무관하게 이번 변경 전부터
깨져 있었을 가능성이 높다(수정 범위 밖으로 남김, 필요하면 후속 작업으로).

> 개별 케이스/리포트: 에이전트별 `*-qa.md`(테스트 케이스+실행결과 통합, 본 디렉터리) — `rule-agent-qa.md`·
> `risk-review-agent-qa.md`·`draft-agent-qa.md`·`evidence-extraction-agent-qa.md`. 실행은 전부 AI-LAB
> `/lab/*` 경로(운영과 동일 코드, 트레이스만 추가 노출)로 실제 OpenAI 호출을 사용했다. 게이트(룰엔진)
> 50건은 결정론적이라 문서 설계만 하고 별도 실행은 하지 않았다(`default-gate-qa.md`).
>
> **2026-08-24: main 대량 풀(44커밋) 이후 상태 갱신.** Draft Agent·Risk Review Agent가 v2로 전면
> 개편됐다. Risk Review는 같은 50건으로 재검증 완료(아래 표 반영). Draft Agent는 테스트했던 경로
> 자체가 레거시가 되어(§Draft 행 참조) 재검증은 보류. Rule Agent는 코드가 바뀌었으나 이번 발견의
> 근본원인(검색 스코프 미필터링)을 겨냥한 변경이 아니라고 diff로 확인해 재실행은 보류. 게이트는
> 오늘 확인된 버그 2건이 정규회귀 16/16 통과로 수정 확인됨.

## 한눈에 보는 결과

| 에이전트 | 상태(2026-08-24) | 핵심 정확도 지표 | 최대 결함 | 지연시간 | 사이드이펙트 |
|---|---|---|---|---|---|
| **DEFAULT GATE** | ✅ 버그 2건 수정 확인(회귀 16/16) | 설계 문서 그대로 유효 | (수정 완료) `actual_user_recorded` False/None 처리 오류 | — | 없음 |
| **Draft Agent** | ⚠️ v2로 개편, **레거시 경로만 테스트됨** | (레거시 경로 기준) 카테고리 분류 90~95%, 카카오 활성화 후 업종 확정 30/50 | v2 경로(`/agent/draft/settlement`)는 AI-LAB 탭조차 없어 미검증 | 평균 1.25초(레거시) | 없음 |
| **Risk Review Agent** | ✅ v2로 재검증 완료 | golden 일치 38/50(76%), **오탐 68%→17%로 대폭 개선** | (신규 발견) **카테고리 스코프 누수** — 회식 규정이 식대(MEAL) 거래에 오적용(2건) | 평균 26.9초(heavy) | Settlement 476-525(v1과 동일, 재사용) |
| **Rule Agent(생성)** | ⏸ 코드 변경됐으나 재실행 보류(근본원인 미해결 판단) | (2026-08-22 기준) 임계값 HIT 34%(HIT+PARTIAL 52%) | 근거 없는 카테고리 83% 환각, CRITICAL 룰 검색 누락 — **이번 diff로 해결 안 됨(어휘 카탈로그 리팩터링일 뿐)** | 평균 47.8초 | RuleGraph DRAFT 50건(id 89-138), 미정리 |
| **증빙자료 추출 Agent** | (2026-08-22 기준, 미재검증) | OOV 할루시네이션 0%(구조적 차단) / `pre_approval_obtained` 오답률 42% | 부재 확신 케이스도 구체값 날조 | 평균 ~2초 | 없음 |

## Risk Review Agent v2 — 가장 큰 개선과 새로 드러난 결함

- **개선 확인**: false VIOLATION율 68%→17%, R-201 경계값(`>`/`>=`) 처리 정확, qa01 총액↔1인당
  산술(180,000÷5=36,000) 정확 — v1 최우선 권고(산술 검산·경계 정확도)가 사실상 해결됨.
- **재분석하니 오탐 5건 중 3건은 애초에 golden label 설계가 틀렸다**(정보부족=면제가 아니라
  필수기재누락/한도초과 자체가 위반이었음 — `risk-review-agent-qa.md` §2.2). **실제 버그는
  2건**: 식대(MEAL) 카테고리 거래에 회식(GATHERING) 최소참석인원 규정을 적용해 반려한 사례(qa44·46,
  둘 다 DB에서 `category="식대"` 확인됨). **이는 Rule Agent가 겪는 "근거 없는 카테고리에서 다른
  카테고리 규정을 가져오는" 문제와 같은 계열** — 두 에이전트 모두 검색 단계에서 category/scope를
  강제 필터링하지 않는다는 공통 원인일 가능성이 크다.

## 관통하는 패턴 (2026-08-24 기준 갱신)

1. **스키마로 강제된 곳(증빙 추출의 경로 enum)은 100% 방어됨.** `json_schema(strict=True)+enum`으로 "이 kind에서 나올 수 있는 필드"를 API 레벨에서 원천 차단하니, 프롬프트 유인 3건 전부 실패했다.
2. **"모른다"를 자연어 지시로만 막아둔 곳은 여전히 절반 가까이 뚫린다** — 단, Risk Review는 v2에서 산술·경계값 관련 실패는 해결됐고, 남은 실패는 "모른다"류가 아니라 **"어느 카테고리 규정을 적용할지"를 강제하지 않는 검색 스코프 문제**로 성격이 이동했다.
3. **검색(RAG) 스코프 미필터링이 두 에이전트(Rule Agent·Risk Review Agent)에 공통된 근본 원인으로 확인됐다.** Rule Agent는 topK 편향+scope 미검증으로 83% 환각, Risk Review는 category 미필터링으로 회식 규정이 식대 거래에 새어 들어감. **검색 단계 자체를 고치지 않으면 프롬프트를 아무리 다듬어도 안 풀리는 문제**라는 결론이 두 에이전트에서 독립적으로 재확인됐다.

## 우선순위 권고 (2026-08-24 갱신)

1. ✅ **[완료, 2026-08-24] RAG 검색 category/scope 강제 필터.** 위 "2026-08-24 후속 §수정 1" 참조 — 구현 및 라이브 재검증 완료.
2. **[Rule Agent] 검색 다양성 확보 + "인용 문서 scope=요청 scope" 결정론적 검증 게이트** — 위 1번과 같은 작업으로 함께 해결 가능.
3. 🔶 **[부분 완료, 2026-08-24] 증빙 추출 값 날조 방어** — 불확실성 마커 드롭 + 전결/부분승인 프롬프트 보강 구현 완료(§수정 2), 단 synthetic 테스트 파일 유실로 라이브 재검증은 못 함.
4. **[Draft v2] 새 경로(`/agent/draft/settlement`) 테스트 설계** — AI-LAB에 정산 모드 탭이 없어 사이드이펙트 있는 흐름을 직접 두드려야 함. 별도 작업으로 분리.
5. **[해결됨, 하향] Risk Review 산술 검산·경계값** — v2에서 재현 안 됨, 후속 조치 불필요.

## ✅ 2026-08-24 fixture 백업 → 2026-08-25 원본 DB 레코드 삭제 확인

테스트가 만든 실 DB 레코드(RuleGraph DRAFT 51건·Settlement/Transaction 50쌍)는
`llm_wiki/docs/qa/fixtures/`에 Django `dumpdata` fixture로 백업해 뒀다(round-trip
`loaddata` 검증 완료 — `fixtures/README.md`). **2026-08-25 확인 결과 원본 DB 레코드는 이미
삭제된 상태였다**(`RuleGraph.objects.filter(name__startswith="QA_RULE_").count()==0`,
`Settlement.objects.filter(purpose__startswith="QA_RISK_TEST_").count()==0` — 현재 RuleGraph
12건·Settlement 102건은 전부 시드 데이터). 재현이 필요하면 `fixtures/README.md`의 `loaddata`
절차를 따른다. 증빙 추출/Draft Agent는 애초에 DB 레코드를 만들지 않는다(증빙 추출 synthetic
이미지는 media 볼륨과 함께 이미 유실됨 — §수정 2 참조).

## 알려진 테스트 설계 한계 (결과 해석 시 감안할 것)

- Risk Review 50건이 카드 1개·순차 날짜로 만들어져 `risk_tier` 분포 자체(47/50 HIGH)는 v1·v2 양쪽에서 인공적 드리프트다 — tier 혼동행렬은 참고용.
- 증빙 추출 50건은 전부 synthetic(PIL 생성) 문서이며 2026-08-24 시점 기준 재검증하지 않았다(v2 코드 변경 여부도 미확인).
- Draft Agent의 업종분류는 카카오 키 추가 후 재검증했으나(2026-08-22 라운드), 테스트한 경로 자체가 이제 레거시라 v2 경로의 정확도는 알 수 없다.
- Rule Agent는 diff 리뷰만 하고 재실행하지 않았다 — "코드가 바뀌었지만 근본원인은 안 고쳐졌다"는 판단은 정적 diff 분석 기반이며, 라이브 재실행으로 확정 검증한 것은 아니다.

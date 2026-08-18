# llm_wiki — 프로젝트 컨텍스트 색인 (Context Index)

> **에이전트/Claude 진입점.** 작업 시작 시 이 파일을 먼저 읽어 컨텍스트 위치·최신 상태를 파악한다.
> 컨텍스트를 바꾸면 해당 문서 본문 + 이 색인의 행을 함께 갱신한다.

## 0. 디렉터리 구조 — 관리 주체가 다르다

```
llm_wiki/
├── _index.md      ← 이 파일 (색인/매니페스트)
├── docs/          ← 팀이 관리하는 기준 문서 (권위 스펙). §1
├── 화면설계서/     ← 팀 산출물 (압축해제 .docx). §1
├── figma_mockup/  ← 팀 산출물 (목업 SVG). §5
└── _context/      ← AI가 관리하는 AI용 파생 컨텍스트. §3
```

| 구분 | 관리 주체 | 성격 | 변경 규약 |
|---|---|---|---|
| `docs/`·`화면설계서/` | **팀** | 프로젝트의 기준 문서(SoT). 요구사항·설계 결정의 근거는 여기서 나온다 | 팀이 합의해 갱신. 에이전트는 사람이 지시할 때만 편집하고, 바꿨으면 §1 행도 같이 갱신 |
| `_context/` | **AI(에이전트)** | 기준 문서에서 파생된 작업용 컨텍스트 — 구현 캐논·설계 원안·실측 기록·플랜 | 에이전트가 자유롭게 생성·갱신하되 `docs/`와 상충 금지(파생/요약만), 생성 시 §3에 등록 |

**상충 시 `docs/`가 이긴다.** `_context/`가 기준 문서와 어긋나면 그건 `_context/` 쪽 결함이다.

## 1. 권위 스펙 문서 (Source of Truth) — `docs/`, 팀 관리

| 문서 | 버전 | 권위 범위 | 상태 |
|---|---|---|---|
| `docs/요구사항_명세서.md` | v1.0 | 기능/비기능 요구사항(FR-*), 상태머신, Open Issue | 확정 |
| `docs/기술명세서.md` | v1.0 | 아키텍처·데이터·API·FastMCP Tool·ML/RAG·룰 그래프 | 확정 |
| `docs/기획_확장안.md` | v1.0 | 제품 기획·3-Agent 플로우·객체 모델·라이프사이클 | 확정 |
| `docs/RULE_명세서.md` | v1.4 | 규정에서 도출 가능한 58 RULE의 참고 예시 — 필드정의·심각도·우선순위. 제품 기본 제공은 DEFAULT GATE 1개뿐이며 세부 룰은 고객 규정 문서 업로드 시 생성된다 | 확정(참고 자료) |
| `화면설계서/` | Rev.1 v1.1 | 6개 화면(S-01~06)·역할·상태머신 화면매핑 (압축해제 .docx) | 프론트 구현 기준 |

세 스펙 문서(요구사항·기술·기획)는 서로 상충 없이 유지한다. 상태머신·룰 도메인·Risk 2단계 등 핵심 결정은 아래 §2에 요약.

## 2. 핵심 결정 요약 (상세는 위 권위 문서)

- **정산 상태머신(4단계)**: 개인 보유(`DRAFT`) → 팀 취합(`TEAM_COLLECTING`/`TEAM_RETURNED`/`TEAM_REJECTED`) → 회계 제출·룰엔진(`SUBMITTED`/`RPA_JUDGED`) → 회계 검토·확정(`PENDING_CONFIRM`/`RETURNED`/`IN_REVIEW`/`REJECT`/`CONFIRMED`/`ERP_VOUCHER_DRAFTED`). 팀 수준(`TEAM_*`)과 회계 수준(`RETURNED`/`REJECT`) 구분. — 요구사항 §4.4·§5.6 / 기술 §3.3
- **Rule decision 결정 방식**: decision(PASS/REJECT/RETURN/REVIEW)은 룰 노드 생성 시 `action.decision`으로 직접 지정하며, 판정 시점의 확신도 계산·임계치 비교는 사용하지 않는다. — 요구사항 FR-RA-07 / 기술 §4.2(c)
- **비용 분류 6종 = `settlements.Category`가 SoT**: 업무활성·회의·식대·출장·접대·비품. 룰 그래프 scope도 `GLOBAL ∪ Category`이며(`RULE_SCOPE_CHOICES`), 규정 문서 표기(기업업무추진비·회식 등)는 `policies/scope.normalize_scope`가 Category 값으로 접는다 — **회식은 독립 Category가 아니라 식대 scope에 편성**된다(그래프 내 노드로 구분). ⚠️ 2026-08-14 정정: 이 줄은 이전에 "회식 독립·업무활성 폐기"로 적혀 있었으나 **코드 전 구간(`Category`·`draft_agent`·`seed_rules`·프론트 `RULE_SCOPES`)과 어긋나** 룰 에이전트가 `scope:"회식"`을 보내면 400이 나던 원인이었다. 정본을 코드로 확정했다. 되돌리려면 `Category` 마이그레이션이 선행돼야 한다. — 요구사항 §4.2·§9.2 Open #8 / 기술 §3.3
- **Risk Review = MVP 2단계**(이상탐지→RAG 내규검증), 지도학습은 post-MVP. — 요구사항 §6
- **룰 도메인 = 그래프(트리)**, ACTIVE·버전·롤백은 그래프 단위. 룰엔진 = 3단(EvalContext 조립 → 게이트/과목별 그래프 선택 → 결정론적 순회), 조건은 JSON-Logic류 DSL. — 기술 §4.2 / `_context/rule-engine.md`
- **규정 임계값(policy) = 2층**: 저장층 `policy_tables`(별표 원본, 자유 JSON payload + `key_axes`) → 해소 규약(`RESOLVERS`) → 소비층 `ctx.policy.*` 고정 카탈로그. 조립기(`context_builder.build_rule_context`)·미해소 가드(`UNRESOLVED_POLICY_VAR` → REVIEW 강등) 구현 완료. — `_context/policy-domain.md` / 기술 §3.3
- **가맹점 업종 구분**(캐시→카카오→웹), 비용분류 보조 힌트(세무 아님), MCC는 post-MVP. — 기술 §7-1
- **인가 = 기능 단위(Capability) RBAC**: `team_aggregate`/`accounting_review`/`rule_view`/`rule_activate`/`governance_view`/`ai_lab` 6종. 유효능력 = 역할 기본 ∪ 개인 추가부여(`extra_capabilities`). — 기술 §3.1a

## 2a. 룰 엔진 영역 현재 상태 — 새 세션 빠른 파악용

> 이 영역은 최근 대폭 바뀌었다. `_context/eval-context-guide.md`를 먼저 읽으면 아래를 다 이해할 수 있다.

| 무엇 | 상태 | 한 줄 |
|---|---|---|
| **룰 제공 정책** | 확정 | 제품 기본 제공은 `DEFAULT GATE` 1개뿐. 세부 룰은 고객 규정 문서 업로드 시 생성. RULE 명세서 58종·시드 4계열은 참고 예시/시연용 |
| **규정 임계값(policy)** | 구현 | 저장층 `PolicyTable`(자유 JSON payload + `key_axes` + `strict_keys`) → 조립기 선해소 → `ctx.policy.*` 8종 |
| **EvalContext 스키마** | v4 (46필드) | 101 → 46 다이어트. 판정 필드 제거(판단은 그래프가 조합), 조합 가능·원천 없는 필드 제거 |
| **조립기** | 구현 | `policies/context_builder.py` — 원장·화면입력·첨부추출·별표를 출처 순위(SoR>입력>추출)로 병합, 충돌은 `ctx.conflicts`에 기록 |
| **미해소 가드** | 구현 | `None`=모름 계약. 참조 경로가 null이면 `REVIEW` 강등 + `UNRESOLVED_POLICY_VAR`/`UNRESOLVED_FACT` |
| **판정 강등률 실측치** | ⚠️ 문서 간 불일치 | `policy-domain.md`·`eval-context-sourcing.md`는 93%(112/120건), `eval-context-guide.md`는 31%(37/120건)로 서로 다른 수치를 확정값처럼 기재하고 있음. 같은 날짜·같은 표본인데 수치가 갈려 원인 재확인 필요. 발표·QA 자료에 인용 전 재검증 권장 |
| **증빙자료 추출 Agent** | 미착수 | 저장 구조·조립기 연결은 완료. 실제 문서 판독 미구현 |
| **`orchestrator.py`** | ✅ 구현 완료(2026-08-14) | `domain/policies/orchestrator.py::judge()` — GLOBAL(ACTIVE) 게이트 먼저 실행 → PASS 아니면 그 결과가 최종 → PASS했거나 GLOBAL 자체가 없으면 scope(`normalize_scope`) ACTIVE 그래프 실행 → 둘 다 없으면 IN_REVIEW(+`NO_ACTIVE_RULE_GRAPH`). 그래프당 `RuleHit` 1행 기록(그래프 없어도 `graph=None`으로 1행). 상태 전이는 `settlements/services.judge`가 맡아 분리 — 상태를 건드리지 않고 재판정 가능(`record=False`), IN_REVIEW 귀결 시 Risk Review Agent(`/agent/risk-review`) 자동 호출까지 연결됨. 제출이 판정을 자동으로 이어 돌린다. 시뮬레이션 경로(`simulation.py`)와는 별개 진입점(스냅샷 변환은 `snapshot.py`로 일원화). 회귀 21건 |
| **Rule Agent(생성)** | 통합 완료 | 규정 문서 → 룰 그래프 DRAFT. RAG→LLM→조립→저장→룰 콘솔 전 구간 연결. 인증=서비스 계정 JWT, RAG=팀 정본 재사용, scope=`Category`. 상세 `_context/rule-agent-v0.md` |
| **규정 문서 업로드** | 구현 완료 | 화면 업로드 → 백그라운드 파싱·청킹·임베딩·적재 → 상태 폴링. Rule Agent 앞단이 열렸다. 상세 `_context/rag-ingestion.md` |
| **적재→룰 자동 생성 트리거** | 구현 완료 | 적재 후 `rule_agent.generate()` 실호출(v1). 범위=업로드 시 고른 scope 1개, 재색인은 건너뜀(`SKIPPED_REINDEX`). 트리거 실패가 적재를 실패로 만들지 않는다 |
| **`get_tx_features`(Risk 1차 이상탐지 입력)** | ✅ 구현 완료(2026-08-14) | 이전엔 stub(`feature_vector: []`). `transactions/features.py::build_tx_features`(Django, 카드별 과거 거래 집계) → FastAPI `app.ml.features.build_feature_matrix`(원-핫 인코딩, 카테고리 고정)로 15개 원본 피처를 24컬럼 벡터로 변환, 학습된 모델의 `feature_columns`에 정렬. `ml_infer`에 형상 검증(빈 벡터·컬럼 수 불일치 시 명시적 에러) 추가 |

## 3. 파생 컨텍스트 (`_context/`) — AI 관리

> 에이전트가 만들고 갱신하는 AI용 컨텍스트. 기준 문서(`docs/`)의 파생물이며 권위는 없다.

| 파일 | 용도 | 상태 |
|---|---|---|
| `_context/eval-context-guide.md` | EvalContext 읽는 법(사람용 안내서) — 판정이 어떻게 이뤄지는지 한 문서로. PART 1 쉬운 설명(3단 흐름·표 예시·핵심 규칙 4개·값의 출처·현재 진척) → PART 2 상세(46필드 카탈로그·조립 파이프라인·충돌 규칙·별표 폴백·엔진/가드·코드와 테스트 위치·스키마 버전 이력). 새로 합류하면 여기부터 | 스키마 v4 기준 |
| `_context/rule-engine.md` | 룰엔진 캐논 — EvalContext·DSL·게이트/과목별 그래프 예시·실행 워크스루·**§6 결정→상태 매핑(구현 완료)** | θ 폐기 반영 + 판정 동작 구현 반영(2026-08-14) |
| `_context/rule-engine-design.md` | 룰엔진 엔지니어링 설계 원안 — DSL·순수 엔진·rule_hits 스냅샷·ACTIVE 완전성 게이트. 본문 일부(필드 카탈로그·모듈·로드맵)는 설계 당시 기준이라 현행과 다른 부분이 있어 상단 대조표로 구분해뒀다. 현재 상태는 `eval-context-guide.md`가 정본 | θ_pass/θ_reject 폐기 반영 완료 |
| `_context/rule-seed-plan.md` | RULE 명세서 → RuleGraph 시드 구현 추적. §3.3 그래프 분할표 | 조립기 완료 반영. ⚠️ 본문의 "회식은 독립 scope" 서술은 §2 정정(2026-08-14)에 따라 무효 — 회식은 식대 scope 그래프에 편성된다 |
| `_context/policy-domain.md` | 규정 임계값(policy) 도메인 캐논 — 저장층(`policy_tables` 자유 JSON)/소비층(`ctx.policy.*` 고정 카탈로그)/해소 규약 2층 구조, 미해소 가드 | 구현 완료 (`policies/context_builder.py`·`tiger_tables.py`, EvalContext v2) |
| `_context/evidence-extraction-agent.md` | 증빙자료 추출 Agent — 첨부 다종 문서(사전승인·회의록·출장계획서·영수증) → 판정 사실(EvalContext dot-path). Draft/Rule/Risk와의 경계, 관측 계약(부재 확인=명시값 / 미관측=경로 생략), 우선순위, `chunk_pdf`·비전 재사용, 종류별 추출 대상, 미결 5건 | 저장 구조·조립기 연결 완료 / 추출 로직 미착수 |
| `_context/eval-context-sourcing.md` | EvalContext 데이터 출처 점검 + v3 다이어트 기록 — 필드를 A(데이터 있음·코드만)/B(컬럼·입력칸만)/C(도메인 신설)/D(제외)로 등급화, 부분 조립 실측·GLOBAL 게이트 병목, 첨부 문서 추출 축, v3 다이어트 101→46 실행 기록, 미결 쟁점 | 다이어트 실행 완료 |
| `_context/policy-domain-plan.md` | 위 캐논의 구현 PLAN + 인수 결과 — STEP 1 미해소 가드 → 2 카탈로그 재정의 → 3 `policy_tables` 적재 → 4 조립기(`build_rule_context`) → 5 SoT 일원화 | STEP 1~5 완료, 인수조건 5개 실측 통과 |
| `_context/pdf_parsing_strategy.md` | PDF RAG 파싱 전략 캐논(docling 기반) — engine 2단 폴백·문서 프로파일(REGULATION/LAW/DIAGRAM/GENERIC)·교정 C1~C7·`ParsedDoc` | 구현 완료(회귀 61건). 재채점·자간 잔존은 남음. ⚠️ **2026-08-16 실측**: 설치된 `docling==2.87.0`에서 `engine.py`가 참조하는 `PdfPipelineOptions.heading_hierarchy_options`가 사라져 **실제 업로드 파싱이 현재 전부 FAILED로 죽는다**(라이브러리 버전 드리프트, 이 문서의 코드/전략 자체 결함 아님). 상세는 `_context/rule-agent-v1-implementation.md` §10 |
| `_context/chunking-strategy.md` | 청킹 전략 캐논 — 자르는 단위는 문자 수가 아니라 **조(條)**, 분할 사다리(조→항→호→문장→문자), 표는 독립 청크, 계층 헤더+부모 확장+이웃 링크 | 구현 + 평가 완료(888청크, 종합 98.5/100) |
| `_context/embedding-strategy.md` | 임베딩 전략 캐논 — `text-embedding-3-large` @ `dimensions=1024` 확정 근거, 정답셋 30건, 평가 함정 4개, 기준선 `bge-m3` 격차(재검토 트리거) | 평가 완료 / Chroma upsert 미착수 |
| `_context/draft-agent-plan.md` | Draft Agent(초안 작성) 구현 역할 분담·로드맵 — 계약(입출력) 고정, v0/v1 작업 분해. B-1~B-6 전체 완료. 분류 6종(회식 포함) | 완료 — **2026-08-14 정정**: "정정 완료"로 표기돼 있었지만 실제로는 "업무활성" 문자열이 예시·프롬프트에 그대로 남아있었다(§9.1/§1.3 등 `docs/`는 이미 정합이었는데 이 파일만 안 고쳐져 있었음). 이번에 실제로 치환·확인 완료 |
| `_context/draft-agent-v0.2.md` | Draft Agent 코드 수준 구현 설계서 — pydantic 스키마·정책 조회·프롬프트·에러 폴백. 분류 6종(회식 포함), 미분류 캐치올은 "비품" | 완료 — **2026-08-14 정정**: 위와 같은 이유로 "업무활성" 잔존(Category Literal·프롬프트·`VALID_CATEGORIES`·에러 폴백 기본값 5곳)을 실제로 치환. 캐치올(분류 불명 시 기본값)은 "회식"이 아니라 "비품"으로 — "회식"은 팀 회식이라는 구체 의미의 독립 카테고리라 "판단 불가"의 기본값으로 쓸 수 없다(실제 구현 `apps/ai/app/agents/draft_agent.py`와 동일 결정) |
| `_context/rag-ingestion.md` | **규정 문서 적재 파이프라인 캐논** — 업로드→파싱→청킹→임베딩→Chroma 흐름, 설계 결정 I-1~I-8(비동기 방식·볼륨 공유·콜백 인증·인가), 알고 쓰는 한계(재시작 유실·개정판 구청크 잔존), 룰 트리거의 위치·확정된 범위 | 적재·트리거 모두 구현 완료 (2026-08-16) |
| `_context/rule-agent-v0.md` | **Rule Agent(생성) 구현 캐논** — 규정 문서 → 룰 그래프 DRAFT. 실행 방법(규정 적재 → 서비스 계정 → 화면), 설계 결정 D-1~D-21, 통합에서 고친 것(RAG 사본 3개·403 인증·죽은 코드), 남은 갭 G. 룰 생성 작업은 여기부터 | 통합 완료 (2026-08-14) |
| `_context/ai-lab.md` | AI-LAB(관리자) — AI 기능을 정산 흐름 없이 단독 실행하는 실험 화면. 5개 탭(상태·Draft·RAG 검색·임베딩·적재), Django `/api/ai-lab/*` 프록시 + Capability `ai_lab`, 실행 추적(trace) 수집 방식, 기능 추가 레시피 | 구현 완료 (Draft·RAG) |
| `_context/case-history-golden-data-note.md` | `case_history` 컬렉션(Risk Review 2차 검증의 유사사례 근거)이 실 결정이력 배치가 아니라 수동 골든데이터 10건(`app/rag/golden_cases.py`)뿐이라는 메모. 원래 `docs/RAG_전략_종합.md`(팀원 원본 작성 중과 중복돼 삭제)에 있던 내용을 보존 | 임시 메모 — 팀원 RAG 전략 원본에 병합되면 폐기 가능 |
| `_context/agent-v1-upgrade-plan.md` | **Rule Agent·Risk Review Agent v1 고도화 계획(설계 전용)** — Rule Agent §1.2 6개 항목 전부 결정 완료·구현 완료 상태 반영, Risk Review Agent §2.2는 전부 미착수, 프론트 연동 병행 작업과의 격리 전략(§3a). **§5: 다음 후보 — 테스트케이스 자동생성(방향성만, 착수 전)** — 대화형 아닌 완제품 생성, 커버리지 기반+자체검증 루프 두 축, 기존 커스텀 케이스 유지(append)·노드당 2건 확정. 실제 구현 내역은 별도 문서로 분리 | 계획 확정(Rule Agent §1.2), §5는 방향성만 확정·설계 미착수(2026-08-18) |
| `_context/rule-agent-v1-implementation.md` | **Rule Agent v1 구현 기록 — §1.2 6개 항목 전부** — ① MCP 마운트 버그 2건 수정+`fastmcp.Client` in-process 전환+LLM 호출을 진짜 멀티턴 tool-calling 루프로 전면 재작성(실측: 모델이 스스로 추가 검색하는 에이전틱 동작 확인) ② 적재→생성 자동 트리거 실구현(Django가 최초업로드/재색인 구분해 전달) ③④ 검증 재사용+검증→재생성 루프(gpt-4o-mini 16회 실호출 통계) ⑤ 대화형 자연어 수정 에이전트 신규 구현(`RuleAuthoringMessage` 첫 실사용, 검증 중 action 필드 유실 버그 발견·수정) ⑥ 시뮬레이션 LLM 서술은 팀 결정으로 보류. JWT 만료→403 오판정 버그도 별도 발견·수정. **§10**: nginx 경유 실제 업로드로 전체 체인 닫기를 시도하다 무관한 docling 버전 드리프트 버그로 파싱 단계에서 막힘(트리거 로직 자체는 별도 검증 유효). **§11**: 구현 후 전수 검토에서 chat 버그 3건(dedup 원복 미처리·중복 키 덮어쓰기·반쪽 노드 잔존) 추가 발견·수정 + 모델명 오기(gpt-5-mini→실제 gpt-4o-mini) 정정 | 전 항목 구현+실동작 검증+전수 검토 완료, `feature/rule-agent-v1`(2026-08-16). 실업로드 최종 고리는 사전 버그로 미해결 |

## 4. 발표·보고 자료 (llm_wiki 밖, 팀 관리)

| 문서 | 용도 | 상태 |
|---|---|---|
| `../scrum/중간발표/중간발표_참고용_context.md` | 중간발표 슬라이드 작성용 원본 컨텍스트 — 문제정의·근거자료·해결방안·아키텍처·기대효과·진행상황·자체평가 | 일정표/목업 캡처/한계 항목은 담당자 작성 대기 |
| `../ml/비지도학습 정리/비지도모델_비교실험_결과보고서.md` | 비지도 이상탐지 8종(IF·COPOD·ECOD·CBLOF·PCA·INNE·GMM·LODA) 동일 조건 비교 + 5-fold 재검증 → IF 유지, COPOD는 설명가능성 대안 | IF·COPOD 성능차 유의성(paired t-test), LODA 부호 재계산 확인 대기 — 미확정 상태로 인용 시 주의 |

## 5. 데이터/자산 위치 (문서 아님)

- `../tiger_inc/` — RAG 소스 데이터(사내 규정·조직). 직접 문서작업 외 열람 금지.
- `figma_mockup/` — 화면 목업 SVG(참고용).
- 외부 참조(레포에 없음): WBS.xlsx, 프로젝트 기획서, 수집 데이터 보고서, 법인카드 사용 규정 `TIGER-REG-2026-003`.
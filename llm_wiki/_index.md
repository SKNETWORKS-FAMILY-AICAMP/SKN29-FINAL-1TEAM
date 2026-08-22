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
- **판정 사유 = 네임드 플래그**: 2계층(시스템=닫힌 `SystemFlag` enum / 룰=열린 `RuleFlag` 레지스트리). **불변식 — 플래그는 상태머신을 움직이지 않는다**(상태는 `decision` 한 축). 레지스트리 행은 표시·분류 속성만 갖고 행동을 갖지 않는다(가지면 `rule_hits` 스냅샷으로 재현 불가한 세 번째 입력이 생긴다). 미등록 플래그는 **막지 않고 경고**(고객 규정에서 새 어휘가 생긴다). `code`는 데이터 계약이라 불변, `label`만 수정 가능. — `_context/rule-flags.md`
- **가맹점 업종 어휘 = 정본 1곳**: 정본 `apps/core/domain/transactions/industry.py`(15종 코드+라벨), ai는 `app/schemas.py` 미러(어긋나면 캐시 적재 API가 400). 이 라벨이 곧 판정 사실 `merchant.merchant_type`이라 룰 DSL `in [...]`·금지업종 별표 키와 **같은 표기**여야 한다. 규정 원문·옛 시드 표기는 별칭으로 흡수하고, **접히지 않으면 `기타`가 아니라 미확정**(`기타`로 밀면 금지업종 별표가 `"*"→False`로 폴백해 확인 안 한 걸 안전하다고 단정한다). — `_context/merchant-industry-vocabulary.md` / 기술 §7-1
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
| `_context/rule-flags.md` | 네임드 플래그(판정 사유 코드) 캐논 — 불변식(상태 불간섭)과 그 근거 3가지, 시스템/룰 2계층, `code` 불변 계약, 인자 붙는 플래그 규칙, 어휘 목록 8분류, 잡은 결함 4건(어휘 드리프트·프론트 사전 복사·`flag` 미검증·사유 프리셋 하드코딩), 활용처 표, API | 구현 완료 (`policies/flags.py`·`RuleFlag` 0016, 회귀 `test_flags.py`) |
| `_context/merchant-industry-vocabulary.md` | 가맹점 업종 어휘 정본 캐논 — 네 갈래로 갈려 있던 어휘(ai 10종/룰 DSL/금지업종 별표/시드·ERP)를 하나로 통일한 배경과 이관 내역, 코드·라벨 분리, 미확정을 `기타`로 밀지 않는 이유, Draft Agent 연동(서버 주입) 규약 | 구현 완료 (`transactions/industry.py`, 마이그레이션 `transactions/0004`·`settlements/0010`, 회귀 10건) |
| `_context/policy-domain.md` | 규정 임계값(policy) 도메인 캐논 — 저장층(`policy_tables` 자유 JSON)/소비층(`ctx.policy.*` 고정 카탈로그)/해소 규약 2층 구조, 미해소 가드 | 구현 완료 (`policies/context_builder.py`·`tiger_tables.py`, EvalContext v2) |
| `_context/evidence-extraction-agent.md` | 증빙자료 추출 Agent — 첨부 다종 문서(사전승인·회의록·출장계획서·영수증) → 판정 사실(EvalContext dot-path). Draft/Rule/Risk와의 경계, 관측 계약(부재 확인=명시값 / 미관측=경로 생략), 우선순위, 비전 재사용, 종류별 추출 대상, §6 결정 5건 | 전 구간(E-1~E-6) 구현 완료 (2026-08-21) |
| `_context/eval-context-sourcing.md` | EvalContext 데이터 출처 점검 + v3 다이어트 기록 — 필드를 A(데이터 있음·코드만)/B(컬럼·입력칸만)/C(도메인 신설)/D(제외)로 등급화, 부분 조립 실측·GLOBAL 게이트 병목, 첨부 문서 추출 축, v3 다이어트 101→46 실행 기록, 미결 쟁점 | 다이어트 실행 완료 |
| `_context/policy-domain-plan.md` | 위 캐논의 구현 PLAN + 인수 결과 — STEP 1 미해소 가드 → 2 카탈로그 재정의 → 3 `policy_tables` 적재 → 4 조립기(`build_rule_context`) → 5 SoT 일원화 | STEP 1~5 완료, 인수조건 5개 실측 통과 |
| `_context/pdf_parsing_strategy.md` | PDF RAG 파싱 전략 캐논(docling 기반) — engine 2단 폴백·문서 프로파일(REGULATION/LAW/DIAGRAM/GENERIC)·교정 C1~C7·`ParsedDoc` | 구현 완료(회귀 61건). 재채점·자간 잔존은 남음. ✅ **2026-08-16 실측 버그 → 2026-08-18 팀원이 근본 수정**: `docling==2.87.0`의 버전 드리프트로 업로드 파싱이 죽던 문제, `requirements.txt`를 정확한 버전(`docling==2.119.0`)으로 고정해 해결(같은 커밋에서 fastmcp 마운트 버그도 같이 해결). 상세는 `_context/rule-agent-v1-implementation.md` §10·§12.1 |
| `_context/chunking-strategy.md` | 청킹 전략 캐논 — 자르는 단위는 문자 수가 아니라 **조(條)**, 분할 사다리(조→항→호→문장→문자), 표는 독립 청크, 계층 헤더+부모 확장+이웃 링크 | 구현 + 평가 완료(888청크, 종합 98.5/100) |
| `_context/embedding-strategy.md` | 임베딩 전략 캐논 — `text-embedding-3-large` @ `dimensions=1024` 확정 근거, 정답셋 30건, 평가 함정 4개, 기준선 `bge-m3` 격차(재검토 트리거) | 평가 완료 / Chroma upsert 미착수 |
| `_context/draft-agent-plan.md` | Draft Agent(초안 작성) 구현 역할 분담·로드맵 — 계약(입출력) 고정, v0/v1 작업 분해. B-1~B-6 전체 완료. 분류 6종(회식 포함) | 완료 — **2026-08-14 정정**: "정정 완료"로 표기돼 있었지만 실제로는 "업무활성" 문자열이 예시·프롬프트에 그대로 남아있었다(§9.1/§1.3 등 `docs/`는 이미 정합이었는데 이 파일만 안 고쳐져 있었음). 이번에 실제로 치환·확인 완료 |
| `_context/draft-agent-v0.2.md` | Draft Agent 코드 수준 구현 설계서 — pydantic 스키마·정책 조회·프롬프트·에러 폴백. 분류 6종(회식 포함), 미분류 캐치올은 "비품" | 완료 — **2026-08-14 정정**: 위와 같은 이유로 "업무활성" 잔존(Category Literal·프롬프트·`VALID_CATEGORIES`·에러 폴백 기본값 5곳)을 실제로 치환. 캐치올(분류 불명 시 기본값)은 "회식"이 아니라 "비품"으로 — "회식"은 팀 회식이라는 구체 의미의 독립 카테고리라 "판단 불가"의 기본값으로 쓸 수 없다(실제 구현 `apps/ai/app/agents/draft_agent.py`와 동일 결정) |
| `_context/rag-ingestion.md` | **규정 문서 적재 파이프라인 캐논** — 업로드→파싱→청킹→임베딩→Chroma 흐름, 설계 결정 I-1~I-8(비동기 방식·볼륨 공유·콜백 인증·인가), 알고 쓰는 한계(재시작 유실·개정판 구청크 잔존), 룰 트리거의 위치·확정된 범위 | 적재·트리거 모두 구현 완료 (2026-08-16) |
| `_context/rule-agent-v0.md` | **Rule Agent(생성) 구현 캐논** — 규정 문서 → 룰 그래프 DRAFT. 실행 방법(규정 적재 → 서비스 계정 → 화면), 설계 결정 D-1~D-21, 통합에서 고친 것(RAG 사본 3개·403 인증·죽은 코드), 남은 갭 G. 룰 생성 작업은 여기부터 | 통합 완료 (2026-08-14) |
| `_context/ai-lab.md` | AI-LAB(관리자) — AI 기능을 정산 흐름 없이 단독 실행하는 실험 화면. 8개 탭(상태·Draft·Rule·Risk Review·증빙자료 추출·RAG 검색·임베딩·적재), Django `/api/ai-lab/*` 프록시 + Capability `ai_lab`, 실행 추적(trace) 수집 방식, 기능 추가 레시피 | 4개 Agent 전부 연결 완료 (2026-08-21) |
| `_context/case-history-golden-data-note.md` | `case_history` 컬렉션(Risk Review 2차 검증의 유사사례 근거)이 실 결정이력 배치가 아니라 수동 골든데이터뿐이라는 메모(2026-08-19 10건→18건으로 확충 — 회식(GATHERING) 카테고리 공백 해소 + 사례 다양성 보강, 여전히 실 이력 자동 적재 파이프라인은 post-MVP). 원래 `docs/RAG_전략_종합.md`(팀원 원본 작성 중과 중복돼 삭제)에 있던 내용을 보존 | 임시 메모 — 팀원 RAG 전략 원본에 병합되면 폐기 가능 |
| `_context/agent-v1-upgrade-plan.md` | **Rule Agent·Risk Review Agent v1 고도화 — 결정 사항 요약(경량화판)** — 구현 근거·코드 위치·검증 결과는 전부 구현 기록 문서로 넘기고 "무엇을 결정했는지"만 표로 정리. §1 Rule Agent 6개 항목 결정 요약, **§2 Risk Review Agent — 항목1~3(MCP 툴콜링 전환·risk_tier 3단계 분류·분류/액션 단계 분리)+항목5(case_history 골든데이터 10→18건) 구현+검증 완료**(근거·검증은 `risk-review-agent-v1-implementation.md`), 항목4(feature_contribs 실값, ML 재학습 필요)만 별도 트랙으로 남음, §3a 프론트 격리, §4 테스트케이스 자동생성 — 구현+검증 완료 | §1·§4·§2(항목1~3·5) 구현 완료, §2 항목4만 미착수(2026-08-19) |
| `_context/agent-evaluation-2026-08-21.md` | **4개 Agent(Draft·Rule·Risk Review·증빙자료 추출) 정량 평가** — 실 컨테이너 대상 라이브 실행, 재현 스크립트 전문 보존(§6). **방법론 자체를 비판적으로 재검토**(§0.3, 데이터 누수·순환논리 여부 점검)한 개정판. Draft 분류정확도 83.3%(접대↔회식 오분류 — 수정 모드로 거래처 사실 전달해도 안 바뀜, 원인은 입력신호 부족이 아니라 수정 모드가 명시적 요청 없인 분류를 재판단 않는 설계). Rule Agent 노드커버리지·시뮬레이션 100%(자체검증 단계가 75%에서 스스로 걸러냄) + 부수발견(이미 배포된 시연용 회식 그래프가 원본 규정 8개 사전승인 트리거 중 3개만 구현). **Risk Review 66.7%로 4개 중 최저 — 1차 원인분석(RAG 오검색) 자체가 틀렸음을 재조사로 확인·정정**(인용된 조항은 실제로 존재하는 회식 규정 원문이었고, 실제 원인은 ①이미 사전승인 받았다는 프롬프트 명시 사실을 무시 ②1인당 금액 나눗셈 미수행). 증빙추출 1차 100%(9/9, 쉬운 합성문서)→2차 강화판 75%(3/4, 세계지식·모호성 반영) — **관측 계약 위반 실측 발견**(승인여부 언급 없는 문서에서 `False`를 지어냄) | 1회성 평가+재검증 완료(2026-08-21) |
| `_context/risk-review-agent-v1-implementation.md` | **Risk Review Agent v1 구현 기록** — §0 main 동시작업 수동 리졸브(팀원 검색품질 개선분 접목), §1 MCP 툴콜링 전환(`mcp_client.py` 공용화, 프리시드 없이는 검색만 반복하다 턴 소진 후 미제출로 끝나던 실측 버그와 수정), §2 risk_tier 3단계 분류(배포된 anomaly.pkl calibration_table 실측 기반 고정 임계값 0.0134/0.0037 산출 근거), §3 분류/액션 단계 분리 설계, §4 case_history 골든데이터 10→18건, §6 실동작 검증. **§6a 구현 후 전수 검토 — 잡은 결함 6건**: ①risk_tier가 Django에서 조용히 버려져 기능 자체가 사망(컬럼·직렬화·프론트 타입 신설) ②`case_id`를 프롬프트에 안 보여줘 모델이 citation 조각으로 지어냄(역추적 불가) ③부분 실패 3곳(stage1·프리시드검색·액션LLM)이 검토결과 전체를 삼킴 → 격하+결정론적 폴백(장애 경로에서도 자동 REJECT 금지) ④툴인자 JSON 파싱 실패 무방비 ⑤프론트가 anomaly_score를 0~1로 오해해 **실 데이터 전 건을 초록 "정상"으로 표시**(HIGH도 6점 초록) ⑥`ordering=-anomaly_score`라 재판정 시 옛 검토가 최신을 가림 | 구현+검증+전수검토 완료(2026-08-19) |
| `_context/rule-agent-v1-implementation.md` | **Rule Agent v1 구현 기록 — 7개 기능 전부** — §1~9: MCP 툴콜링 전환·자동트리거·검증재사용·검증재생성루프·대화형에이전트·(시뮬레이션LLM서술 보류), 검증 중 JWT 403 오판정·chat 버그 3건 발견수정. §10: nginx 실업로드 시도 중 docling 버전드리프트 버그 발견(v1과 무관). §12: 테스트케이스 자동생성 — 조건 역산(`_solve`)+자체검증(`simulate_graph` 재사용)+LLM 라벨링만. **§13(신규): 검증셋 자동생성 프론트 연동 + 대화형 수정 컨텍스트 버그 수정 + 시뮬레이션 보고서 서술 LLM화 + 검증셋 금액/분류 보강 + 실내역 시뮬레이션 scope 필터 + 대화형 수정의 정성적 판단 오남용 가드** — ①검증셋 자동생성 버튼 프론트 연동. ②대화형 수정이 선택 노드·이전 대화 이력을 서버에 안 넘기던 버그(실사용 재현: 의도한 노드 외 다른 노드까지 수정됨) — `node_key` 힌트+`RuleAuthoringMessage` 이력 재구성으로 수정. ③시뮬레이션 보고서 "플레이스홀더" 태그 상시 노출 — 통계·판정은 그대로, 서술문만 신규 `narrate-report`(LLM)로 교체, 실패 시 템플릿 폴백. ④검증셋 자동생성의 금액·분류가 항상 비어 있던 문제 — 조건이 tx.amount를 안 쓰는 노드(1인당 한도 등 파생값 조건)는 원래도 정상이었으나 표시가 오해를 줌 → LLM 라벨링에 표시용 금액 추가 + 분류는 그래프 scope로 결정론적 채움(판정 로직은 불변). ⑤실제 내역 시뮬레이션이 scope 필터 없이 전 과목 섞어 REVIEW 과대계상 — `_previous_month_cases(scope)`에 category 필터 추가. ⑥대화형 수정이 "목적 문구 품질"처럼 룰로 표현 불가능한 정성적 판단을 엉뚱한 필드에 갖다 붙이거나 동어반복 조건으로 부풀려 "적용했다"고 속이던 문제 — 시스템 프롬프트에 강한 금지 규칙 추가, 완곡한 1차 시도는 재현이 안 잡혀 구체적 금지 목록으로 재작성 후 3/3 차단 확인. ⑦대화형 수정이 참석자 200인처럼 업무 상식을 벗어난 숫자값도 그냥 적용하던 문제 — 이례적 값이면 그 턴엔 적용 안 하고 `answer`로 되물은 뒤, 사용자가 다음 턴에 확인해주면(대화 이력 재사용) 그때 적용하도록 규칙 추가, 정상 수치 변경엔 과잉차단 없음 확인(단, 같은 그래프에 테스트 반복으로 이력이 오염되면 무관한 요청까지 잘못 거부되는 부작용 발견·기록만) | 전 항목(§1~13) 구현+실동작 검증 완료(2026-08-18) |
| `_context/session-2026-08-18-handoff.md` | **세션 인수인계** — 2026-08-18 세션(위 §13 8개 항목) 작업 요약, 브랜치 상태(`feature/rule-agent-v1`, main 미머지), 사용자 결정 대기 중인 항목 2건(설명 필드 라벨링, 출장 식대 EvalContext 필드 추가), DB에 남은 실험 흔적 정리 필요 여부 | 다음 세션 시작점 |
| `_context/rule-agent-v1-ux-upgrade-plan.md` | **시뮬레이션/검증셋 UX·품질 고도화 — §9 1~7번 + 후속 재요청까지 구현+검증 완료** — 모델 티어링·최근내역 문구+reversal등급·empty state·타임아웃 수정·검증셋버튼 완전제거·최소5건 원인수정(+그래프81 라우팅버그)·append→replace·§2-2 생성 사유 로그·§4 대화형수정 컨텍스트 주입·§6 사례인용. **§12**: 재요청 4건 — 권장처리 LLM판단(구조poor 서버 하한강제)·시뮬레이션 결과 즉시표시 재환원·검증셋 상한 철회. **§13(신규, 2026-08-19)**: §8 조각 선착수 — decision/severity가 agent.py·chat.py·DraftTab.tsx 3~4곳에 독립 하드코딩돼있던 걸 발견, Django `engine.py`를 단일 소스로 삼아 API(`action-schema`) 신설 + 전 구간(AI서비스·프론트) fetch로 전환 **§8 방향 전환(2026-08-19)**: "문서로 통합" 원계획 폐기 — 사용자 지적("모델에서 받아오게 구현했으면 문서 통합은 불필요") 반영해 열거형 카탈로그는 API 노출, 필드 설명은 API 응답 확장, 엔진 동작원리는 문서화 대상 아님으로 재분류 | §1~7 + §12 전항목 구현+검증 완료, §13은 §8 재분류 중 카탈로그 항목만 완료(DSL연산자·필드설명 API 확장은 다음 착수 후보), §8 전체 본격 착수는 후순위(2026-08-19) |
| `_context/agent-context-tool.md` | **에이전트 컨텍스트 툴 캐논** — 에이전트 프롬프트에 실을 도메인 카탈로그(DSL 연산자·EvalContext 경로+타입+설명·`policy.*` 별표 축과 적재여부·판정 선택지·플래그 어휘)를 live 모델에서 조립해 내려주는 계층. **core는 사실(JSON) / ai는 문장(렌더)**, 프롬프트와 검증기가 같은 `Bundle`을 본다, 실패는 fail-open하되 프롬프트에 명시. 필드 설명을 문서→코드(`FieldSpec`)로 승격. 죽은 창구 2종 제거. `ux-upgrade-plan.md` §8이 "다음 착수 후보"로 남긴 항목(DSL 연산자·필드 설명 API 확장)이 여기서 해소됐다 | P0 구현 완료 (2026-08-22 `sub-claude` 이식, 원 구현 2026-08-20). 회귀 core 13 + ai 10. §6에 카탈로그가 곧바로 드러낸 별표 축 결함 2건 기록(미해결), P1은 `vocab.*`·`graph.current`·`risk_stage2`·MCP tool·AI-LAB 탭 |
| `_context/decision-case-data.md` | **결정 사례 데이터 캐논** — 회계 담당자가 AI·룰과 **다르게 판단했을 때** 그 판단과 사유를 `case_history`에 적재하는 파이프라인. 「다를 때만 남기는」 이유(전부 넣으면 검색이 다수결에 묻힌다), 비교 대상 우선순위(AI 권고 → 룰 판정, `REVIEW`는 제외), 본문 스냅샷 규약, 커밋 후 적재·미적재 복구(`reindex_cases`) | 기틀 구현 완료 (2026-08-21, 회귀 core 16 + ai 8). 실측: AI `RETURN`↔회계 `REJECT` 사례가 Chroma 적재 후 score 0.673으로 회수됨. 골든 시드와의 구분·개인정보 마스킹은 미결 |

## 4. 발표·보고 자료 (llm_wiki 밖, 팀 관리)

| 문서 | 용도 | 상태 |
|---|---|---|
| `../scrum/중간발표/중간발표_참고용_context.md` | 중간발표 슬라이드 작성용 원본 컨텍스트 — 문제정의·근거자료·해결방안·아키텍처·기대효과·진행상황·자체평가 | 일정표/목업 캡처/한계 항목은 담당자 작성 대기 |
| `../ml/비지도학습 정리/비지도모델_비교실험_결과보고서.md` | 비지도 이상탐지 8종(IF·COPOD·ECOD·CBLOF·PCA·INNE·GMM·LODA) 동일 조건 비교 + 5-fold 재검증 → IF 유지, COPOD는 설명가능성 대안 | IF·COPOD 성능차 유의성(paired t-test), LODA 부호 재계산 확인 대기 — 미확정 상태로 인용 시 주의 |

## 5. 데이터/자산 위치 (문서 아님)

- `../tiger_inc/` — RAG 소스 데이터(사내 규정·조직). 직접 문서작업 외 열람 금지.
- `figma_mockup/` — 화면 목업 SVG(참고용).
- 외부 참조(레포에 없음): WBS.xlsx, 프로젝트 기획서, 수집 데이터 보고서, 법인카드 사용 규정 `TIGER-REG-2026-003`.
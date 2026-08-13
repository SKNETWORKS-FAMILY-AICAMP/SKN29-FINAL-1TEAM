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
- **비용 분류 6종은 서로 독립**: 기업업무추진비(=접대)·회식비(=회식)·출장비(=출장)·회의비(=회의)·식대비(=식대)·비품비(=비품). 회식과 식대는 별개 카테고리이며 서로 흡수·통합하지 않는다. — 요구사항 §4.2·§9.2 Open #8 / 기술 §3.3
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
| **`orchestrator.py`** | 미구현 | GLOBAL→scope 그래프 선택·`RuleHit` 기록이 아직 시뮬레이션 경로에만 있다 |

## 3. 파생 컨텍스트 (`_context/`) — AI 관리

> 에이전트가 만들고 갱신하는 AI용 컨텍스트. 기준 문서(`docs/`)의 파생물이며 권위는 없다.

| 파일 | 용도 | 상태 |
|---|---|---|
| `_context/eval-context-guide.md` | EvalContext 읽는 법(사람용 안내서) — 판정이 어떻게 이뤄지는지 한 문서로. PART 1 쉬운 설명(3단 흐름·표 예시·핵심 규칙 4개·값의 출처·현재 진척) → PART 2 상세(46필드 카탈로그·조립 파이프라인·충돌 규칙·별표 폴백·엔진/가드·코드와 테스트 위치·스키마 버전 이력). 새로 합류하면 여기부터 | 스키마 v4 기준 |
| `_context/rule-engine.md` | 룰엔진 캐논 — EvalContext·DSL·게이트/과목별 그래프 예시·실행 워크스루 | θ_pass/θ_reject 폐기 반영 완료 |
| `_context/rule-engine-design.md` | 룰엔진 엔지니어링 설계 원안 — DSL·순수 엔진·rule_hits 스냅샷·ACTIVE 완전성 게이트. 본문 일부(필드 카탈로그·모듈·로드맵)는 설계 당시 기준이라 현행과 다른 부분이 있어 상단 대조표로 구분해뒀다. 현재 상태는 `eval-context-guide.md`가 정본 | θ_pass/θ_reject 폐기 반영 완료 |
| `_context/rule-seed-plan.md` | RULE 명세서 → RuleGraph 시드 구현 추적. §3.3 그래프 분할표에서 회식(R-2xx)이 식대로 잘못 매핑돼 있던 오류 정정 완료(회식은 독립 scope) | 조립기 완료 반영 |
| `_context/policy-domain.md` | 규정 임계값(policy) 도메인 캐논 — 저장층(`policy_tables` 자유 JSON)/소비층(`ctx.policy.*` 고정 카탈로그)/해소 규약 2층 구조, 미해소 가드 | 구현 완료 (`policies/context_builder.py`·`tiger_tables.py`, EvalContext v2) |
| `_context/evidence-extraction-agent.md` | 증빙자료 추출 Agent — 첨부 다종 문서(사전승인·회의록·출장계획서·영수증) → 판정 사실(EvalContext dot-path). Draft/Rule/Risk와의 경계, 관측 계약(부재 확인=명시값 / 미관측=경로 생략), 우선순위, `chunk_pdf`·비전 재사용, 종류별 추출 대상, 미결 5건 | 저장 구조·조립기 연결 완료 / 추출 로직 미착수 |
| `_context/eval-context-sourcing.md` | EvalContext 데이터 출처 점검 + v3 다이어트 기록 — 필드를 A(데이터 있음·코드만)/B(컬럼·입력칸만)/C(도메인 신설)/D(제외)로 등급화, 부분 조립 실측·GLOBAL 게이트 병목, 첨부 문서 추출 축, v3 다이어트 101→46 실행 기록, 미결 쟁점 | 다이어트 실행 완료 |
| `_context/policy-domain-plan.md` | 위 캐논의 구현 PLAN + 인수 결과 — STEP 1 미해소 가드 → 2 카탈로그 재정의 → 3 `policy_tables` 적재 → 4 조립기(`build_rule_context`) → 5 SoT 일원화 | STEP 1~5 완료, 인수조건 5개 실측 통과 |
| `_context/pdf_parsing_strategy.md` | PDF RAG 파싱 전략 캐논(docling 기반) — engine 2단 폴백·문서 프로파일(REGULATION/LAW/DIAGRAM/GENERIC)·교정 C1~C7·`ParsedDoc` | 구현 완료(회귀 61건). 재채점·자간 잔존은 남음 |
| `_context/chunking-strategy.md` | 청킹 전략 캐논 — 자르는 단위는 문자 수가 아니라 **조(條)**, 분할 사다리(조→항→호→문장→문자), 표는 독립 청크, 계층 헤더+부모 확장+이웃 링크 | 구현 + 평가 완료(888청크, 종합 98.5/100) |
| `_context/embedding-strategy.md` | 임베딩 전략 캐논 — `text-embedding-3-large` @ `dimensions=1024` 확정 근거, 정답셋 30건, 평가 함정 4개, 기준선 `bge-m3` 격차(재검토 트리거) | 평가 완료 / Chroma upsert 미착수 |
| `_context/draft-agent-plan.md` | Draft Agent(초안 작성) 구현 역할 분담·로드맵 — 계약(입출력) 고정, v0/v1 작업 분해. B-1~B-6 전체 완료. 분류 6종 중 잔존 오타(업무활성)를 회식으로 정정 완료 | 완료 |
| `_context/draft-agent-v0.2.md` | Draft Agent 코드 수준 구현 설계서 — pydantic 스키마·정책 조회·프롬프트·에러 폴백. 분류 6종 정정 완료(업무활성→회식) | 완료 |
| `_context/ai-lab.md` | AI-LAB(관리자) — AI 기능을 정산 흐름 없이 단독 실행하는 실험 화면. 5개 탭(상태·Draft·RAG 검색·임베딩·적재), Django `/api/ai-lab/*` 프록시 + Capability `ai_lab`, 실행 추적(trace) 수집 방식, 기능 추가 레시피 | 구현 완료 (Draft·RAG) |

## 4. 발표·보고 자료 (llm_wiki 밖, 팀 관리)

| 문서 | 용도 | 상태 |
|---|---|---|
| `../scrum/중간발표/중간발표_참고용_context.md` | 중간발표 슬라이드 작성용 원본 컨텍스트 — 문제정의·근거자료·해결방안·아키텍처·기대효과·진행상황·자체평가 | 일정표/목업 캡처/한계 항목은 담당자 작성 대기 |
| `../ml/비지도학습 정리/비지도모델_비교실험_결과보고서.md` | 비지도 이상탐지 8종(IF·COPOD·ECOD·CBLOF·PCA·INNE·GMM·LODA) 동일 조건 비교 + 5-fold 재검증 → IF 유지, COPOD는 설명가능성 대안 | IF·COPOD 성능차 유의성(paired t-test), LODA 부호 재계산 확인 대기 — 미확정 상태로 인용 시 주의 |

## 5. 데이터/자산 위치 (문서 아님)

- `../tiger_inc/` — RAG 소스 데이터(사내 규정·조직). 직접 문서작업 외 열람 금지.
- `figma_mockup/` — 화면 목업 SVG(참고용).
- 외부 참조(레포에 없음): WBS.xlsx, 프로젝트 기획서, 수집 데이터 보고서, 법인카드 사용 규정 `TIGER-REG-2026-003`.
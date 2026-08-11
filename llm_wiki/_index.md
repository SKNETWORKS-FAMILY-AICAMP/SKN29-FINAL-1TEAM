# llm_wiki — 프로젝트 컨텍스트 색인 (Context Index)

> **에이전트/Claude 진입점.** 작업 시작 시 이 파일을 먼저 읽어 컨텍스트 위치·최신 상태를 파악한다.
> 컨텍스트를 바꾸면 **해당 문서 본문 + 이 색인의 행**을 함께 갱신한다. (규약: `CLAUDE.md §4`)

## 1. 권위 스펙 문서 (Source of Truth)

| 문서 | 버전 | 권위 범위 | 상태 | 최종 갱신 |
|---|---|---|---|---|
| `요구사항_명세서.md` | Draft v0.5 | 기능/비기능 요구사항(FR-*), 상태머신, Open Issue | 최신 · 제출 2단계·팀 배치·분류 정합 갭 명시(FR-ST-05·Open #8~9) | 2026-07-31 |
| `기술명세서.md` | Draft v0.2 | 아키텍처·데이터·API·FastMCP Tool·ML/RAG·룰 그래프 | 최신 · §3.3 제출플로우/계정과목 구현 정합 갭 명시 | 2026-07-31 |
| `기획_확장안_v2.md` | Draft v0.2 | 제품 기획·3-Agent 플로우·객체 모델·라이프사이클 | 최신 · §1.5 1인 팀 경로·정합 갭 크로스레퍼런스 | 2026-07-31 |
| `화면설계서/` | Rev.1 v1.1 | 6개 화면(S-01~06)·역할·상태머신 화면매핑 (압축해제 .docx) | 프론트 구현 기준 | — |
| `법인카드_사용규정_기반_RULE_명세서.md` | v1.4 | Rule 콘솔 등록용 활성 58 RULE(공통14·업무추진비14·회식16·출장14)·필드정의·심각도·우선순위 | 룰 시드 SoT | 2026-07-30 |

> 세 스펙 문서(요구사항·기술·기획)는 서로 **상충 없이** 유지한다. 상태머신·룰 도메인·Risk 2단계 등 핵심 결정은 `CLAUDE.md §2`에 요약.

## 2. 핵심 결정 요약 (상세는 위 권위 문서)

- **정산 상태머신(4단계)**: 개인 보유(`DRAFT`) → 팀 취합(`TEAM_COLLECTING`/`TEAM_RETURNED`/`TEAM_REJECTED`) → 회계 제출·룰엔진(`SUBMITTED`/`RPA_JUDGED`) → 회계 검토·확정(`PENDING_CONFIRM`/`RETURNED`/`IN_REVIEW`/`REJECT`/`CONFIRMED`/`ERP_VOUCHER_DRAFTED`). 팀 수준(`TEAM_*`)과 회계 수준(`RETURNED`/`REJECT`) 구분. — 요구사항 §4.4·§5.6 / 기술 §3.3
- **Risk Review = MVP 2단계**(이상탐지→RAG 내규검증), 지도학습은 post-MVP. — 요구사항 §6
- **룰 도메인 = 그래프(트리)**, ACTIVE·버전·롤백은 그래프 단위. **룰엔진 = 3단(EvalContext 조립 → 게이트/과목별 그래프 선택 → 결정론적 순회), 조건은 JSON-Logic류 DSL**. — 기술 §4.2 / `_context/rule-engine.md`
- **규정 임계값(policy) = 2층**: 저장층 `policy_tables`(별표 원본, 자유 JSON payload + `key_axes`) → 해소 규약(`RESOLVERS`) → 소비층 `ctx.policy.*` **고정 카탈로그**(DSL 계약·ACTIVE 검증 게이트·룰 편집 UI가 의존하므로 자유화 금지). 초기 `Policy` 모델은 폐기. 조립기(`context_builder.build_rule_context`)·미해소 가드(`UNRESOLVED_POLICY_VAR` → REVIEW 강등) 구현 완료, EvalContext 스키마 v2. — `_context/policy-domain.md` / 기술 §3.3-4 / 요구사항 Open #16·#17
- **가맹점 업종 구분**(캐시→카카오→웹), 비용분류 보조 힌트(세무 아님), MCC는 post-MVP. — 기술 §7-1
- **인가 = 기능 단위(Capability) RBAC**: `team_aggregate`/`accounting_review`/`rule_activate`/`governance_view` 4종. 유효능력 = 역할 기본 ∪ 개인 추가부여(`extra_capabilities`). 역할은 라벨·기본값용. 백엔드 강제(리뷰/확정·팀취합·룰활성·거버넌스) + 프론트 `useCan()` 게이트 전환 완료(mock=역할기본, 실=`/api/me`). — 기술 §3.1a

## 3. 파생 컨텍스트 (`_context/`, 에이전트 생성)

| 파일 | 용도 | 상태 |
|---|---|---|
| `_context/rule-engine.md` | 룰엔진 캐논 — EvalContext·DSL·게이트/과목별 그래프 예시·실행 워크스루 | 2026-07-28 |
| `_context/rule-engine-design.md` | 룰엔진 **엔지니어링 설계·구현 추적** — EvalContext 필드 카탈로그·DSL·순수 엔진·rule_hits 스냅샷·ACTIVE 완전성 게이트. 로드맵 1·2·4 완료, 3·5 진행 | 2026-07-31 |
| `_context/rule-seed-plan.md` | RULE 명세서 → RuleGraph 시드 구현 추적. GLOBAL R-002·R-003 v1 구현 완료, 카테고리 RULE 후속 | 2026-07-31 |
| `_context/policy-domain.md` | **규정 임계값(policy) 도메인 캐논** — 저장층(`policy_tables` 자유 JSON)/소비층(`ctx.policy.*` 고정 카탈로그 13종)/해소 규약 2층 구조, 8개 항목 검토·누락 6종, 필드명 상수 금지 규칙, 미해소 가드 | 2026-08-11 · **구현 완료** (`policies/context_builder.py`·`tiger_tables.py`, EvalContext v2) |
| `_context/eval-context-sourcing.md` | **EvalContext 데이터 출처 점검 + v3 다이어트 기록** — 필드를 A(데이터 있음·코드만)/B(컬럼·입력칸만)/C(도메인 신설)/D(제외)로 등급화(§1~7), 부분 조립 실측·GLOBAL 게이트 병목(§8), 첨부 문서 추출 축(§9), 재설계 대신 그래프 축소(§10), **v3 다이어트 101→46 실행 기록(§12)**, 미결 쟁점 8건(§13) | 2026-08-11 · **다이어트 실행 완료** |
| `_context/policy-domain-plan.md` | 위 캐논의 **구현 PLAN + 인수 결과** — STEP 1 미해소 가드 → 2 카탈로그 재정의 → 3 `policy_tables` 적재 → 4 조립기(`build_rule_context`) → 5 SoT 일원화 | 2026-08-11 · **STEP 1~5 완료, 인수조건 5개 실측 통과** |
| `_context/pdf_parsing_strategy.md` | **PDF RAG 파싱·청킹 전략**(실측 기반) — 페이지 단위 하이브리드 파이프라인·CDM·전처리 조건부 게이트·조(條) 단위 청킹·메타 스키마·품질 지표 | 2026-08-10 · **파싱→청킹 구현 완료** (`apps/ai/app/rag/parsing/`, MCP `chunk_pdf`). 임베딩·Chroma upsert(§13.1⑪⑫)는 미착수 |
| `_context/draft-agent-plan.md` | Draft Agent(초안 작성) 구현 **역할 분담·로드맵** — 계약(입출력) 고정, v0(@김정민)/v1(@이지현) 작업 분해. **B-1~B-6 전체 완료**(2026-08-10). ⚠️ 정책 조회는 현재 구 `Policy` 모델 사용 — 위 `policy-domain.md` 체계 구현 시 재연동 필요(§7) | 2026-08-10 |
| `_context/draft-agent-v0.2.md` | Draft Agent **코드 수준 구현 설계서** — pydantic 스키마·정책 조회·프롬프트·에러 폴백. as-is stub 실태 포함 | 2026-08-10 |

## 4. 발표·보고 자료

| 문서 | 용도 | 상태 |
|---|---|---|
| `중간발표_참고용_context.md` | 중간발표(2026-08-06) 슬라이드 작성용 원본 컨텍스트 — 문제정의·근거자료·해결방안·아키텍처·기대효과(기획/엔지니어링 2버전)·진행상황·자체평가 | 2026-08-03 · 일정표/목업 캡처/한계 항목은 담당자 작성 대기 |
| `비지도모델_비교실험_결과보고서.md` | 비지도 이상탐지 8종(IF·COPOD·ECOD·CBLOF·PCA·INNE·GMM·LODA) 동일 조건 비교 + 5-fold 재검증 → **IF 유지, COPOD는 설명가능성 대안** | 2026-08-03 · LODA 부호·쌍대 차이 재계산 확인 대기 |

## 5. 데이터/자산 위치 (문서 아님)

- `../tiger_inc/` — **RAG 소스 데이터**(사내 규정·조직). ⚠️ 직접 문서작업 외 열람 금지(`CLAUDE.md §5`).
- `figma_mockup/` — 화면 목업 SVG(참고용).
- 외부 참조(레포에 없음): WBS.xlsx, 프로젝트 기획서, 수집 데이터 보고서, 법인카드 사용 규정 `TIGER-REG-2026-003`.

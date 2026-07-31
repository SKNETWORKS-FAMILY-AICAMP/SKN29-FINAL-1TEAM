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
- **가맹점 업종 구분**(캐시→카카오→웹), 비용분류 보조 힌트(세무 아님), MCC는 post-MVP. — 기술 §7-1
- **인가 = 기능 단위(Capability) RBAC**: `team_aggregate`/`accounting_review`/`rule_activate`/`governance_view` 4종. 유효능력 = 역할 기본 ∪ 개인 추가부여(`extra_capabilities`). 역할은 라벨·기본값용. 백엔드 강제(리뷰/확정·팀취합·룰활성·거버넌스) + 프론트 `useCan()` 게이트 전환 완료(mock=역할기본, 실=`/api/me`). — 기술 §3.1a

## 3. 파생 컨텍스트 (`_context/`, 에이전트 생성)

| 파일 | 용도 | 상태 |
|---|---|---|
| `_context/rule-engine.md` | 룰엔진 캐논 — EvalContext·DSL·게이트/과목별 그래프 예시·실행 워크스루 | 2026-07-28 |
| `_context/rule-engine-design.md` | 룰엔진 **엔지니어링 설계·구현 추적** — EvalContext 필드 카탈로그·DSL·순수 엔진·rule_hits 스냅샷·ACTIVE 완전성 게이트. 로드맵 1·2·4 완료, 3·5 진행 | 2026-07-31 |
| `_context/rule-seed-plan.md` | RULE 명세서 → RuleGraph 시드 생성 계획(매핑·scope 분할·오픈이슈, 구현 아님) | 2026-07-30 |

## 4. 데이터/자산 위치 (문서 아님)

- `../tiger_inc/` — **RAG 소스 데이터**(사내 규정·조직). ⚠️ 직접 문서작업 외 열람 금지(`CLAUDE.md §5`).
- `figma_mockup/` — 화면 목업 SVG(참고용).
- 외부 참조(레포에 없음): WBS.xlsx, 프로젝트 기획서, 수집 데이터 보고서, 법인카드 사용 규정 `TIGER-REG-2026-003`.

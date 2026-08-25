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
| `docs/요구사항_명세서.md` | v1.1 | 기능/비기능 요구사항(FR-*), 상태머신, Open Issue | 확정 |
| `docs/기술명세서.md` | v1.1 | 아키텍처·데이터·API·FastMCP Tool·ML/RAG·룰 그래프 + 서비스 기획(§12, 2026-08-24 `기획_확장안.md` 병합: 문제정의·UI 목업·대시보드·카드구분×분류 흐름분기) | 확정 |
| `docs/RULE_명세서.md` | v1.4 | 규정에서 도출 가능한 76 RULE의 참고 예시(접대·회식·출장·회의·식대 5개 카테고리) — 필드정의·심각도·우선순위. 제품 기본 제공은 DEFAULT GATE 1개뿐이며 세부 룰은 고객 규정 문서 업로드 시 생성된다 | 확정(참고 자료) |
| `docs/agent_test_result.md` | 2026-08-24 | Rule Agent·Risk Review Agent 실측 검증 결과 요약(발표용) — 정량 지표·발견한 결함·조치. 상세 데이터는 `docs/qa/` | 확정 |
| `화면설계서/` | Rev.1 v1.1 | 6개 화면(S-01~06)·역할·상태머신 화면매핑 (압축해제 .docx) | 프론트 구현 기준 |

> **2026-08-24**: `기획_확장안.md`는 §12로 기술명세서에 병합·삭제됐다.
> **2026-08-25**: `_context/` 1차 정리 — v1/v2 문서로 완전 대체된 v0 구현 기록·낡은 계획·상위 문서로 흡수된 메모 7건 삭제(§3.2 안내 참조).

세 스펙 문서(요구사항·기술·기획)는 서로 상충 없이 유지한다. 상태머신·룰 도메인·Risk 2단계 등 핵심 결정은 아래 §2에 요약.

## 2. 핵심 결정 — 어디를 봐야 하나

**결정 본문은 `CLAUDE.md §2`에 있다**(매 세션 자동 로드되므로 여기 옮겨 적지 않는다 — 같은 내용이
두 곳에 있으면 하나는 반드시 뒤처진다). 이 표는 **결정 → 근거 문서** 대응만 담는다.

| 결정 | 근거·상세 |
|---|---|
| 정산 상태머신(4단계) | 요구사항 §4.2·FR-ST-01 / 기술 §3.3 |
| Risk Review = MVP 2단계 | 요구사항 §6 / `_context/risk-review-agent-v1-implementation.md` |
| 룰 도메인 = 그래프, 엔진 = 3단 파이프라인 | 기술 §4.2 / `_context/rule-engine.md` |
| decision은 노드 생성 시 직접 지정(θ 방식 폐기) | `_context/rule-engine.md` §6 |
| 룰은 사전 탑재하지 않는다 — 기본 게이트 1개 | `_context/default-gate.md` |
| 판정 사유 = 네임드 플래그(상태를 움직이지 않는다) | `_context/rule-flags.md` |
| 규정 임계값 = 저장층/소비층 2층 + 적재된 표에서 파생 | `_context/policy-domain.md` |
| 비용분류 어휘 = 서버가 내려준다 · `기타` ≠ 미기재 | `_context/category-vocabulary.md` |
| 가맹점 업종 어휘 = 정본 1곳 · 미확정을 `기타`로 안 민다 | `_context/merchant-industry-vocabulary.md` |
| AI는 판정을 예측하지 않는다(엔진 dry-run) | `_context/draft-agent-v2.md` |
| 화면·흐름 불변식(이상 건 정의·결정 버튼·저장 vs 파생) | `_context/settlement-ui-rules.md` |
| 알림 = 메시지 + 이동할 페이지 · 생성 지점 한 곳 | `_context/notifications.md` |
| 인가 = Capability RBAC 6종 | 기술 §3.1a |

## 2a. 지금 무엇이 되고 무엇이 안 되나

**`CLAUDE.md §3 상태 보드`가 정본이다.** 이 섹션은 예전에 룰 엔진 영역만 따로 요약했는데,
상태 보드와 갈라져 **틀린 값이 남았다**(EvalContext를 v4로, 증빙자료 추출을 미착수로 적고
있었다 — 둘 다 사실이 아니었다). 두 곳에서 진행 상태를 관리하지 않는다.

## 3. 파생 컨텍스트 (`_context/`) — AI 관리

에이전트가 만들고 갱신하는 AI용 컨텍스트. 기준 문서(`docs/`)의 파생물이며 권위는 없다.
**한 줄 용도만 적는다** — 상세는 문서 본문에 있다(여기서 요약하면 곧 갈린다).

### 3.1 구현 캐논 — 작업 전에 읽는 것

| 파일 | 용도 |
|---|---|
| `eval-context-guide.md` | **EvalContext 읽는 법(사람용 안내서).** 판정이 어떻게 이뤄지는지 한 문서로 — 새로 합류하면 여기부터 |
| `rule-engine.md` | 룰엔진 캐논 — DSL·게이트/과목별 그래프·실행 워크스루·결정→상태 매핑. §8에 설계 이력(구 `rule-engine-design.md`, 2026-08-25 병합) |
| `rule-flags.md` | 판정 사유 코드 2계층. **불변식: 플래그는 상태머신을 움직이지 않는다** |
| `default-gate.md` | 기본 게이트 설계 — 방향(기본 REVIEW+사유), `PASS_THROUGH` 체인, 미해소 가드 우회(§4·실측 결함 2건 §4.1), 시드 3종(`seed_clean`/`seed_adopted`/`seed`) 차이 §6 |
| `policy-domain.md` | 규정 임계값 2층 구조 + `ctx.policy.*` 동적화(§3) + 축 정합 검사. §8에 구현 계획·인수 조건 실측 기록(구 `policy-domain-plan.md`, 2026-08-25 병합) |
| `category-vocabulary.md` | 비용분류 어휘 정본 — 서버 단일 창구, `기타` ≠ 미기재 |
| `merchant-industry-vocabulary.md` | 가맹점 업종 어휘 정본 15종 — 코드/라벨 분리, 미확정 처리 |
| `notifications.md` | 알림 11종 — 자격 조건, 수신자(Capability 기준), 묶기, 「화면에 있으면 화면이 접는다」 |
| `settlement-ui-rules.md` | **정산 화면·흐름 불변식** — 새 화면·버튼 만들기 전에 읽는다 |
| `risk-review-agent-v2.md` | Risk Review 등급 분기(하=LLM 0회 / 중=fast / 상=heavy) + 구조화 보고서, LLM 프로파일 어댑터(`app/llm.py`), 서버측 근거 대조 |
| `draft-agent-v2.md` | Draft Agent — 사실 주입 + 엔진 dry-run 판정 미리보기 |
| `evidence-extraction-agent.md` | 증빙 추출 — 관측 계약(부재 확인 ≠ 미관측), 종류별 추출 대상 |
| `decision-case-data.md` | 결정 사례 적재 — 「다르게 판단한 것」만, 본문은 스냅샷 |
| `agent-context-tool.md` | 에이전트 프롬프트용 도메인 카탈로그(어휘) — TTL·stale 규약 |
| `document-triage.md` | 조항 분류(성격 판별 → **문서 단위 우선순위 선별** 2단) + 별표 승인 — 제안이지 차단이 아니다, 축만 강제 |
| `rag-ingestion.md` | 규정 문서 적재 파이프라인 + 룰 트리거 |
| `pdf_parsing_strategy.md` | PDF 파싱(docling) — 프로파일·교정 C1~C7 |
| `chunking-strategy.md` | 청킹 — **자르는 단위는 조(條)** |
| `embedding-strategy.md` | 임베딩 — `3-large @ 1024` 확정 근거, `bge-m3` 격차(재검토 트리거) |
| `ai-lab.md` | AI-LAB — 운영과 같은 코드를 부르고 근거를 편다 |

### 3.2 구현 기록·계획 — 배경이 필요할 때

| 파일 | 용도 |
|---|---|
| `rule-agent-v1-implementation.md` | Rule Agent v1 구현 기록. §0에 결정 사항 요약(구 `agent-v1-upgrade-plan.md`, 2026-08-25 병합) + 근거·코드 위치·검증 결과 |
| `risk-review-agent-v1-implementation.md` | Risk Review v1 구현 기록. §0에 결정 사항 요약(구 `agent-v1-upgrade-plan.md` §2, 2026-08-25 병합) + 근거·코드 위치·검증 결과 |
| `rule-agent-v1-ux-upgrade-plan.md` | 룰 콘솔 UX 고도화 계획·구현 |
| `eval-context-sourcing.md` | EvalContext 다이어트 실행 기록(§12~) + v6·DSL null 의미론·참석인원 출처 결정(§15~18). 다이어트 이전 조사(구 §0~11)는 2026-08-25에 배경 요약으로 압축 |

> **2026-08-25 삭제(§3.2 舊)**: `rule-agent-v0.md`·`risk-review-agent-v0-summary.md`(v1/v2로 완전 대체) · `rule-seed-plan.md`(2026-07-30 시점 계획, 엔진 부재 전제로 현행과 무관) · `agent-evaluation-2026-08-21.md`(같은 4개 Agent를 더 엄밀히 재평가한 `qa/`로 완전 대체, `docs/agent_test_result.md`가 그 요약본) · `case-history-golden-data-note.md`(파이프라인 기틀이 구현된 `decision-case-data.md`가 완전 대체).

## 4. 발표·보고 자료 (llm_wiki 밖, 팀 관리)

| 문서 | 용도 | 상태 |
|---|---|---|
| `../scrum/중간발표/중간발표_참고용_context.md` | 중간발표 슬라이드 작성용 원본 컨텍스트 — 문제정의·근거자료·해결방안·아키텍처·기대효과·진행상황·자체평가 | 일정표/목업 캡처/한계 항목은 담당자 작성 대기 |
| `../ml/비지도학습 정리/비지도모델_비교실험_결과보고서.md` | 비지도 이상탐지 8종(IF·COPOD·ECOD·CBLOF·PCA·INNE·GMM·LODA) 동일 조건 비교 + 5-fold 재검증 → IF 유지, COPOD는 설명가능성 대안 | IF·COPOD 성능차 유의성(paired t-test), LODA 부호 재계산 확인 대기 — 미확정 상태로 인용 시 주의 |

## 5. 데이터/자산 위치 (문서 아님)

- `../tiger_inc/` — RAG 소스 데이터(사내 규정·조직). 직접 문서작업 외 열람 금지.
- `figma_mockup/` — 화면 목업 SVG(참고용).
- 외부 참조(레포에 없음): WBS.xlsx, 프로젝트 기획서, 수집 데이터 보고서, 법인카드 사용 규정.
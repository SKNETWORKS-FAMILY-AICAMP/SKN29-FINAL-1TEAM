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
| `법인카드_사용규정_기반_RULE_명세서.md` | v1.4 | **참고용 예시** — 규정에서 도출 가능한 58 RULE을 사람이 손으로 뽑아 본 산출물. 필드정의·심각도·우선순위 | ⚠️ **권위 스펙 아님.** 제품 기본 제공은 **DEFAULT GATE 1개**뿐이고 세부 룰은 **고객 규정 문서 업로드 시 생성**된다. 필드 정의는 이상 집합이며 실제 스키마는 v3(46) | 2026-08-11 |

> 세 스펙 문서(요구사항·기술·기획)는 서로 **상충 없이** 유지한다. 상태머신·룰 도메인·Risk 2단계 등 핵심 결정은 `CLAUDE.md §2`에 요약.

## 2. 핵심 결정 요약 (상세는 위 권위 문서)

- **정산 상태머신(4단계)**: 개인 보유(`DRAFT`) → 팀 취합(`TEAM_COLLECTING`/`TEAM_RETURNED`/`TEAM_REJECTED`) → 회계 제출·룰엔진(`SUBMITTED`/`RPA_JUDGED`) → 회계 검토·확정(`PENDING_CONFIRM`/`RETURNED`/`IN_REVIEW`/`REJECT`/`CONFIRMED`/`ERP_VOUCHER_DRAFTED`). 팀 수준(`TEAM_*`)과 회계 수준(`RETURNED`/`REJECT`) 구분. — 요구사항 §4.4·§5.6 / 기술 §3.3
- **Risk Review = MVP 2단계**(이상탐지→RAG 내규검증), 지도학습은 post-MVP. — 요구사항 §6
- **룰 도메인 = 그래프(트리)**, ACTIVE·버전·롤백은 그래프 단위. **룰엔진 = 3단(EvalContext 조립 → 게이트/과목별 그래프 선택 → 결정론적 순회), 조건은 JSON-Logic류 DSL**. — 기술 §4.2 / `_context/rule-engine.md`
- **규정 임계값(policy) = 2층**: 저장층 `policy_tables`(별표 원본, 자유 JSON payload + `key_axes`) → 해소 규약(`RESOLVERS`) → 소비층 `ctx.policy.*` **고정 카탈로그**(DSL 계약·ACTIVE 검증 게이트·룰 편집 UI가 의존하므로 자유화 금지). 초기 `Policy` 모델은 폐기. 조립기(`context_builder.build_rule_context`)·미해소 가드(`UNRESOLVED_POLICY_VAR` → REVIEW 강등) 구현 완료, EvalContext 스키마 v2. — `_context/policy-domain.md` / 기술 §3.3-4 / 요구사항 Open #16·#17
- **가맹점 업종 구분**(캐시→카카오→웹), 비용분류 보조 힌트(세무 아님), MCC는 post-MVP. — 기술 §7-1
- **인가 = 기능 단위(Capability) RBAC**: `team_aggregate`/`accounting_review`/`rule_activate`/`governance_view` 4종. 유효능력 = 역할 기본 ∪ 개인 추가부여(`extra_capabilities`). 역할은 라벨·기본값용. 백엔드 강제(리뷰/확정·팀취합·룰활성·거버넌스) + 프론트 `useCan()` 게이트 전환 완료(mock=역할기본, 실=`/api/me`). — 기술 §3.1a

## 2a. 룰 엔진 영역 현재 상태 (2026-08-11) — 새 세션 빠른 파악용

> 이 영역은 최근 대폭 바뀌었다. **`_context/eval-context-guide.md`를 먼저 읽으면 아래를 다 이해할 수 있다.**

| 무엇 | 상태 | 한 줄 |
|---|---|---|
| **룰 제공 정책** | ✅ 확정 | 제품 기본 제공은 **`DEFAULT GATE` 1개**뿐. 세부 룰은 **고객 규정 문서 업로드 시 생성**. RULE 명세서 58종·시드 4계열은 **참고 예시/시연용** |
| **규정 임계값(policy)** | ✅ 구현 | 저장층 `PolicyTable`(자유 JSON payload + `key_axes` + `strict_keys`) → 조립기 선해소 → `ctx.policy.*` 8종. 개정은 INSERT(유효일) |
| **EvalContext 스키마** | ✅ **v4 (46필드)** | 101 → 46 다이어트. **판정 필드 제거**(판단은 그래프가 조합), 조합 가능·원천 없는 필드 제거. `tables`·`conflicts`는 동적 감사 섹션 |
| **조립기** | ✅ 구현 | `policies/context_builder.py` — 원장·화면입력·첨부추출·별표를 **출처 순위(SoR>입력>추출)** 로 병합, 충돌은 `ctx.conflicts`에 기록 |
| **미해소 가드** | ✅ 구현 | `None`=**모름** 계약. 참조 경로가 null이면 `REVIEW` 강등 + `UNRESOLVED_POLICY_VAR`(표 채우면 해결)/`UNRESOLVED_FACT`(원천 필요) |
| **판정 입력 원천** | 🚧 절반 | `Settlement` 판정 컬럼 9종 + `Attachment`(첨부 추출 저장 틀) 신설. **조립 커버리지 24/46**, 실 정산 강등 **31%** |
| **증빙자료 추출 Agent** | 🔲 미착수 | 저장 구조·조립기 연결은 완료. 실제 문서 판독 미구현 |
| **`orchestrator.py`** | 🔲 미구현 | GLOBAL→scope 그래프 선택·`RuleHit` 기록이 아직 시뮬레이션 경로에만 있다 |

**다음 후보**(우선순위): ① GLOBAL 게이트에 적용 조건 부착(컬럼 추가 0으로 강등 감소) ② A등급 조립 채우기(`user.*`·`history.*` — 데이터는 있고 코드만 없음) ③ 추출 Agent 구현 ④ `orchestrator.py`

## 3. 파생 컨텍스트 (`_context/`, 에이전트 생성)

| 파일 | 용도 | 상태 |
|---|---|---|
| `_context/eval-context-guide.md` | ⭐ **EvalContext 읽는 법 (사람용 안내서)** — 판정이 어떻게 이뤄지는지 한 문서로. **PART 1 쉬운 설명**(3단 흐름·표 예시·핵심 규칙 4개·값의 출처·현재 진척) → **PART 2 상세**(46필드 카탈로그·조립 파이프라인·충돌 규칙·별표 폴백·엔진/가드·코드와 테스트 위치·스키마 버전 이력). **새로 합류하면 여기부터** | 2026-08-11 · 스키마 v4 기준 |
| `_context/rule-engine.md` | 룰엔진 캐논 — EvalContext·DSL·게이트/과목별 그래프 예시·실행 워크스루 | 2026-07-28 |
| `_context/rule-engine-design.md` | 룰엔진 **엔지니어링 설계 원안(2026-07-31)** — DSL·순수 엔진·rule_hits 스냅샷·ACTIVE 완전성 게이트. ⚠️ **본문 §2.3 필드 카탈로그·§5 모듈·§7 로드맵은 설계 당시 기준이라 현행과 다르다** — 문서 상단에 현행 대조표를 넣어 뒀고, 현재 상태는 `eval-context-guide.md`가 정본 | 2026-08-11 · 상단 대조표 갱신 |
| `_context/rule-seed-plan.md` | RULE 명세서 → RuleGraph 시드 구현 추적. 조립기 미구현 항목은 해소 표기. ⚠️ RULE 명세서 58종은 **참고용 예시**로 확정돼 전량 시드가 목표가 아니다 | 2026-08-11 · 조립기 완료 반영 |
| `_context/policy-domain.md` | **규정 임계값(policy) 도메인 캐논** — 저장층(`policy_tables` 자유 JSON)/소비층(`ctx.policy.*` 고정 카탈로그 13종)/해소 규약 2층 구조, 8개 항목 검토·누락 6종, 필드명 상수 금지 규칙, 미해소 가드 | 2026-08-11 · **구현 완료** (`policies/context_builder.py`·`tiger_tables.py`, EvalContext v2) |
| `_context/evidence-extraction-agent.md` | **증빙자료 추출 Agent** — 첨부 다종 문서(사전승인·회의록·출장계획서·영수증) → 판정 사실(EvalContext dot-path). Draft/Rule/Risk와의 경계, **관측 계약**(부재 확인=명시값 / 미관측=경로 생략), 우선순위, `chunk_pdf`·비전 재사용, 종류별 추출 대상, 미결 5건 | 2026-08-11 · **저장 구조·조립기 연결 완료 / 추출 로직 미착수** |
| `_context/eval-context-sourcing.md` | **EvalContext 데이터 출처 점검 + v3 다이어트 기록** — 필드를 A(데이터 있음·코드만)/B(컬럼·입력칸만)/C(도메인 신설)/D(제외)로 등급화(§1~7), 부분 조립 실측·GLOBAL 게이트 병목(§8), 첨부 문서 추출 축(§9), 재설계 대신 그래프 축소(§10), **v3 다이어트 101→46 실행 기록(§12)**, 미결 쟁점 8건(§13) | 2026-08-11 · **다이어트 실행 완료** |
| `_context/policy-domain-plan.md` | 위 캐논의 **구현 PLAN + 인수 결과** — STEP 1 미해소 가드 → 2 카탈로그 재정의 → 3 `policy_tables` 적재 → 4 조립기(`build_rule_context`) → 5 SoT 일원화 | 2026-08-11 · **STEP 1~5 완료, 인수조건 5개 실측 통과** |
| `_context/pdf_parsing_strategy.md` | **PDF 파싱 전략 (docling 기반)** — 엔진 확정(docling+pypdfium2)·실측 결함 6종·문서 유형 프로파일(REGULATION/LAW/DIAGRAM)별 교정 단계 C1~C7·`ParsedDoc` 중간표현·품질 게이트/회귀·결정대기 4건. 청킹은 범위 밖(§9에 인터페이스만) | 2026-08-12 · **전면 재작성 + P0/P1 구현 완료** (구 PyMuPDF+pdfplumber 수제안 폐기). `apps/ai/app/rag/parsing/` C1~C7 + 회귀 61건 통과. 고아 마커 95→0 · 자동번호 항 882→0 · 장/조 순서 11종 전건 정합 · 자간 667→372. GT 대비 재채점 미착수. **청킹은 `chunking-strategy.md`로 분리·구현 완료** |
| `_context/chunking-strategy.md` | **RAG 청킹 전략 (구조 기반)** — 코퍼스 실측(문단 중앙 76자·조 블록 중앙 449자·항 p90 420자)에서 **조=청크 단위** 도출, 전략 A~E 실측 비교(Fixed는 조 경계 위반 190건, 우리 안 1건), 표 원자화·별표 독립·계층 헤더·Parent-Child·오버랩 미사용(이웃 확장), 메타/ID 설계, 내재 지표 6종+영역 점수, **예산 민감도 스윕(§10.2)**, 결정대기 7건 중 **④ 해소** | 2026-08-12 · **구현+평가 완료, 결정대기 ④ 해소 반영** (`apps/ai/app/rag/chunking/`, 회귀 164건 · 평가 노트북 `docling_eval/chunking_evaluation.ipynb` → `output/chunking/`). 실측 888청크·커버리지 100%·유실 0·표 행보존 100%·종합 98.5(Structure 100 / Context 98.6 / Size 96.4 / **Retrieval N/A는 가중치 제거**). 남은 감점은 파편 91건(법령 성질, 예산 무관). **④ 항/호는 프로파일이 아니라 조 단위 판정으로 확정**(기본 `항`, 도입부 `각 호`인 조만 `호` — 규정 26개 조의 틀린 호칭 교정), `Budget` 정합 가드 추가. **결정대기 ①② 해소(2026-08-12)** — 임베딩 평가 노트북 `docling_eval/docling_embedding_strategy.ipynb`(→ `output/embedding/`)가 **OpenAI 채택 전제**에서 모델·차원 4변형 + 로컬 기준선 3종을 실측해 **`text-embedding-3-large` @ `dimensions=1024` + 문서입력 `헤더+본문` + 질의 `사내 규정 조문 검색:` 접두 + cosine**으로 확정하고 **질의 정답셋 30건**(정답=조문 ID)을 만들었다. 📏 MRR .906 / R@1 .817 / R@5 .950 / 표 R@5 1.00. **차원 1024는 네이티브 3072 대비 ΔMRR −0.006(잡음)인데 저장 −67%**(9.8→3.3MB)이고, 256은 −0.091로 실제 손실(하한 확인). ⚠️ 기준선 `bge-m3`가 MRR .933으로 더 높지만 CI가 0을 포함해 못 가른다 — 공급자 결정이 먼저였으므로 **격차는 재검토 트리거로 기록**. `Recall@5`는 천장에 붙었다. 📏 한국어는 cl100k_base에서 토큰이 1.6배(358 vs 223) — 비용 추정 시 주의. **청킹 A~E의 검색 비교(§10.4)·Chroma upsert·사람 검수 40건은 여전히 미착수** |
| `_context/embedding-strategy.md` | **RAG 임베딩 전략 (OpenAI `text-embedding-3-large` @ 1024)** — 청킹 다음 단계 캐논. 고정 계약(모델·차원·문서입력·질의접두·cosine·배치), 코퍼스 토큰 실측, 모델 7종 순위 + **부트스트랩 CI 판정 밴드**, 차원 트레이드오프(3072→1024는 공짜 / →256은 손실), 입력전략 A~E·질의전략 3안·표 처리, **Chroma upsert/검색 3단 계약**, 정답셋 30건 설계, **평가에서 잡은 함정 4개**, 결정대기·재검토 트리거 7건, 구현 배치(미착수) | 2026-08-12 · **평가 완료 / 구현 미착수**. 근거 `docling_eval/docling_embedding_strategy.ipynb` → `output/embedding/`(결과 25종+벡터). 📏 MRR .906 / R@1 .817 / R@5 .950 / nDCG@10 .916 / 표 R@5 1.00, 약점은 `numeric`(R@5 .800·MRR .667) 단 하나. ⚠️ **점수 1위는 기준선 `bge-m3`(.933, 처리량 9배)** — 공급자 OpenAI 결정이 평가보다 먼저였으므로 이 표는 그 결정을 정당화하지 않는다, **재검토 트리거로 기록**. `Recall@5` 천장·정답셋 저자 편향으로 순위는 방향으로만 읽을 것 |
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

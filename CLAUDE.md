# CLAUDE.md — 팀 공용 컨텍스트

> Hybrid AI 기반 **법인카드 정산 자동화 플랫폼** (가상기업 "타이거 주식회사" 페르소나).
> 정산 업무(입력→검토→확정→정책결정)를 3개 AI Agent(초안 작성 / Rule / Risk Review) + 사람 최종 확정으로 자동화한다.
> 이 파일은 매 세션 자동 로드된다. **간결하게 유지**하고, 큰 변경 시 아래 "상태 보드"를 갱신할 것.

---

## 1. 저장소 구조

```
apps/
  web/      React + Vite + TS (SPA) — 6개 역할별 화면
  core/     Django + DRF — System of Record(SoR): 도메인·상태머신·RBAC·ERP전표(안)
  ai/       FastAPI — AI Orchestrator: 3-Agent + 단일 FastMCP 서버 + 비지도 이상탐지
infra/nginx/  리버스 프록시(/ → web, /api → core)
docker-compose.yml  로컬 개발 오케스트레이션 (db·chroma·core·ai·web·nginx)
llm_wiki/     설계·기획 산출물(아래 §4)
tiger_inc/    RAG 소스 데이터 — §5 열람 규칙 주의
daily_scrum/  주차별 진행 보고
```

아키텍처 원칙(기술명세서 기준): **SoR은 Postgres 하나**(AI는 "제안"만, 확정은 Django 서비스 레이어) · **관계형=Django 경유 / 벡터=Chroma 직접**(LLM/Tool의 Postgres 직접 SQL 금지) · **FastAPI는 내부 전용**(사용자 트래픽은 Django만) · **동기 REST(MVP)**, 무거운 작업은 관리자 온디맨드 배치.

---

## 2. 핵심 설계 결정 (변경 시 세 문서 + 화면 모두 동기화)

- **Risk Review = MVP 2단계**: ① 단순 이상거래 탐지(비지도, anomaly_score) → ② RAG 내규 검증(이상 후보 한정). 지도학습(`review_probability`)·자동 재학습 피드백 루프는 **post-MVP 확장**. (콜드스타트/라벨부족 대응)
- **상태머신(FR-ST-01)** — 4단계: **① 개인 보유(`DRAFT`) → ② 팀 취합(`TEAM_COLLECTING`/`TEAM_RETURNED`/`TEAM_REJECTED`) → ③ 회계 제출·룰엔진(`SUBMITTED`/`RPA_JUDGED`) → ④ 회계 검토·확정(`PENDING_CONFIRM`/`RETURNED`/`IN_REVIEW`/`REJECT`/`CONFIRMED`/`ERP_VOUCHER_DRAFTED`)**. **팀 수준 보완/반려(`TEAM_*`, 팀장)** 와 **회계 수준(`RETURNED`/`REJECT`, 회계)** 은 별개 상태. `REJECT`=회계 최종반려(재제출 불가). 제출=2단계(개인 올림 `raise_to_team`: `DRAFT→TEAM_COLLECTING` / 팀 제출 `submit`: `TEAM_COLLECTING→SUBMITTED`), 1인 팀도 동일 경로. ✅ **구현 반영**: ① `DRAFT→SUBMITTED` 직행 제거·S-01 "팀에 올림" ② 계정과목=비용분류(`Category`) 매핑 `policies/scope.normalize_scope`. 🚧 남음: `/submit` 팀 동일성 배치 강제(Open #8), 엔진 scope 연결. (기술 §3.3 / 요구사항 FR-ST-05·Open #8~9)
- **예산·정책은 통제(차단)가 아니라 지표·추천으로만** 반영.
- **사람 확정 원칙**: 확신 통과 건도 회계 담당자 확정 없이는 CONFIRMED 불가.
- 영수증은 별도 OCR 없이 **OpenAI 비전**으로 직접 판독. Rule 적용은 결정론적 엔진, LLM은 Rule 생성 단계에서만.
- **가맹점 업종 구분 시스템**: 자체 DB 캐시 → 카카오 지도 API → 웹검색 캐스케이드로 업종 판별 → 비용분류 **보조 힌트**로만 사용(세무 판단 아님). 표준 업종코드(MCC)는 카드사 제휴 **post-MVP** 확장. (기술 §7-1 / 요구사항 §6.5 / FR-DA-03a~c)
- **룰 도메인 = 그래프(트리)**: 단건 룰은 `condition+action+next_routings` 노드, 조립된 **룰 그래프(RuleGraph)** 가 최종 상태 도메인. **ACTIVE·버전관리·시뮬레이션·롤백은 그래프 단위**. (기술 §3.1·§4.2 / 요구사항 FR-RB·FR-RV·FR-RA)
- **룰엔진 = 3단 파이프라인**: ① `build_rule_context(tx_id)`로 **EvalContext(facts 스냅샷)** 조립(모든 I/O·데이터 접근은 여기서만) → ② 그래프 선택(**필수 게이트 GLOBAL → 계정과목별 scope**) → ③ **결정론적 순회**(엔진은 EvalContext만 참조, 외부 I/O 0). 조건은 **JSON-Logic류 DSL**(임의코드 금지). context는 `rule_hits.eval_context`에 스냅샷 저장 → 재현·감사. 상세: `llm_wiki/_context/rule-engine.md`. (기술 §4.2(d) / 요구사항 FR-RA-08~10)
- **인가 = 기능 단위(Capability) RBAC**: 역할이 아니라 5개 Capability(`team_aggregate`·`accounting_review`·`rule_view`·`rule_activate`·`governance_view`)로 판정. **유효능력 = 역할 기본값 ∪ 개인 추가부여(`users.extra_capabilities`)** — 예: `acc`=회계+룰열람+팀취합, `acclead`=회계+룰열람+룰활성. 룰콘솔은 열람(`rule_view`)/활성(`rule_activate`) 분리. DRF `HasCapability` 파생 권한으로 백엔드 강제, `/api/me`에 `capabilities` 노출, 프론트는 `useCan()`로 게이트. **Django admin에서 사용자별 `extra_capabilities` 체크박스 부여**. (기술 §3.1a)

---

## 3. 상태 보드 (Status Board) — _최종 갱신: 2026-08-04_

작업 진행/추적용. **의미 있는 진척마다 이 섹션을 갱신**한다.

| 영역 | 상태 | 비고 |
|---|---|---|
| 문서: Risk Review 2단계 반영 | ✅ 완료 | 요구사항·기술·기획 3문서 + 화면설계서 일관 |
| 모노레포 스캐폴드 | ✅ 부팅 가능 | `docker compose config`·`py_compile` 통과 |
| 프론트 6개 화면(S-01~06) | ✅ 빌드 통과 | mock 데이터 렌더. `npm run build` OK |
| Django 도메인 모델 | ✅ 구현 완료 | 8개 도메인 18개 테이블(실 필드·FK·제약·마이그레이션). `RuleHit.eval_context/flags/schema_version/builder_version` + `0002` 마이그레이션 반영. 설계 문서 `.personal/데이터베이스_저장소_설계문서.md` |
| FastAPI Agent 로직 | 🔲 stub | `apps/ai/app/agents/*`·`mcp/tools.py` 대부분 자리표시자 |
| 프론트 ↔ 백엔드 연동 | 🚧 진행 중 | **S-04 Rule 콘솔 3개 탭 전 구간 실 API 연동 완료**(초안 편집·저장, 검증셋·시뮬레이션 실행/보고서, Active 승인·버전이력·롤백, 작성 대화 로그). S-03 검토 화면은 RAG 보고서·EvalContext 스냅샷 연동. 나머지 화면 순차 진행 |
| 이상탐지 실학습/RAG upsert | 🔲 미착수 | IsolationForest 래퍼·Chroma heartbeat까지만 |
| 가맹점 업종 구분 시스템 | 📄 문서화 완료 / 🔲 구현 미착수 | 3개 명세 반영. `classify_merchant` Tool·`merchant_categories` 캐시·카카오/웹 연동 필요 |
| 룰 그래프(트리) 도메인 | ✅ 1차 완료 | scope별 버전·DRAFT 복제/원복·노드 삭제·자동 저장·**DSL 쉽게보기(`RuleNode.condition_text`)** 에 더해 **검증 시뮬레이션 도메인**(`RuleTestCase`/`RuleSimulationRun`/`RuleSimulationResult` — 실행 스냅샷+해시 보존, 낡은 결과 표시)과 **승인 흐름**(Active 요청 시 검토자 코멘트·스코프당 승인대기 1건 제한, 활성자/검토자 추적, 버전 이력 롤백) 구현. 구조 시각화는 위→아래 스크롤 플로우차트(순환 감지 포함) |
| 화면 임시 비활성화 | ⏸ 규정 문서 관리(S-?/`/policy-docs`) | 실 API 미연동(mock 전용)이라 사이드바 메뉴·라우트를 주석 처리. 화면 파일(`PolicyDocuments.tsx`)은 그대로 두었고, `App.tsx` import·라우트와 `Sidebar.tsx` MENU 한 줄만 되살리면 복구 |
| 시연 시드 데이터 | ✅ 완료 | 룰 그래프 4계열(GLOBAL v1~v3·기업업무추진비 v1~v2·회식비 활성+초안·출장비 승인대기) + 작성 대화 로그, 정산 84건(회계팀 자체 지출 포함)·검토 대기 30건·검토 이전처리 10건, 하이라이트 3건은 RAG 검증 보고서(마크다운)+실제 EvalContext 스냅샷(`rule_hits`). **모든 거래일자는 이번 달 1~30일 안에 배치**(`seed.at()`) — 팀 통계·검토 이력의 "이번 달" 필터와 정합 |
| 화면 데이터 스코프 규약 | ✅ 정리 완료 | "이번 달" 경계는 `web/src/lib/period.ts`에서만 정의(하드코딩 월 상수 제거). **S-01 내 지출**=오늘이 속한 달(단순 월 기준, 일자 무관). **S-02 팀 통계 대시보드**(KPI·예산)=팀·이번달·`REJECT` 제외 **전 상태** / **S-02 취합 목록**=팀·이번달·`TEAM_*`만. **S-03 이전 처리**=이번 달 회계 결정 완료 건(`api/settlements.ts:REVIEW_DECIDED_STATUSES`) |
| 팀 예산(TeamBudget) 정합 | ✅ 수정 완료 | 한도만 DB, 사용액은 팀·월·`REJECT` 제외 Settlement 집계(`TeamBudgetView`). **불변식 2개**: ① 팀 총한도(`category=''`) = 과목 한도 합 ② 과목 사용 합 = 총 사용액. 시드는 실제 집계에서 한도를 역산(`seed.py` BASE_USAGE_RATE)해 내역이 바뀌어도 어긋나지 않게 하고, **6개 과목 전부** 예산 행을 만든다(과거 `업무활성` 누락으로 항목 합 ≠ 총액이었음). 예산 행 없는 과목 지출은 API `unbudgetedUsed`로 노출 |
| 기능 단위(Capability) RBAC | ✅ 백엔드+프론트 완료 | `Capability` 4종·`extra_capabilities`·`HasCapability` 권한·`/api/me` 노출·seed 반영. 프론트: `useCan()`로 Sidebar·팀취합·검토·룰활성 게이트 전환(role 문자열 제거). mock은 역할 기본값, 실 모드는 `/api/me` capabilities |

다음 후보: 도메인 모델·마이그레이션 → 정산 상태전이 서비스 → Draft Agent(비전) → Risk Review 2단계 실동작.

---

## 4. 프로젝트 컨텍스트 구조 (llm_wiki) — 에이전트 자동 생성·활용

`llm_wiki/`는 이 프로젝트 컨텍스트의 **단일 진실 원천(SoT)**. 에이전트/Claude는 **`llm_wiki/_index.md`(색인)를 세션 시작 시 먼저 읽고**, 컨텍스트를 바꾸면 해당 문서와 색인 행을 함께 갱신한다.

```
llm_wiki/
├── _index.md            ← 컨텍스트 색인/매니페스트 (에이전트가 읽고 갱신하는 진입점)
├── 요구사항_명세서.md    ┐ 권위(authored) 스펙 문서 — SoT
├── 기술명세서.md         │  (권위 범위·버전·상태는 _index.md 표에서 관리)
├── 기획_확장안_v2.md     ┘
├── 화면설계서/           ← 압축해제 .docx (본문 word/document.xml, 추출 레시피는 CLAUDE.local.md)
├── figma_mockup/         ← 화면 목업 SVG (참고용, 픽셀 매칭 불필요)
└── _context/            ← 에이전트 생성 파생 컨텍스트 (결정 로그·용어집 등, 필요 시 생성)
```

**자동 생성·갱신 프로토콜(에이전트 규약):**
1. **세션 시작**: `_index.md`를 읽어 어떤 컨텍스트가 어디에 있는지·최신 상태를 파악한다.
2. **컨텍스트 변경**: 결정·스펙이 바뀌면 **① 권위 문서 본문 + ② `_index.md`의 해당 행(버전/상태/최종갱신)** 을 같은 커밋에서 함께 갱신한다. 세 스펙 문서 간 상충 금지.
3. **새 cross-cutting 컨텍스트**(결정 로그, 용어집, 상태머신 캐논 등): `_context/<slug>.md`로 생성하고 `_index.md`에 등록한다. (권위 스펙 문서와 중복 서술 금지 — 파생/요약만)
4. **파일명 규칙**: 권위 스펙은 한글 문서명 유지, 에이전트 생성물은 `_` 접두(예: `_index.md`, `_context/decisions.md`)로 구분.

- 외부 참조(레포에 없음): WBS.xlsx(2026-07-20~09-03), 프로젝트 기획서, 수집 데이터 보고서(AI Hub 합성데이터 벤치마크), 법인카드 사용 규정 `TIGER-REG-2026-003`.

---

## 5. ⚠️ tiger_inc = RAG 소스 데이터 (열람 규칙)

`tiger_inc/`는 시스템이 **RAG로 검색·활용할 사내 규정/조직 데이터**다(코드/설계 산출물 아님).

- **해당 문서를 직접 편집·작성하는 작업이 아닌 한 열람하지 않는다.** (컨텍스트 오염 방지)
- 규정 값이 필요하면 실제 런타임에선 Chroma(`policy_docs`/`case_history`/`tax_refs`)를 거친다. 코딩 중 규정 내용을 추측해 하드코딩하지 말 것.
- 포함: `법인카드_사용규정_타이거.md`, `부서소개.md`, `조직도.md`, `직급체계.md`, `타이거_조직설계_상세기획서.md`.

---

## 6. 자주 쓰는 명령

```bash
# 전체 스택 (repo 루트)
docker compose up --build            # 웹 :5173 / nginx :8080 / core :8000 / ai :9000 / chroma :8001
docker compose down [-v]             # 종료 (-v: 볼륨까지)
docker compose config                # compose 문법 검증

# 프론트 (apps/web) — 이 머신에선 --prefix 절대경로 권장(§CLAUDE.local.md)
npm install --prefix apps/web
npm run dev --prefix apps/web        # Vite dev (HMR)
npm run build --prefix apps/web      # tsc 타입체크 + vite build

# Django (core)
docker compose exec core python manage.py migrate
docker compose exec core python manage.py createsuperuser
```

---

## 7. 규약

- 코드/주석은 주변 코드의 밀도·스타일에 맞춘다. 각 stub 파일 docstring에 대응 문서(§ 참조)를 남긴다.
- 요구사항/화면 변경은 §4 문서에 먼저 반영 후 코드에 반영(문서가 SoT).
- 개인 로컬 환경 노트·명령 tip은 `CLAUDE.local.md`(git 미추적) 참고.

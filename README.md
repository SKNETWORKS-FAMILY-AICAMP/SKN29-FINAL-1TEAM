# 법인카드 정산 자동화 플랫폼 (Hybrid AI)

법인카드 정산 업무(입력 → 검토 → 확정)를 **3개 AI Agent + 결정론적 룰 엔진 + 사람 최종 확정**으로
자동화하는 사내 플랫폼. 가상기업 "타이거 주식회사" 페르소나로 구성돼 있다.

```
브라우저 ─► Nginx ─┬─► React SPA (Vite)
                   └─► Django + DRF   = System of Record (확정 데이터·상태머신·RBAC·ERP 전표안)
                                │
                                └─► FastAPI = AI Orchestrator (내부 전용)
                                      ├─ Draft / Rule / Risk Review Agent
                                      ├─ 단일 FastMCP 서버 (도구 12종)
                                      └─ 비지도 이상탐지 서빙
   PostgreSQL = 확정 데이터 SoT      Chroma = 규정·사례 임베딩(RAG)
```

- 문서 정본은 [`llm_wiki/`](llm_wiki/) — 시작점은 [`llm_wiki/_index.md`](llm_wiki/_index.md).
- 팀 공용 개발 컨텍스트·상태 보드는 [`CLAUDE.md`](CLAUDE.md).

---

## 1. 빠른 시작

```bash
cp .env.example .env          # OPENAI_API_KEY 등은 §7 참고 — 없어도 부팅은 된다
docker compose up --build     # 최초 빌드는 수 분

docker compose exec core python manage.py seed --fresh   # 시연 데이터 (§2)
```

→ http://localhost:5173 에서 `kim` / `pass1234` 로그인.
프론트를 **실제 백엔드에 붙이려면** `.env`의 `VITE_USE_MOCK=false` (기본값은 `true` = 목업).

`core`는 기동 시 `migrate`를 자동 수행한다.

---

## 2. 시드 데이터 — 목적이 정반대인 둘

**둘 중 무엇을 보여줄 것인지 먼저 정하고 고른다.** 서로 상대의 데이터를 지운다.

| | `seed` | `seed_clean` |
|---|---|---|
| 만드는 상태 | **시연용 회사** — 데이터가 가득 찬 운영 중 조직 | **막 설치한 회사** — 사람과 기본 게이트만 |
| 정산 | 87건 (전 상태 분포 · 검토 대기 30 · 이전 처리 10 · 하이라이트 3) | 0건 |
| 룰 그래프 | 4계열 (GLOBAL v1~v3 · 기업업무추진비 v1~v2 · 회식비 활성+초안 · 출장비 승인대기) + TEST | **`DEFAULT GATE` 1개만** |
| 규정 문서 | 없음(적재는 §4에서 별도) | 0건 |
| 팀 예산 | 6개 과목 전부 | 없음 |
| 이럴 때 쓴다 | 화면을 채워 보여줄 때 — 검토 워크스페이스·버전 이력·롤백·시뮬레이션 | **규정 업로드 → Rule Agent가 룰을 만드는 흐름**을 처음부터 시연할 때 |

> 제품이 미리 제공하는 룰은 **`DEFAULT GATE` 하나뿐**이다. 과목별 세부 룰은 고객이 자기 규정
> 문서를 올리면 Rule Agent가 만든다. `seed`의 4계열은 **시연용 예시**지 기본 제공물이 아니다.

### 명령

```bash
# ── 시연 데이터 한가득 ───────────────────────────────────────────
docker compose exec core python manage.py seed --fresh
#   --fresh 없이 돌리면 기존 데이터 위에 얹는다. 보통은 --fresh를 쓴다.
#   내부적으로 seed_rules + PolicyTable 적재까지 함께 수행한다.

# ── 막 설치한 회사 상태 ─────────────────────────────────────────
docker compose exec core python manage.py seed_clean --dry-run   # 지울 건수만 보고 멈춤
docker compose exec core python manage.py seed_clean

# ── 부분 시드 (위 둘이 내부에서 호출하지만 단독 실행도 된다) ──────
docker compose exec core python manage.py seed_rules [--no-test]   # 룰 그래프만
docker compose exec core python manage.py seed_policy_tables       # 규정 별표(임계값)만

# ── 계정 ────────────────────────────────────────────────────────
docker compose exec core python manage.py createsuperuser
docker compose exec core python manage.py ensure_service_account          # ai → core 쓰기 계정
docker compose exec core python manage.py ensure_service_account --check  # 401 날 때 진단
```

### 로그인 계정 (두 시드 공통, pw `pass1234`)

시드를 갈아끼워도 헤매지 않도록 `seed`와 `seed_clean`이 같은 계정을 만든다.

| 계정 | 역할 | 기본 Capability | 볼 수 있는 것 |
|---|---|---|---|
| `kim` | 임직원(영업팀) | — | 내 지출 / 팀 예산 현황 |
| `lead` | 팀장(영업팀) | `team_aggregate` | 팀 취합 + 보완요청·반려·제출 |
| `acc` | 회계 담당자 | `accounting_review`, `rule_view` | 검토 워크스페이스 · 룰 콘솔(열람) |
| `acclead` | 회계팀장 | + `rule_activate`, `ai_lab` | 룰 ACTIVE 승인·롤백 · AI-LAB |
| `exec` | 운영진 | `governance_view` | 거버넌스 대시보드 |

> **인가는 역할이 아니라 Capability로 판정**한다 — `유효능력 = 역할 기본값 ∪ 개인 추가부여`.
> Django Admin에서 사용자별 `extra_capabilities`를 체크박스로 더 줄 수 있다.
> 백엔드에서도 강제된다(DRF `HasCapability`). 회원가입 화면은 없다 — 계정은 CLI/Admin에서만.

### 서비스 계정 (ai → core 쓰기)

룰 그래프 DRAFT 저장·규정 적재 결과 회신은 사람 세션이 없으므로 전용 계정 하나(`rule-agent`,
capability `rule_view`만)로 JWT를 받는다.

```bash
# .env에 AI_SERVICE_PASSWORD를 채운 뒤 ─ env 변경은 컨테이너 재생성이 먼저다
docker compose up -d --force-recreate core ai
docker compose exec core python manage.py ensure_service_account
```

재생성을 건너뛰면 core만 옛 env로 돌아 **원인과 동떨어진 401**이 난다.

---

## 3. 접속 주소

| 대상 | URL | 비고 |
|---|---|---|
| 웹앱(개발) | http://localhost:5173 | Vite dev, HMR |
| 통합 진입(Nginx) | http://localhost:8080 | prod-like (`/`, `/api`) |
| Django Admin | http://localhost:8000/admin/ | 슈퍼유저 필요 |
| Core API health | http://localhost:8000/api/health/ | |
| AI health / docs | http://localhost:9000/health · /docs | 내부 전용(디버깅 노출) |
| AI-LAB (관리자) | http://localhost:5173/ai-lab | `ai_lab` 권한 (회계팀장 기본) |
| PostgreSQL | localhost:5432 | settlement / settlement |
| Chroma | http://localhost:8001 | |

---

## 4. RAG 규정 적재 — 경로가 둘이다

규정 문서를 검색 가능한 상태로 만드는 작업. 한 번 적재하면 유지되며, 그때부터 Rule/Risk Agent의
근거 검색과 AI-LAB RAG 탭이 실제 결과를 낸다.

### ① 화면 업로드 (실제 제품 흐름)

**규정 문서 관리**(`/policy-docs`, `rule_view` 권한) → PDF 업로드 → 백그라운드로
`파싱(docling) → 교정 → 조 단위 청킹 → 임베딩 → Chroma upsert → 조항 추출 → 룰 자동 생성 트리거`.
상태는 목록 폴링으로 확인한다.

- 문서당 수십 초~수 분(docling 파싱이 대부분).
- **ai 재시작 시 진행 중 작업은 유실**된다 → `PARSING`/`INDEXING`에 멈추면 "재색인"으로 복구.
- 업로드 시 scope를 골랐고 **최초 적재**일 때만 룰 자동 생성이 돈다(재색인은 건너뜀).

### ② CLI 배치 (평가·재현용 — 미리 만들어 둔 파싱 덤프 재적재)

```bash
# 무엇이 어디로 갈지만 확인 — API·Chroma 미호출, 과금 없음 (항상 먼저)
docker compose exec ai python -m app.rag.embedding.index --dump /data/docling_eval/output --dry-run

# 실제 적재 (OpenAI 임베딩 호출 → 과금)
docker compose exec ai python -m app.rag.embedding.index --dump /data/docling_eval/output

# 적재 현황
docker compose exec ai python -m app.rag.embedding.index --peek
```

문서 11종 · 888청크 기준:

| 컬렉션 | 청크 | 문서 |
|---|---|---|
| `policy_docs` | 103 | 법인카드 / 업무추진비 / 출장비 / 회식 규정 |
| `tax_refs` | 730 | 법인세법 · 부가가치세법 · 여신전문금융업법 |
| `org_docs` | 55 | 부서소개·조직도·직급체계·조직설계 (판정 근거로는 인용하지 않음) |

전량 1회 약 30만 토큰(`text-embedding-3-large`).

### 다시 돌려야 하는 때

청크 id가 `{doc_id}#{조}#{순번}`으로 결정론적이라 같은 입력 재실행은 upsert일 뿐 중복이 안 쌓인다.
아래가 바뀌면 재적재가 필요하다:

| 바뀐 것 | 왜 |
|---|---|
| 임베딩 모델·차원 | 벡터 신원(`embedder_version`)이 달라짐 — 섞이면 배치가 멈춘다 |
| 청킹 예산·교정 로직 | 청크 경계 → **id가 달라짐 → 옛 청크가 그대로 남는다**(upsert는 삭제를 안 함) |
| 규정 문서 자체 | 새 파싱이 먼저 |

> ⚠️ 같은 문서를 ①과 ② 두 경로로 번갈아 넣지 말 것. `doc_id`가 각각 파일 해시 / `dump:<이름>`이라
> **같은 내용이 다른 id로 두 벌** 들어간다.

### 데이터는 어디에 남나

Chroma는 named volume `skn-settlement_chromadata`. `docker compose down`·재부팅·`up --build`로는
유지되고, **`down -v`는 삭제**된다(Postgres `pgdata`도 함께 — 그 뒤엔 migrate + seed + 적재를 다시).

---

## 5. 구현 상태 한눈에

| 영역 | 상태 | 메모 |
|---|---|---|
| Django 도메인 모델 · 상태머신 · Capability RBAC | ✅ | 8도메인 18테이블, 4단계 상태머신 |
| 룰 엔진 (EvalContext 조립 → 그래프 선택 → 결정론적 순회) | ✅ | 제출이 판정을 자동으로 이어 돌린다 |
| 룰 콘솔 (S-04) 3개 탭 | ✅ 실 API | 초안 편집·시뮬레이션·ACTIVE 승인·버전 롤백·대화형 수정 |
| Rule Agent (규정 → 룰 그래프 DRAFT) | ✅ | RAG → LLM 툴콜링 → 결정론적 조립 → 저장 |
| Draft Agent (초안 작성) | ✅ (비전 제외) | 가맹점 업종 구분 연동 완료 |
| Risk Review Agent (① 이상탐지 → ② RAG 내규 검증) | ✅ 실동작 | **①은 학습된 모델 파일이 있어야 실값** — §6 참고 |
| 규정 문서 업로드 → 인덱싱 → 룰 트리거 | ✅ | §4-① |
| RAG 파싱·청킹·임베딩 전략 | ✅ 구현+평가 완료 | 채점 노트북은 `docling_eval/` |
| 에이전트 컨텍스트 툴 (도메인 카탈로그 주입) | 🔶 **미머지** | `feature/context-build-tool` 브랜치에만 있다 — §6.5 |
| 검토 워크스페이스(S-03) · 규정 문서 관리(S-05) · 팀 취합(S-02) | ✅ 실 API | |
| 내 지출(S-01) · 내역 불러오기 | ✅ 실 API | ERP 결제기록 수집 → DRAFT 생성 |
| 예산 관리 · 카드 관리 · 거버넌스 대시보드 · ERP 전표 확인 | 🚧 목업 | §6 |
| 증빙자료 추출 Agent | 🔲 미착수 | 저장 구조(`Attachment`)와 조립기 연결만 완료 |

---

## 6. 미완 · 미연동 (알고 쓰는 한계)

### 6.1 실물이 없어서 안 도는 것

- **이상탐지 모델(`anomaly.pkl`)이 레포에 없다.** `apps/ai/var/`는 `.gitignore` 대상이라 클론 직후엔
  파일이 없고, 그러면 Risk Review 1차가 **stub으로 통과**한다(`anomaly_score: 0.0`,
  `note: "no trained model (stub)"`). 2차 RAG 내규 검증은 그대로 돈다.
  학습해서 넣으려면:
  ```bash
  docker compose exec ai python -m app.ml.train --train-csv <경로> --test-csv <경로>
  # → /app/var/models/anomaly.pkl (호스트 apps/ai/var/models/)
  ```
  기존 pkl을 얹어 쓸 경우 `feature_columns` 개수(현재 24)와 sklearn 버전이 맞는지 확인할 것 —
  옛 pkl은 `feature_stats`가 없어 **feature 기여도가 빈 배열**로 나온다.
- **`case_history`(유사 과거 사례) 컬렉션은 골든 시드 10건뿐**이다. 실 결정이력을 적재하는
  파이프라인이 없다. `docker compose exec ai python -m app.rag.case_store --upsert`로 넣는다.
- **`OPENAI_API_KEY`가 없으면** Draft/Rule/Risk Agent와 임베딩이 전부 멈춘다(부팅은 된다).
- **`KAKAO_REST_API_KEY`가 없으면** 캐시에 없는 가맹점은 업종 미확정으로 남고, 금지업종·주의업종
  룰이 판정할 근거가 사라진다(경고 로그 1회 후 조용히 건너뜀).

### 6.2 화면이 아직 목업인 곳

실 API 없이 화면 안 상수로 도는 화면들. 백엔드 집계·엔드포인트가 없다.

| 화면 | 상태 |
|---|---|
| 예산 관리 (`BudgetManagement`) | 전 팀 예산 조회 화면 전체가 목데이터. 수정 기능은 권한 모델 미정으로 제외 |
| 카드 관리 (`CardManagement`) | 카드 배정·회수 화면 전체 목데이터(`Card` 모델은 있음) |
| 거버넌스 대시보드 (`GovernanceDashboard`) | 차트·KPI 전부 목데이터. `/api/dashboard/EXECUTIVE/`는 일부 집계만 반환 |
| ERP 전표 확인 (`ErpVoucherConfirm`) | 화면은 로컬 상태로만 동작. 서버는 CONFIRMED 시 `ErpVoucher` DRAFT를 실제로 만들고 `GET /api/erp/vouchers/`로 읽을 수 있는데 화면이 안 붙어 있다 |
| 알림 패널 (`NotificationPanel`) | `data/mock`의 고정 목록 |

### 6.3 연동 gap (`VITE_USE_MOCK=false`로 붙일 때)

1. **데이터 스코프가 서버에서 안 갈린다.** `/api/settlements/`는 `submitted_by`·`team` 쿼리
   파라미터를 받지만 로그인 사용자로 **자동 제한하지 않는다**. "내 지출 / 우리 팀"은 프론트가
   client-side로 거른다. 서버측 스코프 쿼리가 필요하다.
2. **쓰기 후 재조회가 없다.** 상태 전이는 낙관적 로컬 반영만 하고 서버를 다시 읽지 않는다.
3. **id 타입 불일치.** 서버는 정수, 프론트 타입은 문자열(런타임 동작엔 문제없음).
4. **로딩/에러 UI.** `loading` 플래그만 있고 화면별 스피너·에러 처리가 없다.
5. **세션 인증에서 CSRF를 생략**하고 있다(dev 편의) — 운영 전 재활성 필요.

### 6.4 도메인 차원의 미완

- **비전 판독(영수증·증빙문서)이 흐름에 안 붙어 있다.** `read_receipt`·`read_evidence_document`는
  MCP 도구로 구현·노출돼 있지만 Draft Agent나 정산 저장 경로에서 **호출하지 않는다**.
- **증빙자료 추출 Agent 미착수.** `Attachment.extracted`(EvalContext dot-path → 값) 저장 틀과
  조립기 연결은 끝났고, 채우는 주체가 없다.
- **EvalContext 사실 조립이 부분적이다.** 47개 경로 중 조립되는 건 절반가량 —
  참조한 경로가 `null`이면 미해소 가드가 판정을 「검토 필요」로 낮춘다(조용한 통과는 없다).
- **가맹점 업종 구분이 Draft에만 붙어 있다.** Risk Review 연동은 미착수.
- **`/submit`이 팀 동일성을 강제하지 않는다.**
- **Rule Agent가 기존 계열에 버전을 얹지 못한다** — 항상 새 계열(v1) DRAFT를 만든다.
- **별표 축 정합 결함 2건**(2026-08-20 발견, 미해결): 로컬 DB의 한도 별표 3종 축이
  `user.position`(스키마에서 사라진 경로)이라 직책과 무관하게 와일드카드 기본값으로 떨어진다
  (재시드로 해소) / `dining_per_person_limit_table`의 축 `category.scope`는 코드에 있는데
  스키마에 없다.

### 6.5 아직 main에 없는 브랜치 작업

| 브랜치 | 내용 |
|---|---|
| `feature/context-build-tool` | **에이전트 컨텍스트 툴 P0** — DSL 연산자·EvalContext 경로(타입·설명 포함)·별표 축과 적재여부·판정 선택지·플래그 어휘를 live 모델에서 조립해 Rule Agent 프롬프트에 주입. `domain/context` + `app/context`, 회귀 23건. 위 §6.4의 별표 축 결함 2건도 이 작업에서 발견됐다. 캐논은 브랜치의 `llm_wiki/_context/agent-context-tool.md` |

다른 `feature/*` 브랜치도 여럿 남아 있다 — `git log --oneline main..<브랜치>`로 확인할 것.

---

## 7. 자주 쓰는 명령

```bash
# ── 로그 ─────────────────────────────────────────────
docker compose logs -f core ai        # 실시간
#   호스트 ./logs/core.log · ./logs/ai.log 에도 파일로 쌓인다 (5MB×3 로테이션, git 미추적)
#   레벨을 올리려면 .env의 LOG_LEVEL=DEBUG 후 컨테이너 재생성

# ── 테스트 ───────────────────────────────────────────
docker compose exec ai python -m pytest -q                    # ai (FastAPI)
docker compose exec core python manage.py test domain         # core (Django)

# ── 마이그레이션 ─────────────────────────────────────
docker compose exec core python manage.py makemigrations
docker compose exec core python manage.py migrate

# ── 프론트 (호스트) ──────────────────────────────────
npm install --prefix apps/web
npm run dev   --prefix apps/web       # Vite dev
npm run build --prefix apps/web       # tsc 타입체크 + vite build

# ── 기타 ─────────────────────────────────────────────
docker compose config                 # compose 문법 검증
docker compose up --build core        # 개별 재빌드
docker compose down [-v]              # 종료 (-v: 볼륨까지 삭제)
```

---

## 8. 알려진 함정

| 증상 | 원인 · 회피 |
|---|---|
| `--dump /data/...`가 "No such file or directory" | **Git Bash가 `/data/...`를 윈도우 경로로 변환**한다. PowerShell을 쓰거나 앞에 `MSYS_NO_PATHCONV=1` |
| ai → core 요청이 401 | `.env`를 고치고 컨테이너를 재생성하지 않았다 → `docker compose up -d --force-recreate core ai` 후 `ensure_service_account --check` |
| 업로드한 PDF 내용이 무시된다 | `DOCLING_MOCK=1`이 켜져 있다. 파싱만 미리 떠둔 덤프로 대체되며 **문서명으로만** 덤프를 고른다. 화면 상단 노란 배너·`dump:` doc_id로 구분된다. **운영에서 절대 켜지 말 것** |
| 규정 PDF 업로드가 413 | nginx `client_max_body_size` — 기본 1MB로는 규정 PDF가 곧바로 막힌다(현재 50m로 설정돼 있음) |
| `down -v` 후 아무것도 안 보임 | DB·Chroma 볼륨이 삭제됐다. `migrate` → `seed` → RAG 적재를 다시 |
| 한글 경로 파일 작업이 깨진다 | Git Bash의 cp949 mojibake. PowerShell + 절대경로 사용 |

---

## 9. 디렉터리 구조

```
.
├── docker-compose.yml          # db · chroma · core · ai · web · nginx
├── .env.example                # 환경변수 + 각 값의 의미·주의사항 (→ .env로 복사)
├── infra/nginx/                # 리버스 프록시 ( / → web, /api → core )
├── logs/                       # 컨테이너 로그 바인드 (git 미추적) — 디버깅은 여기부터
├── llm_wiki/                   # 설계·기획 산출물. 진입점 _index.md
│   ├── docs/                   #   팀 관리 기준 문서 (요구사항·기술명세서·기획·RULE 명세서)
│   ├── _context/               #   AI가 관리하는 구현 캐논·실측 기록
│   ├── 화면설계서/ · figma_mockup/
├── tiger_inc/                  # RAG 소스 데이터(사내 규정·조직 문서) — 직접 열람 자제
├── docling_eval/               # 파싱·청킹·임베딩 평가 노트북 + 파싱 덤프(적재 배치 입력)
├── daily_scrum/                # 주차별 진행 보고
└── apps/
    ├── web/                    # React + Vite + TS (SPA)
    │   └── src/{api,screens,components,context,lib,data}
    ├── core/                   # Django + DRF (SoR)
    │   ├── config/
    │   └── domain/
    │       ├── accounts/       #   users · teams · roles · capabilities · 직책/직급
    │       ├── cards/          #   cards
    │       ├── transactions/   #   transactions · receipts · 가맹점 업종 어휘(정본)
    │       ├── settlements/    #   settlements · events(상태머신) · attachments · ERP 수집
    │       ├── policies/       #   룰 그래프 · DSL · 엔진 · EvalContext · 별표 · 플래그 · 규정문서
    │       ├── risk/           #   risk_reviews · decision_labels
    │       ├── erp/            #   erp_vouchers
    │       └── common/         #   health · dashboard · 관리 명령(seed 등)
    └── ai/                     # FastAPI (AI Orchestrator, 내부 전용)
        └── app/
            ├── api/            #   /agent · /ml · /embeddings · /lab
            ├── agents/         #   draft · risk_review · rule_agent_v0
            ├── mcp/            #   단일 FastMCP 서버 + 도구 12종
            ├── rag/            #   parsing · chunking · embedding · retrieval · ingest
            ├── vision/         #   영수증·증빙문서 판독 (도구는 있으나 흐름 미연동)
            ├── ml/             #   비지도 이상탐지 + 레지스트리 + 학습 CLI
            ├── merchant/       #   가맹점 업종 분류 캐스케이드
            └── clients/        #   Django 내부 API 클라이언트 · 서비스 계정 인증
```

---

## 10. 설계 원칙

- **SoR은 Postgres 하나** — AI는 "제안"만 만들고, 확정 전이는 Django 서비스 레이어에서만.
- **관계형 = Django 경유 / 벡터 = Chroma 직접** — LLM·Tool의 Postgres 직접 SQL 금지.
- **FastAPI는 내부 전용** — 사용자 트래픽은 Django만 받는다.
- **동기 REST(MVP)** — 메시지 큐 없음. 임베딩·학습은 관리자 온디맨드 배치.
- **사람 확정 원칙** — 확신 통과 건도 회계 담당자 확정 없이는 `CONFIRMED`가 되지 않는다.
- **엔진은 최종반려를 만들지 않는다** — 룰 노드가 `REJECT`여도 상태는 「보완요청」. 재제출 불가
  단말은 회계 담당자만 찍는다.
- **`null`은 「거짓」이 아니라 「모른다」** — 판정이 참조한 사실이 `null`이면 미해소 가드가
  「검토 필요」로 낮춘다. 모르는 걸 안전하다고 단정하지 않는다.
- **예산·정책은 통제(차단)가 아니라 지표·추천으로만** 반영한다.
- **룰은 사전 탑재하지 않는다** — 기본 게이트 1개 + 고객 규정 문서에서 Rule Agent가 생성.

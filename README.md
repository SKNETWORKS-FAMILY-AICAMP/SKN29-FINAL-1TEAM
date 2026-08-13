# 법인카드 정산 자동화 플랫폼 (Hybrid AI)

기술명세서(`llm_wiki/docs/기술명세서.md`) 아키텍처 기준 모노레포입니다.

- **React SPA** ─► **Nginx** ─► **Django(DRF)** = System of Record(확정 데이터·상태머신·RBAC)
- **FastAPI** = AI Orchestrator (3-Agent + 단일 FastMCP 서버 + ML 이상탐지 서빙) — *내부 전용*
- **PostgreSQL** = 확정 데이터 SoT / **Chroma** = 규정·사례 임베딩(RAG)

> 현재는 **부팅 가능한 스캐폴드**입니다. 도메인 모델·API·Agent 로직은 대부분 `TODO`/`stub`이며,
> 각 파일 docstring에 기술명세서 참조가 달려 있습니다.

---

## 디렉터리 구조

```
.
├── docker-compose.yml         # 로컬 개발 오케스트레이션
├── .env.example               # 환경변수 예시 (→ .env 로 복사)
├── infra/
│   └── nginx/nginx.conf        # 리버스 프록시 ( / → web, /api → core )
└── apps/
    ├── web/                    # React + Vite + TS (SPA)
    ├── core/                   # Django + DRF  (SoR, 상태머신, RBAC, ERP 전표안)
    │   ├── config/             #   프로젝트 설정 (settings/urls/wsgi/asgi)
    │   └── domain/             #   도메인 앱 (기술명세서 §3.1 테이블 매핑)
    │       ├── common/         #     health 등 공통
    │       ├── accounts/       #     users/teams/roles
    │       ├── cards/          #     cards
    │       ├── transactions/   #     transactions/receipts
    │       ├── settlements/    #     settlements/settlement_events (상태머신)
    │       ├── policies/       #     policies/rules/rule_hits
    │       ├── risk/           #     risk_reviews/decision_labels
    │       └── erp/            #     erp_vouchers/audit_logs
    └── ai/                     # FastAPI (AI Orchestrator)
        └── app/
            ├── api/            #   REST 라우터 (/agent, /ml, /embeddings)
            ├── agents/         #   Draft / Rule / Risk Review Agent
            ├── mcp/            #   단일 FastMCP 서버 + 도구 8종
            ├── ml/             #   비지도 이상탐지(IsolationForest) + 레지스트리
            ├── rag/            #   Chroma 클라이언트
            └── clients/        #   Django 내부 read API 클라이언트
```

---

## 실행 방법

### 사전 준비
- Docker / Docker Compose (Docker Desktop 등)

### 1) 환경변수 준비
```bash
cp .env.example .env
# 필요 시 OPENAI_API_KEY 등만 채우면 됩니다. (스캐폴드 부팅에는 없어도 동작)
```

### 2) 빌드 & 실행
```bash
docker compose up --build
```
> 최초 빌드는 이미지·의존성 설치로 다소 시간이 걸립니다. `core`는 기동 시 자동으로 `migrate`를 수행합니다.

### 3) 접속
| 대상 | URL | 비고 |
|---|---|---|
| **웹앱(개발)** | http://localhost:5173 | Vite dev, HMR |
| **통합 진입(Nginx)** | http://localhost:8080 | prod-like ( / , /api ) |
| Core API health | http://localhost:8000/api/health/ | Django |
| AI health / API docs | http://localhost:9000/health · http://localhost:9000/docs | FastAPI(내부용, 디버깅 노출) |
| Django Admin | http://localhost:8000/admin/ | 슈퍼유저 생성 후 |
| PostgreSQL | localhost:5432 | settlement/settlement |
| Chroma | http://localhost:8001 | 벡터 스토어 |

### 4) 종료
```bash
docker compose down          # 컨테이너 종료
docker compose down -v        # 볼륨(DB/Chroma 데이터)까지 삭제
```

---

## 자주 쓰는 명령

```bash
# 로그 보기
docker compose logs -f core
docker compose logs -f ai

# Django 관리 명령
docker compose exec core python manage.py createsuperuser
docker compose exec core python manage.py makemigrations
docker compose exec core python manage.py migrate

# 개별 재빌드
docker compose up --build core
```

---

## 관리자(superuser) 생성 & Django Admin

Django 기본 관리자 페이지(`/admin/`)에서 사용자·팀·정산·상태이력·룰 그래프·감사로그 등 **모든 도메인 데이터를 직접 조회·편집**할 수 있습니다.
> 이 서비스는 **회원가입 화면을 제공하지 않습니다.** 계정 생성은 아래 CLI(`createsuperuser`) 또는 Django Admin에서만 이뤄집니다.

### 1) 슈퍼유저 생성
```bash
docker compose exec core python manage.py createsuperuser
# username · (email 생략 가능) · password 입력
```
> 로컬 venv로 직접 실행 시:
> `PYTHONPATH=apps/core DJANGO_SETTINGS_MODULE=config.settings python -m django createsuperuser` (Postgres 연결 필요)

### 2) 관리자 페이지 접속
- **http://localhost:8000/admin/** 에서 위 계정으로 로그인
- 커스텀 User(역할 `EMPLOYEE`/`TEAM_LEAD`/`ACCOUNTANT`/`EXECUTIVE` · 팀), 정산·상태머신 이력, 룰 그래프(노드·라우팅·버전), Risk 결과, ERP 전표(안), 감사로그를 관리
- 계정 추가 시 하단 **"정산 플랫폼"** 섹션에서 역할·팀을 지정

### 3) 데모 데이터 주입(선택)
```bash
docker compose exec core python manage.py seed
# → 사용자 kim / lead / acc / exec (pw: pass1234) + 정산 6건 + 룰 그래프 1개
```

> 프론트 로그인 화면(`/`)은 `VITE_USE_MOCK=false`일 때 **Django 세션 로그인**(사번=username / 비밀번호)으로 동작합니다. mock 모드에서는 역할선택 UI로 대체됩니다. 계정 생성은 회원가입 없이 CLI/Admin에서만.

### 데모 계정 & 권한(RBAC)
`seed` 생성 계정 (pw `pass1234`):

| 계정 | 역할 | 접근/권한 |
|---|---|---|
| `kim` | 임직원(영업팀) | 내 지출 / 팀 **예산 현황만**(개별 건 안내문) |
| `lead` | 팀장(영업팀) | 팀 개별 건 조회 + 제출/보완요청/반려 |
| `acc` | 회계 담당자 | 검토 워크스페이스·Rule 콘솔 (검토/확정) |
| `acclead` | **회계팀장** | 회계 권한 + **Rule ACTIVE 승인/롤백** |
| `exec` | 운영진 | 거버넌스 대시보드 |

> 권한은 서버에서도 강제됩니다 — 검토/확정=`IsAccountant`, Rule 승인/롤백=`IsAccountantLead`. (세션 인증은 dev 편의상 CSRF 생략 — 운영 전 재활성 필요)

---

## 프론트 ↔ Django 연동 (mock ↔ real)

프론트는 데이터 소스를 **`VITE_USE_MOCK` 플래그**로 전환합니다.

| 값 | 동작 |
|---|---|
| `true` (기본) | `data/mock.ts` + 로컬 상태로 동작 — **백엔드 없이** 화면 시연 가능 |
| `false` | 마운트 시 **`GET /api/settlements/`** 에서 fetch, 상태전이(submit/review/confirm)는 실제 Django로 전송 |

```bash
# 실제 연동으로 켜기 (Django·DB 기동 + 시드 후)
docker compose exec core python manage.py migrate
docker compose exec core python manage.py seed
VITE_USE_MOCK=false docker compose up web       # 또는 .env 에 VITE_USE_MOCK=false
```

연결 경로: 브라우저 → (vite proxy 또는 Nginx) → `/api/` → Django. 정산 목록은 `SettlementsContext`가 fetch해
`내 지출 / 팀 취합 / 검토(IN_REVIEW)` 3분류로 나눕니다. API 응답은 프론트 `Settlement`/`ReviewItem`과 camelCase로 정합(부서·시각·anomaly·RAG 근거 평탄화 포함).

> **아직 부족한 부분(연동 gap)** — `VITE_USE_MOCK=false`로 붙일 때 남는 항목:
> 1. **데이터 스코프 서버 미분리**: 세션 로그인·역할 권한은 적용됐으나, "내 지출/우리 팀" 목록은 여전히 프론트가 로그인명으로 client-side 필터(서버가 `submitted_by=현재유저`/팀으로 안 가름). 서버측 스코프 쿼리 필요.
> 2. **신규 지출 등록(F-1)**: 정산 생성 API가 거래(transaction) 선생성 전제라 프론트 draft만으론 미완 → 통합 create 엔드포인트 필요(현재 create는 낙관적 mock 유지).
> 3. **쓰기 후 재조회 없음**: 상태전이는 낙관적 로컬 반영만(서버 재fetch 안 함).
> 4. **id 타입**: 서버 id는 정수, 프론트 타입은 문자열(런타임 동작엔 무리 없음).
> 5. **로딩/에러 UI**: `loading` 플래그만 노출, 화면별 스피너/에러 처리 미구현.
> 6. **룰 콘솔·거버넌스**: 여전히 자체 mock(ruleConsoleMock) — `/api/rules` 연동·대시보드 집계 연결 미완.

---

## 설계 메모 (아키텍처 원칙)

- **SoR은 Postgres 하나** — AI는 "제안"만 만들고, 확정 전이는 Django 서비스 레이어에서만.
- **관계형=Django 경유 / 벡터=Chroma 직접** — LLM/Tool은 Postgres에 직접 SQL 금지 (FastMCP §5.1).
- **FastAPI는 내부 전용** — 사용자 트래픽은 Django만 받는다. Nginx는 `/api`를 core로만 프록시.
- **동기 REST(MVP)** — 별도 메시지 큐(Redis/Celery) 없음. 임베딩·학습은 관리자 온디맨드 배치.
- **Risk Review(MVP)** — 단순 이상탐지(비지도) 1차 → RAG 내규 검증 2차.
  지도학습(review_probability)·자동 재학습 피드백 루프는 **post-MVP 확장**.

# 법인카드 정산 자동화 플랫폼 (Hybrid AI)

기술명세서(`llm_wiki/기술명세서.md`) 아키텍처 기준 모노레포입니다.

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

## 설계 메모 (아키텍처 원칙)

- **SoR은 Postgres 하나** — AI는 "제안"만 만들고, 확정 전이는 Django 서비스 레이어에서만.
- **관계형=Django 경유 / 벡터=Chroma 직접** — LLM/Tool은 Postgres에 직접 SQL 금지 (FastMCP §5.1).
- **FastAPI는 내부 전용** — 사용자 트래픽은 Django만 받는다. Nginx는 `/api`를 core로만 프록시.
- **동기 REST(MVP)** — 별도 메시지 큐(Redis/Celery) 없음. 임베딩·학습은 관리자 온디맨드 배치.
- **Risk Review(MVP)** — 단순 이상탐지(비지도) 1차 → RAG 내규 검증 2차.
  지도학습(review_probability)·자동 재학습 피드백 루프는 **post-MVP 확장**.

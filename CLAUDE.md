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
- **상태머신(FR-ST-01)**: `DRAFT→SUBMITTED→RPA_JUDGED→(PENDING_CONFIRM/RETURNED/IN_REVIEW/REJECT)→CONFIRMED→ERP_VOUCHER_DRAFTED`. **REJECT=최종반려(재제출 불가)**, **RETURNED=보완요청(재제출 가능)** 구분.
- **예산·정책은 통제(차단)가 아니라 지표·추천으로만** 반영.
- **사람 확정 원칙**: 확신 통과 건도 회계 담당자 확정 없이는 CONFIRMED 불가.
- 영수증은 별도 OCR 없이 **OpenAI 비전**으로 직접 판독. Rule 적용은 결정론적 엔진, LLM은 Rule 생성 단계에서만.

---

## 3. 상태 보드 (Status Board) — _최종 갱신: 2026-07-22_

작업 진행/추적용. **의미 있는 진척마다 이 섹션을 갱신**한다.

| 영역 | 상태 | 비고 |
|---|---|---|
| 문서: Risk Review 2단계 반영 | ✅ 완료 | 요구사항·기술·기획 3문서 + 화면설계서 일관 |
| 모노레포 스캐폴드 | ✅ 부팅 가능 | `docker compose config`·`py_compile` 통과 |
| 프론트 6개 화면(S-01~06) | ✅ 빌드 통과 | mock 데이터 렌더. `npm run build` OK |
| Django 도메인 모델 | 🔲 stub | `apps/core/domain/*/models.py` docstring에 테이블 매핑만 |
| FastAPI Agent 로직 | 🔲 stub | `apps/ai/app/agents/*`·`mcp/tools.py` 대부분 자리표시자 |
| 프론트 ↔ 백엔드 연동 | 🔲 미착수 | `apps/web/src/api/client.ts` 엔드포인트 헬퍼가 연결 지점 |
| 이상탐지 실학습/RAG upsert | 🔲 미착수 | IsolationForest 래퍼·Chroma heartbeat까지만 |

다음 후보: 도메인 모델·마이그레이션 → 정산 상태전이 서비스 → Draft Agent(비전) → Risk Review 2단계 실동작.

---

## 4. llm_wiki 문서 활용 추적

각 문서의 **권위 범위(authority)**. 관련 변경 시 반드시 해당 문서를 함께 갱신하고, 세 문서 간 상충이 없도록 유지한다.

| 문서 | 버전 | 권위 범위 | 상태 |
|---|---|---|---|
| `llm_wiki/요구사항_명세서.md` | Draft v0.3 | 기능/비기능 요구사항(FR-*), Open Issue | 최신 · REJECT 상태 추가됨 |
| `llm_wiki/기술명세서.md` | Draft v0.1 | 아키텍처·데이터·API·FastMCP Tool·ML/RAG 파이프라인 | 유지 |
| `llm_wiki/기획_확장안_v2.md` | Draft v0.2 | 제품 기획·3-Agent 서비스 플로우·객체 모델 | 유지 |
| `llm_wiki/화면설계서/` | Rev.1 v1.1 | 6개 화면(S-01~06)·역할·상태머신 화면매핑. **압축해제된 docx 폴더** | 프론트 구현 기준 |

- 화면설계서는 `.docx`를 풀어놓은 폴더다. 본문은 `word/document.xml`에 있으며, 읽으려면 §CLAUDE.local.md의 추출 레시피 사용.
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

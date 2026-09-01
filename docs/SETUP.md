# 셋업·운영 가이드

[README](../README.md)의 "빠른 시작" 다음 단계 — 시드 데이터 전략, RAG 적재, 자주 쓰는 명령, 알려진 함정,
디렉터리 구조, 미완/미연동 항목까지 **개발·시연을 위한 심화 운영 내용**을 담는다.
설계 결정의 "왜"는 [`../CLAUDE.md`](../CLAUDE.md)와 [`../llm_wiki/_index.md`](../llm_wiki/_index.md)가 정본이다.

---

## 1. 접속 주소

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

## 2. 시드 데이터 — 회사의 "언제"를 고른다

이 제품의 핵심 서사는 **"규정 문서를 올리면 룰이 자라나고, 룰이 쌓일수록 자동 확정이 는다"**이다.
그래서 시연 데이터도 화면 단위가 아니라 **회사가 어느 시점에 있는가**로 나뉜다.

| | `seed_clean` — 초기 적용 | `seed_adopted` — 적용 완료 |
|---|---|---|
| **무엇을 시연하나** | **규정 업로드 → Rule Agent가 룰을 만드는 흐름** | **실제 정산 흐름과 판정** |
| 회사의 시점 | 방금 도입해 세팅만 끝난 상태 | 3개월째 굴러가는 상태 |
| 사용자·팀·카드 | 5명 / 3팀 / 카드 10장 | + 팀원 10명 (직책이 흩어져 있다) |
| 룰 그래프 | **`DEFAULT GATE` 하나뿐** | GLOBAL 게이트 v7 + 접대·회식·출장 그래프 (`DEFAULT GATE`는 ARCHIVED로 물러남) |
| 규정 별표(한도표) | 없음 | 11행 |
| 정산 | **0건** | **299건** (직전 3개월, 전표 278) |
| 결정 사례 | 없음 | **30건** (§2.2) |
| 예산 | 한도만 | 한도 + 3개월 실사용액 |
| 이 시드로 살아나는 화면 | 규정 문서 관리 · 룰 콘솔(빈 상태에서 시작) | 팀 취합 · 검토 워크스페이스 · 예산 · 거버넌스 · ERP 전표 |

> **둘은 서로의 데이터를 지운다.** `seed_adopted`는 안에서 `seed_clean`을 먼저 부른 뒤 그 위에
> 3개월을 얹는다 — 그래서 **로그인 계정은 둘이 같다.**

```bash
docker compose exec core python manage.py seed_clean --dry-run   # 지울 건수만 보고 멈춤
docker compose exec core python manage.py seed_clean

docker compose exec core python manage.py seed_adopted           # 2~3분
```

### 2.1 무엇이 "진짜"인가 — `seed_adopted`의 규율

**판정을 손으로 박지 않는다.** 상태·판정로그·전표·검토 이력은 전부 실제 상태 전이를 태워서
나온 결과다(`raise_to_team → submit → judge → review/confirm`). 시드는 **사실만 정하고 판정은
기대만 적으며**, 엔진이 다른 답을 내면 끝에 **불일치 목록을 출력한다.**

```
[경고] 시드가 기대한 판정과 엔진 결과가 다른 건 3개:
  - 회식 호프 갈매기 739,000원 기대=REVIEW 실제=RETURN [사례 A] · 창립기념 전사 회식
```

이 경고가 실제로 일을 했다. 「검토를 거쳐 승인」 시나리오 몇 건이 두 달 내내 성립하지 않고
있었는데(회식 1인당 한도 초과는 `REVIEW`가 아니라 `RETURN`이고, 심야·주말 룰은 게이트에서
사라졌다) 그게 이 목록으로 드러났다. **룰이 바뀌면 시드가 그 자리에서 알려준다.**

손으로 만드는 것은 둘뿐이고 둘 다 이유가 있다.
  · **시각** — `created_at`이 `auto_now_add`라 지난달 이력이 전부 오늘로 찍힌다. 결제일 기준으로 되돌린다.
  · **이상탐지 결과·AI 보고서** — Risk Review Agent를 수백 번 부르면 시연 준비에 수십 분과
    토큰이 든다. **모양은 실제 산출물과 같게** 맞춘 대역값이다.

끝에 나오는 지표(실측):

```
정산 299건 / 판정로그 419행 / 전표 278건 / 별표 11행
자동처리율 87.2% (판정 296건 중 사람 검토 38건)
결정 사례 30건 (A 10건 · B 10건 · C 10건)
```

### 2.2 결정 사례 30건 — RAG `case_history`의 원천

**회계 담당자가 AI 권고와 다르게 판단한 건**만 사례로 남는다(일치 건까지 넣으면 검색 상위가
다수결에 묻혀 정작 봐야 할 예외가 밀려난다). 세 패턴이 서로 다른 것을 가르친다.

| 패턴 | 전이 | 가르치는 것 |
|---|---|---|
| **A 소명 확인** | AI 반려 → 사람 승인 | **오탐 교정** — 형식 신호가 곧 위반이 아니다 |
| **B 놓친 실질** | AI 승인 → 사람 보완·반려 | **미탐 교정** — 통과 신호가 곧 정상이 아니다 |
| **C 수위 조정** | AI 반려 → 사람 보완요청 | **처리 등급** — `REJECT`는 재제출을 막는다. 고칠 수 있으면 보완이다 |

사례도 손으로 쓰지 않는다 — 검토를 실제로 태우면 `services.review()`가 「사람이 기계와 다르게
판단했다」고 보고 남긴다. 그래서 **중간 고리가 하나만 끊겨도 조용히 0건이 되고**(실제로 오랫동안
0건이었다), 지금은 끝에서 수를 대조해 어긋나면 경고한다.

사례 본문은 Chroma `case_history`에 올라간다. **ai가 꺼져 있으면 적재만 밀린다**(결정은 이미
확정됐다) — 나중에 되살린다:

```bash
docker compose exec core python manage.py reindex_cases --list   # 밀린 목록만
docker compose exec core python manage.py reindex_cases          # 적재
```

### 2.3 규정 문서 — 시드가 만들 수 없는 것

`seed_clean`도 `seed_adopted`도 **규정 문서를 하나도 만들지 않는다.** 문서 하나가 화면에 뜨려면
파싱·프로파일 판정·조 단위 청킹·임베딩·Chroma upsert·조항 분류·별표 추출이 차례로 돌아야 하고
**그중 둘은 LLM 호출**이며 청킹 결과는 파서 버전에 딸려 있다. 손으로 적으면 조항의 `chunk_ids`가
실제 청크를 안 가리켜 **근거 링크가 조용히 끊긴다.**

그래서 **한 번 진짜로 돌리고, 그 결과를 얼려서 재생한다.**

```bash
# ① 화면(/policy-docs)에서 규정 PDF를 올려 적재를 끝낸다  → §3
# ② 그 결과를 얼린다 — 절반이 둘이라 같은 시점에 둘 다 뜬다
docker compose exec core python manage.py dump_policy_docs                                     # 관계형
docker compose exec ai   python -m app.rag.embedding.snapshot dump --out /data/rag_snapshot    # 벡터
```

| 절반 | 무엇이 | 어디에 |
|---|---|---|
| 관계형 | 문서 메타 · 조항 · 조항 분류 · 별표와 승인 제안 | Postgres |
| 벡터 | 검색이 실제로 매칭하는 청크 | Chroma (별개 저장소) |

> ⚠️ **한쪽만 옮기면 에러 없이 반쪽이 된다.** 문서 화면은 멀쩡히 뜨는데 그 조항을 근거로
> 끌어오는 검색만 빈손이 된다. 덤프에 컬렉션과 `doc_id`를 적어 두고, 복원할 때 무엇을 더
> 되살려야 하는지 출력한다.

복원은 `seed_adopted`가 자동으로 절반을 하고(덤프가 있을 때만), 벡터는 직접 넣는다:

```bash
docker compose exec ai python -m app.rag.embedding.snapshot restore --in /data/rag_snapshot
docker compose exec core python manage.py load_policy_docs    # 시드를 안 돌릴 때만 직접
```

### 2.4 전체 세팅 순서

처음부터 끝까지. **①~③이면 화면은 다 산다** — ④는 RAG·Agent 근거 검색까지 살릴 때다.

```bash
# ① 기동
cp .env.example .env && docker compose up --build

# ② 서비스 계정 (ai → core 쓰기). .env의 AI_SERVICE_PASSWORD를 채운 뒤
docker compose up -d --force-recreate core ai      # env를 고쳤으면 재생성이 먼저다
docker compose exec core python manage.py ensure_service_account

# ③ 시드 — 둘 중 하나
docker compose exec core python manage.py seed_clean       # 초기 적용 시연
docker compose exec core python manage.py seed_adopted     # 적용 완료 시연

# ④ RAG (선택) — 규정 검색·Rule Agent 근거·Risk Review 2차가 실제 결과를 내려면
docker compose exec ai python -m app.rag.embedding.snapshot restore --in /data/rag_snapshot
docker compose exec core python manage.py reindex_cases    # 결정 사례 적재
#   스냅샷이 없으면 §3의 두 경로 중 하나로 처음 적재한다

# ⑤ 관리자 계정 (선택)
docker compose exec core python manage.py createsuperuser
```

### 2.5 옛 시연 시드 (`seed`)

화면별 상태를 골고루 흩어 놓은 **이전 시연 데이터**. 이번 달 안에 온갖 상태를 배치해 한 화면씩
채워 보여주는 용도라, 위 둘과 달리 **회사의 시점이라는 서사가 없다.** 룰 4계열·정산 87건·검토
대기 30건. 새로 시연을 짠다면 `seed_clean`/`seed_adopted`를 쓴다.

```bash
docker compose exec core python manage.py seed --fresh
```

### 2.6 부분 시드·계정

```bash
docker compose exec core python manage.py seed_rules [--no-test]   # 룰 그래프만
docker compose exec core python manage.py seed_policy_tables       # 규정 별표(임계값)만
docker compose exec core python manage.py ensure_service_account --check   # 401 날 때 진단
```

### 로그인 계정 (세 시드 공통, pw `pass1234`)

시드를 갈아끼워도 헤매지 않도록 셋이 같은 계정을 만든다.

| 계정 | 역할 | 기본 Capability | 볼 수 있는 것 |
|---|---|---|---|
| `kim` | 임직원(영업팀) | — | 내 지출 / 팀 예산 현황 |
| `lead` | 팀장(영업팀) | `team_aggregate` | 팀 취합 + 보완요청·반려·제출 |
| `acc` | 회계 담당자 | `accounting_review`, `rule_view` | 검토 워크스페이스 · 룰 콘솔(열람) |
| `acclead` | 회계팀장 | + `rule_activate`, `ai_lab` | 룰 ACTIVE 승인·롤백 · AI-LAB |
| `exec` | 운영진 | `governance_view` | 거버넌스 대시보드 |

`seed_adopted`는 여기에 팀원 10명(`emp1`~`emp10`)을 더한다 — 팀 통계가 사람 한둘로 채워지지
않도록, 그리고 **직책을 흩어 놓아야** 직책별로 판정이 갈리는지 확인할 수 있어서다.

> **인가는 역할이 아니라 Capability로 판정**한다 — `유효능력 = 역할 기본값 ∪ 개인 추가부여`.
> Django Admin에서 사용자별 `extra_capabilities`를 체크박스로 더 줄 수 있다.
> 백엔드에서도 강제된다(DRF `HasCapability`). 회원가입 화면은 없다 — 계정은 CLI/Admin에서만.

### 서비스 계정 (ai → core 쓰기)

룰 그래프 DRAFT 저장·규정 적재 결과 회신은 사람 세션이 없으므로 전용 계정 하나(`rule-agent`,
capability `rule_view`만)로 JWT를 받는다. **`.env` 변경 뒤 컨테이너 재생성을 건너뛰면** core만
옛 env로 돌아 **원인과 동떨어진 401**이 난다.

---

## 3. RAG 규정 적재 — 경로가 둘이다

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

### ③ 스냅샷 복원 (시연 재현용 — 재임베딩 0회)

이미 적재해 둔 벡터를 **그대로** 옮긴다. OpenAI 호출 0회·과금 0·재현 100%.

```bash
docker compose exec ai python -m app.rag.embedding.snapshot dump    --out /data/rag_snapshot
docker compose exec ai python -m app.rag.embedding.snapshot restore --in  /data/rag_snapshot
#   복원은 upsert다(기존을 지우지 않는다). 깨끗한 상태가 필요하면 --reset을 명시.
```

시연 데이터를 확정하려면 벡터도 함께 고정돼야 한다 — 원문을 다시 파싱·임베딩하면 파서·청커·모델이
바뀔 때 **어제 보던 검색 결과가 오늘 달라진다.** 관계형 절반과 짝이므로 §2.3과 같이 읽는다.

### 데이터는 어디에 남나

Chroma는 named volume `skn-settlement_chromadata`. `docker compose down`·재부팅·`up --build`로는
유지되고, **`down -v`는 삭제**된다(Postgres `pgdata`도 함께 — 그 뒤엔 migrate + seed + 적재를 다시).

---

## 4. 미완 · 미연동 (알고 쓰는 한계)

### 4.1 실물이 없어서 안 도는 것

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
- **`case_history`는 ai가 떠 있어야 적재된다.** 결정 시 자동 적재되지만 그때 ai가 꺼져 있었거나
  임베딩이 실패하면 `indexed_at`이 빈 채로 남는다(결정 자체는 확정됐다 — 적재 실패로 되돌리지
  않는다). `manage.py reindex_cases`로 되살린다. 골든 시드는
  `docker compose exec ai python -m app.rag.case_store --upsert`.
- **`OPENAI_API_KEY`가 없으면** Draft/Rule/Risk Agent와 임베딩이 전부 멈춘다(부팅은 된다).
- **`KAKAO_REST_API_KEY`가 없으면** 캐시에 없는 가맹점은 업종 미확정으로 남고, 금지업종·주의업종
  룰이 판정할 근거가 사라진다(경고 로그 1회 후 조용히 건너뜀).

### 4.2 화면이 아직 목업인 곳

실 API 없이 화면 안 상수로 도는 화면들. 백엔드 집계·엔드포인트가 없다.

| 화면 | 상태 |
|---|---|
| 거버넌스 대시보드 (`GovernanceDashboard`) | 차트·KPI 전부 목데이터. `/api/dashboard/EXECUTIVE/`는 일부 집계만 반환 |
| 예산 **수정** (S-08 Frame 22) | 조회는 실 API. 쓰기 API가 없고 "누가 고칠 수 있는가"가 미정이라 버튼은 비활성 |

### 4.3 연동 gap (`VITE_USE_MOCK=false`로 붙일 때)

1. **데이터 스코프가 서버에서 안 갈린다.** `/api/settlements/`는 `submitted_by`·`team` 쿼리
   파라미터를 받지만 로그인 사용자로 **자동 제한하지 않는다**. "내 지출 / 우리 팀"은 프론트가
   client-side로 거른다. 서버측 스코프 쿼리가 필요하다.
2. **쓰기 후 재조회가 없다.** 상태 전이는 낙관적 로컬 반영만 하고 서버를 다시 읽지 않는다.
3. **id 타입 불일치.** 서버는 정수, 프론트 타입은 문자열(런타임 동작엔 문제없음).
4. **로딩/에러 UI.** `loading` 플래그만 있고 화면별 스피너·에러 처리가 없다.
5. **세션 인증에서 CSRF를 생략**하고 있다(dev 편의) — 운영 전 재활성 필요.

### 4.4 도메인 차원의 미완

- **영수증 판독의 「사용내역」은 저장되지 않는다.** 증빙 첨부 판독은 연결됐지만
  (`업로드 → /agent/extract-evidence → Attachment.extracted → EvalContext`), 영수증에서 읽은
  **가맹점·금액·품목**은 `Attachment`에 담을 자리가 없어 버려진다 — 판정 사실
  (`dining.includes_alcohol` 등)만 남는다. 금액·가맹점 자동 채움은 여전히 Draft Agent 경로다.
- **EvalContext 사실 조립에 빈칸이 남아 있다.** 56개 경로(v6) 중 룰이 참조하는데 화면 입력칸이
  없는 것이 하나 있다(`trip.*` — 첨부 추출은 되는데 입력 UI가 없어 0%). 참조한 경로가 `null`이면
  미해소 가드가 판정을 「검토 필요」로 낮춘다(조용한 통과는 없다).
- **가맹점 업종 구분이 Draft에만 붙어 있다.** Risk Review 연동은 미착수.
- **`/submit`이 팀 동일성을 강제하지 않는다.**
- **`merchant.forbidden`이 채워지는데 참조되지 않는다.** 게이트가 리터럴로 직접 비교해 선해소
  목적이 사라졌다 — 게이트를 고치거나 선해소를 빼거나 정해야 한다.
- **`anomaly.pkl` 재학습 필요.** 배포 pkl에 `feature_stats`가 없어 기여도가 빈 배열이고
  sklearn 버전이 어긋난다(1.8.0 vs 1.5.2).
- **알림 딥링크가 없다.** 지금은 페이지 이동까지다 — `?open=`/`?graph=`를 만드는 코드는 있는데
  읽는 코드가 없어 이미 죽어 있다.

### 4.5 브랜치

`feature/*` 브랜치가 여럿 남아 있다 — `git log --oneline main..<브랜치>`로 확인할 것.

---

## 5. 자주 쓰는 명령

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

# ── 시연 데이터 얼리기·되살리기 (§2.3) ──────────────
docker compose exec core python manage.py dump_policy_docs      # 규정문서 관계형 절반
docker compose exec ai python -m app.rag.embedding.snapshot dump --out /data/rag_snapshot   # 벡터 절반
docker compose exec core python manage.py reindex_cases         # 밀린 결정 사례 적재

# ── 기타 ─────────────────────────────────────────────
docker compose config                 # compose 문법 검증
docker compose up --build core        # 개별 재빌드
docker compose down [-v]              # 종료 (-v: 볼륨까지 삭제)
```

---

## 6. 알려진 함정

| 증상 | 원인 · 회피 |
|---|---|
| `--dump /data/...`가 "No such file or directory" | **Git Bash가 `/data/...`를 윈도우 경로로 변환**한다. PowerShell을 쓰거나 앞에 `MSYS_NO_PATHCONV=1` |
| ai → core 요청이 401 | `.env`를 고치고 컨테이너를 재생성하지 않았다 → `docker compose up -d --force-recreate core ai` 후 `ensure_service_account --check` |
| 업로드한 PDF 내용이 무시된다 | `DOCLING_MOCK=1`이 켜져 있다. 파싱만 미리 떠둔 덤프로 대체되며 **문서명으로만** 덤프를 고른다. 화면 상단 노란 배너·`dump:` doc_id로 구분된다. **운영에서 절대 켜지 말 것** |
| 규정 PDF 업로드가 413 | nginx `client_max_body_size` — 기본 1MB로는 규정 PDF가 곧바로 막힌다(현재 50m로 설정돼 있음) |
| `down -v` 후 아무것도 안 보임 | DB·Chroma 볼륨이 삭제됐다. `migrate` → `seed` → RAG 적재를 다시 |
| 한글 경로 파일 작업이 깨진다 | Git Bash의 cp949 mojibake. PowerShell + 절대경로 사용 |
| 규정 문서는 뜨는데 검색이 못 찾는다 | **두 절반 중 벡터만 빠졌다**(§2.3). `snapshot restore`를 같이 돌릴 것 — 조항의 `chunk_ids`는 살아 있어도 그 청크가 Chroma에 없으면 에러 없이 빈손이 된다 |
| `seed_adopted`가 판정 불일치를 경고한다 | 룰이 바뀌었는데 시드의 기대값이 안 따라온 것이다. **정상 동작이다** — 사실(`Spend`)을 고치거나 기대값을 갱신한다 |
| 결정 사례가 0건 | `ai`가 꺼져 있으면 적재만 밀린다(결정은 확정됐다). `reindex_cases`로 되살린다. 시드 끝의 「기대 30건 / 실제 N건」 경고를 먼저 볼 것 |

---

## 7. 디렉터리 구조

```
.
├── docker-compose.yml          # db · chroma · core · ai · web · nginx
├── .env.example                # 환경변수 + 각 값의 의미·주의사항 (→ .env로 복사)
├── infra/nginx/                # 리버스 프록시 ( / → web, /api → core )
├── logs/                       # 컨테이너 로그 바인드 (git 미추적) — 디버깅은 여기부터
├── llm_wiki/                   # 설계·기획 산출물. 진입점 _index.md
│   ├── docs/                   #   팀 관리 기준 문서 (요구사항·기술명세서·기획·RULE 명세서)
│   ├── _context/                #   AI가 관리하는 구현 캐논·실측 기록
│   ├── 화면설계서/ · figma_mockup/
├── tiger_inc/                  # RAG 소스 데이터(사내 규정·조직 문서) — 직접 열람 자제
├── docling_eval/                # 파싱·청킹·임베딩 평가 노트북 + 파싱 덤프(적재 배치 입력)
├── daily_scrum/                # 주차별 진행 보고
├── docs/                        # 사람이 읽는 운영·셋업 문서 (이 파일)
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
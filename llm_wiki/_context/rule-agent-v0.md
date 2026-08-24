# Rule Agent (생성) — 구현 캐논 (v0 스냅샷)

> ⚠️ **2026-08-24: `docs/`에서 `_context/`로 이동.** 이 문서는 2026-08-14 시점 v0 구현 기록이다.
> 이후 진행된 재시도 루프·MCP 툴콜링 전면 전환·대화형 수정·검증셋 자동생성 등은
> **[[rule-agent-v1-implementation]]이 정본**이다. 이 문서는 v0 설계결정(D-1~D-21)·잔여 갭(G-1~G-18)
> 기록 목적으로만 남긴다.

# Rule Agent (생성) — 구현 캐논

> 최종 갱신: 2026-08-14 · 상태: **전 구간 통합 완료** (RAG→LLM→조립→저장→화면)
> 원본: 2026-08-13 v0 배선 검증(한경찬) + 2026-08-14 통합 작업
> 권위 스펙: `docs/기술명세서.md §4.2(a)/§5/§6.2` · `docs/요구사항_명세서.md FR-RB-01~05`

3-Agent 중 **Rule Agent — 생성(Generate)** 단계. 사내 규정 문서에서 실행 가능한
룰 그래프 **DRAFT**를 만든다.

```
search_policy(RAG) → LLM 노드 초안 → 결정론적 그래프 조립 → Django DRAFT 저장 → 룰 콘솔
```

**자동 승인은 없다.** 생성물은 언제나 DRAFT이고, 담당자가 룰 콘솔에서 검토·수정 →
시뮬레이션 → Active 요청 → 활성 권한자 승인을 거쳐야 판정에 쓰인다(FR-RV-04).

---

## 1. 지금 어떻게 도는가

| 단계 | 무엇 | 어디 |
|---|---|---|
| ① 진입 | 룰 콘솔 Tab1 "신규 그래프 생성 → 규정 문서에서 생성" | `web/src/screens/rule-console/NewRuleGraphModal.tsx` |
| ② 인가·전달 | `POST /api/rules/generate/` (capability `rule_view`) → FastAPI 전달 | `core/domain/policies/views.py: generate_graph` |
| ③ RAG | `policy_docs`(+옵션 `tax_refs`) 검색 — 부모 청크 제외·부모 확장·컬렉션 라우팅 | `ai/app/agents/rule_agent_v0/search.py` → `ai/app/rag/embedding/store.py` |
| ④ LLM | 노드 "재료"만 생성. JSON-Logic은 파이썬이 조립 | `ai/.../agent.py: _call_llm` · `_build_condition` |
| ⑤ 1차 검증 | DSL 화이트리스트 + EvalContext 경로. 탈락은 `rejected_nodes`로 노출 | `ai/.../agent.py: _sanitize_nodes` |
| ⑥ 조립 | severity 순 선형 체인 + `_SCOPE_PASS` 종단 | `ai/.../agent.py: _assemble_linear_graph` |
| ⑦ 저장 | 서비스 계정 JWT로 룰 콘솔 API 3종 오케스트레이션 | `ai/.../django_client.py` |

**⑦이 전용 API를 안 쓰는 이유**: 룰 콘솔이 쓰는 `POST /api/rules/drafts/` →
`POST /api/rules/{id}/nodes/` → `PATCH /api/rules/{id}/nodes/{key}/` 3단계가 이미
같은 일을 한다. 이걸 그대로 타면 **사람이 만들든 Agent가 만들든 같은 서비스 레이어·
같은 감사로그(`services.py`)** 를 지나간다. 우회 API를 만들면 그 불변식 밖에서
그래프가 생겨난다.

### 실행

```bash
# 0) 규정 문서가 Chroma에 적재돼 있어야 한다 (관리자 온디맨드 배치)
docker compose exec ai python -m app.rag.embedding.index --dump /data/docling_eval/output --dry-run
docker compose exec ai python -m app.rag.embedding.index --dump /data/docling_eval/output

# 1) 서비스 계정 (RULE_AGENT_SERVICE_PASSWORD 를 .env에 채운 뒤)
docker compose exec core python manage.py ensure_service_account

# 2) 화면: 룰 콘솔 → 신규 그래프 생성 → "규정 문서에서 생성"
#    또는 API 직접 (로그인 세션 필요)
curl -X POST localhost:8000/api/rules/generate/ -H 'Content-Type: application/json' \
     -d '{"scope":"접대","top_k":6}'
```

---

## 2. 설계 결정 (D)

| # | 결정 | 근거 |
|---|---|---|
| D-1 | **LLM은 노드만 생성, 그래프 위상은 파이썬이 결정론적 조립**(severity 순 선형 체인 → `_SCOPE_PASS` 종단) | 시드 GLOBAL 그래프(R-002→R-003→`_GLOBAL_PASS`)와 동일 패턴. LLM에 라우팅까지 맡기면 구조 검증 실패 모드가 늘어난다. FR-RB-04의 "next_routings 제안"은 배타그룹·부분 트리와 함께 뒤로 |
| D-2 | **decision은 `action.decision` 직접 지정**(REJECT/RETURN/REVIEW만 LLM 허용, PASS 종단은 시스템이 추가) | 기술명세서 §4.2 확정("판정 시점 확신도 계산 없음"). θ_pass/θ_reject는 폐기 |
| D-3 | **condition 저장 = JSON-Logic 객체 직접**(`{"expr": 원문}` 래핑 아님). 출처조항은 `action.source_clause` | 기술명세서 §4.2(d)·`dsl.py` 계약 |
| D-4 | 2-hop 확장 미적용(top-k 순수 검색) | 선행 조건 미충족 — G-2 |
| D-5 | DRAFT 저장 검증: DSL 화이트리스트 = hard, EvalContext 경로 = report-only | ACTIVE 게이트(`validate_graph_vars` hard)가 이미 있으므로 이중 차단 대신 DRAFT에서 리포트 → 룰 콘솔에서 수정 유도 |
| D-6 | 쓰기 경로 = Django API (FastAPI는 Postgres 무접근) | §5.1 원칙. DRAFT는 확정 상태가 아니므로 "FastAPI never writes confirmed state"와 충돌 없음 |
| D-16 | **condition을 LLM이 JSON 문자열로 짜지 않고, 재귀 구조화 필드(comparison/group)로 받아 파이썬이 조립** | 근본 원인: LLM에게 중첩 JSON을 손으로 짜게 하는 구조 자체. 프롬프트에 ✅/❌ 예시를 넣어도(D-15) `{"var":"tx.amount",300000}` 같은 다른 문법 변종이 계속 나왔다. 구조화 후 **이 클래스의 오류가 발생 불가능**해짐 — 재검증 시 파싱 실패 0건 |
| D-17 | 재귀 스키마가 캐논 DSL 연산자 **전체**(`and/or/not/==/!=/>/>=/</<=/in/var`)를 커버 | 구현 편의로 캐논의 표현력을 줄이지 않는다. `comparison`(6개 비교 + `negate`=not) + `group`(and/or + 재귀) + `right_kind:string_list`(in) |
| **D-18** | **RAG 층은 사본을 두지 않고 팀 정본(`app.rag.embedding.store`)을 부른다** | v0의 자체 `embedding.py`/`vector_store.py`가 정본과 세 곳에서 달랐고 전부 검색 품질을 깎았다 — §3 참조 |
| **D-19** | **인증 = 전용 서비스 계정(`rule-agent`) + 런타임 JWT 발급** | capability `rule_view` **하나만** 준다(최소 권한). SimpleJWT access 수명이 짧아(기본 5분) 정적 토큰을 env에 박는 방식은 못 쓴다 → `django_client`가 직접 발급하고 401이면 1회 재발급 재시도. 회계 담당자 계정을 빌려 쓰면 감사로그 actor가 사람으로 찍혀 "누가 만든 룰인지"가 흐려진다 |
| **D-20** | **scope 정본은 Django `Category`** | 문서(`_index.md`)·코드·프론트가 서로 달라 `scope:"회식"`이 400을 냈다. 코드로 확정하고 문서를 정정. 규정 표기(기업업무추진비·회식)는 `normalize_scope`가 접는다 — **회식은 독립 Category가 아니라 식대 scope** |
| **D-21** | **`generation_meta`는 그래프 단위로 저장, 다음 버전으로 복제하지 않는다** | 노드별 출처는 `action.source_clause`에 있다. 그래프 단위 이력(모델·질의·검색 출처)이 DB에 없어 "무엇을 보고 만든 룰인지"가 API 응답에만 있었다(구 G-5). 복제하지 않는 이유: 그 이력은 **그 버전**을 Agent가 만들었다는 기록이지, 사람이 손댄 다음 버전의 출처가 아니다 |

---

## 3. 통합에서 고친 것 (2026-08-14)

v0는 "격리 우선"으로 만들어져 기존 코드를 거의 안 건드렸다. 그 격리가 통합 시점에
그대로 결함이 됐다 — 사본이 정본과 어긋난 지점이 전부 여기다.

### 3.1 RAG — 사본 3개 제거

| 무엇 | v0가 하던 것 | 정본 | 결과 |
|---|---|---|---|
| 부모 청크 | 필터 없음 | `where={"chunk_role": {"$ne": "parent"}}` | 부모는 조 전문이라 **무엇과도 어중간하게 닮아** top-k를 잠식했다 |
| 부모 확장 | 없음 | 맞은 잎에 `parent_document` 부착 | 항 단위 조각만 LLM에 넘어가 조 맥락이 빠졌다 |
| `embedding_function` | 미지정 | 명시적 `None` | upsert가 컬렉션을 먼저 만들면 저장 문서로 벡터를 다시 계산하는 사고가 가능했다 |
| `embedder_version` | 미기입 | `to_chroma()`가 새김 | `assert_single_embedder`의 사각지대. bge-m3와 3-large@1024가 **똑같이 1024차원**이라 섞여도 Chroma가 못 막는다 |
| 컬렉션 라우팅 | `policy_docs` 고정 | `COLLECTION_OF`(LAW→`tax_refs`) | 세법 근거를 못 찾았다. 지금은 `include_law` 옵션 |
| 점수 | `distance` | `score = 1 - distance` | AI-LAB RAG 탭과 다른 숫자를 보여줬다 |

**가장 컸던 것 — docker에서는 검색이 아예 안 됐다.** `RULE_AGENT_V0_CHROMA_HOST`
기본값이 빈 문자열이고, 비면 로컬 `PersistentClient("./chroma_data_v0")`로 **조용히**
폴백하는데 compose가 그 변수를 주입하지 않았다 → 컨테이너에서 부르면 빈 로컬 DB를
조회해 0건, 에러 없이 `NO_SOURCE`만 나왔다. 실측 성공 기록은 전부 호스트에서
`export`로 덮어쓴 상태였다. (커밋돼 있던 `apps/ai/chroma_data_v0/` 423KB가 그 폴백의
산물 — 삭제 + `.gitignore` 등록)

지금은 Chroma·Django·OpenAI 주소를 **중앙 `app.config.settings`** 에서만 읽는다.
`rule_agent_v0/settings.py`에는 이 Agent 고유값(LLM 모델·서비스 계정)만 남았다.

### 3.2 인증 — 403의 실제 원인

`CanViewRule`은 `is_authenticated`를 요구하는데, `django_client`가 보내던
`RULE_AGENT_V0_DJANGO_SERVICE_TOKEN` Bearer 토큰을 **검증할 인증 클래스가 없었다**
(DRF는 세션 + SimpleJWT 둘뿐). 토큰 자리만 있고 받아줄 쪽이 없어 익명 → 403.
→ D-19로 해소.

### 3.3 삭제한 것

- **`apps/ai/app/agents/rule_agent_v0/apps/core/...`** — ai 패키지 안에 Django 앱 트리가
  통째로 들어 있었다. 어디서도 import되지 않는 죽은 코드였고, 그 안 `views.py`는
  `errs = dsl.validate_expr(...)`로 **반환값이 없는 함수의 반환값을 검사**해 DSL 검증을
  항상 통과시켰다. 실제 배선된 것은 `core/domain/policies/rule_agent_v0_views.py` 하나.
- **`/agent/rule-v0/embeddings/upsert`** — 사본 임베딩으로 Chroma에 직접 써서
  `embedder_version`을 안 남기고 컬렉션 EF 계약도 안 지켰다. 규정 적재의 정본 경로는
  관리자 CLI(`app.rag.embedding.index`) 하나다.
- `apps/main.py`(레포 `apps/` 루트의 2줄짜리 잘린 파일), 패키지 안의 `GAPS.md`/`WIRING.md`
  (내용은 이 문서로 흡수).

### 3.4 그 외

- `OpenAI()` 클라이언트를 import 시점이 아니라 첫 호출에 만든다 — 키가 비면 라우터
  import가 터져 룰과 무관한 화면까지 같이 죽었다.
- 예외를 전부 502로 뭉개지 않는다 — Django 400(scope 불량)과 401(인증)이 구분된다.
- `group` 조건의 빈 `children`을 FastAPI에서 잡는다(그대로 보내면 저장 단계 422가 나고
  어느 노드 탓인지 흐려진다).
- `mcp/tools.py`의 `search_policy` stub을 실구현으로 교체 — Risk Review Agent가 같은
  tool·같은 검색 경로·같은 로깅을 공유한다(구 G-7 해소).

---

## 4. 남은 갭 (G)

| # | 갭 | 상태 |
|---|---|---|
| G-1 | **규정 문서 업로드 트리거 부재** — 적재 경로가 관리자 CLI(미리 만든 docling 덤프 입력) 하나뿐. 사용자가 올린 PDF를 받아 `parse→chunk→embed→upsert`로 잇는 경로가 없다. 프론트 `PolicyDocuments.tsx`는 mock 전용·비활성, 그것이 부르는 `/policy-docs/`는 Django에 라우트가 없다(모델 `PolicyDoc`만 존재) | 🔲 **가장 큰 남은 덩어리** (이번 범위 밖) |
| G-2 | 청크 메타에 `refs_internal`/`refs_external` 부재 → 2-hop RAG 확장 불가. `chunking-strategy` §8.2 메타 스키마에 refs가 없다 | 🔲 |
| G-8 | `RETURN`을 `OnResult` enum에 정식 추가할지 | 🔲 팀 합의 (현 라우팅은 MATCH/NO_MATCH만 써서 충돌 없음) |
| G-9 | 임계값 리터럴 린트 부재 — LLM이 규정 원문 숫자(3만·30만)를 리터럴로 박아도 기계적으로 못 잡는다. policy-domain 원칙 위반 가능 | 🔲 |
| G-12 | 멀티테넌트 미적용 (Chroma tenant 바인딩) — 단일 tenant 전제 | 🔲 Open Issue #5 |
| G-13 | `/agent/rule/validate` 프록시 미배선. 시뮬레이션 실체는 Django `simulation.py`에 있고 룰 콘솔에서 이미 돌아간다 | 🔲 우선순위 낮음 |
| G-14 | **`orchestrator.py` 미구현** — GLOBAL→scope 그래프 선택·`RuleHit` 기록이 시뮬레이션 경로에만 있다. 생성·승인된 그래프가 **실 정산 판정 경로에서는 아직 안 돈다** | 🔲 별건, 크다 |
| G-18 | 정식 엔드포인트 이관 — `/agent/rule-v0/generate` → `/agent/rule/generate`(§6.2). 현재 `api/rule.py`의 정식 경로는 아직 stub | 🔲 |
| ~~G-3~~ | EvalContext 카탈로그 공유 경로 | ✅ `GET /api/internal/rule-agent-v0/eval-context-schema/` |
| ~~G-4/G-15~~ | 그래프 쓰기 경로 | ✅ 기존 룰 콘솔 API 오케스트레이션으로 대체 |
| ~~G-5~~ | generation_meta 저장 자리 | ✅ `RuleGraph.generation_meta` (D-21) |
| ~~G-6/G-16~~ | 내부 API 인증 | ✅ 서비스 계정 + JWT (D-19) |
| ~~G-7~~ | tool call 로깅 미탑승 | ✅ `mcp/tools.py: search_policy` 실구현 |
| ~~G-10~~ | `_SCOPE_PASS` 리터럴 `true` | ✅ `dsl._validate`가 bare literal 통과 확인 |
| ~~G-11~~ | 룰 콘솔 미연동 | ✅ Tab1에 생성 진입점 + 같은 API 사용 |

---

## 5. 검증되지 않은 것 — 규칙 **내용**의 타당성

지금까지 확인한 건 **배선과 계약**이지 "생성된 룰이 회계적으로 말이 되는가"가 아니다.
인증·RAG가 풀린 지금은 실제로 저장된 그래프를 규정 원문과 대조할 수 있다:

- `action.decision`(REJECT/RETURN/REVIEW)이 규정 취지와 맞는지
- `action.source_clause`가 그 조문 내용을 정확히 반영하는지(환각 여부)
- `generation_meta.sources`의 인용이 실제 근거로 쓰였는지
- 시스템 프롬프트(`agent.py: _SYSTEM_PROMPT`) 개선 여지

`scope`별로 돌려 재귀 구조화 스키마(D-16)가 다른 도메인에서도 안정적인지 보는 것만으로도
의미 있는 추가 검증이 된다.

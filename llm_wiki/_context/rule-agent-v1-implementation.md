# Rule Agent v1 — 구현 기록

> 계획/설계 근거는 `_context/agent-v1-upgrade-plan.md`(§1.2 전 항목)를 참조. 이 문서는 **실제로 무엇을 만들었고, 어떻게 검증했는지**만 다룬다. 브랜치: `feature/rule-agent-v1`. §1.2 6개 항목 전부 이 문서에 있다 — ①검증재사용(§3) ②재생성루프(§1~4) ③자동트리거(§7) ④대화형에이전트(§8) ⑤MCP툴콜링전환(§6) ⑥시뮬레이션LLM서술(결정: 안 함, 코드변경없음).

## 1. 변경 파일 (검증→재생성 루프, §1.2-3·4)

| 파일 | 변경 내용 |
|---|---|
| [`apps/ai/app/agents/rule_agent_v0/django_client.py`](../../apps/ai/app/agents/rule_agent_v0/django_client.py) | `simulate_graph(graph_id)`·`discard_draft(graph_id)` 함수 추가. 새 엔드포인트 아님 — 기존 `POST /api/rules/{id}/simulate/`·`DELETE /api/rules/{id}/draft/`(프론트 `client.ts`가 이미 쓰는 것과 동일 경로) 재사용 |
| [`apps/ai/app/agents/rule_agent_v0/agent.py`](../../apps/ai/app/agents/rule_agent_v0/agent.py) | `generate()`를 단발 실행 → 최대 3회 검증→재생성 루프로 재작성. `_call_llm`/`_build_user_prompt`에 `feedback` 파라미터 추가, `_build_sanitize_feedback`/`_build_structure_feedback` 신설 |
| [`apps/core/domain/policies/views.py`](../../apps/core/domain/policies/views.py) | `generate_graph` 액션의 Django→FastAPI 프록시 타임아웃 120s→300s (재시도로 총 소요시간이 늘어난 데 대응) |
| [`apps/ai/app/clients/core_auth.py`](../../apps/ai/app/clients/core_auth.py) | **검증 중 발견한 별개 버그 수정** — 아래 §3 참조. 재시도 루프와 무관하지만 실동작 검증 도중 발견해 같이 고쳤다 |

## 2. 재시도 루프 동작 방식

```
for attempt in 1..3:
    LLM 호출(feedback=이전 시도 실패 사유, 최초엔 None)   # RAG 청크는 최초 1회만 조회, 이후 재사용
    sanitize → accepted/rejected
    if accepted 없음:
        attempt==3? → status="NO_VALID_NODES_EXHAUSTED"로 최종 종료
        아니면      → rejected 사유를 feedback으로 다음 loop
        continue
    조립 → create_rule_graph_draft() 저장(실제 DRAFT 그래프 생성됨)
    simulate_graph() 호출 → structureError 확인
    if structureError 없음 → status="DRAFT_SAVED"로 성공 종료 (기존 응답 계약 그대로)
    structureError 있음:
        discard_draft() 로 방금 저장한 그래프 삭제
        attempt==3? → status="STRUCTURE_INVALID_EXHAUSTED"로 최종 종료(흔적 없음)
        아니면      → structureError를 feedback으로 다음 loop
```

**상태값**: 기존 유지(비침습) `NO_SOURCE`(RAG 검색 0건)·`DRAFT_SAVED`(성공, 응답 필드 동일). 신규 `NO_VALID_NODES_EXHAUSTED`·`STRUCTURE_INVALID_EXHAUSTED`(둘 다 실패 시 `attempts` 이력 배열 포함). 기존 `NO_VALID_NODES`는 더는 안 씀(의미가 "1차 실패"에서 "N회 소진"으로 바뀌므로 이름을 새로 팠다).

## 3. 검증 중 발견·수정한 별개 버그: JWT 만료가 403으로 응답됨

Rule Agent 재시도 루프와는 무관하지만, 실동작 검증 중 재현돼 같이 고쳤다.

**증상**: 서비스 계정(`rule-agent`)으로 처음 생성한 지 5분(SimpleJWT access 수명) 넘게 지나자, 이후 모든 룰 생성 요청이 "capability 없음" 403으로 실패. 그런데 DB로 직접 확인한 capability는 정상(`rule_view` 있음).

**근본 원인**: 이 배포의 SimpleJWT 설정에서 **만료된 토큰은 401이 아니라 403**을 반환한다(직접 실험으로 확인 — 강제로 만료시킨 토큰으로 `/api/rules/drafts/` 호출 시 `403 {"code":"token_not_valid","message":"Token is invalid or expired"}`). `core_auth.py`의 기존 재시도 로직은 **401일 때만** 토큰을 재발급하도록 돼 있어서, 만료로 인한 403은 재발급 시도조차 없이 곧장 "capability 부족"이라는 **잘못된 진단 메시지**를 내며 포기했다. 한 번 이 상태에 빠지면(만료 후 첫 요청) FastAPI 프로세스가 재시작되기 전까지 **영원히 같은 403만 반복**한다(재발급이 트리거될 조건 자체가 안 옴).

**수정**: 진짜 권한 부족(`{"detail":"룰 콘솔 권한이 필요합니다."}`)과 토큰 만료(`{"code":"token_not_valid"}`)를 응답 바디로 구분해서, **후자일 때만** 401과 동일하게 한 번 재발급 후 재시도하도록 `_is_expired_token()` 판별 함수를 추가(`core_auth.py`). 진짜 권한 부족 케이스는 기존처럼 즉시 명확한 에러로 종료 — 재시도로 뭉뚱그려 원인 파악을 흐리지 않는다.

**영향 범위**: `core_auth.request()`는 Rule Agent(`django_client.py`)와 규정 문서 적재 콜백(`api/embeddings.py`)이 공유하는 인증 클라이언트라, 이 버그는 원래 두 경로 모두에 잠재해 있었다(적재 콜백도 5분 넘게 방치되면 같은 증상 가능). 수정으로 둘 다 같이 해소됨 — 별도로 손댈 곳 없음.

## 4. 실동작 검증 결과 (2026-08-16, docker 환경)

### 4.1 사전 확인
- 문법 체크(`py_compile`) 4개 파일 통과
- 권한 확인: `simulate`/`draft`(DELETE) 액션 모두 기존 서비스 계정 capability(`rule_view`)로 호출 가능 — 신규 권한 부여 불필요
- URL 경로 확인: 프론트 `client.ts`가 쓰는 `/rules/{id}/simulate/`·`/rules/{id}/draft/`와 동일 경로 사용
- 로컬 환경에 `RULE_AGENT_SERVICE_PASSWORD`가 비어 있어(서비스 계정 인증 자체가 막혀 있었음) `.env`에 값 추가 + `ensure_service_account` 재실행 + `docker compose up -d --force-recreate ai core` 선행 필요했음. `.env.example`엔 원래 있던 항목이라 이번 작업으로 생긴 신규 요구사항은 아님 — 팀원 로컬/CI에도 값이 비어 있으면 동일하게 막힘.

### 4.2 재시도 루프 자체 (5개 케이스, `agent.generate()` 레벨)
| # | 케이스 | 결과 |
|---|---|---|
| 1 | 정상 생성(실제 LLM·실제 RAG, scope=회의) | `DRAFT_SAVED`/`attempts:1`, DB에 그래프+`RuleSimulationRun` 실제 저장 확인 |
| 2 | `discard_draft()` 단독 호출 | 실제 그래프 DB 삭제 확인 |
| 3 | sanitize 전멸(1차, 존재하지 않는 EvalContext 경로) → 재시도 | `attempts:2`, 1차엔 feedback 없음/2차엔 반려 사유 정확히 전달, 2차 성공 |
| 4 | sanitize 3회 전부 전멸 | `NO_VALID_NODES_EXHAUSTED`, LLM 정확히 3회 호출, DB에 그래프 없음(저장 전 단계라 정리 불필요 자체 확인) |
| 5 | 구조검증 실패(1차, `simulate_graph` 응답 주입) → discard → 재시도 | `attempts:2`, 1차 그래프는 `discard_draft` 실제 호출로 삭제, 2차 재시도 성공 |

케이스 3·4·5는 실제 OpenAI 과금을 피하려고 `_call_llm`/`simulate_graph` 응답만 결정론적으로 주입했고, `create_rule_graph_draft`/`discard_draft`는 실제 Django HTTP 호출 그대로 태웠다(모킹 아님). 테스트로 만든 그래프(id 40~44) 전부 최종적으로 DB에 안 남은 것까지 확인.

### 4.3 실제 사용자 경로 (`POST /api/rules/generate/`, Django 프록시)
케이스 1~5는 FastAPI 엔드포인트(`/agent/rule-v0/generate`, 9000 포트)를 직접 호출한 것이라, **실제 화면이 타는 Django 프록시 경로(`views.py:generate_graph`)는 별도로 검증**했다.

- `Django Client().login(username='acclead', password='pass1234')`(capability `rule_view` 보유 역할) → `POST /api/rules/generate/` 실호출
- 최초 시도: `403 → 401` 혼동 문제로 실패(§3의 버그, 이 검증 과정에서 실제로 재현됨) → 버그 수정 후 재실행
- 수정 후: **`200 DRAFT_SAVED, attempts:1, graph_id:45`** — 정상 확인. 테스트 그래프(45)는 `discard_draft`로 정리 완료.
- 이걸로 §1.2-4의 타임아웃 증가(120s→300s)를 포함해 실제 진입점 전체가 동작함을 확인.

### 4.4 아직 안 한 것
- 룰 콘솔 화면(프론트)에서 버튼을 눌러 눈으로 확인하는 건 안 함 — API 레벨 검증까지만. `attempts`/신규 status 값을 화면에 노출할지는 프론트 쪽 결정 사항(§3a 계약상 새 필드 추가는 비침습이라 프론트가 안 봐도 안 깨짐).

### 4.5 실제 LLM 통계 검증 (2026-08-16, 실호출 16건, 모델=gpt-4o-mini)

§4.4에서 "재시도의 실제 효과·빈도는 미검증"이라고 남겼던 항목을 실제 LLM 호출로 메웠다. `_call_llm`/`simulate_graph`를 주입하지 않고 **전 구간 실제 RAG+실제 LLM+실제 Django 저장**으로 `agent.generate()`를 반복 실행해 지표를 수집했다(테스트 그래프는 전부 `discard_draft`로 정리).

> ⚠️ **모델명 정정(2026-08-16 검토 중 발견)**: 이 통계는 처음에 "gpt-5-mini"로 기록됐으나 **실제 사용된 모델은 `gpt-4o-mini`다**(실측 `generation_meta.model` 확인). Rule Agent 설정(`rule_agent_v0/settings.py`)은 `RULE_AGENT_MODEL` 환경변수를 읽는데 compose 기본값이 `gpt-4o-mini`이고, `.env`에 남아 있는 `RULE_AGENT_V0_MODEL=gpt-5-mini`는 **compose가 컨테이너에 전달하지 않는 죽은 설정**이라 아무 효과가 없다(v0 시절 잔재 — `RULE_AGENT_V0_CHROMA_*` 등과 함께 정리 대상). 모델을 바꾸려면 `.env`에 `RULE_AGENT_MODEL=...`을 넣어야 한다.

**1차 라운드 — 정상 조건, 7개 scope × (5개는 1회, 접대·회의는 3회씩) = 11건**

| scope | 시도횟수 | 응답시간(초) | 승인 노드 수 |
|---|---|---|---|
| GLOBAL | 1 | 8.45 | 6 |
| 접대 ×3 | 1,1,1 | 12.05 / 13.46 / 11.37 | 7 / 7 / 8 |
| 식대 | 1 | 5.75 | 5 |
| 출장 | 1 | 7.31 | 6 |
| 비품 | 1 | 10.21 | 6 |
| 회의 ×3 | 1,1,1 | 6.00 / 5.84 / 5.85 | 5 / 5 / 5 |
| 회식 | 1 | 10.75 | 9 |

**2차 라운드 — RAG 컨텍스트 고사(top_k=1로 낮춰 LLM이 근거 부족한 채로 추측하게 유도) 5건**

| scope | 시도횟수 | 응답시간(초) |
|---|---|---|
| GLOBAL | 1 | 7.84 |
| 접대 | 1 | 8.41 |
| 식대 | 1 | 2.26 |
| 출장 | 1 | 4.33 |
| 비품 | 1 | 2.55 |

**수치 지표(전체 16건 합산)**

| 지표 | 값 | 산출 방법 |
|---|---|---|
| 1차 시도 성공률 | **100%** (16/16) | `attempts==1`인 비율 |
| 재시도 발생률 | **0%** (0/16) | `attempts>1`인 비율 |
| 응답시간 평균 | **7.65초** | 16건 산술평균 |
| 응답시간 중앙값 | **7.58초** | 정렬 후 8·9번째 값 평균 |
| 응답시간 최소/최대 | **2.26초 / 13.46초** | — |
| 응답시간 p95(근사) | **≈13.1초** | 정렬 16건 중 95th 백분위 근사 |
| 3회 전부 재시도 시 예상 최악 총 소요시간 | **≈42초**(관측 최대값×3 + discard 왕복 여유) | 300초 타임아웃 대비 **약 7배 여유** |

**통계적 해석 — "0% 실패"를 곧이곧대로 "절대 실패 안 함"으로 읽으면 안 된다**: 표본이 16건뿐이라 진짜 실패율이 0이라고 확정할 수 없다. **Rule of Three**(사건이 0번 관측된 이항분포에서 95% 신뢰상한은 대략 `3/n`)를 적용하면, 실패율의 95% 신뢰상한은 `3/16 ≈ 18.75%` — 즉 "최대 5번에 1번 정도는 실패(재시도 진입)할 가능성이 통계적으로 아직 배제되지 않는다"는 뜻이다. 재시도 루프가 **드물게라도 실제로 필요해질 가능성은 여전히 있고**, 이번 검증은 "루프가 정상 작동한다"와 "정상 조건에서는 자주 발동하지 않는다"까지만 입증한다.

**RAG 고사(top_k=1) 조건에서도 5/5 성공** — 컨텍스트를 줄여 LLM이 추측할 여지를 늘려도 sanitize/구조검증 실패가 유발되지 않았다. 현재 프롬프트의 스키마 제약(strict JSON schema로 `decision`은 enum 강제, `var` 경로는 텍스트 나열이지만 모델이 비교적 보수적으로 따름)이 실패를 잘 막고 있다는 정황 — 다만 이것도 표본 5건이라 결정적이진 않음.

**결론**: 재시도 루프는 정상 작동하지만 관측된 조건에서는 **안전망 역할**(자주 발동하지 않음)에 가깝다. 타임아웃 증가(120s→300s)는 관측된 최악 케이스 대비 충분한 여유(약 7배)가 있다.

## 6. MCP 툴콜링 전면 재작성 (§1.2-1)

### 6.1 마운트 버그 2건 (v1과 무관한 기존 결함, 검증 착수하며 발견·수정)

MCP가 "연결만 하면 된다"는 초기 추정을 검증하던 중, MCP 서버 자체가 **두 겹으로 죽어 있었다**는 게 드러났다.

1. **`mcp/server.py`**: `mcp.tool(_fn)`로 9개 툴을 등록하고 있었는데, 설치된 fastmcp 2.1.2의 `FastMCP.tool()`은 `(name=None, description=None, tags=None) -> Callable[[Callable],Callable]` — **데코레이터 팩토리**라 먼저 `()`로 호출해야 한다. `mcp.tool(_fn)`은 `_fn`을 `name` 위치인자로 넘기는 꼴이라 실제로는 아무것도 등록되지 않았다. 수정: `mcp.tool()(_fn)`.
2. **`main.py`**: `app.mount("/mcp", mcp.http_app())` — `http_app()`은 fastmcp 이후 버전(Streamable HTTP)에 추가된 메서드로, 설치된 2.1.2엔 없다(`AttributeError`). 이 버전에서 ASGI 앱을 얻는 방법은 `sse_app()`뿐. 수정: `mcp.sse_app()`.

둘 다 `main.py`의 `try/except`가 조용히 삼키고 경고 로그만 남겨서(`FastMCP mount skipped: ...`), 앱은 정상 부팅되고 아무도 실패를 눈치채지 못한 채 오래 방치돼 있었다. **레포 전체에서 이 마운트 코드는 최근에 아무도 안 건드렸고**(마지막 커밋이 초기 `모노레포 구조`/`policy 1차 정합`), **3개 에이전트(Draft/Rule/Risk) 전부 이 마운트를 거치지 않고 `app.mcp.tools` 함수를 직접 import해서 우회하고 있었다** — 그래서 아무도 이 마운트가 죽어 있다는 걸 몰랐다. 고쳐도 기존 세 에이전트 동작에 영향 없음(다들 우회 중이므로) — 순수 추가 효과만 있다고 판단하고 진행.

수정 확인: `fastmcp.Client(mcp)`로 in-process 접속해 `list_tools()` → 9개 정상 등록 확인, `call_tool("search_policy", ...)` → 실제 RAG 결과 반환 확인.

### 6.2 Rule Agent를 실제 MCP 클라이언트로 전환

신규 파일 [`apps/ai/app/agents/rule_agent_v0/mcp_client.py`](../../apps/ai/app/agents/rule_agent_v0/mcp_client.py) — `fastmcp.Client(mcp)`가 `FastMCP` 인스턴스를 직접 받으면 **in-process 트랜스포트**로 붙는다(HTTP 왕복 없음, `/mcp` HTTP 마운트와는 별개 경로 — 그건 Claude Desktop 같은 외부 클라이언트용). `Client`는 비동기 전용이라 매 호출을 `asyncio.run()`으로 감싼 동기 `call_tool(name, **kwargs)` 하나만 노출한다(FastAPI 동기 라우트 핸들러는 스레드풀에서 돌아 이미 실행 중인 루프가 없어 안전).

`agent.py`의 LLM 호출 방식 자체를 재작성:
- **이전**: `search_policy()`를 파이썬이 미리 실행해 청크를 프롬프트에 박아넣고, `response_format=json_schema`로 LLM을 1회 호출해 끝.
- **이후**: `_run_generation_loop()`가 OpenAI `tools=[search_policy, submit_rule_nodes]`로 멀티턴 루프를 돈다. `search_policy`는 `mcp_client.call_tool()`로 진짜 MCP 프로토콜을 태워 실행되고, `submit_rule_nodes`(종료 툴, 파라미터 스키마는 기존 `_RESPONSE_SCHEMA`를 그대로 재사용)가 호출돼야 루프가 끝난다. 안전판 `MAX_TOOL_TURNS=6`.

**기존 "RAG 청크는 outer 재시도 3회 전체에서 재사용" 결정(§1.2-4)과의 정합**: outer 루프가 매 attempt마다 새로 만들지 않고, `generate()`가 최초 1회만 MCP로 검색한 청크(`initial_chunks`)를 매 attempt의 대화 맥락에 고정으로 심는다. 모델이 그걸로 부족하다고 판단할 때만 **대화 안에서** 추가로 `search_policy`를 호출한다 — outer 재시도 간의 재사용 보장은 유지하면서, 한 attempt 내부에서는 진짜 에이전틱하게 검색할 수 있게 절충했다.

### 6.3 실동작 검증

- 실제 LLM(gpt-4o-mini) 호출 3건(식대·출장·회의 scope)에서 전부 `DRAFT_SAVED` 성공.
- **`mcp_client.call_tool` 호출을 트레이싱**해 실제로 모델이 몇 번, 어떤 질의로 `search_policy`를 불렀는지 확인: 출장 scope에서 초기 1회(top_k=6) + 모델이 스스로 2회 추가 호출("출장비 사전승인 기준", "출장비 정산", 각 top_k=5) — **진짜 에이전틱 동작**(단순히 초기 청크만 쓰고 끝내는 게 아니라, 부족하다고 판단해 스스로 재검색)을 실측으로 확인.
- outer 재시도 루프 회귀 확인: `_run_generation_loop`를 가짜 실패→성공으로 주입해 재시도 카운터·피드백 전달이 새 아키텍처에서도 정상 작동하는 것 확인(`attempts:2`).
- 실제 Django 프록시 경로(`/api/rules/generate/`)로도 재확인 — `200 DRAFT_SAVED`.
- 테스트로 만든 그래프 전부 `discard_draft`로 정리, DB 잔존 없음 확인.

## 7. 적재→생성 자동 트리거 (§1.2-2)

### 7.1 확정된 스코프와 구현

- **scope 범위**: 업로드 시 고른 scope 1개만(팀 결정) — `IngestRequest.ruleScope`가 이미 단일 값 계약이라 별도 변경 불필요.
- **재색인 제외**(팀 결정): 같은 문서를 재색인할 때마다 새 그래프 계열이 쌓이는 걸 막기 위해, **최초 업로드에서만** 자동 생성하고 재색인에서는 안 한다.
- **재색인 여부를 어떻게 판별했나**: Django가 정답을 이미 갖고 있다 — `PolicyDocViewSet.create()`(최초 업로드)와 `.reembed()`(재색인) 두 액션이 공통으로 `_start(doc)`/`_dispatch(doc)`를 거치는데, 이 둘을 `is_reindex: bool` 키워드 인자로 구분해서 FastAPI로 보내는 `IngestRequest`에 `isReindex` 필드를 새로 실었다. FastAPI `rule_trigger.trigger()`가 이 값으로 분기.

### 7.2 변경 파일

| 파일 | 변경 |
|---|---|
| [`apps/core/domain/policies/policy_doc_views.py`](../../apps/core/domain/policies/policy_doc_views.py) | `_dispatch`/`_start`에 `is_reindex` 키워드 인자 추가, `create()`는 `False`로 `reembed()`는 `True`로 호출. 페이로드에 `isReindex` 추가 |
| [`apps/ai/app/api/embeddings.py`](../../apps/ai/app/api/embeddings.py) | `IngestRequest.isReindex: bool = False` 추가, `rule_trigger.trigger(..., is_reindex=req.isReindex)`로 전달 |
| [`apps/ai/app/rag/rule_trigger.py`](../../apps/ai/app/rag/rule_trigger.py) | **전면 구현** — `NOT_IMPLEMENTED` 스텁을 실제 `rule_agent_v0.agent.generate()` 호출로 교체. 신규 상태값 `SKIPPED_NO_SCOPE`(scope 미지정)·`SKIPPED_REINDEX`(재색인). 실패해도 예외를 삼켜 적재 자체를 실패로 만들지 않음(`ERROR` 상태로 보고) |

### 7.3 실동작 검증

`trigger()`를 직접 호출해(무거운 docling 파싱까지 갈 필요 없이, 이 함수의 신규 로직만 검증) 3가지 분기 전부 확인:

| 케이스 | 결과 |
|---|---|
| `is_reindex=True` | `SKIPPED_REINDEX`, `generate()` 호출 자체가 안 일어남(그래프 생성 없음) |
| `scope=""` | `SKIPPED_NO_SCOPE` |
| `is_reindex=False` + 유효 scope(비품) | 실제 `generate()` 호출 → `DRAFT_SAVED`, `detail`에 "자동 생성 완료 — 그래프 #67 (DRAFT, 시도 1회)" 같은 사람이 읽을 문구 합성(기존 `generate()` 성공 응답엔 `detail` 필드가 원래 없어서 화면 표시용으로 별도 조립) |

프론트 `PolicyDocuments.tsx`가 읽는 필드(`d.ruleTrigger?.detail`)는 모든 분기에서 문자열로 채워지도록 확인 — 기존 표시 로직이 안 깨짐(비침습).

## 8. 대화형 자연어 수정 에이전트 (§1.2-5)

### 8.1 설계

§1.2-1에서 만든 MCP 툴콜링 패턴을 그대로 재사용 — 신규 모듈 [`apps/ai/app/agents/rule_agent_v0/chat.py`](../../apps/ai/app/agents/rule_agent_v0/chat.py):

- 사용자가 자연어로 지시하면(`"이 노드 삭제해줘"`, `"3만원 이상으로 바꿔줘"`, `"몇 개 노드 있어?"`) LLM이 현재 그래프 상태(`django_client.get_graph`로 조회, 프롬프트에 전문 주입) + EvalContext 허용 경로를 보고 툴을 호출.
- 툴 5종: `search_policy`(MCP, 근거 재검색) / `update_node` / `create_node` / `delete_node`(전부 **기존 룰 콘솔 CRUD API 재사용**, 신규 저장 경로 없음) / `answer`(종료 툴, 텍스트 요약).
- 안전판 `MAX_CHAT_TURNS=10`(여러 노드를 한 지시로 고치는 경우를 감안해 생성 루프보다 여유 있게).
- 대화 로그를 `django_client.post_messages()`로 `RuleAuthoringMessage`에 남긴다 — **이 테이블은 예전부터 있었지만 실제로 쓰는 코드가 없었다**(§1.2-5 설계 시점 실측). 이번이 첫 실제 쓰기 경로.
- **스코프 축소 결정**: "노드 재생성"을 위한 전용 툴은 안 만들었다 — LLM이 `search_policy`로 근거를 다시 찾은 뒤 `update_node`를 부르는 것으로 충분히 커버된다고 판단(별도 RAG 기반 "단일 노드 재생성" 전용 파이프라인은 안 만듦, 필요해지면 후속 과제).
- 편집 직후 자동 시뮬레이션은 안 돌린다 — 사람이 콘솔에서 직접 고칠 때도 검증은 별도 명시적 단계(①테스트검증)라 이 기본 동작에 맞췄다.

### 8.2 변경/신규 파일

| 파일 | 변경 |
|---|---|
| [`apps/ai/app/agents/rule_agent_v0/chat.py`](../../apps/ai/app/agents/rule_agent_v0/chat.py) | 신규 — 대화 루프 본체 |
| [`apps/ai/app/agents/rule_agent_v0/django_client.py`](../../apps/ai/app/agents/rule_agent_v0/django_client.py) | `get_graph`/`create_node`/`update_node`/`delete_node`/`post_messages` 추가(전부 기존 콘솔 API 호출 — `GET /rules/{id}/`, `POST /rules/{id}/nodes/`, `PATCH·DELETE /rules/{id}/nodes/{key}/`, `POST /rules/{id}/messages/`) |
| [`apps/ai/app/agents/rule_agent_v0/api.py`](../../apps/ai/app/agents/rule_agent_v0/api.py) | `POST /agent/rule-v0/converse` 신설 |
| [`apps/core/domain/policies/views.py`](../../apps/core/domain/policies/views.py) | `POST /api/rules/{id}/converse/` 신설(`generate_graph`와 같은 얇은 프록시 패턴), `get_permissions`에 `converse` 액션을 `CanViewRule` 그룹에 추가 |

### 8.3 검증 중 발견·수정한 버그: 부분 수정이 다른 필드를 지움

**증상**: "severity를 CRITICAL로 바꿔줘"만 지시했는데, 실제로 반영된 노드에서 `title`/`decision`/`origin`/`flag` 등 손대지 않은 필드가 전부 사라짐.

**원인**: Django `update_node` 액션은 `action` 필드를 **부분 병합이 아니라 통째로 교체**한다(`node.action = request.data["action"]`). `chat.py`가 LLM이 명시한 필드(`severity`만)로 새 딕셔너리를 만들어 그대로 보냈더니, 나머지 필드가 빈 채로 덮어써졌다.

**수정**: 요청 전에 **기존 `action` 딕셔너리를 베이스로 복사한 뒤 변경분만 덮어써서** 보내도록 수정(`existing.get("action")` → 복사 → 변경 필드만 갱신 → 그 전체를 payload로 전송). 같은 대화 턴 안에서 같은 노드를 또 건드릴 경우를 대비해, 툴 실행 성공 시 로컬 `graph` 스냅샷(`nodes`/`action`/`condition`)도 같이 갱신(`create_node`/`delete_node`도 동일하게 로컬 반영) — Django에 매번 재조회하지 않고도 턴 내 일관성을 유지.

이 버그는 **실제 검증 과정에서 잡혔다** — "그럴듯하게 보이지만 실제로 데이터를 깨뜨리는" 클래스의 결함이라, 실동작 테스트 없이 코드 리뷰만 했으면 놓쳤을 가능성이 크다.

### 8.4 실동작 검증 (전부 실제 LLM+실제 Django CRUD, 임시 그래프는 이후 discard로 정리)

| 시나리오 | 결과 |
|---|---|
| 노드 삭제("이 노드 삭제해줘") | `applied_changes:[{"action":"delete_node",...}]`, 실제로 그래프에서 사라짐 확인 |
| severity만 변경(버그 수정 전) | title/decision 등 유실 — **버그 재현** |
| severity만 변경(버그 수정 후) | severity만 바뀌고 나머지 필드 전부 보존 확인(필드별 비교로 검증) |
| 새 노드 생성("tx.amount가 50만원 넘으면 REVIEW") | `create_node` 적용, 생성된 노드의 condition/action 정확히 확인 |
| 순수 질문("노드 몇 개 있어?") | `applied_changes` 빈 배열 — 그래프 변경 없이 텍스트로만 답변 |
| 실제 Django 프록시 경로(`/api/rules/{id}/converse/`) | `200`, 정상 응답. `RuleAuthoringMessage`에 실제 user/ai 로그 행 생성 확인(이 테이블의 첫 실사용) |

## 9. §1.2 전 항목 최종 상태

| # | 항목 | 상태 |
|---|---|---|
| 1 | MCP 툴콜링 전환 | ✅ 구현+검증 완료(§6) |
| 2 | 적재→생성 자동 트리거 | ✅ 구현+검증 완료(§7) |
| 3 | 검증(그래프 검증) 재사용 | ✅ 구현+검증 완료(§1~4) |
| 4 | 검증→재생성 루프 | ✅ 구현+검증 완료(§1~5) |
| 5 | 대화형 자연어 수정 에이전트 | ✅ 구현+검증 완료(§8) |
| 6 | 시뮬레이션 보고서 LLM 서술 | 결정: 추가 안 함(팀 확인, 코드 변경 없음) |

**남은 것**: 프론트 화면에서 실제 버튼/채팅 UI로 눈으로 확인하는 것(API 레벨까지만 검증, §3a 계약상 프론트 작업은 별도), Risk Review Agent 쪽 MCP 전환(§2.2, 미착수), 원격 브랜치 push 여부.

## 10. nginx 경유 전체 체인 검증 (2026-08-16) — 자동 트리거 최종 고리에서 무관한 사전 버그로 막힘

프론트 UI만 빼고 **nginx(`localhost:8080`) → Django 세션 로그인 → 실제 PDF 업로드 → 백그라운드 파싱** 순으로 실제 사용자 경로를 그대로 밟아 검증을 시도했다.

**성공 확인:**
- `POST /api/auth/login/`(nginx 경유, `acclead` 실로그인) → 세션 쿠키 정상 발급
- `POST /api/policy-docs/`(nginx 경유, `multipart/form-data` 실제 PDF 업로드 + `ruleScope=비품`) → `201`, `PolicyDoc` 생성, 상태 `PENDING`
- Django `_dispatch()` → `POST /embeddings/ingest`(FastAPI) 호출 → 백그라운드 태스크 기동까지 정상(§1.2-2에서 추가한 `isReindex` 필드도 정상 전달, 이 경로 자체는 문제 없음)

**여기서 막힘 — v1과 무관한 사전 존재 버그:**
파싱 단계(`ingest_pdf()` 내부 docling 호출)에서 `'PdfPipelineOptions' object has no attribute 'heading_hierarchy_options'`로 실패. 원인: `requirements.txt`가 `docling>=2.0,<3.0`로 버전을 열어뒀는데, 컨테이너에 실제 설치된 `docling==2.87.0`에서는 `apps/ai/app/rag/parsing/engine.py:48`가 참조하는 `PdfPipelineOptions.heading_hierarchy_options` 속성 자체가 없어졌다(직접 확인: `dir(PdfPipelineOptions())`에 `heading`/`hierarch` 관련 속성 0개). **이 세션에서 `apps/ai/app/rag/parsing/`은 전혀 건드리지 않았다** — Rule Agent v1 작업과 무관한, docling 라이브러리 버전 드리프트로 인한 별도 결함.

**결정(2026-08-16, 팀 확인)**: 지금은 넘어간다 — 이 버그는 파싱 파이프라인 자체의 문제라 별도로 다룰 사안. 자동 트리거(§1.2-2, §7)의 **트리거 판단 로직 자체**(`SKIPPED_REINDEX`/`SKIPPED_NO_SCOPE`/실제 `generate()` 호출)는 §7.3에서 이미 직접 호출로 검증됐고 유효하다 — 이번에 막힌 건 "실제 업로드→파싱까지 끝나야 트리거가 불린다"는 **선행 조건(파싱 성공)** 쪽이지, 트리거 로직 자체가 아니다.

**남은 검증 공백**: 실제 업로드가 파싱까지 성공했을 때 트리거가 자동으로 불려서 `PolicyDoc.ruleTrigger` 필드에 결과가 실제로 채워지는 것까지의 **마지막 한 고리**는, 이 docling 버그가 고쳐지기 전까지는 실제 업로드로 닫아볼 수 없다.

## 11. 구현 후 전수 검토 (2026-08-16) — 잡은 버그 3건 + 문서 정정 1건

전 변경 파일을 다시 정독하고 회귀를 돌린 결과(Django 100건 전체 통과 · ai 12건 통과 — 컨테이너에서 원래 실행 불가한 파싱/청킹 테스트 2파일 제외, 경로 계산이 호스트 레포 기준이라 기존부터 컨테이너에선 collection 에러):

### 11.1 [수정] 대화형 수정이 dedup 원복(그래프 삭제)을 처리 못 함
Django `update_node`에는 "편집 결과가 같은 계열의 ACTIVE와 내용이 같아지면 **DRAFT를 삭제**하고 `revertedToGraphId`를 반환"하는 dedup이 있다(`views.py`, 룰 콘솔 프론트는 이 키를 처리함). `chat.py`는 이 응답을 무시하고 계속 진행하다 마지막 `get_graph()`에서 404로 터졌다 — **실측 재현 완료**: ACTIVE 회식 그래프(id 36)에서 `POST /versions`로 v3 초안을 만들고 노드를 내용 그대로 update하니 `{'revertedToGraphId': 36}` 반환 + 초안 실제 삭제 + 이후 `get_graph` 404. 룰 콘솔의 정상 편집 흐름(ACTIVE에서 버전 초안 생성 후 대화로 편집, "방금 바꾼 거 되돌려줘")에서 실제로 도달 가능한 경로다. **수정**: `saved.get("revertedToGraphId")`를 감지해 `graph_gone` 플래그를 세우고 — 같은 배치의 나머지 편집 툴 호출은 404 대신 명확한 사유로 차단(answer만 허용), 응답의 `applied_changes`에 `reverted_to_active` 항목 추가, 최종 `graph`는 재조회 없이 `None` 반환.

### 11.2 [수정] `create_node`가 기존 노드를 조용히 덮어씀
Django `create_node`는 `get_or_create`라 이미 있는 node_key로 부르면 200이 나고, 이어지는 update가 기존 노드를 통째로 교체한다 — "새 노드 생성" 의도로 다른 노드가 파괴되는 사고. **수정**: 로컬 그래프 스냅샷에서 중복 키를 먼저 확인해 거부(LLM에게 update_node를 쓰거나 다른 키를 쓰라고 안내). **검증**: 실 LLM은 중복 키 지시를 받아도 알아서 다른 키로 회피하는 경향이 있어(실측), 가드 자체는 LLM 응답을 스크립트로 주입해 중복 키를 강제하는 방식으로 결정론적으로 확인 — `applied_changes` 비어 있고 기존 노드 무사.

### 11.3 [수정] `create_node` 성공 후 내용 채우기 실패 시 반쪽 노드 잔존
빈 노드 생성(`POST /nodes/`)은 성공했는데 이어지는 `PATCH`가 실패하면 "(제목 미설정)" 빈 노드가 그래프에 남았다. **수정**: PATCH 실패 시 best-effort로 방금 만든 노드를 `delete_node`로 정리한 뒤 원인 예외를 다시 올림(정리 실패는 원인을 가리지 않게 무시).

### 11.4 [문서 정정] 검증 통계의 모델명 오기
§4.5 참조 — "gpt-5-mini"로 기록했던 16회 통계의 실제 모델은 `gpt-4o-mini`. `.env`의 `RULE_AGENT_V0_MODEL`은 compose가 전달하지 않는 죽은 설정.

### 11.5 [기록만, 수정 안 함] 알고 넘어가는 한계
- **converse 프록시 타임아웃 180s vs 이론 최악(10턴×60s=600s)**: 실측 턴당 2~6초라 현실적으로 여유 있지만, 병리적 케이스에선 Django 프록시가 먼저 끊기고 FastAPI 쪽 편집은 계속 진행될 수 있다(편집 자체는 반영됨, 사용자만 503을 봄). 문제로 관측되면 그때 타임아웃 조정.
- **`generate()` 응답의 `attempts` 타입 비일관**: 성공 시 int(시도 횟수), 소진 실패 시 list(시도별 이력). §2에 문서화된 의도적 선택이지만 프론트가 붙을 때 헷갈릴 수 있는 지점.
- **적재 중 상태 표시**: `_run`(embeddings.py)이 룰 트리거(LLM 호출 ~10초)를 돌리는 동안 문서 상태가 `PARSING`에 머문다 — DONE 콜백이 트리거 완료 후에 나가므로. 표시 문제일 뿐 동작 문제 아님.
- **`search_policy` 모델 호출 실패 시 재시도 유도 없이 바로 예외 전파**: `_run_generation_loop`(agent.py)·`converse`(chat.py) 안에서 모델이 스스로 부른 `search_policy`가 실패하면(Chroma 일시 장애 등) 그 예외가 캐치 없이 그대로 위로 올라가 시도/대화 턴 전체가 502로 끝난다. "검색 실패, 다시 시도해봐" 식으로 tool 메시지에 담아 모델에게 돌려주고 계속 진행하게 만들 수도 있는 자리인데, 지금은 안 그렇게 돼 있다. 버그는 아님(에러가 삼켜지지 않고 정상적으로 올라감) — 견고성 개선 여지로만 기록, 미착수.

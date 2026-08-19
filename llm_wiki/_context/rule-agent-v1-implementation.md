# Rule Agent v1 — 구현 기록

> 계획/설계 근거는 `_context/agent-v1-upgrade-plan.md`(§1 전 항목)를 참조. 이 문서는 **실제로 무엇을 만들었고, 어떻게 검증했는지**만 다룬다. 브랜치: `feature/rule-agent-v1`. §1 6개 항목 전부 이 문서에 있다 — ①검증재사용(§3) ②재생성루프(§1~4) ③자동트리거(§7) ④대화형에이전트(§8) ⑤MCP툴콜링전환(§6) ⑥시뮬레이션LLM서술(결정: 안 함, 코드변경없음).

## 1. 변경 파일 (검증→재생성 루프, §1 항목3·4)

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
- 이걸로 §1 항목4의 타임아웃 증가(120s→300s)를 포함해 실제 진입점 전체가 동작함을 확인.

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

## 6. MCP 툴콜링 전면 재작성 (§1 항목1)

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

**기존 "RAG 청크는 outer 재시도 3회 전체에서 재사용" 결정(§1 항목4)과의 정합**: outer 루프가 매 attempt마다 새로 만들지 않고, `generate()`가 최초 1회만 MCP로 검색한 청크(`initial_chunks`)를 매 attempt의 대화 맥락에 고정으로 심는다. 모델이 그걸로 부족하다고 판단할 때만 **대화 안에서** 추가로 `search_policy`를 호출한다 — outer 재시도 간의 재사용 보장은 유지하면서, 한 attempt 내부에서는 진짜 에이전틱하게 검색할 수 있게 절충했다.

### 6.3 실동작 검증

- 실제 LLM(gpt-4o-mini) 호출 3건(식대·출장·회의 scope)에서 전부 `DRAFT_SAVED` 성공.
- **`mcp_client.call_tool` 호출을 트레이싱**해 실제로 모델이 몇 번, 어떤 질의로 `search_policy`를 불렀는지 확인: 출장 scope에서 초기 1회(top_k=6) + 모델이 스스로 2회 추가 호출("출장비 사전승인 기준", "출장비 정산", 각 top_k=5) — **진짜 에이전틱 동작**(단순히 초기 청크만 쓰고 끝내는 게 아니라, 부족하다고 판단해 스스로 재검색)을 실측으로 확인.
- outer 재시도 루프 회귀 확인: `_run_generation_loop`를 가짜 실패→성공으로 주입해 재시도 카운터·피드백 전달이 새 아키텍처에서도 정상 작동하는 것 확인(`attempts:2`).
- 실제 Django 프록시 경로(`/api/rules/generate/`)로도 재확인 — `200 DRAFT_SAVED`.
- 테스트로 만든 그래프 전부 `discard_draft`로 정리, DB 잔존 없음 확인.

## 7. 적재→생성 자동 트리거 (§1 항목2)

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

## 8. 대화형 자연어 수정 에이전트 (§1 항목5)

### 8.1 설계

§1 항목1에서 만든 MCP 툴콜링 패턴을 그대로 재사용 — 신규 모듈 [`apps/ai/app/agents/rule_agent_v0/chat.py`](../../apps/ai/app/agents/rule_agent_v0/chat.py):

- 사용자가 자연어로 지시하면(`"이 노드 삭제해줘"`, `"3만원 이상으로 바꿔줘"`, `"몇 개 노드 있어?"`) LLM이 현재 그래프 상태(`django_client.get_graph`로 조회, 프롬프트에 전문 주입) + EvalContext 허용 경로를 보고 툴을 호출.
- 툴 5종: `search_policy`(MCP, 근거 재검색) / `update_node` / `create_node` / `delete_node`(전부 **기존 룰 콘솔 CRUD API 재사용**, 신규 저장 경로 없음) / `answer`(종료 툴, 텍스트 요약).
- 안전판 `MAX_CHAT_TURNS=10`(여러 노드를 한 지시로 고치는 경우를 감안해 생성 루프보다 여유 있게).
- 대화 로그를 `django_client.post_messages()`로 `RuleAuthoringMessage`에 남긴다 — **이 테이블은 예전부터 있었지만 실제로 쓰는 코드가 없었다**(§1 항목5 설계 시점 실측). 이번이 첫 실제 쓰기 경로.
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

## 9. §1 전 항목 최종 상태

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
- Django `_dispatch()` → `POST /embeddings/ingest`(FastAPI) 호출 → 백그라운드 태스크 기동까지 정상(§1 항목2에서 추가한 `isReindex` 필드도 정상 전달, 이 경로 자체는 문제 없음)

**여기서 막힘 — v1과 무관한 사전 존재 버그:**
파싱 단계(`ingest_pdf()` 내부 docling 호출)에서 `'PdfPipelineOptions' object has no attribute 'heading_hierarchy_options'`로 실패. 원인: `requirements.txt`가 `docling>=2.0,<3.0`로 버전을 열어뒀는데, 컨테이너에 실제 설치된 `docling==2.87.0`에서는 `apps/ai/app/rag/parsing/engine.py:48`가 참조하는 `PdfPipelineOptions.heading_hierarchy_options` 속성 자체가 없어졌다(직접 확인: `dir(PdfPipelineOptions())`에 `heading`/`hierarch` 관련 속성 0개). **이 세션에서 `apps/ai/app/rag/parsing/`은 전혀 건드리지 않았다** — Rule Agent v1 작업과 무관한, docling 라이브러리 버전 드리프트로 인한 별도 결함.

**결정(2026-08-16, 팀 확인)**: 지금은 넘어간다 — 이 버그는 파싱 파이프라인 자체의 문제라 별도로 다룰 사안. 자동 트리거(§1 항목2, §7)의 **트리거 판단 로직 자체**(`SKIPPED_REINDEX`/`SKIPPED_NO_SCOPE`/실제 `generate()` 호출)는 §7.3에서 이미 직접 호출로 검증됐고 유효하다 — 이번에 막힌 건 "실제 업로드→파싱까지 끝나야 트리거가 불린다"는 **선행 조건(파싱 성공)** 쪽이지, 트리거 로직 자체가 아니다.

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

## 12. 검증셋(테스트케이스) 자동생성 — 구현 (2026-08-18, `agent-v1-upgrade-plan.md` §4)

### 12.1 사전 정정 — 팀원이 독립적으로 발견한 같은 버그 2건

이 기능을 시작하기 전, `git pull origin main`으로 다른 팀원 작업을 받았는데 **§10에서 발견한 docling 버그와 §6.1의 MCP 마운트 버그를 팀원이 독립적으로 같은 원인까지 진단해서 근본 수정**했다("도클링환경수정"·"버그 수정" 커밋) — `requirements.txt`를 열린 범위(`>=2.0,<3.0`)에서 정확한 버전 고정(`docling==2.119.0`, `fastmcp==2.4.0` 등)으로 바꿔서 둘 다 해결. 팀원 커밋 메시지의 원인 서술이 이 문서 §6.1·§10의 서술과 사실상 동일 — 두 세션이 독립적으로 같은 결론에 도달했다는 뜻.

버전이 올라가면서 `main.py`가 예전(fastmcp 2.1.2용) 우회책(`mcp.sse_app()`)을 여전히 쓰고 있길래, 정석 메서드(`mcp.http_app()`)로 정리했다. `docker compose build ai` 재빌드 후 `fastmcp==2.4.0` 확인, `/mcp` 마운트 정상(307 리다이렉트 — Starlette 마운트의 정상 동작), Rule Agent 회귀(`generate()` 1건 실호출) 통과 확인.

### 12.2 설계 — §4의 두 축을 그대로 구현

신규 모듈 [`apps/ai/app/agents/rule_agent_v0/testcases.py`](../../apps/ai/app/agents/rule_agent_v0/testcases.py):

- **축1(커버리지 기반 결정론적 생성)**: `_solve(condition, want_match, boundary)` — 그래프 노드의 JSON-Logic 조건 트리(`and`/`or`/`not`/비교 연산자)를 재귀적으로 역산해서 그 조건을 만족(혹은 경계)시키는 `facts`(EvalContext dot-path → 값)를 계산한다. `var op 리터럴` 비교와 그 조합만 지원 — 지원 안 되는 형태(예: 목록에 없는 값을 요구하는 `in` 부정)는 `None`을 반환해 해당 노드를 건너뛰고 사유를 응답에 남긴다(지어내지 않음).
  - **var-vs-var 처리**(예: `tx.amount > policy.dining_per_person_limit`): 참조 대상 경로에 기준값(30000)을 박아넣고, 좌변을 그 기준값 대비로 계산 — 두 경로를 모두 facts에 채운다.
  - 노드당 2건: `boundary=False`(임계값 대비 넉넉한 마진)와 `boundary=True`(임계값 바로 옆 1단위) — `>`/`>=` 같은 연산자 실수를 경계값이 잡는다.
- **축2(자체 검증 루프) — "기대값 vs 실행 결과" 비교 방식**: 이 기능의 핵심 메커니즘이라 명시적으로 적어둔다.
  1. **기대값(정답)을 실행 전에 결정론적으로 먼저 만든다**: 후보의 `decision`은 노드 메타데이터(`action.decision`)를 그대로 가져온 값이고, `facts`는 축1의 `_solve()`가 그 노드의 조건식만 보고 역산한 값이다 — **LLM도 엔진도 아직 아무것도 실행하기 전에** "이 값을 넣으면 이 노드가 걸려서 이 decision이 나와야 한다"는 결론이 먼저 정해진다.
  2. **실제값은 진짜 룰 엔진을 돌려서 얻는다**: 후보를 실제로 저장하고 `django_client.simulate_graph()`(§1-3, 기존 `/simulate` 재사용)를 호출 — 이건 에이전트가 만든 그래프를 Django의 실제 결정론적 엔진(`engine.py::run_rule_engine`)으로 진짜 실행시키는 것이다. **[설계 문서에서 정정]** §4.2가 지목했던 MCP `run_rule_engine`은 실제 Settlement+ACTIVE 그래프 대상이라 DRAFT 그래프의 가상 케이스엔 못 쓴다는 게 구현 중 드러나서 이걸로 바꿨다.
  3. **비교**: `testResults`의 `path`(실제로 지나간 노드 목록)에 의도한 노드가 있고, `decision`이 1번의 기대값과 같아야 통과. `path` 확인을 같이 하는 이유 — 단순히 최종 decision 값만 같으면 통과시키면, **다른 노드가 우연히 같은 decision을 내서 통과한 척하는 경우**(예: 상위 노드가 먼저 걸려서 같은 REJECT를 내는 경우)를 못 잡는다.
- LLM은 **라벨링에만** 관여 — 모든 후보를 한 번에 모아 1회 배치 호출로 `label`/`merchant`만 채운다(구조/정확성엔 관여 안 함). 실패해도 기본 라벨로 대체하고 생성 자체는 안 막는다.

### 12.2a [수정] 구현 후 재검토에서 잡은 버그 — `<=` 부정 매핑 오류

`_NEGATE_OP`(연산자를 `not`으로 감쌀 때 뒤집는 표)에 `"<=": "<"`로 잘못 적혀 있었다(정답은 `"<=": ">"` — `NOT(x<=L)`은 `x>L`인데 `x<L` 쪽으로 풀고 있었다). `not(tx.amount <= 30000)` 같은 조건에서 **조건을 만족 안 시키는 값을 만들어내는** 실질적 버그였다 — 실제 LLM 생성 그래프들에 `not` 연산자가 안 나와서 실측 검증(§12.5)에서는 안 걸렸다(잠재 버그). 코드 재검토 중 발견, 수정 후 `not(<=30000)` → `30001`(경계)/`45001`(여유) 둘 다 30000 초과로 올바르게 나오는 것 확인, 전체 회귀 재실행(Django 149건 통과) 확인.

### 12.3 실측으로 드러난 진짜 이유 — "조건만 보면 맞는데 실제로는 안 걸리는" 사례

첫 실제 테스트(scope=비품, 실제 LLM이 만든 그래프)에서 **8개 후보 중 4개가 자체검증에서 탈락**했다 — 전부 "상위 우선순위 노드가 먼저 걸려서" 의도한 노드에 도달하지 못한 케이스였다(그래프가 severity 순 선형 체인이라, 뒤쪽 노드를 위해 만든 값이 앞쪽 노드 조건도 만족시켜버리면 앞쪽에서 먼저 걸린다). 이건 **노드 조건 하나만 보고 값을 역산하는 방식으로는 원천적으로 못 잡고, 실제로 그래프를 돌려봐야만 드러나는 문제** — 자체검증 루프가 정확히 이걸 위해 필요하다고 설계 시점에 예상했던 그대로 실측에서 재현됐다. 탈락한 4건은 `unresolved`에 실제 관측된 `decision`/`path`와 함께 보고되고, **최종 검증셋에는 포함되지 않는다**(틀린 케이스를 몰래 끼워넣지 않음).

### 12.4 변경/신규 파일

| 파일 | 변경 |
|---|---|
| [`apps/ai/app/agents/rule_agent_v0/testcases.py`](../../apps/ai/app/agents/rule_agent_v0/testcases.py) | 신규 — 조건 역산·자체검증·라벨링·append 오케스트레이션 |
| [`apps/ai/app/agents/rule_agent_v0/django_client.py`](../../apps/ai/app/agents/rule_agent_v0/django_client.py) | `get_test_cases`/`put_test_cases` 추가(기존 `GET/PUT /rules/{id}/test-cases/` 재사용) |
| [`apps/ai/app/agents/rule_agent_v0/api.py`](../../apps/ai/app/agents/rule_agent_v0/api.py) | `POST /agent/rule-v0/test-cases/generate` 신설 |
| [`apps/core/domain/policies/views.py`](../../apps/core/domain/policies/views.py) | `POST /api/rules/{id}/test-cases/generate/` 신설(`converse`와 같은 얇은 프록시 패턴), DRAFT 상태 가드, `get_permissions`에 액션 추가 |
| [`apps/ai/app/main.py`](../../apps/ai/app/main.py) | §12.1의 `sse_app()`→`http_app()` 정리 |

### 12.5 실동작 검증 (전부 실제 LLM+실제 Django, 임시 그래프는 discard로 정리)

| 시나리오 | 결과 |
|---|---|
| 신규 그래프(기존 케이스 없음)에서 생성 | 8후보 중 4건 검증 통과·저장, 4건은 상위 노드 선점으로 탈락해 `unresolved`로 보고(§12.3) |
| 기존 케이스가 있는 그래프에 추가 생성(가짜 기존 케이스 1건 미리 심음) | 생성 후 기존 케이스 그대로 살아있음 확인 + 신규 6건이 `AUTO-N` 키로 추가됨 |
| 실제 Django 프록시 경로(`/api/rules/{id}/test-cases/generate/`) | `200`, `generated:10 unresolved:4` |
| **`SIMULATED` 상태인 실제 그래프(38번, 사람이 만든 진짜 케이스 5건)에 호출** | `400 "DRAFT 그래프만 검증셋을 자동생성할 수 있습니다"` — 시도조차 안 하고 막힘, 5건 그대로 무사 확인 |
| Django 전체 테스트 스위트 | 149건 통과(팀원 merge로 늘어난 e2e 테스트 포함) |

### 12.6 §4.4 결정 사항 반영

자체검증 재시도 2회(최초+1), append 키는 `AUTO-N`, 생성 직후 `/simulate` 자동 실행해 응답에 `simulationReport` 포함 — 전부 `agent-v1-upgrade-plan.md` §4.4에 최종 결정으로 반영.

### 12.7 v1 스코프 한계 (의도적으로 안 만든 것)

- 조건이 `var op 리터럴`형 비교의 and/or/not 조합이 아니면(예: 산술식) 생성 자체를 건너뛴다 — LLM 폴백으로 억지로 값을 만들지 않는다.
- 자체검증 실패 시 LLM에게 "왜 실패했는지" 피드백을 주고 다시 만들게 하는 건 안 만들었다(§1-4·§1-5의 피드백 루프와 다른 점) — 결정론적 역산이 실패하는 원인(주로 상위 노드 선점, §12.3)은 "가치가 조금 더 큰 값을 시도"하는 식으로 LLM이 반복해서 고칠 수 있는 성질이 아니라고 판단해서, 대신 재시도 1회(마진 조정) 후 실패로 보고하는 쪽을 택했다.

### 12.8 후속 정리 (2026-08-18)

- **워크플로우 순서 결정**: "①테스트검증" 단계는 이제 **검증셋 자동생성이 먼저, 사람의 수동 보정은 그다음**이 권장 순서로 정정됐다(`agent-v1-upgrade-plan.md` §1 항목3). `/simulate`가 자동으로 생성을 먼저 트리거하게 만드는 건 하지 않기로 함(명시적으로 확인됨) — 화면에 별도 "검증셋 자동생성" 버튼(§13.1)을 두는 쪽으로 확정.
- **시드 예시 케이스 정리**: 그래프 38("출장비 검증 그래프")에 있던 사람이 만든 예시 케이스 5건을 실제 API(`PUT /test-cases/` 빈 배열)로 삭제 — DB 직접 삭제가 아니라 정식 경로로 처리, 자동생성 기능이 생겼으니 더는 필요 없다는 판단.

## 13. 신규 기능 프론트 연동 + 대화형 수정 컨텍스트 버그 수정 (2026-08-18)

기존 기능(그래프 생성·대화형 수정·시뮬레이션·Active 승인)은 팀원이 이미 프론트 연동을 마친 상태였다. 이 세션에서 새로 추가한 기능(검증셋 자동생성)만 프론트가 비어 있어 이어서 연동하고, 사용 중 실제로 발견된 대화형 수정 버그(아래 §13.2)를 고쳤다.

### 13.1 검증셋 자동생성 — 프론트 연동

- `apps/web/src/api/client.ts`: `generateRuleTestCases(id)` — `POST /rules/{id}/test-cases/generate/`, timeout 200s(조건 역산+자체검증 왕복이 노드 수만큼 순차로 돎).
- `apps/web/src/screens/rule-console/SimulationReport.tsx`: 빈 검증셋 상태(`SimulationEmptyState`)와 결과 화면(`SimulationReportView`) 양쪽에 "검증셋 자동생성"(Sparkles 아이콘) 버튼 추가.
- `apps/web/src/screens/rule-console/SimulationTab.tsx`: `generating`/`genNote` 상태 + `autoGenerate()` 핸들러 — 생성 완료 후 응답에 포함된 `simulationReport`로 바로 화면을 갱신(§12.6, 별도 `/simulate` 재호출 없음).
- 실측: 실제 화면에서 버튼 클릭 → 검증셋 22건 생성(기존 케이스에 append) → 자동 실행된 시뮬레이션 결과가 화면에 바로 반영되는 것을 스크린샷으로 확인(정상 19 / 불일치 3, 불일치는 `UNRESOLVED_FACT:*` 게이트로 인한 정상적인 REVIEW 강등이라 버그 아님).

### 13.2 [버그 수정] 대화형 수정이 선택된 노드·이전 대화 이력을 서버에 보내지 않음

**증상(사용자 실제 재현)**: 화면에서 한 노드(T-10)를 선택한 채 "40만원으로 바꿔줘"라고만 지시했는데, 의도하지 않은 다른 노드(T-41)도 함께 수정됐다. 원인은 `converseRule()`이 매 턴 완전히 무상태(stateless)로 호출되고 있었던 것 — 화면이 지금 어느 노드를 보고 있는지도, 이전에 무슨 대화를 했는지도 서버에 전혀 넘기지 않아 LLM이 매번 그래프 전체 스냅샷만 보고 추측해야 했다.

**수정**:
- `chat.py`: `converse(graph_id, message, node_key=None)`로 시그니처 확장. `_build_user_prompt()`가 `node_key`로 "[사용자가 지금 화면에서 보고 있는 노드]" 블록을 프롬프트에 주입. 시스템 프롬프트에 규칙 7 추가 — 노드가 명시되지 않고 여러 노드가 똑같이 그럴듯하면 지어맞추지 말고 되묻는다. 신규 `_load_history(graph_id)`가 기존 `RuleAuthoringMessage` 로그(화면엔 항상 보이던 것)를 실제 LLM 메시지로 재구성해 최근 `MAX_HISTORY_MESSAGES=20`건을 시스템 프롬프트 뒤에 이어붙인다.
- `django_client.py`: `get_messages(graph_id)` 신규 — `GET /api/rules/{id}/messages/` 래퍼.
- `api.py`(`RuleConverseRequest`) · `views.py`(`converse` 액션) · `client.ts`/`ruleService.ts`/`DraftTab.tsx`: `node_key`/`nodeKey`를 요청 본문에 실어 나르도록 전 구간 배선.

**실동작 검증(실제 LLM, 임시 그래프 80·discard로 정리)**: 접대 scope 룰그래프(금액 구간이 겹치는 노드 rule_1~rule_4 포함)를 생성해 3가지 시나리오 확인 —
1. `node_key` 없이 "금액을 50만원으로 바꿔줘" → 인접 3개 구간 노드(rule_2/3/4)를 경계값 정합을 유지하며 함께 수정(구간 파티션이라 경계 하나만 바꾸면 빈 구간이 생기므로 타당한 동작 — 원래 버그였던 "무관한 노드까지 건드림"과는 다름).
2. `node_key='rule_1'`로 "금액을 20만원으로 바꿔줘" → rule_1과 그 인접 경계 rule_2만 수정, 더 먼 노드는 건드리지 않음.
3. 이력 검증 — 직전 턴에서 rule_1을 만졌는데, 노드명 언급 없이 "방금 그거 다시 25만원으로 해줘"만 보내자 이력에서 rule_1을 정확히 재식별해 수정. `_load_history`가 실제로 동작함을 확인.

Django 전체 테스트(149건) · 프론트 `tsc -b` 모두 통과.

### 13.3 시뮬레이션 보고서 — 서술문을 Rule Agent 실호출로 교체(플레이스홀더 해소)

**배경**: 시뮬레이션의 통계·판정(`stats`/`grades`/`testResults`/`historyResults`)은 애초부터 전부 실제 룰 엔진 결과였다. 다만 그 위에 얹는 서술문(`agentReport`, "## 개요 / ## 그래프 구성 평가 / ## 실행결과 / ## 주의깊게 살펴봐야 할 부분")은 `simulation.py`의 결정론적 마크다운 템플릿이 만들고, 응답에 `placeholder: True`를 항상 하드코딩해서 화면에 "플레이스홀더 보고서" 태그가 늘 붙어 있었다. 최초 팀 결정(§1 항목6)은 "추가 안 함"이었으나, 다른 Agent 기능들이 실제로 연결된 뒤에도 이 태그만 남아 있는 게 실사용 중 눈에 띄어 재검토·구현으로 전환했다.

**설계**: 통계·판정은 절대 LLM이 다시 계산하지 않는다 — LLM은 Django가 이미 확정한 사실(`facts`)을 문장으로 풀어쓰는 역할만 한다.
- `simulation.py`: `_agent_report()`를 두 함수로 분리 — `_narrative_facts(...)`(reasons/watch/verdict/decision-mix 등 서술 재료만 뽑은 JSON dict)와 `_render_template_report(facts)`(그 dict를 결정론적 마크다운으로 조립, 기존 템플릿 로직 그대로 이동). `_agent_report()`는 둘을 이어붙인 래퍼로 남겨 `run_and_save`·`seed_rules.py` 등 기존 호출부 무변경. 신규 `narrative_facts_for_run(run)`(저장된 실행에서 같은 facts를 재구성) · `apply_narrative(run, text)`(LLM 서술을 반영하고 `agent_report_placeholder=False`로 내리며 `graph.sim_result["placeholder"]`도 같이 갱신).
- `models.py`: `RuleSimulationRun.agent_report_placeholder`(기본 `True`) 신규 필드 + 마이그레이션(`0016`) — "이 서술문의 저자가 LLM인지 템플릿인지"만 표시, 판정 데이터의 신뢰도와는 무관.
- FastAPI `narrate.py`(신규) — `narrate_report(facts) -> str | None`. 시스템 프롬프트가 "facts에 없는 수치를 지어내지 마라"를 명시(재계산 금지, 서술만). 단일 LLM 호출(`testcases.py`의 라벨링 호출과 같은 패턴), 실패 시 `None`.
- `api.py`: `POST /agent/rule-v0/narrate-report` 신규 — 실패해도 500이 아니라 `{"report": null}` 반환(호출부의 정상 폴백 경로이지 에러가 아님).
- `views.py`(`simulate`액션): `run_and_save()` 직후 이 엔드포인트를 얇은 프록시로 호출 — 200이고 `report`가 있으면 `apply_narrative()`로 반영, 실패(연결 실패·타임아웃·빈 응답)해도 `except: pass`로 삼켜 **시뮬레이션 자체는 항상 성공** — 이미 저장된 템플릿 서술(`placeholder=True`)이 그대로 응답된다.
- `report_from_run()`·`simulate()`: 하드코딩됐던 `"placeholder": True`를 각각 `run.agent_report_placeholder`/(계산 단계라 항상 True, 저장 후 뷰가 바꿈)로 정정.

**실동작 검증**: 기존 DRAFT 그래프(id=39, "구조 검증용 TEST 그래프")로 `Client().force_login()` + `POST /api/rules/39/simulate/` 실호출 — 응답 로그에 실제 `POST http://ai:9000/agent/rule-v0/narrate-report "HTTP/1.1 200 OK"` 확인, `placeholder: False`, `agentReport`가 이 그래프의 실제 구조 오류·미도달 노드(`R-N1`/`T-90`/`T-91`)·테스트 불일치 건수를 그대로 인용한 자연스러운 산문으로 옴(템플릿의 리스트 나열이 아님). 이어서 `GET /api/rules/39/simulation/`(저장된 실행 재조회)도 같은 `placeholder: False`와 실서술을 반환 — 저장이 실제로 반영됐음을 확인. `graph.sim_result["placeholder"]`도 `False`로 갱신 확인. Django 전체 테스트 149건 재통과, 프론트 `tsc -b`+`vite build` 통과(화면 쪽 코드 변경 없음 — `report.placeholder` 조건부 태그는 이미 있던 그대로 두면 이제 자연히 실데이터를 반영한다).

**의도적으로 안 만든 것**: LLM 실패 시 재시도 루프 없음(1회로 충분, 실패하면 템플릿 폴백이 이미 "판정은 실제, 서술은 템플릿"이라는 사실을 명시하므로 사용자에게 숨겨지는 정보가 없음). `seed_rules.py`의 시드용 시뮬레이션은 이 LLM 호출을 타지 않는다(뷰 레이어에서만 호출) — 시딩은 오프라인·결정론적이어야 하므로 의도된 설계.

### 13.4 [수정] 검증셋 자동생성 — 금액·분류가 항상 비어 있던 문제

**배경**: 사용자가 실제 화면에서 검증셋 자동생성 결과를 보다가 "금액"·"분류" 컬럼이 8건 전부 비어 있는(₩0, `-`) 걸 지적했다. 조사 중 한 번은 잘못 진단해서 되레 기존 동작을 깨뜨렸다 — `tx.per_person_amount`(1인당 한도 노드가 참조하는 파생값)를 직접 fact로 넣는 대신 `tx.amount`+인원수 조합으로 바꾸면 "더 현실적"일 거라 판단했는데, 실제로 돌려보니 `PER_PERSON_LIMIT_OVER` 플래그가 안 뜨고 미해소 가드로만 REVIEW가 나왔다. 원인: 검증셋 케이스(실 정산 아님)는 `empty_eval_context()` + `apply_facts()`(단순 dict 오버레이)로 조립되고, 운영 조립기(`build_rule_context`)에만 있는 `derive_after_merge()`(`tx.amount // participants.participant_count`로 파생)가 이 경로엔 없다 — 그래서 `tx.per_person_amount`를 직접 주입하는 게 유일하게 그 조건을 실제로 성립시키는 방법이었다. 되돌렸다(§12.2a와 비슷한 성격의 실수 — 코드를 안 보고 "더 실제 같아 보이는" 방향으로 고쳤다가 검증 없이는 몰랐을 회귀).

**진짜 원인**: `_to_payload()`가 표시용 `amount`를 오직 `facts["tx.amount"]`에서만 가져왔다. 그런데 1인당 한도(`tx.per_person_amount`)·2차 여부·주류 포함 같은 조건은 애초에 `tx.amount`를 안 쓴다 — 조건 역산이 그 조건에 필요한 값만 정확히 만들기 때문에 정상이다. `category`는 아예 어느 코드 경로에서도 채운 적이 없었다(payload에 키 자체가 없었음).

**수정**: 판정 로직(`facts`)은 건드리지 않고 **표시 전용 필드만** 보강했다.
- `_label_candidates()`의 LLM 호출(기존에 label/merchant만 짓던 것)에 `amount`를 추가 — `facts`에 이미 금액 관련 값이 있으면 그것과 앞뒤가 맞게, 없으면(참석자 수·2차 여부 등 금액 무관 조건) 시나리오에 맞는 현실적인 금액(3만~80만원)을 짓게 프롬프트 지시. 결과는 `cand["display_amount"]`에 저장하고 `facts`엔 넣지 않는다.
- `_to_payload(cand, category)`: `amount`는 `facts["tx.amount"]`가 있으면 그 값을 최우선(판정 근거와 화면이 어긋나면 안 됨), 없으면 `display_amount`, 둘 다 없으면 0. `category`는 그래프의 `scope`를 그대로 채운다(이 검증셋 전체가 그 scope 전용이므로 결정론적으로 정할 수 있다 — LLM에 맡길 필요 없음).

**실동작 검증**: 그래프 37(회식비 검증 그래프)로 재생성 — 8건 중 6건이 실제 조건 값과 정합한 금액(예: 1인당 한도 초과 45,001원 = 2인 기준 1인당 22,500원대... 실측값은 45,001/30,001/50,000/30,000)을 받았고, 분류는 8건 전부 `회식`으로 채워짐. 참석자 명단 누락 2건은 LLM이 "참석자가 없으니 지출도 없다"는 취지로 여전히 0을 반환(프롬프트로 완전히 막히진 않음 — 화면엔 "해당없음"으로 뜨는데, 이 두 건은 실제로 조건 자체가 금액과 무관해 진짜 이상 없음). 8건 전부 기대 판정 재일치(`matchedExpectation: true`) 확인 — 표시 필드만 바꿨으므로 판정 로직 회귀 없음. Django 149건, 프론트 `tsc -b`+`vite build` 재통과.

### 13.5 [수정] 실제 내역 시뮬레이션이 scope 필터 없이 전 과목을 섞어 돌리던 문제

**배경**: 회식 scope 그래프(37)의 시뮬레이션 보고서에서 "위험 변경 10건", 자동처리율 2.5%처럼 유난히 나쁜 수치가 나온 이유를 사용자가 물어 조사했다. `_previous_month_cases()`(직전 달 정산 40건, 없으면 최근 40건 폴백)가 **`Settlement.category` 필터가 아예 없어서** scope별 그래프를 시뮬레이션할 때도 전 과목(비품·식대·출장·접대·회식·회의) 뒤섞인 최근 40건을 그대로 돌리고 있었다. `_run_rows()`는 `run_rule_engine(context, snapshot)`을 그냥 호출할 뿐 scope 게이팅 개념이 없다(그건 실제 판정에서만 쓰는 `orchestrator.py`의 역할) — 그래서 회식 그래프가 비품·출장 정산까지 억지로 판정하며 `dining.*` 같은 회식 전용 필드가 죄다 미해소로 REVIEW 강등되고 있었다.

**수정**: `_previous_month_cases(scope: str = GLOBAL)`에 `scope != GLOBAL`이면 `Settlement.objects.filter(category=scope)`를 추가. `simulate()` 호출부가 `graph.scope`를 넘긴다. GLOBAL 그래프(전 과목에 적용되는 공통 게이트)는 의도대로 필터 없이 그대로 둔다.

**실동작 검증**: 그래프 37(회식) 재시뮬레이션 → `historyTotal: 3`(실제 회식 정산 3건만, 이전엔 40건), `history categories: {'회식': 3}`. 그래프 33(GLOBAL, ACTIVE) → 여전히 `historyTotal: 40`, 전 과목 뒤섞임 유지(의도대로). Django 149건 재통과.

### 13.6 [수정] 대화형 수정 — 룰로 표현 불가능한 정성적 판단을 엉뚱한 필드에 갖다 붙이던 문제

**배경**: 사용자가 "자연어 수정 중 '이건 이 노드가 아니라 사람이 봐야 하는 부분'이라고 에이전트가 스스로 판단해 되돌려줄 수 있는지" 확인을 요청했다. TEST_DEMO 그래프(39)의 T-22("사용 목적 누락", `evidence.expense_purpose_missing == True`)를 선택한 채 "목적이 부실하게 작성된 것도 여기서 같이 걸러줘"라고 지시 — "부실하게 작성됨"은 EvalContext 어떤 필드로도 참/거짓을 못 가리는 정성적 판단인데도(seed_rules.py 자체 주석이 "목적 문구의 품질은 룰이 아니라 초안 작성 단계에서 다루는 게 맞다"고 이미 명시), 에이전트는 실제로 조건을 고쳤다:
  1차 시도: 의미가 비슷해 보이는 엉뚱한 필드(`evidence.has_supporting_evidence` — 증빙 첨부 여부, 목적 품질과 무관)를 갖다 붙임.
  2차 시도(같은 지시 재실행): 같은 var를 논리적으로 동어반복인 조건(`A==True` OR `NOT(A==False)`)으로 부풀리고 "이제 이것도 걸러진다"고 답변 — 실제로는 아무것도 안 바뀌었는데 바뀌었다고 주장.

**수정**: `_SYSTEM_PROMPT`에 규칙 8 추가 — "[허용 경로 목록]에 요청의 뜻을 정확히 담은 var가 있는지 먼저 스스로 확인하고, 없으면 엉뚱한 var를 대신 쓰거나 동어반복 조건을 덧붙이는 것 둘 다 금지, `update_node`/`create_node`를 호출하지 말고 `answer`로만 한계를 알리라"고 명시. **1차 시도(완곡한 지침)로는 재현이 그대로 남았다** — "지어내지 마세요" 정도로는 막히지 않았고, 금지 행동을 구체적으로 나열한 강한 지침(2차 시도)으로 바꾸고서야 막혔다.

**실동작 검증**: 같은 지시를 3회 반복 — 3/3 모두 `applied_changes: []`, `answer`로 "표현할 수 있는 변수가 없어 처리할 수 없다"고만 응답(조건 미변경). 회귀로 정상 케이스(T-10 "고액 결제 기준을 50만원으로 바꿔줘" — 객관적 숫자 임계값)는 여전히 정상적으로 `update_node` 호출되는 것 확인(과잉 차단 없음). 실험 중 변경했던 T-22·T-10은 원래 조건으로 복원. Django 149건 재통과.

### 13.7 [수정] 검증셋 자동생성 — 같은 그래프에 다시 누르면 사실상 복제본이 쌓이던 문제

**배경**: 사용자가 "검증셋 생성"을 두 번 눌러 8건이던 그래프 37이 16건이 됐고, 내용을 보니 같은 4개 노드에 대해 facts가 완전히 똑같은 케이스가 라벨·가맹점 이름만 새로 지어져(`맛있는 식당`↔`맛있는 식당`, `정갈한 밥상`↔`정갈한 다이닝` 등) `AUTO-9`~`AUTO-16`으로 또 추가돼 있었다("숫자만 바뀌고 그대로 복붙"). 원인: `generate_test_cases()`가 매번 그래프의 모든 노드를 처음부터 다시 역산해 **기존 검증셋에 이미 같은 조건의 케이스가 있는지 확인 없이** append했다 — 그래프가 안 바뀌었으면 `_solve()`는 결정론적이라 매번 같은 facts를 내놓으므로, 다시 누를 때마다 실질적으로 똑같은 케이스가 새 키로 계속 쌓이는 구조였다.

**수정**: `generate_test_cases()`가 기존 검증셋 중 `AUTO-`로 시작하는 케이스의 `facts`를 `frozenset`으로 모아두고(`covered`), 새로 역산한 후보의 facts가 이미 그 안에 있으면 건너뛴다(`_facts_signature()`). 전부 건너뛰면 새 상태값 `ALREADY_COVERED`를 반환 — 기존 `NO_CANDIDATES`(역산 불가)와 원인이 다르므로 구분했다. 프론트(`SimulationTab.tsx::autoGenerate`)는 이미 `status !== 'DONE'`이면 `detail`을 경고 배너로 보여주는 범용 처리라 프론트 변경 없이 그대로 동작한다.

**실동작 검증**: 그래프 37을 8건으로 정리한 뒤 생성을 다시 호출 → `status: ALREADY_COVERED`, `detail: "...8건 건너뜀..."`, 검증셋은 8건 그대로 유지(중복 없음). Django 149건, 프론트 `tsc -b`+`vite build` 재통과.

### 13.8 이번 실사용 검증에서 버그가 아니라고 확인한 것들

같이 확인해달라고 한 항목 중 실제로는 정상인 것들 — 기록해 둔다.

- **자동처리율 0%·검토 감소량 0%가 이상해 보인다는 지적**: 실측 확인 결과 진짜 0%다. §13.5로 scope 필터가 걸린 뒤 회식 그래프의 실제 내역이 3건(전부 실제 회식 정산)으로 줄었는데, 이 3건이 전부 `REVIEW`로 판정된다 — `autoCount: 0` → `autoRate: 0.0`. `reviewReduction`도 직전 버전 시뮬레이션 이력이 없어(`hasPrevVersion: False`) 기준선을 0.0으로 잡고 계산해 0.0이 나온다(이건 "0%→0%라 감소 없음"이 아니라 "비교할 이전 실행이 없다"는 뜻인데 수치로는 구분이 안 되는 것 — 별도 개선 후보로 남겨둠, 이번엔 안 고침). 3건 중 1건(baseline `PENDING_CONFIRM`=과거 PASS)이 이 DRAFT 그래프에서는 REVIEW로 바뀌어 `riskChangedCount: 1`로 잡히는 것도 실측대로다.
- **테스트 8건이 "노드 추가하기 나름"인지**: 맞다. `CASES_PER_NODE=2` × REJECT/RETURN/REVIEW decision을 가진 노드 수. 그래프 37은 그런 노드가 4개(1인당 한도·2차 결제·참석자 명단·주류 과다)라 2×4=8건. 노드를 추가/삭제하면 그만큼 자동으로 늘거나 준다(PASS 노드는 대상 아님).

### 13.9 [수정] 대화형 수정 — 비상식적인 숫자값도 그냥 적용되던 문제

**배경**: 사용자가 화면에서 "참석자 과다" 노드(정상 임계값 8인)를 "200인으로 수정해"라고 지시했더니 그대로 적용되는 걸 발견하고, 방향을 물었다. §13.6(정성적 판단 가드)과는 다른 종류의 문제 — 200이라는 값 자체는 `participants.participant_count`로 얼마든지 표현 가능한 정상적인 숫자라 §13.6 가드에는 안 걸린다. 순수하게 "그 값이 이 업무 도메인에서 말이 되는가"의 문제.

**설계 판단**: 결정론적 범위표(필드별 min/max 하드코딩)로 강하게 차단하는 안과, LLM이 상식적으로 판단해 되묻는 안을 사용자와 논의 — 전자는 "진짜 200명 규모 회식이 있는 회사"를 오탐으로 막을 수 있고, 이 제품의 핵심 원칙 자체가 "AI는 제안, 확정은 사람"(룰도 DRAFT→시뮬레이션→Active 요청 승인을 거쳐야 반영)이라 실제 안전판은 사람 검토 단계여야 한다는 점을 먼저 짚었다. 사용자는 그래도 **채팅 응답 자체에서 되물어주는 방식**을 선택 — 대화형 수정이 룰 콘솔 화면의 직접 입력칸 수정과 달리 "말로 지시하면 그대로 실행된다"는 인상을 주기 쉬워, 최소한 이례적인 값은 한 번 확인받고 넘어가는 게 더 안전하다는 판단.

**수정**: `_SYSTEM_PROMPT` 규칙 9 추가 — 숫자를 바꾸는 지시를 받으면 "법인카드 정산 업무의 상식적인 범위"를 벗어나 보이는지 스스로 판단하고, 벗어나 보이면 그 턴에는 `update_node`/`create_node`를 호출하지 않고 `answer`로만 "확인해주시면 반영하겠습니다"라고 되묻는다. 사용자가 다음 턴에서 확인해주면(대화 이력에 남으므로 §13.2의 이력 로딩이 그대로 재사용됨) 그때 적용한다.

**실동작 검증**: "참석자 제한을 200인으로 수정해"(T-30, 정상값 8) → 3회 반복 모두 `applied_changes: []`로 되묻기만 함. 이어서 "네 맞아요, 200명 맞습니다"를 보내자 이력에서 확인을 인식해 실제로 8→200으로 적용됨(2턴 확인 흐름 정상 동작). 회귀: 별도 그래프(81, 대화 이력 없는 깨끗한 상태)에서 "숙박비 1박 한도를 15만원으로 수정해줘"(정상적인 숫자 변경) → 즉시 적용, 과잉 차단 없음 확인.

**발견(수정 안 함, 기록만)**: 같은 그래프(39)에 테스트를 반복해 대화 이력이 40건 이상 쌓인 상태에서 "10인으로 수정해"(정상 요청)를 보내니, §13.6 가드의 "적절한 변수가 없다"는 **엉뚱한 사유**로 잘못 거부됐다. 원인은 이번 규칙 9가 아니라 누적된 이력 안의 "거부" 패턴(§13.6 테스트로 쌓인 것)이 이후 무관한 요청까지 오염시킨 것으로 보인다 — 별도의 깨끗한 그래프에서는 재현 안 됨. `MAX_HISTORY_MESSAGES=20`이 이미 상한을 두고 있지만, 짧은 시간에 같은 그래프에 많은 테스트/거부 사례가 몰리면 이력 자체가 few-shot처럼 작용해 판단을 오염시킬 수 있다는 신호 — 실사용에서 재현되면 다시 볼 것. 실험 후 T-30(그래프 39)·T-102(그래프 81) 모두 원래 값으로 복원. Django 149건 재통과.

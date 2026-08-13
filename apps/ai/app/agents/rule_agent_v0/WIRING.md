# Rule Agent v0 — 배선(Wiring) 가이드 (서브패키지 격리판)

## 0. 격리 원칙

이번 버전은 **기존 파일을 거의 건드리지 않는다.** 신규 파일은 전부 두 서브패키지
안에 들어 있고, 기존 코드에 대한 변경은 아래 **4곳, 총 4줄**이 전부다.

```
apps/ai/app/main.py           +2줄 (import + include_router)
apps/ai/requirements.txt      +1줄 (chromadb)
apps/core/config/urls.py      +1줄 (path(...) include)
```

`mcp/tools.py`, `app/config.py`(Settings 클래스), `domain/policies/models.py`,
`domain/policies/dsl.py`, `domain/policies/engine.py` 등 기존 로직은 **전혀
수정하지 않는다.** v0가 통째로 잘못됐거나 v1에서 설계가 바뀌어도, 위 4줄만
되돌리고 서브패키지 2개(폴더)를 지우면 착수 이전 상태로 완전히 복귀한다.

## 1. 파일 배치

```
apps/ai/app/agents/rule_agent_v0/          ← FastAPI 쪽, 통째로 신규
├── __init__.py            router만 노출
├── settings.py            v0 전용 env 설정 (중앙 config.py 미수정)
├── embedding.py           OpenAI 임베딩 (3-large@1024, Q_ctx 접두, L2)
├── vector_store.py        Chroma 접근 (policy_docs 컬렉션)
├── search.py              search_policy 구현 (mcp/tools.py 미경유)
├── django_client.py       Django 내부 API 호출 (v0 네임스페이스 전용)
├── agent.py               생성 로직 본체 (RAG→LLM→조립→저장)
└── api.py                 라우터 (/agent/rule-v0/*)

apps/core/domain/policies/rule_agent_v0/   ← Django 쪽, 통째로 신규
├── __init__.py
├── views.py                EvalContextSchemaView, RuleGraphDraftCreateView
└── urls.py                 이 서브패키지 전용 urlpatterns
```

기존 `mcp/tools.py`의 `search_policy` stub은 **v0에서 건드리지 않는다.**
v0는 자체 `search.py`를 직접 호출하고, MCP tool 계층은 경유하지 않는다
(격리 우선 — 대신 GAPS.md에 v1 승격 시 필요한 조치를 남겨둠).

## 2. FastAPI 등록 (`apps/ai/app/main.py`) — 2줄

```python
from app.agents.rule_agent_v0 import router as rule_agent_v0_router
app.include_router(rule_agent_v0_router)
```

엔드포인트는 `/agent/rule-v0/generate`, `/agent/rule-v0/embeddings/upsert`로
뜬다 — 정식 스펙 경로(`/agent/rule/generate`)와 겹치지 않아 나중에 정식
엔드포인트를 별도로 만들어도 충돌이 없다.

## 3. Django 등록 (`apps/core/config/urls.py`) — 1줄

```python
urlpatterns += [
    path("api/internal/rule-agent-v0/",
         include("domain.policies.rule_agent_v0.urls")),
]
```

실제 뜨는 경로: `/api/internal/rule-agent-v0/eval-context-schema/`,
`/api/internal/rule-agent-v0/rule-graphs/drafts/`.

## 4. 설정 (.env) — 전부 선택값, 없으면 기본값으로 동작

```
OPENAI_API_KEY=...                        # 중앙 config.py와 동일 키 재사용
RULE_AGENT_V0_CHROMA_HOST=                 # 비우면 로컬 PersistentClient
RULE_AGENT_V0_CHROMA_PORT=8001
RULE_AGENT_V0_CHROMA_PATH=./chroma_data_v0
RULE_AGENT_V0_DJANGO_BASE=http://core:8000
RULE_AGENT_V0_MODEL=gpt-4o-mini
```

`apps/ai/requirements.txt`에 `chromadb` 1줄 추가.

## 5. 실동작 검증 순서

```bash
cd apps/ai && uvicorn app.main:app --reload --port 9000
```

**① 임베딩 적재 — Chroma 배선 확인**

```bash
curl -s -X POST localhost:9000/agent/rule-v0/embeddings/upsert \
  -H "Content-Type: application/json" \
  -d '{"chunks":[{"chunk_id":"test:doc#c01a001#01",
       "embedding_text":"법인카드_사용규정 > 제3장 > 제10조 (사용 한도)\n제10조 본문...",
       "context_text":"[법인카드_사용규정 제10조] 본문...",
       "metadata":{"doc_name":"법인카드_사용규정","citation":"법인카드_사용규정 제10조","flags":""}}]}'
```

청킹 파이프라인(`chunk_pdf`)의 실제 출력 인터페이스는 아직 대조 전이므로, v0는
**chunks 직접 전달 모드만** 지원한다(파일 경로 자동 청킹은 v1). 실 파이프라인
연결은 GAPS.md G-1 참조.

**② search_policy 단독 확인** (python shell)

```python
from app.agents.rule_agent_v0.search import search_policy
search_policy("사전승인 기준 금액")   # citation 포함 청크가 나와야 함
```

**③ Django 내부 API 확인**

```bash
curl -s localhost:8000/api/internal/rule-agent-v0/eval-context-schema/ | jq '.paths | length'
```

**④ 엔드투엔드 — 생성 flow**

```bash
curl -s -X POST localhost:9000/agent/rule-v0/generate \
  -H "Content-Type: application/json" \
  -d '{"scope":"접대","top_k":6}' | jq
```

확인 포인트:
1. `status == "DRAFT_SAVED"`, `graph.version`, `graph.validation` 존재
2. Django admin/룰 콘솔에서 DRAFT 그래프·노드·라우팅이 보임
3. `validation.missing_eval_context_paths` — 비어 있으면 시뮬레이션 후 ACTIVE
   승인 게이트를 통과할 수 있는 상태
4. `rejected_nodes` / `llm_skipped` — LLM이 만들다 버린 것들이 응답에 노출되는지
5. 룰 콘솔에서 `condition_text`(언제 걸리나요/걸리면 어떻게 되나요)가 렌더되는지

**⑤ 승인 플로우 접속 확인 (v0 범위 밖이지만 배선 검증)**
생성된 DRAFT를 기존 시뮬레이션 → 승인대기 → ACTIVE 전환 경로에 태워
`validate_graph_vars` hard gate가 실제로 걸리는지 1회 확인.

## 6. 되돌리기(rollback)

```bash
rm -rf apps/ai/app/agents/rule_agent_v0
rm -rf apps/core/domain/policies/rule_agent_v0
# main.py 2줄, urls.py 1줄, requirements.txt 1줄 제거
```

이게 전부다. 다른 파일은 손댄 적이 없으므로 git diff에 저 4곳 외에는 아무것도
안 잡혀야 정상이다.

## 7. v1 승격 시 체크리스트 (지금 하지 않아도 됨)

- [ ] `search.py` → `mcp/tools.py`의 `search_policy` stub과 교체 (Risk Review Agent와
      tool 호출·로깅 경로 공유)
- [ ] `rag/`, `django_client.py` 로직을 중앙 모듈로 승격할지 결정 (컬렉션명은
      이미 실제 스펙값(`policy_docs`)이라 데이터 마이그레이션 불필요)
- [ ] `/agent/rule-v0/*` → `/agent/rule/generate`(§6.2 정식 경로)로 이관
- [ ] `RuleGraph.generation_meta` 필드 신설 여부 팀 합의

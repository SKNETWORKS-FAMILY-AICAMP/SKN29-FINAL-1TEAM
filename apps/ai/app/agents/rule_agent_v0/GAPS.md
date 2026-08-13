# Rule Agent v0 — 설계 결정 & 발견된 갭

> 기준: 기술명세서 §4.2·§5·§6.2·§8 / 요구사항 FR-RB-01~05 / RAG_전략_종합 / 룰엔진 설계 캐논.
> 업로드된 파생 문서가 설계문서와 어긋나는 지점은 설계문서 기준으로 판단했다(아래 D-3, G-8).
>
> **구조**: 신규 로직을 전부 `apps/ai/app/agents/rule_agent_v0/`,
> `apps/core/domain/policies/rule_agent_v0/` 두 서브패키지 안에 격리했다.
> 기존 파일 수정은 main.py 2줄·urls.py 1줄·requirements.txt 1줄뿐
> (WIRING.md §6 되돌리기 참조). 이로 인해 D-9~D-11이 추가됐다.

---

## A. v0 설계 결정 (의도적 단순화)

| # | 결정 | 근거 |
|---|---|---|
| D-1 | **LLM은 노드만 생성, 그래프 위상은 파이썬이 결정론적 조립**(선형 체인: severity 순 정렬 → NO_MATCH 체인 → `_SCOPE_PASS` 종단) | 시드 GLOBAL 그래프(R-002→R-003→`_GLOBAL_PASS`)와 동일 패턴. LLM에 라우팅까지 맡기면 구조 검증 실패 모드가 늘어난다. FR-RB-04의 "next_routings 제안"은 v1에서 배타그룹·부분 트리와 함께 |
| D-2 | **decision은 `action.decision` 직접 지정** (REJECT/RETURN/REVIEW만 LLM 허용, PASS 종단은 시스템 자동 추가) | 기술명세서 §4.2 확정("판정 시점 확신도 계산 없음"). θ_pass/θ_reject는 deprecated — `rule-engine.md` 업로드본의 §6 표는 구버전이므로 따르지 않음 |
| D-3 | **condition 저장 = JSON-Logic 객체 직접** (`{"expr": 원문}` 래핑 아님). 출처조항은 `action.source_clause`로 | 기술명세서 §4.2(d)·dsl.py 계약 기준. `rule-seed-plan.md` §3.1의 expr-래핑 매핑은 엔진 부재 시절 설계라 현행과 불일치 — 시드 R-002/R-003 실물 저장 형태와 대조 필요 |
| D-4 | **2-hop 확장 미적용** (top-k 순수 검색만) | 선행 조건 미충족 — G-2 참조 |
| D-5 | **DRAFT 저장 검증 정책**: DSL 화이트리스트 = hard(422), EvalContext 경로 = report-only | ACTIVE 게이트(validate_graph_vars hard)는 기존 구현에 이미 있으므로 이중 차단 대신 DRAFT에서는 리포트로 노출 → 룰 콘솔에서 수정 유도 |
| D-6 | **쓰기 경로 = Django 내부 API** (FastAPI는 Postgres 무접근) | §5.1 원칙 + rule-engine-design §5.1 배치 결정("쓰기·감사는 Django에"). DRAFT는 확정 상태가 아니므로 "FastAPI never writes confirmed state" 원칙과도 충돌 없음 |
| D-7 | scope에서 `업무활성` 제외, `회식` 포함 | 계정과목 확정사항(업무활성비 폐기·회식 독립) 반영. 최종 정합은 `normalize_scope` |
| D-8 | 임베딩 계약 고정: `text-embedding-3-large` @1024, Q_ctx 접두, L2 1회, cosine | embedding-strategy §1 확정 계약 그대로 |
| D-9 | **신규 로직을 서브패키지 2개로 완전 격리**, 기존 파일 수정은 4줄로 최소화 | 버전업·롤백 시 기존 로직과 꼬이지 않도록. WIRING.md §6 |
| D-10 | **v0는 `mcp/tools.py`를 경유하지 않고 자체 `search.py`를 직접 호출** | tools.py의 기존 `search_policy` stub을 안 건드리기 위한 격리 선택. 대가: v0의 tool call이 §5 "모든 tool call 로깅" 경로를 안 탄다(G-7 재확인) |
| D-11 | **엔드포인트를 `/agent/rule-v0/*` 네임스페이스에 격리** (정식 경로 `/agent/rule/generate` 아님) | 정식 스펙 경로와 충돌 방지, v1 승격 시 이관 |
| D-15 | **(1차 시도, 불충분함으로 판명) 시스템 프롬프트에 JSON-Logic 배열 문법 예시(✅/❌ 대조) 추가** | LLM이 `{"==": {"var":a,"var":b}}` 형태(하나의 객체 안에 `var` 키 2개)를 반복 생성하던 문제에 대응해 프롬프트에 ✅/❌ 예시 추가. **2026-08-13 실 데이터(policy_docs 888청크) 기반 재검증에서 D-15가 못 잡는 다른 변종**(`{"var":"tx.amount",300000}` — 키-값 쌍 뒤에 키 없이 리터럴을 바로 붙이는, 아예 JSON 신택스 자체가 깨지는 패턴)이 5개 노드 전부에서 재현됨 → D-16으로 근본 해결 |
| D-16 | **condition을 LLM이 JSON 문자열로 직접 조립하지 않고, 재귀 구조화 필드(`condition` 객체: comparison/group)로 채우게 하고 파이썬이 JSON-Logic으로 결정론적으로 조립** | 근본 원인: LLM에게 중첩 JSON을 손으로 짜게 하는 구조 자체가 문제 — 프롬프트 예시를 아무리 추가해도 다른 문법 변종이 계속 나옴. `_RESPONSE_SCHEMA`에서 `condition_json`(string) 필드 제거 → `condition`(`$ref: condition_node`, strict 재귀 스키마) 필드로 교체, 신규 `_build_condition()`이 구조를 JSON-Logic으로 조립(`agent.py`). `_sanitize_nodes`의 `json.loads(condition_json)` 호출도 `_build_condition(condition)`으로 교체 — **JSON 파싱 실패라는 에러 클래스 자체가 발생 불가**(구조가 스키마로 보장됨). **2026-08-13 실측 재검증**: `rejected_nodes`에 파싱 에러 0건, LLM 생성 노드가 전부 검증 통과 → `POST /api/rules/drafts/`까지 도달해 **G-15(403)가 재현**(HTTP 502 래핑, `Client error '403 Forbidden' for url 'http://localhost:8000/api/rules/drafts/'`) — 이번엔 조기 종료 없이 의도한 최종 지점까지 도달 |
| D-17 | **재귀 구조화 스키마가 rule-engine.md 캐논의 DSL 연산자 전체(`and`/`or`/`not`/`==`/`!=`/`>`/`>=`/`<`/`<=`/`in`/`var`)를 커버** | 표현력을 임의로 줄이지 않는다는 설계 원칙 — `kind: comparison`(6개 비교연산자 + `negate`로 `not` 표현) + `kind: group`(`and`/`or` + 재귀 `children`) + `right_kind: string_list`(`in`)로 전체 연산자 집합을 그대로 반영. 캐논이 SoT, 구현이 여기 맞춤 |

---

## B. 발견된 갭 (배선하면서 드러난 부족분)

### 선행 의존 — 이게 없으면 flow가 안 돈다

| # | 갭 | 내용 | 필요한 일 |
|---|---|---|---|
| **G-1** | **Chroma upsert 미구현 상태** | embedding-strategy는 "평가 완료 / 구현 미착수". v0는 `chunks` 직접 전달 모드만 지원(파일 자동 청킹은 뺐다 — `chunk_pdf` 실제 인터페이스 대조 전이라 격리 원칙상 파싱 모듈에 손대지 않음) | 실물 `chunk_pdf` 인터페이스 확인 후 v1에서 파일 업로드 모드 추가 |
| **G-2** | **청크 메타에 `refs_internal`/`refs_external` 부재** | RAG_전략_종합 §3.3은 refs 메타 추출을 요구하고 §4.5의 2-hop 확장이 이 필드에 의존하는데, **chunking-strategy §8.2 확정 메타 스키마에 refs 필드가 없다** — 두 문서 간 불일치. 이대로면 2-hop은 영구히 배선 불가 | 청커에 refs 추출 추가(파싱 §3.3 정규식은 이미 정의됨) + `to_chroma()` 스칼라 규칙(콤마 접기)으로 직렬화. v1 과제로 등록 권장 |
| **G-3** | **EvalContext 카탈로그 공유 경로 부재** | 카탈로그 SoT는 Django `eval_context.py`인데 FastAPI가 읽을 방법이 없었다. 프롬프트에 허용 경로를 안 주면 LLM이 미정의 경로를 양산한다 | 신설 `GET /api/internal/rule-agent-v0/eval-context-schema/` (격리 서브패키지에 포함) |
| **G-4** | **rule 그래프 쓰기 내부 API 부재** | 기존 내부 API는 read 관례(PolicyLookupView 등)뿐. 생성 Agent 산출물을 저장할 경로가 없었다 | 신설 `POST /api/internal/rule-agent-v0/rule-graphs/drafts/` (격리 서브패키지에 포함) |

### 정합·합의 필요 — 저장은 되지만 팀 결정이 남음

| # | 갭 | 내용 |
|---|---|---|
| **G-5** | **generation_meta 저장 자리 없음** | 기획 확장안 룰 콘솔 상세는 "생성 이유·관련조항 링크"를 요구한다. 노드별 출처는 `action.source_clause`에 넣었지만, **그래프 단위 생성 메타**(모델·질의·검색 소스 목록)를 넣을 필드가 `RuleGraph`에 없다. v0는 API 응답으로만 반환 — DB에 남지 않는다. `RuleGraph.generation_meta` JSONField 추가 여부 결정 필요 |
| **G-6** | **내부 API 인증 미정** | FastAPI ↔ Django 내부 호출·`/agent/rule-v0/embeddings/upsert`(관리자 트리거) 모두 서비스 인증이 미정(기존 Open Issue). views.py는 기존 internal 뷰 관례를 따르도록 비워둠 — docker 내부망 전제. 운영 전 결정 필요 |
| **G-7** | **tool call 로깅 경로 미탑승** | §5 설계 규칙 "모든 tool call 로깅". D-10에서 격리를 위해 `mcp/tools.py`를 우회했으므로, v0의 `search_policy` 호출은 이 로깅 경로를 타지 않는다. v1 승격 시 tools.py로 이관하면서 함께 해결(WIRING.md §7) |
| **G-8** | **`RETURN` enum 위상** | seed-plan §6 미결이 그대로 남아 있다. v0 LLM이 `action.decision=RETURN`을 생성한다(기술명세서 §4.2는 RETURN을 정식 decision으로 명시 → 설계문서 기준 채택). 다만 `OnResult` enum에 RETURN을 정식 추가할지는 여전히 팀 합의 대상 — v0 라우팅은 MATCH/NO_MATCH만 쓰므로 당장 충돌은 없음 |
| **G-9** | **임계값 리터럴 린트 부재** | 프롬프트로 "별표값은 policy.* 경로 사용"을 지시했지만, LLM이 규정 원문의 숫자(3만·30만)를 리터럴로 박아도 기계적으로 못 잡는다. policy-domain 원칙(임계값 상수를 DSL에 두지 않음) 위반 가능성. v1: "숫자 리터럴 + 대응 policy.* 필드 존재" 감지 린트를 DRAFT 검증에 추가 |
| **G-10** | **`_SCOPE_PASS` 리터럴 `true` 조건** | dsl 문법상 literal은 허용(설계 §3.1)이지만 `validate_expr`가 bare literal을 통과시키는지 실물 확인 필요. 거부하면 `{"==":[1,1]}`로 대체 |
| **G-11** | **룰 콘솔 미연동(기존 이슈 재확인)** | `ruleConsoleMock.ts`가 백엔드 graph 스키마와 미연동 — 생성된 DRAFT를 담당자가 실제로 검토·수정하려면 rule-console 실연동이 선행돼야 한다. 생성 flow의 가치가 화면에서 검증되지 않는 상태 |
| **G-12** | **멀티테넌트 미적용** | Chroma tenant 바인딩(RAG_전략 §7)은 v0 범위 밖 — 단일 tenant 전제. Open Issue #5와 함께 재검토 |

### 검증 flow(FR-RV)와의 접점

| # | 갭 | 내용 |
|---|---|---|
| **G-13** | **`/agent/rule/validate` 프록시 미배선** | 시뮬레이션 실체는 Django `simulation.py`에 이미 있으므로, FastAPI 쪽은 프록시 1개만 추가하면 된다. v0에서 뺀 이유: 생성→(룰 콘솔에서 시뮬)→승인 경로가 이미 동작하므로 배선 검증 목적에는 불필요 |
| **G-14** | **`/agent/rule/apply` 선행 조건 미충족** | orchestrator.py(GLOBAL→scope 선택·RuleHit 기록) 미구현 — 기존 알려진 갭. apply 배선은 orchestrator 이후 |
| **G-15** | **`CanViewRule`(RULE_VIEW capability) 인증 블로커 — 실측 재현 확인** | G-6("내부 API 인증 미정")과 연결된 구체 사례. FastAPI(rule_agent_v0)는 세션 로그인이 없어 `CanViewRule`(`RULE_VIEW` capability, 역할 기본값 ∪ `extra_capabilities`)을 충족 못 함. **2026-08-13 실측**: STEP 3 ④ 엔드투엔드 `POST /agent/rule-v0/generate` 실행 시 LLM 노드 생성·DSL 검증까지 정상 통과 후 `POST /api/rules/drafts/` 호출 단계에서 **403 Forbidden** 재현(HTTP 502로 래핑되어 `detail`에 원문 노출: `Client error '403 Forbidden' for url 'http://localhost:8000/api/rules/drafts/'`). **의도된 정상 동작** — 코드 결함 아님. 팀 결정 필요: FastAPI↔Django 내부 서비스 인증 방식(서비스 토큰에 `RULE_VIEW` 위임 부여 vs 별도 내부 전용 우회 경로) |

---

## C. 요약 — 다음 액션 우선순위

1. **G-3·G-4**: `views.py`의 임포트 경로·모델 필드명(`dsl.validate_expr`,
   `eval_context.EVAL_CONTEXT_SCHEMA_PATHS`, `models.RuleGraph` 등)을 실물
   레포와 대조 → 안 맞으면 이 서브패키지 안에서만 수정하면 된다(다른 파일 영향 없음)
2. 엔드투엔드 1회 실행(WIRING.md §5) → `missing_eval_context_paths`·
   `rejected_nodes` 실측
3. **G-1**: `chunk_pdf` 실물 인터페이스 대조 → v1에서 파일 업로드 모드 추가
4. **G-5·G-8** 팀 합의 (generation_meta 필드 / RETURN enum)
5. v1 백로그: 2-hop(G-2), 임계값 린트(G-9), validate 프록시(G-13),
   `mcp/tools.py` 이관(D-10/G-7 해소), 배타그룹·부분 트리 조립

# Rule Agent / Risk Review Agent — v1 고도화 계획

> 이 문서는 **설계 캐논이 아니라 v1 범위 정리 문서**다. "무엇을 만들지"는 각 항목 아래 한 줄 방향성만 적고, 상세 설계·구현 코드·실동작 검증 결과는 `_context/rule-agent-v1-implementation.md`로 뗐다. 원칙: **미구현 항목을 켜는 작업이 이미 동작 중인 v0 경로를 절대 깨지 않는다** — 대부분 "새 진입점 추가" 또는 "기존 흐름 뒤에 옵션 스텝 삽입"이지, 기존 함수 시그니처/응답 계약을 바꾸는 작업이 아니다.

> **진행 상태(2026-08-16)**: Rule Agent §1.2 6개 항목 **전부 구현+실동작 검증 완료**(`feature/rule-agent-v1` 브랜치, 로컬 커밋). Risk Review Agent §2.2는 전부 미착수. 구현 코드·검증 결과는 `_context/rule-agent-v1-implementation.md`.

---

## 0. 공통 결정 사항 — MCP는 배관과 루프를 분리해서 본다

실측(2026-08-14 세션, 이후 2026-08-16 재확인): `apps/ai/app/mcp/server.py`에 FastMCP 서버가 등록돼 있었지만 실제로는 **두 겹으로 깨져 있었다** — ① `mcp.tool(_fn)` 호출 방식이 fastmcp 2.x API(데코레이터 팩토리, `mcp.tool()(_fn)`이어야 함)와 안 맞아 툴 등록 자체가 조용히 실패 ② 그걸 고치고 나니 `main.py`의 `mcp.http_app()` 호출도 설치된 fastmcp==2.1.2엔 없는 메서드(이 버전엔 `sse_app()`만 있음)라 마운트가 또 실패. `main.py`의 예외 가드가 둘 다 삼켜서 앱은 계속 부팅됐고, 아무도 몰랐다.

- Risk Review Agent(`agents/risk_review_agent.py`)는 `from app.mcp import tools`로 이 모듈의 함수를 **파이썬 직접 호출**로 씀.
- Rule Agent(`agents/rule_agent_v0/agent.py`)는 v1 이전엔 `app.mcp.tools`조차 안 쓰고 자체 `search.py`로 병렬 구현이었음.
- **v1에서 Rule Agent는 이 상태를 완전히 벗어났다** — 마운트 버그 2건을 고치고, `fastmcp.Client`로 MCP 서버에 in-process 접속해 `search_policy`를 실제 MCP 프로토콜로 호출하며, LLM 호출 자체도 단발 구조화출력에서 **진짜 멀티턴 tool-calling 루프**로 재작성했다(§1.2-1). Risk Review Agent는 아직 손대지 않아 여전히 직접 호출 상태.

**v1 스코프 결정**: 이 전환을 Rule Agent 먼저 전체 재작성으로 진행했다(§1.2-1). Risk Review Agent 전환은 별도 작업으로 남아 있다.

---

## 1. Rule Agent

### 1.1 구현 상태 — 전부 완료

| 워크플로우 단계 (사용자 원안) | 상태 |
|---|---|
| ① 테스트 검증 | ✅ 기존부터 구현(`policies/engine.py`/`simulation.py`, 수동 트리거). LLM 서술은 팀 결정으로 추가 안 함(§1.2-6) |
| ② 문서 업로드 시 초안 자동생성 | ✅ **v1 구현 완료** — §1.2-2 |
| 생성→검증→재생성 루프 | ✅ **v1 구현 완료** — §1.2-4 |
| ③ 대화형 자연어 수정 | ✅ **v1 구현 완료** — §1.2-5 |
| ④ 검토/시뮬레이션 보고서 | 🚧 기존 상태 유지(LLM 서술 없음) — 팀 결정으로 안 바꾸기로 확정(§1.2-6) |
| 룰생성/전체그래프검증 MCP 툴 | ✅ **v1 구현 완료(형태 변경)** — 새 MCP 툴이 아니라 기존 `/simulate` 재사용(§1.2-3) |
| MCP 툴콜링 루프 전환 | ✅ **v1 구현 완료** — §1.2-1 |

상세 코드·실동작 검증은 전부 `_context/rule-agent-v1-implementation.md`.

### 1.2 구현된 6개 항목 요약

1. **MCP 툴콜링 전면 재작성 — ✅ 구현 완료.** 마운트 버그 2건 수정 + `fastmcp.Client` in-process 클라이언트(`mcp_client.py` 신설) + `agent.py`의 LLM 호출을 단발 구조화출력 → `search_policy`(MCP)/`submit_rule_nodes`(종료 툴) 멀티턴 루프로 전면 교체. 기존 "RAG 청크는 시도 전체 재사용" 결정(§1.2-4)과 충돌하지 않도록, outer 재시도 루프가 재사용하는 최초 청크는 그대로 두고 **모델이 부족하다고 판단할 때만 추가 검색**하게 설계. 실측: 3회 연속 실호출에서 모델이 스스로 `search_policy`를 2회씩 추가 호출하는 진짜 에이전틱 동작 확인.
2. **적재→생성 자동 트리거 — ✅ 구현 완료(트리거 로직), ⚠️ 실사용 경로는 별개 버그로 현재 막혀 있음.** `rule_trigger.py`가 실제로 `rule_agent_v0.agent.generate()`를 호출. 확정 스코프: 업로드 시 고른 scope 1개만, **재색인 때는 자동 생성 안 함**(Django `policy_doc_views.py`가 `create`/`reembed` 경로를 구분해 `isReindex` 플래그를 FastAPI로 넘김). 트리거 판단 로직 자체는 직접 호출로 검증됐지만, **지금은 docling 버전 드리프트 버그(무관한 사전 결함, `rule-agent-v1-implementation.md` §10) 때문에 실제 업로드 자체가 파싱 단계에서 전부 실패해 트리거가 실전에서 불릴 일이 없다** — 그 버그가 고쳐지기 전까지는 아래 §3a의 "자동으로 DRAFT가 쌓인다" 경고가 실제로는 발동하지 않는다.
3. **"그래프 검증" — ✅ 구현 완료.** 새 MCP 툴이 아니라 기존 `POST /api/rules/{id}/simulate` 재사용(`django_client.simulate_graph`).
4. **생성→검증→재생성 루프 — ✅ 구현 완료.** A안(저장→검증→실패시 discard) 채택, 최대 3회, 신규 종료 상태값(`NO_VALID_NODES_EXHAUSTED`/`STRUCTURE_INVALID_EXHAUSTED`) 도입. 실제 LLM(gpt-4o-mini) 16회 호출로 통계 검증(1차 성공률 100%, Rule of Three로 통계적 한계도 명시).
5. **대화형 자연어 수정 에이전트 — ✅ 구현 완료.** 신규 모듈 `chat.py` + 신규 엔드포인트(`POST /agent/rule-v0/converse`, Django `POST /api/rules/{id}/converse/`). MCP 툴콜링 패턴 재사용(`update_node`/`create_node`/`delete_node`/`search_policy`/`answer` 툴). 기존 그래프 CRUD API 3종을 그대로 재사용(신규 CRUD 없음, 비침습 원칙 준수). `RuleAuthoringMessage`(그동안 아무도 안 쓰던 로그 테이블)의 **첫 실제 쓰기 경로**가 됨.
6. **시뮬레이션 보고서 LLM 서술 — 결정: 추가 안 함(팀 확인, 2026-08-16).** 코드 변경 없음, 현재 룰 기반 템플릿 유지로 확정.

전부 `rule-agent-v1-implementation.md`에 구현 코드 위치·설계 근거·실동작 검증 결과가 있다.

---

## 2. Risk Review Agent — 전부 미착수

### 2.1 구현 상태

| 항목 | 상태 | 근거 |
|---|---|---|
| anomaly score → RAG → 보고서 2단계 파이프라인 | ✅ 구현 | `agents/risk_review_agent.py`: Stage1(`_stage1`, `get_tx_features`→`ml_infer`) → Stage2(`_stage2`, `search_policy`+`search_cases`→LLM 1회→`RiskVerdict`) |
| anomaly score 높을 때 3범주 분류 | ❌ 미구현 | `RiskVerdict` 스키마에 해당 필드 없음. 유일한 버킷 개념은 무관한 것 — 원시 점수의 10분위 보정 밴드(`ml/calibration.py`, `percentile_band`)뿐 |
| 분류(판단)와 액션(실행) 분리 | 🚧 부분 | Stage1/Stage2는 분리돼 있으나, Stage2 내부에서 `violation_verdict`(분류)와 `recommendation`(액션)이 한 LLM 호출·한 스키마로 동시 산출 |
| Rule Agent와 공유하는 MCP 툴 사용 | ✅ 일부 | `from app.mcp import tools`로 공용 함수 재사용(단 직접 호출, 툴콜링 아님 — §0) |

### 2.2 v1에 필요한 것 (전부 미착수)

1. **[기반] MCP 툴콜링 루프 전환** — §0. Rule Agent의 `mcp_client.py`/전환 패턴을 그대로 재사용 가능(신규 설계 불필요, 이식만 하면 됨).
2. **3범주 분류 스키마 신설** — anomaly score가 높은 건에 한정해 도는 서브스텝. `RiskVerdict` 기존 필드는 유지, 신규 필드는 추가만.
3. **분류 단계와 액션(recommendation) 단계 분리** — Stage2를 "① 분류" → "② 액션 결정" 2단으로 쪼갬.
4. **[선행 필요, 별도 트랙] `feature_contribs` 실값 확보** — `anomaly.pkl` 재학습 필요(ML 파이프라인 작업, Agent 코드와 무관).
5. **[선행 필요, 별도 트랙] `case_history` 골든데이터 확충** — 현재 10건 수동 시드뿐.

---

## 3. 비침습 체크리스트 (착수 전 재확인용, 구현 완료 후 회고용으로도 유효)

- [x] 기존 함수의 **반환 계약(응답 shape)**을 바꾸지 않고 확장만 하는가 — `generate()` 성공 케이스(`DRAFT_SAVED`) 응답 필드 동일 확인
- [x] 새 자동 트리거(적재→생성)가 실패해도 **기존 수동 경로(룰 콘솔 수동 생성)는 그대로 동작**하는가 — 룰 콘솔 "규정 문서에서 생성" 버튼은 안 건드림
- [x] 대화형 에이전트가 **기존 그래프 CRUD API를 재사용**하고 새 저장 경로를 만들지 않는가 — `update_node`/`create_node`/`delete_node` 재사용 확인
- [x] MCP 툴콜링 전환이 **기존 단발 호출 경로를 완전히 대체하지 않고**, 실패 시 폴백 가능한가 — 아웃터 재시도 루프(§1.2-4)가 안전판으로 유지됨

---

## 3a. 프론트 연동 작업과의 격리 전략

**배경**: 프론트-에이전트 연동을 다른 팀원이 병행 작업 중. 격리 지점은 "코드 위치"가 아니라 **계약(contract)** — 프론트가 실제로 붙는 건 Django API 엔드포인트지 `apps/ai` 내부 함수가 아니다.

**레포 전례**: `Review List v0`를 만들 때 운영 모델은 그대로 import하되 별도 서브패키지+별도 라우트로 격리했다. v1도 동일 패턴 — 신규 엔드포인트(`/converse` 등)로 노출하고 기존 엔드포인트 응답 shape는 동결.

**적재→생성 자동 트리거(§1.2-2)가 코드상 켜졌다는 게 이번 격리 전략에서 가장 중요한 지점이다** — 문서를 새로 업로드(scope 지정)하면 룰 콘솔에 DRAFT 그래프가 자동으로 쌓이는 동작이 이제 코드에 들어가 있다. **단, 지금 당장은 무관한 docling 버전 드리프트 버그(§1.2-2 각주, `rule-agent-v1-implementation.md` §10) 때문에 업로드 자체가 파싱 단계에서 죽어 트리거가 실제로는 안 불린다** — 그 버그가 고쳐지는 순간부터 이 리스크가 살아나므로, 그 버그 수정 시점에 프론트 팀원과 다시 한번 확인이 필요하다.

### 3a.1 브랜치·PR 전략 (Rule Agent v1)

- **브랜치**: `feature/rule-agent-v1` — 작업자는 이 브랜치에 커밋만 올리고, **머지는 다른 팀원이 수행**.
- **커밋/PR은 §1.2 항목 단위로 쪼갠다.**
- **`rule_trigger.py` 활성화(§1.2-2)는 특히 명시적으로 표시** — 이제 실제로 자동생성이 동작하므로, 머지 담당자가 프론트 팀원과 타이밍을 맞출 시점을 판단해야 한다(§3a 참조).

---

## 4. 결정 사항 종합 (전부 확정)

**Rule Agent §1.2 전 항목 결정 완료(2026-08-16):**

1. 적재→생성 자동트리거 scope 범위 → **업로드 시 선택 1개만**
2. 재색인 시 자동 생성 재실행 여부 → **최초 적재 시에만, 재색인 제외**
3. 시뮬레이션 보고서 LLM 서술 → **추가 안 함(현행 유지)**
4. 검증→재생성 루프 설계(A안/재시도 범위/횟수/RAG 재사용/상태값 이름) → **전부 확정, 구현 완료**
5. MCP 툴콜링 범위 → **전체 재작성**(마운트 수정+배선+실제 tool-calling 루프)
6. 재시도 시 LLM 프롬프트 피드백 포맷 → **단순 텍스트 나열**(`_build_sanitize_feedback`/`_build_structure_feedback`)로 구현, 이 이상 정교화는 보류

**남은 미결정 (Risk Review Agent 범위, 이 브랜치 밖):**

1. Risk Review 3범주 분류의 정의 자체(어떤 기준으로 3개로 나누는지 — anomaly score 구간? 위반 확신도? 아직 미정의)
2. `case_history` 실 이력 적재 파이프라인을 v1에 포함할지, post-MVP로 유지할지

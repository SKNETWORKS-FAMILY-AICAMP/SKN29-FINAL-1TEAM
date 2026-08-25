# Risk Review Agent v1 구현 기록

> 이 문서는 **결정의 근거·코드 위치·실동작 검증 결과**를 남긴다. Rule Agent 쪽의 같은 역할은
> `rule-agent-v1-implementation.md`. §0에 "무엇을 결정했는지"(구 `agent-v1-upgrade-plan.md` §2,
> 2026-08-25 이 문서로 병합) 요약이 있다.

**범위**: 아래 §0.1의 5개 항목 중 4개(1·2·3·5) 구현·검증 완료(2026-08-19). 항목4(`feature_contribs` 실값)는 `anomaly.pkl` 재학습이 선행돼야 하는 별도 ML 트랙이라 이번 범위 밖.

## 0. 결정 배경 — v1 고도화 계획 요약 (Risk Review Agent 부분)

> Rule Agent 쪽 결정·MCP 배경은 `rule-agent-v1-implementation.md` §0 참조.

### 0.1 구현 상태

| 항목 | 상태 | 근거 |
|---|---|---|
| anomaly score → RAG → 보고서 2단계 파이프라인 | ✅ 구현 | `agents/risk_review_agent.py`: Stage1(`_stage1`, `get_tx_features`→`ml_infer`→`risk_tier`) → Stage2(`_stage2`, `_classify`(MCP 툴콜링)→`_decide_action`) |
| anomaly score 높을 때 3범주 분류 | ✅ 구현 | `stage1_anomaly.risk_tier`(HIGH/MEDIUM/LOW) — 고정 anomaly_score 임계값, §0.2-2 참조 |
| 분류(판단)와 액션(실행) 분리 | ✅ 구현 | `_classify()`(위반 여부만, MCP 툴콜링 루프) → `_decide_action()`(분류 결과만 입력받아 recommendation만 결정, 별도 LLM 호출) |
| Rule Agent와 공유하는 MCP 툴 사용 | ✅ 구현 | `mcp_client.py`를 `agents/rule_agent_v0/`에서 `agents/`(공용)로 승격, Rule Agent·Risk Review Agent 둘 다 같은 in-process 클라이언트로 `search_policy`/`search_cases`를 진짜 MCP 툴콜링으로 호출 |

### 0.2 v1에 필요한 것 — 처리 현황

1. **[기반] MCP 툴콜링 루프 전환** — ✅ 완료. `apps/ai/app/agents/mcp_client.py`(구 `rule_agent_v0/mcp_client.py`, 내용 변경 없이 이동)를 Rule Agent(`agent.py`/`chat.py`)와 Risk Review Agent(`_classify`)가 공유. Rule Agent와 달리 **초기 검색 1회분(policy+cases)을 파이썬이 먼저 실행**해 대화 맥락에 심어둔다 — 안 그러면 `search_policy`/`search_cases` 두 툴을 오가며 재검색만 반복하다 `MAX_TOOL_TURNS`(=6)를 다 쓰고도 한 번도 `submit_classification`을 못 부르는 사례가 실측됐다(정상 케이스에서도 발생). 프리시드 후 재검증 4건 전부 1턴 내 정상 종료 확인.
2. **3범주 분류 스키마 신설** — ✅ 완료(팀 결정: 고정 anomaly_score 임계값). `risk_tier`는 `violation_verdict`와 별개 필드로 Stage1에 추가(기존 필드는 그대로 유지, 확장만). 경계값은 배포된 `anomaly.pkl`의 실측 calibration_table에서 "80~90% 밴드(관측 이상비율 1.7%) → 90~100% 밴드(28.19%, lift 8.08배)"로 급등하는 지점을 HIGH 경계(`RISK_TIER_HIGH_THRESHOLD=0.0134`)로, 기존 운영 `is_outlier` 컷오프(모델 `threshold`)를 MEDIUM 경계(`RISK_TIER_MEDIUM_THRESHOLD=0.0037`)로 삼았다. 재학습해도 이 상수는 자동 갱신되지 않는다(고정값을 고른 이유이자 트레이드오프) — 분포가 크게 바뀌면 재학습 시 사람이 다시 실측해 갱신해야 한다.
3. **분류 단계와 액션(recommendation) 단계 분리** — ✅ 완료. `_classify()`(MCP 툴콜링, `Classification` 스키마: violation_verdict/review_reasons/citations/similar_cases) → `_decide_action()`(단일 호출, `ActionDecision` 스키마: recommendation/rationale, 분류 결과가 이미 확정된 전제로만 판단하고 위반 여부를 재판단하지 않음). **반환 계약은 그대로**(`stage2_rag_review`의 5개 필드 동일) — `_stage2()`가 두 결과를 기존 shape으로 재조립.
4. **[선행 필요, 별도 트랙] `feature_contribs` 실값 확보** — ❌ 여전히 미착수. `anomaly.pkl` 재학습 필요(ML 파이프라인 작업, Agent 코드와 무관) — 이번 세션 범위 밖.
5. **[선행 필요, 별도 트랙] `case_history` 골든데이터 확충** — ✅ 완료(팀 결정: 이번에 같이 확충). `app/rag/golden_cases.py` 10건→18건 — "업무활성"→"회식"(GATHERING) 리네임 후 회식 사례가 0건이던 공백을 메우고(3건 추가), 나머지 카테고리도 사례 다양성 보강. `python -m app.rag.case_store --upsert`로 `case_history` 재적재 완료(18건, 기존 id는 upsert라 멱등 갱신).

**해소된 미결정(2026-08-19, 팀 확인):**
1. 3범주 분류 정의 → 고정 anomaly_score 임계값(위 §0.2-2)
2. `case_history` 실 이력 적재 파이프라인 → v1에서 골든데이터만 확충(수동 셋), **실 결정이력 자동 적재 파이프라인 자체는 여전히 post-MVP**(항목 5의 범위는 "골든데이터 보강"이지 "적재 자동화"가 아님 — 착오 주의). 이후 실제 파이프라인은 `decision-case-data.md`로 구현됨.

---

## 0a. main 병합 시점에 발견한 동시 작업 — 수동 리졸브(2026-08-19)

이 v1 재작성을 로컬에서 진행하는 동안, 팀원이 같은 파일(`risk_review_agent.py`)을 다른 목적(검색 품질 개선)으로 고쳐 이미 `main`에 병합해 둔 상태였다(`c605e99`·`21ffe4f`). `git fetch`로 뒤늦게 발견해 `git stash` → `git merge origin/main --ff-only` → `git stash pop`으로 충돌을 수동 리졸브했다. 두 변경이 같은 함수(`_build_query`/`_format_chunks`/`_stage2`)를 다른 방향으로 건드리고 있어 **자동 병합이 불가능했다** — 정확히는 어느 한쪽을 버리는 게 아니라 **둘 다 적용**해야 했다.

**팀원 변경분(먼저 main에 있던 것, 유지+접목)**:
- `app.rag.retrieval.build_query(category, merchant, contribs, summary)` — 원시 ML 피처명을 그대로 검색어에 넣던 방식(예: "거래금액_Zscore_확장")을 자연어 문장으로 교체 + Settlement 판정필드(`facts_nl`)를 검색어에 결합. 실측 ΔMRR +0.020(95% CI가 0 배제).
- `_format_policy_chunks`(구 `_format_chunks`)에 `parent_text`(같은 조 전문) 포함 — 잎 청크만 넘기면 항 단위로 쪼개진 조의 다른 항이 안 보이는 문제.
- 분류 시스템 프롬프트에 "확정 판정(VIOLATION/NO_VIOLATION)엔 '판단 보류' 같은 유보 표현 금지" 규칙 추가.
- 분류 프롬프트에 `거래 사실: {facts}` 필드 추가(검색은 판정필드를 아는데 판정 LLM은 몰랐던 불일치 수정).
- `tests/test_risk_review_agent.py` 7건(당시 `_format_chunks`/`_build_user_prompt` 대상).

**이 세션 v1 변경분(§1~4, 유지)**: MCP 툴콜링 루프, `risk_tier`, 분류/액션 분리, `mcp_client.py` 공용화.

**리졸브 방법**: 팀원 변경분의 검색·프롬프트 품질 개선을 v1의 새 구조(`_classify()`/`_decide_action()`) 안으로 그대로 옮겼다 — `_build_query` 대신 `build_query`(팀원 함수)를 초기 질의 조립에 쓰고, `_format_policy_chunks`가 `parent_text`를 포함하도록 하고, 분류 프롬프트에 `facts_nl(summary)`를 채웠다. 팀원의 `_build_user_prompt`(v0의 단일 프롬프트 조립 함수)는 사라졌지만 그 역할은 신설 `_build_classify_prompt(summary, stage1, initial_query, policy_hits, case_hits)`가 이어받는다(순수 함수, 네트워크 없음 — 팀원 테스트와 같은 성격으로 단위 테스트 가능하게 의도적으로 분리). `tests/test_risk_review_agent.py`는 새 함수명(`_format_policy_chunks`/`_build_classify_prompt`)에 맞춰 갱신하되 검증 의도(부모 텍스트 포함·인용은 잎 기준·거래 사실 누락 방지)는 그대로 보존했다.

**검증**: `pytest tests/test_risk_review_agent.py tests/test_retrieval.py` 21건 통과. 실제 IN_REVIEW 정산(383·370)으로 재실행해 `build_query` 경유 검색이 실제 조문을 정확히 찾아오는 것(`제8조 (사전승인이 필요한 경우)` 등 조 제목까지 포함된 인용) 확인 — v0의 원시 피처명 기반 질의보다 더 구체적인 근거로 좁혀짐.

---

## 1. MCP 툴콜링 전환 (§0.1 항목1)

### 1.1 `mcp_client.py` 공용화

기존 `apps/ai/app/agents/rule_agent_v0/mcp_client.py`(Rule Agent 전용 경로에 있었지만 내용 자체는 `fastmcp.Client`로 `app.mcp.server.mcp`에 in-process 접속하는 범용 헬퍼)를 `apps/ai/app/agents/mcp_client.py`(공용 위치)로 **내용 변경 없이 이동**했다. Rule Agent(`rule_agent_v0/agent.py`, `rule_agent_v0/chat.py`)의 import를 `from .. import mcp_client`로 갱신하고, Risk Review Agent가 같은 모듈을 `from app.agents import mcp_client`로 가져다 쓴다. Agent별 사본을 만들지 않는다는 원칙(`rule-agent-v1-implementation.md` §0.2 비침습 체크리스트) 그대로 유지.

### 1.2 Stage2를 실제 툴콜링 루프로 재작성

이전(v0)엔 파이썬이 `search_policy`/`search_cases`를 미리 한 번 실행해 결과를 프롬프트 문자열에 박아넣고 `beta.chat.completions.parse`로 단발 구조화 출력을 받았다. v1은 Rule Agent(`rule-agent-v1-implementation.md` §0.1 항목1)와 같은 패턴 — `tools=[search_policy, search_cases, submit_classification]`로 멀티턴 루프를 돌리고, `submit_classification`(종료 툴)이 호출돼야 끝난다. 안전판 `MAX_TOOL_TURNS=6`(Rule Agent와 동일 근거).

### 1.3 실측으로 잡은 버그: 프리시드 없이는 턴을 다 쓰고도 제출을 못 함

**증상**: 실제 IN_REVIEW 정산 건(settlement 369, 식대)으로 최초 구현을 그대로 돌려보니, 모델이 `search_policy`/`search_cases`를 번갈아 5회 호출하며 질의를 계속 바꿔가다가(`"식대 본죽"` → `"출장 중 식대"` → `"출장 중 식사"` → …) `MAX_TOOL_TURNS=6`을 전부 소진하고 한 번도 `submit_classification`을 부르지 않았다. 안전판(`INSUFFICIENT_INFO` 폴백)이 정상 작동해 죽지는 않았지만, **정상적으로 판단 가능한 건이 안전판으로 떨어지는 건 품질 저하**다.

**원인**: Rule Agent는 첫 턴에 이미 파이썬이 실행한 `initial_chunks`를 대화 맥락에 심어두고 "부족하면 추가 검색"만 모델에게 맡긴다(`rule-agent-v1-implementation.md` §0.1 항목1 결정 그대로). Risk Review v1 최초 구현은 이 프리시드 없이 "질의 힌트 문자열"만 주고 첫 검색부터 모델에게 맡겼다 — 그러다 보니 매 턴이 "검색 한 번"으로 소모되고, 두 개의 검색 툴(policy+cases)을 오가느라 Rule Agent(검색 툴 1개)보다 두 배 빠르게 턴을 잡아먹었다.

**수정**: `_classify()` 진입 시 `mcp_client.call_tool("search_policy", ...)`와 `search_cases`를 파이썬이 먼저 1회씩 실행해 첫 user 메시지에 통째로 심는다(`_format_policy_chunks`/`_format_case_hits`). 시스템 프롬프트도 "먼저 검색을 호출하라"에서 "주어진 근거로 충분하면 바로 제출, 부족하면 추가 검색"으로 바꿨다.

**재검증**: 같은 settlement 369를 포함해 4건(383·370·382·368, 회식·비품·식대 카테고리 혼합) 전부 **1턴 내 정상 종료** 확인 — 프리시드된 근거만으로 충분하다고 판단하면 즉시 `submit_classification`을 호출하고, 그 자리에서 끝난다.

---

## 2. risk_tier 3단계 분류 (§0.2-2)

### 2.1 결정: 고정 anomaly_score 임계값

팀 결정(AskUserQuestion, 2026-08-19) — 10분위 보정 밴드(`calibration_table`)를 그대로 재사용하는 대신, 재학습돼도 자동으로 흔들리지 않는 **고정 스코어 상수**를 코드에 박는다. 트레이드오프는 명확히 인지: 분포가 크게 바뀌면 사람이 재실측해서 상수를 갱신해야 한다.

### 2.2 임계값을 어떻게 잡았나 — 실측 기반

배포된 `apps/ai/var/models/anomaly.pkl`을 직접 로드해 `calibration_table`을 확인했다:

```
70~80%  score_lower_bound=-0.0310  observed_rate=0.0125
80~90%  score_lower_bound=-0.0142  observed_rate=0.0170
90~100% score_lower_bound= 0.0134  observed_rate=0.2819  (lift 8.08x)
```

80~90%에서 90~100%로 넘어가는 지점에서 관측 이상비율이 1.7% → 28.19%로 **급등**한다(다른 구간 전이는 완만한데 이 지점만 계단형). 이 지점을 `RISK_TIER_HIGH_THRESHOLD = 0.0134`로 잡았다. MEDIUM 경계는 새 상수를 만들지 않고 기존 운영 `is_outlier` 컷오프(`model.threshold`, 실측 `0.0037`)를 그대로 재사용했다 — 이미 "이상치로 볼지" 판단에 쓰이고 있는 값이라 이중 기준을 늘리지 않기 위함.

```python
RISK_TIER_HIGH_THRESHOLD = 0.0134
RISK_TIER_MEDIUM_THRESHOLD = 0.0037
```

`_risk_tier(anomaly_score)`가 `stage1_anomaly.risk_tier`(HIGH/MEDIUM/LOW)로 채운다. 모델 미학습 시(stub 경로)는 `LOW` 고정.

### 2.3 검증

```
_risk_tier(0.02)  == "HIGH"
_risk_tier(0.005) == "MEDIUM"
_risk_tier(0.0)   == "LOW"
```

실제 정산 건 기준: settlement 383(회식, score 0.0567) → HIGH, settlement 370(비품, score −0.0262) → LOW.

---

## 3. 분류(violation_verdict) ↔ 액션(recommendation) 단계 분리 (§0.2-3)

### 3.1 설계

- **`_classify()`**: MCP 툴콜링 루프(§1). 산출물은 `Classification` 스키마 — `violation_verdict`/`review_reasons`/`citations`/`similar_cases`. **`recommendation`을 포함하지 않는다** — 이 단계는 "위반인가 아닌가"만 본다.
- **`_decide_action()`**: 단일 LLM 호출(검색 없음 — 분류 단계가 이미 확보한 근거만 입력으로 받는다). 산출물은 `ActionDecision` 스키마 — `recommendation`/`rationale`. 시스템 프롬프트가 "위반 여부를 재판단하거나 뒤집지 말 것"을 명시.
- `_stage2()`가 두 결과를 기존 v0 응답 shape(`violation_verdict`/`review_reasons`/`recommendation`/`citations`/`similar_cases` 5개 필드)으로 재조립한다 — **Django `risk_review.py`의 소비 코드는 한 글자도 안 바꿨다**(`.get()` 기반 dict 접근이라 shape 동일하면 무영향, 비침습 체크리스트 그대로 통과).

### 3.2 왜 나눴나

이전엔 한 번의 LLM 호출·한 스키마(`RiskVerdict`)가 위반 여부와 권장 처리를 동시에 냈다. "이 건이 규정을 어겼는가"(사실판단)와 "그래서 어떻게 처리할까"(정책적 선택)를 같은 근거 확보 루프에 묶어두면, 검색 루프가 두 관심사를 동시에 만족시켜야 해 프롬프트가 무거워지고 재사용성도 떨어진다. 분리하면 향후 recommendation 정책만 바꾸고 싶을 때(예: SUPPLEMENT/REJECT 기준 조정) 분류 로직·검색 로직을 건드리지 않고 `_decide_action()`만 고치면 된다.

---

## 4. `case_history` 골든데이터 확충 (§0.2-5)

팀 결정(AskUserQuestion, 2026-08-19) — "이번에 같이 확충"을 선택. `app/rag/golden_cases.py`: 10건 → 18건.

**보강 이유**: `Category` enum이 "업무활성"→"회식"(GATHERING)으로 리네임된 이후(2026-08-14, CLAUDE.md 상태보드 참조) `golden_cases.py`가 갱신되지 않아 **정산 카테고리 6종 중 "회식" 사례가 0건**이었다 — Risk Review 2차 검증이 회식 건을 볼 때 `search_cases`가 관련 없는 사례만 돌려주는 죽은 구간이 있었던 셈. 회식 사례 3건(REJECT/APPROVE/RETURN 각 1건, 1인당 한도·2차 결제 패턴 반영)을 추가하고, 비품·회의·출장·접대·식대에도 카테고리당 outcome 다양성을 보강했다(총 8건 추가).

**주의(범위 명확화)**: 이건 **수동 골든데이터 보강**이지, `case_history`에 실 결정이력을 자동으로 쌓는 파이프라인이 아니다. 그 파이프라인(Django `RiskReview`/`Settlement` 실데이터를 정기 배치로 임베딩)은 여전히 post-MVP다 — `golden_cases.py` 파일 docstring에도 명시된 기존 계약 그대로.

**적재**: `python -m app.rag.case_store --upsert` 재실행 — `case_id` 기준 upsert라 기존 10건은 그대로 갱신되고 신규 8건만 추가된다(멱등). 실행 후 `case_history` 컬렉션 count 18 확인.

---

## 5. 변경 파일

| 파일 | 변경 |
|---|---|
| [`apps/ai/app/agents/mcp_client.py`](../../apps/ai/app/agents/mcp_client.py) | 신규(이동) — `rule_agent_v0/mcp_client.py`를 공용 위치로, 내용 무변경 |
| [`apps/ai/app/agents/rule_agent_v0/mcp_client.py`](../../apps/ai/app/agents/rule_agent_v0/mcp_client.py) | 삭제(위로 이동) |
| [`apps/ai/app/agents/rule_agent_v0/agent.py`](../../apps/ai/app/agents/rule_agent_v0/agent.py) | import만 `from .. import mcp_client`로 변경 |
| [`apps/ai/app/agents/rule_agent_v0/chat.py`](../../apps/ai/app/agents/rule_agent_v0/chat.py) | 동일 |
| [`apps/ai/app/agents/risk_review_agent.py`](../../apps/ai/app/agents/risk_review_agent.py) | 전면 재작성 — `_classify()`(MCP 툴콜링, 프리시드 포함) + `_decide_action()`(단일 호출) 신설, `_risk_tier()`/임계값 상수 추가, `_stage1`이 `risk_tier` 채움, `_stage2`가 기존 shape으로 재조립. `run()`/`_stage1`/외부 반환 계약은 확장만(필드 삭제·개명 없음) |
| [`apps/ai/app/rag/golden_cases.py`](../../apps/ai/app/rag/golden_cases.py) | 10건 → 18건(회식 3건 신규 + 카테고리별 보강 5건) |
| `apps/ai/app/api/risk.py` | **무변경** — `risk_review_agent.run()` 반환을 그대로 통과시키는 얇은 라우터라 내부 재작성의 영향을 받지 않음 |
| `apps/core/domain/settlements/risk_review.py` | **무변경** — `stage1`/`stage2` 필드를 `.get()`으로만 읽어 추가 필드(`risk_tier`)에 영향받지 않음 |

---

## 6. 실동작 검증

전부 실제 LLM(`gpt-4o-mini`) + 실제 Chroma(`policy_docs`/`case_history`) + 실제 Django 내부 API(`settlement-summary`/`tx-features`) 경로로 검증(mock 없음).

| 항목 | 방법 | 결과 |
|---|---|---|
| import 정합성 | 컨테이너 내 `from app.agents import risk_review_agent, mcp_client` + `rule_agent_v0.agent/chat` | 정상 로드 |
| `_risk_tier` 경계 | 단위 호출 3개 값 | HIGH/MEDIUM/LOW 기대대로 |
| 프리시드 전 회귀(버그 재현) | settlement 369 실행 | 6턴 소진, `submit_classification` 미호출 → `INSUFFICIENT_INFO` 폴백(안전판은 작동, 품질 저하 확인) |
| 프리시드 후(수정 확인) | 동일 settlement 369 재실행 | 1턴 내 `NO_VIOLATION`/`APPROVE`로 정상 종료, 실제 정책·사례 인용 포함 |
| 카테고리 다양성 | settlement 383(회식,HIGH)·370(비품,LOW)·382(회식,HIGH)·368(비품,LOW) | 4건 전부 1턴 내 정상 종료, `risk_tier`·`violation_verdict`·`recommendation` 모두 합리적 값(REJECT/APPROVE 각각 위반 근거·비위반 근거와 일치) |
| `case_history` 재적재 | `python -m app.rag.case_store --upsert` | `적재 완료: case_history 18건`, `peek` count 18 확인 |
| AI 회귀 스위트 | `pytest --ignore=<사전 실패 docling 3파일>` | 12 passed, 6 skipped(무관한 기존 docling 버전드리프트 실패 5건 제외 시 전부 통과) |
| Django 회귀 스위트 | `manage.py test` | 149 passed(`risk_review.py` 소비 경로 무영향 확인) |

---

## 6a. 구현 후 전수 검토 (2026-08-19) — 잡은 결함 6건

구현·병합을 끝낸 뒤 Risk Review 경로를 처음부터 다시 정독하고 실패 경로를 주입해 재현했다. **6건 전부 실측으로 재현한 뒤 고쳤고, 회귀 테스트를 붙였다**(ai 6건 + core 3건). 공통점이 있다 — 전부 "정상 경로에서는 안 보이는" 결함이었다.

### 6a.1 [기능 사망] `risk_tier`가 Django에서 조용히 버려짐

§2에서 만든 3단계 분류가 **AI 응답에만 있고 어디에도 저장되지 않았다.** `settlements/risk_review.py`가 `stage1`에서 `anomaly_score`·`contribs`만 꺼내 쓰고 `risk_tier`는 읽지 않아서, DB·API·화면 어디에도 닿지 않았다. AI 단독 실행으로 테스트하면 응답에 값이 보이니 "됐다"고 착각하기 쉬운 자리다.

**수정**: `RiskReview.risk_tier` 컬럼 신설(마이그레이션 `risk/0005`) → `risk_review.py`가 저장 → `SettlementSerializer.riskTier`·`RiskReviewSerializer.riskTier`로 노출 → 프론트 `ReviewItem.riskTier` 타입 추가. **파생값인데 왜 저장하나**: 임계값이 코드 상수라 사람이 튜닝하는데, 읽을 때마다 다시 계산하면 과거 판정 등급까지 소급해 바뀌어 감사 기록이 흔들린다. `rule_hits.eval_context` 스냅샷과 같은 이유로 **판정 시점 스냅샷**으로 굳힌다(재판정하면 새 임계값으로 다시 매겨진다).

### 6a.2 [데이터 오염] 모델이 `case_id`를 지어냄

`submit_classification` 스키마는 `similar_cases[].case_id`를 요구하는데, `_format_case_hits`가 검색 결과를 `[outcome] citation: text`로만 보여줘 **case_id를 한 번도 노출하지 않았다.** 모델은 알 길이 없으니 citation 문자열 조각을 채웠다 — 실측: 실제 id가 `case-golden-005`인 사례가 `#0511`로 기록됐고, 그 값이 Django `rag_refs`의 "사례 …"로 검토 화면까지 갔다. `case_history`에 없는 id라 원 사례로 되짚을 수 없다. v0부터 있던 결함을 그대로 물려받은 것.

**수정**: 포맷에 `case_id=...`를 넣고, 시스템 프롬프트 3번에 "citation 조각을 case_id로 쓰지 말고 표시된 값을 그대로 복사하라"를 명시. **검증**: 같은 건 재실행 → `case-golden-005`·`case-golden-011`로 정상 기록.

### 6a.3 [가용성] 부분 실패가 검토 결과 전체를 삼킴 (3곳)

Django `risk_review.run()`은 AI 호출이 실패하면 경고만 남기고 **`RiskReview` 행을 아예 안 만든다**(판정을 되돌리지 않으려는 의도적 설계). 그래서 AI 쪽에서 예외가 하나라도 올라오면 검토자 화면엔 근거는커녕 흔적도 안 남는다. 그런데 예외가 올라올 자리가 세 군데 무방비였다:

| 자리 | 실패 예 | 전 → 후 |
|---|---|---|
| `_stage1` | `get_tx_features` 500, `ml_infer` 형상 불일치 | 2차까지 통째로 유실 → stub+사유로 격하하고 **2차는 계속 실행** |
| `_classify` 프리시드 검색 | Chroma 다운 | 전체 유실 → 빈 근거로 진행, 모델이 재검색하거나 `INSUFFICIENT_INFO`로 정직하게 수렴 |
| `_decide_action` | OpenAI 5xx·타임아웃 | **이미 성공한 ①분류(검색·인용, 비용 지불 완료)까지 폐기** → 결정론적 폴백 |

액션 폴백은 `NO_VIOLATION→APPROVE` / `VIOLATION·INSUFFICIENT_INFO→SUPPLEMENT`다. **VIOLATION이어도 REJECT로 자동 강등하지 않는다** — 최종반려는 되돌릴 수 없는 단말이라 사람만 내린다는 도메인 원칙(CLAUDE.md "엔진은 최종반려를 만들지 않는다")을 장애 경로에서도 지킨다.

### 6a.4 [가용성] 툴 인자 JSON 파싱 실패가 안 잡힘

`json.loads(tc.function.arguments)`가 무방비라, LLM이 깨진 JSON을 내면(드물지만 잘림·인용부호 오류로 발생) 2차 검증 전체가 죽었다. **수정**: 그 툴 호출만 실패로 돌려주고 모델이 다시 시도하게 한다.

### 6a.5 [표시 오류] 검토 화면이 실 데이터에서 전 건을 "정상(초록)"으로 칠함

S-03가 `Math.round(anomalyScore * 100)`을 점수로 찍고 `>= 60`이면 빨강으로 칠했다. 그런데 `anomaly_score`는 확률이 아니라 IsolationForest 결정함수의 부호 반전값이라 **실측 범위가 −0.03~+0.06**이다. 즉 실 데이터에선 −3·6 같은 값이 나와 **관측 이상비율 28%(기준 대비 8배)인 HIGH 건조차 초록 "6"으로 보였고**, "고위험 N건"은 항상 0이었다. 목업(`anomalyScore: 0.92`)은 0~1이라 이 결함이 가려져 있었다 — 실 모드에서만 틀리는 종류.

**수정**: 등급 판정을 프론트가 다시 하지 않고 백엔드 `riskTier`를 쓴다(단일 원천). 숫자 배지를 `고위험/주의/정상` 라벨로 교체(원시 점수는 `title` 툴팁으로), 목업 6건에 `riskTier` 명시, `.risk-score` CSS를 한글 3글자에 맞게 조정. Risk Review 미실행 건은 `—`로 비운다(`''`=등급 없음이지 `LOW`(안전)가 아니다 — `aiRecommendation`과 같은 계약).

### 6a.6 [정합] 재판정 시 옛 검토 결과가 최신을 가림

`RiskReview.Meta.ordering`이 `-anomaly_score`인데 소비처는 전부 `.first()`/`rrs[0]`로 "이 정산의 **현재** 검토 결과"를 읽는다. 재판정·재제출은 이 테이블에 행을 새로 쌓으므로(갱신이 아니라 이력), 점수가 같거나 더 높은 옛 행이 최신 행을 가린다. **실측 재현**: settlement 383에서 03:08 행(등급 없음)이 04:45 행(HIGH)을 가려 화면에 옛 판정이 떴다.

**수정**: `ordering = ["-created_at", "-id"]`(마이그레이션 `risk/0006`). 검토 큐의 위험도 정렬은 프론트가 `anomalyScore`로 따로 하므로 여기서 점수순을 유지할 이유가 없다. CLAUDE.md 룰 엔진 ⑧에서 EvalContext 스냅샷에 대해 이미 한 번 고친 것과 **같은 종류의 결함**이다.

### 6a.7 회귀 테스트

`apps/ai/tests/test_risk_review_agent.py` +6건(case_id 노출·stage1 격하·검색 장애·액션 폴백 2건·등급 경계값), `apps/core/domain/policies/tests/test_agent_wiring.py` +3건(risk_tier 저장·API 노출·최신 행 선택). 전체: core 214건 · ai 70건 · 프론트 빌드 통과.

---

## 7. 남은 것

- **항목4(`feature_contribs` 실값)**: `anomaly.pkl`이 `feature_stats` 없이 학습된 시점의 pkl이라 여전히 빈 배열(CLAUDE.md 상태보드 기존 기록 그대로) — `train.py`(feature_stats 포함 버전)로 재학습해야 해소. Agent 코드와 무관한 별도 ML 트랙.
- **`case_history` 실 이력 자동 적재 파이프라인**: post-MVP로 유지(§4 "주의" 참조). 지금은 골든데이터 18건이 전부.
- 분류/액션 분리 이후 `_decide_action()`의 recommendation 판단 기준(REJECT vs SUPPLEMENT 경계)은 프롬프트 규칙으로만 정의돼 있고 별도 정량 검증셋은 없음 — Rule Agent의 `RuleTestCase` 같은 자동 검증 장치가 아직 없다. 필요해지면 후속 과제.

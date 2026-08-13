# Rule Agent v0 — 작업 요약 (배선 검증 완료)

> 작성일: 2026-08-13 · 작성자: 한경찬(AI Agent·ML·리소스)
> 상태: **배선 검증 완료 · 인증(G-16) 1건만 남음**

---

## 1. 목적

3-Agent 중 **Rule Agent — 생성(Generate)** 단계 v0 구현. 목표는 규칙 품질이
아니라 **연결(배선) 확인**이었다:

> `search_policy(RAG) → LLM 노드 초안 생성 → 결정론적 그래프 조립 → Django 저장`
> 플로우가 실제 시스템 위에서 끝까지 연결되는지 실동작으로 검증

권위 스펙: `기술명세서.md §4.2(a)/§5/§6.2`, `요구사항_명세서.md FR-RB-01~05`.

---

## 2. 결론 먼저

**배선은 5단계 전 구간이 실제 데이터로 검증됐다.** 마지막 한 곳(Django 쓰기
직전의 인증)에서 의도대로 멈춰 있고, 이건 코드 버그가 아니라 **다음 단계에서
풀어야 할 운영 결정 사항**이다.

```
① search_policy(실 규정 데이터) → ② LLM 노드 생성(구조화, 문법오류 불가)
   → ③ 1차 검증(DSL 화이트리스트) → ④ 결정론적 그래프 조립
   → ⑤ Django 저장 요청 → 🔒 403 (인증 미해결, 의도된 정지 지점)
```

| 단계 | 상태 |
|---|---|
| ① RAG 검색 | ✅ 실제 규정 문서(업무추진비/회식/출장/법인카드 규정) 90개 청크 대상 실측 성공 |
| ② LLM 노드 생성 | ✅ 실제 조문 근거로 규칙 생성, 문법 오류 클래스 자체를 구조적으로 제거 |
| ③ 검증 | ✅ DSL 화이트리스트·경로 검증 정상 동작 |
| ④ 그래프 조립 | ✅ severity 순 결정론적 체인 조립 확인 |
| ⑤ Django 저장 | 🔒 **인증 미해결로 403** — 코드 문제 아님, 팀 결정 대기 |

---

## 3. 아키텍처 — 왜 이렇게 만들었나

### 3.1 격리 원칙

신규 로직을 전부 **격리 서브패키지** 안에 넣고, 기존 코드 수정은 최소화했다.

```
apps/ai/app/agents/rule_agent_v0/          FastAPI 쪽, 전부 신규
├── settings.py       v0 전용 env 설정 (중앙 config.py 미수정)
├── embedding.py       OpenAI 임베딩 (text-embedding-3-large@1024)
├── vector_store.py    Chroma 접근 (policy_docs 컬렉션)
├── search.py           search_policy 구현
├── django_client.py    Django 내부 API 오케스트레이션
├── agent.py             생성 로직 본체 (RAG→LLM→조립→저장)
└── api.py                라우터 (/agent/rule-v0/*, 정식 경로와 분리)

apps/core/domain/policies/
└── rule_agent_v0_views.py    Django 쪽, 신규 파일 1개 (EvalContext 스키마 조회 전용)
```

**기존 파일 수정은 4곳뿐**:
- `apps/ai/app/main.py` — 라우터 등록 2줄
- `apps/ai/requirements.txt` — `chromadb` 1줄
- `apps/core/config/urls.py` — import 1줄 + path 1줄

**되돌리기**: 위 서브패키지 2개 삭제 + 이 4곳만 원복하면 착수 전 상태로 완전 복귀.

### 3.2 핵심 설계 결정

| 결정 | 이유 |
|---|---|
| **그래프 저장은 신규 API를 만들지 않고, 기존 `RuleGraphViewSet`(룰 콘솔 API)을 오케스트레이션** | 실물 코드 확인 결과 `POST /api/rules/drafts/` → `POST /api/rules/{id}/nodes/` → `PATCH /api/rules/{id}/nodes/{key}/` 3단계로 이미 동일 기능 존재. 중복 구현 회피 |
| **LLM은 노드 "재료"만 생성, JSON-Logic 문법은 파이썬이 조립** | LLM이 JSON을 문자열로 직접 작성하게 하면 반복적으로 문법 오류를 냄(아래 §5 참조). 재귀 구조화 필드(`condition` 객체)로 받아서 결정론적으로 조립하도록 전환 — 이 클래스의 오류가 구조적으로 발생 불가능해짐 |
| **decision은 `action.decision` 직접 지정** | 기술명세서 §4.2 확정 방식. θ_pass/θ_reject 임계값 방식(구버전 문서에 남아있던 것)은 채택하지 않음 |
| **v0는 `mcp/tools.py`를 경유하지 않고 자체 `search.py` 직접 호출** | 기존 tool 계층을 안 건드리기 위한 격리 선택. 대가: tool call 로깅 경로를 안 탐(v1에서 이관 필요) |
| **v0는 항상 새 그래프 계열(v1)만 생성**, 기존 계열에 버전 추가는 미지원 | 오케스트레이션 복잡도를 낮추기 위한 v0 범위 제한. v1에서 `POST /api/rules/{id}/versions` 추가 예정 |

---

## 4. 실측 검증 상세

### 4.1 RAG 파이프라인 실데이터 연결

- 팀 인덱서(`app.rag.embedding.index`)로 규정 문서 11종·888청크를 실제 docker
  Chroma에 적재(`text-embedding-3-large@1024`)
  - `policy_docs` 103청크(잎 90) — 법인카드/업무추진비/출장비/회식 규정
  - `tax_refs` 730청크, `org_docs` 55청크
- `search_policy("사전승인 기준 금액")` 호출 시 실제 `업무추진비_사용규정
  제6조(사용 승인)` 조문이 정확한 citation과 함께 반환됨을 확인

### 4.2 엔드투엔드 실행 결과 (최종)

```bash
curl -X POST localhost:9000/agent/rule-v0/generate -d '{"scope":"접대","top_k":6}'
```

```json
{"detail":"rule generate 실패: Client error '403 Forbidden' for url 'http://localhost:8000/api/rules/drafts/'"}
```

- `search_policy`가 업무추진비 관련 조문 6건을 정확히 검색
- LLM이 이를 근거로 실제 규정 기반 노드 생성 (제6조 사전승인 구간별 룰,
  제6조7항 정산거부, 제6조4항 청탁금지법 등 — `source_citation` 정확)
- 노드 검증(DSL 화이트리스트) 전건 통과 — **문법 오류로 인한 탈락 0건**
- 결정론적 조립 완료, Django에 저장 요청 → **정확히 예측했던 지점에서 403**

### 4.3 확인된 배선 이슈와 조치 (실측 기반)

| # | 이슈 | 조치 |
|---|---|---|
| 로컬 실행 시 `POSTGRES_HOST=db`, `RULE_AGENT_V0_DJANGO_BASE=http://core:8000` 등 docker 서비스명 기반 기본값 | 로컬 개발 시 export로 `localhost`/실제 포트로 덮어씀. `.env` 파일 자체는 docker용 값 유지(도커 실행 시 깨지지 않도록) |
| Chroma host/port 미설정 시 로컬 파일(`./chroma_data_v0`)로 조용히 폴백 | `RULE_AGENT_V0_CHROMA_HOST=localhost`, `RULE_AGENT_V0_CHROMA_PORT=8001`로 실제 docker Chroma 지정 |
| conda 환경 PATH 꼬임으로 `python3`가 시스템 파이썬을 가리킴 | 명시적 인터프리터 경로(`/opt/miniconda3/envs/final_prj/bin/python3`) 사용으로 우회 |

### 4.4 부가 발견 — `ai` 컨테이너 이미지 stale (팀 공유 필요, v0 범위 밖)

로컬 방식(호스트에서 직접 uvicorn 실행)과 팀 표준 절차
(`docker compose exec ai python -m app.rag.embedding.index`)가 같은 데이터를
보는지 대조하는 과정에서 발견:

- `docker compose exec ai ...` 실행 시 `ModuleNotFoundError: No module named
  'chromadb'` — `ai` 이미지에 chromadb가 설치되어 있지 않음
- 원인: 로컬 `skn-settlement-ai:latest` 이미지 빌드 시각이 2026-08-03인데,
  `requirements.txt`에 `chromadb`가 추가된 커밋은 2026-08-12 — **이미지가
  9일 stale 상태**. `docker compose build ai` 재빌드 없이는 컨테이너 경유
  인덱싱/조회가 원천적으로 불가
- Chroma host/port 설정 자체는 로컬 방식과 완전히 동일한 볼륨
  (`skn-settlement_chromadata`)을 가리키는 구조로 확인됨 — 재빌드만 하면
  `docker compose exec ai --peek`도 동일한 값(`policy_docs 103` 등)을
  보여줄 것으로 예상. 재빌드는 포트 9000 충돌 우려로 이번 작업에서는
  진행하지 않음(v0 범위 밖, 팀 전체 배포 이슈)
- **다음 `docker compose build`/`up --build` 시 팀 전체가 자연히 해소됨**

---

## 5. 겪은 문제와 해결 — LLM JSON 문법 오류 (D-15 → D-16)

### 문제

LLM에게 JSON-Logic 조건을 **문자열로 직접 작성**하게 했더니, 여러 차례에
걸쳐 다른 패턴으로 문법이 깨졌다:
- `{"==": {"var": a, "var": b}}` (한 객체에 `var` 키 2개)
- `{"and":[{"<":{"var":"tx.amount","var":"..."}},{">":{"var":"tx.amount",300000}}]}`
  (연산자 객체 안에 키 없는 값이 바로 붙는 진짜 JSON 신택스 에러)

1차로 시스템 프롬프트에 ✅/❌ 예시를 추가했으나(D-15), 다른 변종 패턴에서
또 깨짐 — **프롬프트 패치로는 근본 해결이 안 됨**을 확인.

### 근본 해결 (D-16)

LLM이 JSON 문자열을 손으로 짜는 구조 자체를 없앴다. 비교 조건을 **재귀
구조화 필드**(`comparison`/`group` 두 종류, `left_path`/`op`/`right_kind`
등)로 받고, 파이썬이 JSON-Logic을 결정론적으로 조립하도록 전환.

- **결과**: 이 클래스의 오류가 **구조적으로 발생 불가능**해짐. 재검증 시
  문법 오류로 인한 노드 탈락 0건
- **설계 원칙(D-17)**: 재귀 스키마가 `rule-engine.md` 캐논의 DSL 연산자
  전체(`and/or/not/==/!=/>/>=/</<=/in/var`)를 100% 커버하도록 구성 —
  구현 편의를 위해 캐논의 표현력을 임의로 줄이지 않음

---

## 6. 남은 것 — G-16 (인증), 유일한 미해결 항목

### 무엇이 막혀 있나

Django의 `RuleGraphViewSet`(`drafts`/`nodes`/`nodes/{key}` 3개 엔드포인트)은
`CanViewRule` 권한(`RULE_VIEW` capability)을 요구한다. 이건 **사람이 룰
콘솔 화면에 로그인해서 쓰는 걸 전제**로 설계된 것이라, FastAPI(프로그램)가
호출하면 "로그인 안 된 요청"으로 거부당한다(403).

### 왜 지금 안 풀었나

코드 문제가 아니라 **"Rule Agent용 서비스 계정을 어떻게 발급하고 권한을
줄지"**를 정하는 운영 결정이라, 팀 논의 없이 임의로 우회하지 않기로 했다.

### 예상 해결 방법 (다음 단계, 難이도 낮음)

기존 JWT 인프라(`/api/auth/token/`, `TokenObtainPairView`)가 이미 있어서
재사용 가능. 아래 3단계면 될 것으로 예상:

1. Django에 서비스 계정(`rule-agent-service`) 생성 + `RULE_VIEW` capability 부여
2. 로그인해서 JWT 토큰 발급
3. `.env`의 `RULE_AGENT_V0_DJANGO_SERVICE_TOKEN`에 채우기
   (`django_client.py`에 이미 `Authorization: Bearer` 전송 로직 준비되어 있음)

---

## 7. 전체 갭 목록 (요약)

상세는 `GAPS.md` 참조. 주요 항목만:

| # | 내용 | 상태 |
|---|---|---|
| G-15 | 그래프 저장용 신규 API 불필요, 기존 API 오케스트레이션으로 대체 | ✅ 해소 (아키텍처 결정) |
| G-16 | Django 인증(RULE_VIEW capability) | 🔲 팀 결정 대기 (본 문서 §6) |
| G-2 | Chroma 청크 메타에 `refs_internal`/`refs_external` 부재 → 2-hop RAG 확장 불가 | 🔲 v1 과제 |
| G-5 | 그래프 단위 생성 메타(모델·질의·출처)를 저장할 필드가 `RuleGraph`에 없음 | 🔲 팀 합의 필요 |
| G-7 | v0가 `mcp/tools.py`를 경유하지 않아 tool call 로깅 미탑승 | 🔲 v1에서 이관 |
| G-8 | `RETURN`을 `OnResult` enum에 정식 추가할지 | 🔲 팀 합의 필요(seed-plan 이전 이슈) |
| G-11 | 룰 콘솔(`ruleConsoleMock.ts`)이 백엔드 graph 스키마와 미연동 | 🔲 재확인 필요(우리가 쓰는 API가 콘솔과 동일하므로 가능성 있음) |

---

## 8. 다음 단계 제안

1. **G-16 인증 해결** — 위 §6 방법으로 진행하면 진짜 DRAFT 그래프가 DB에
   저장되고 룰 콘솔 화면에서 보이는지까지 최종 확인 가능
2. **품질 검토** — 지금까지는 배선 확인이 목적이라 생성된 규칙 내용을
   깊이 검토하지 않았음. 인증 해결 후 실제로 저장된 그래프의 내용
   타당성(회계 담당자 관점) 검토 필요
3. **v1 승격 항목**: `mcp/tools.py` 이관(G-7), 정식 엔드포인트(`/agent/rule/generate`)로
   이동, `RuleGraph.generation_meta` 필드 신설(G-5), 2-hop RAG(G-2)

---

## 9. 팀원별로 지금 해볼 수 있는 것

### (누구나) 다른 scope로 재현·관찰

지금까지 `접대` scope만 테스트했다. 나머지 카테고리(식대/출장/회식) 규정
문서도 이미 Chroma에 적재되어 있으니, 재귀 구조화 스키마(D-16)가 다른
도메인에서도 안정적으로 동작하는지 돌려보는 것만으로 의미 있는 추가 검증이 된다.

```bash
cd apps/ai
export CHROMA_HOST=localhost CHROMA_PORT=8001
export OPENAI_API_KEY=<본인 키 또는 팀 공용 키>
export RULE_AGENT_V0_DJANGO_BASE=http://localhost:8000
uvicorn app.main:app --reload --port 9000
```

```bash
curl -s -X POST localhost:9000/agent/rule-v0/generate \
  -H "Content-Type: application/json" -d '{"scope":"식대","top_k":6}' | jq

curl -s -X POST localhost:9000/agent/rule-v0/generate \
  -H "Content-Type: application/json" -d '{"scope":"출장","top_k":6}' | jq

curl -s -X POST localhost:9000/agent/rule-v0/generate \
  -H "Content-Type: application/json" -d '{"scope":"회식","top_k":6}' | jq
```

### 이지현님 (ML / Rule Agent) — 생성 규칙 내용 품질 검토

지금까지는 "배선이 되는지"만 검증했지 "규칙이 실제로 말이 되는지"는
검토되지 않았다. `curl` 결과의 `accepted`/`rejected_nodes`에 나온 규칙을
실제 규정 원문(`법인카드_사용규정_업무추진비.md` 등)과 대조해서:
- `decision`(REJECT/RETURN/REVIEW)이 규정 취지와 맞는지
- `source_citation`이 실제 그 조문 내용을 정확히 반영하는지(환각 여부)
- 시스템 프롬프트(`agent.py` `_SYSTEM_PROMPT`) 개선 여지

### 정영석님 (PM) — G-16 인증 방식 결정

§6에 정리한 옵션 3가지 중 선택 필요. 코드 문제가 아니라 팀 결정 사항 —
결정만 나면 구현은 반나절 내 완료 가능(기존 JWT 인프라 재사용).

### 김진욱님 (Backend) — 룰 콘솔 화면 연동 확인 (G-11)

우리가 쓰는 API(`POST /api/rules/drafts/` 등)는 **기존 룰 콘솔이 이미
쓰는 API와 동일**하다. G-16만 풀리면 우리가 만든 DRAFT 그래프가 룰 콘솔
화면에 그대로 보일 가능성이 높다 — 실제로 그런지 화면에서 확인 부탁.

### 김정민님 (Frontend) — 현재는 별도 액션 없음

프론트는 기존 룰 콘솔이 쓰는 API를 그대로 재사용하는 구조라(G-11 참고),
이번 작업으로 프론트에 새로 필요해지는 건 없다. G-16 해결 후 실제
데이터가 화면에 정상 노출되는지 정도만 확인하면 된다.

---

## 10. 참고 문서

- `GAPS.md` — 설계 결정(D-1~D-17) 및 갭(G-1~G-18) 전체 상세 목록
- `IMPLEMENTATION_BRIEF.md` — 배선 작업 지시서(완료됨, 인수인계 참고용)
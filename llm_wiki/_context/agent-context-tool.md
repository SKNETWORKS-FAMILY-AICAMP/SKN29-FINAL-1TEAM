# 에이전트 컨텍스트 툴 (Agent Context) — 구현 캐논

> 에이전트 프롬프트에 실을 **도메인 카탈로그**를 live 모델에서 조립해 내려주는 계층.
> 코드: `apps/core/domain/context/` (사실) + `apps/ai/app/context/` (문장)
> 최종 갱신: 2026-08-22 · P0 구현 완료
> (원 구현 2026-08-20 `feature/context-build-tool` → 2026-08-22 `sub-claude`로 이식.
>  브랜치 병합이 아니라 **이 계층에 해당하는 파일만** 옮겼다 — 그 브랜치엔 무관한
>  프론트 UX 커밋이 섞여 있다. 이식 중 드리프트는 한 곳뿐이었다: `mcp_client`가
>  `agents/` 공용 위치로 올라가 import 경로가 `from .. import mcp_client`로 바뀐 것.)

---

## 1. 무엇을 푸는 문제인가

LLM 에이전트가 룰을 쓰거나 내규를 검증하려면 우리 도메인의 어휘를 알아야 한다 — DSL
연산자, EvalContext 허용 경로, 판정 선택지, 플래그 코드, 별표 축. 이 값들은 전부 모델·
enum에 **이미 실재**하는데, 프롬프트에는 일부만, 그것도 에이전트마다 제각각인 사본으로
들어가고 있었다.

구현 전 실측(2026-08-20):

| 증상 | 실제 상태 |
|---|---|
| 카탈로그 사본 | `agent.py`의 `_ALLOWED_OPS`가 `dsl.OPERATORS`와 별개로 존재(값은 같았다 — 그래서 더 위험하다. 갈려도 아무 신호가 없다) |
| 프롬프트가 버전을 직접 적음 | `[허용 경로 목록 — EvalContext v4]` ↔ 코드는 `EVAL_CONTEXT_SCHEMA_VERSION = 5` |
| 영구 캐시 | `_action_schema_cache`가 프로세스 수명 동안 유지 → 런타임에 늘어난 플래그·별표를 재시작 전까지 영영 모름 |
| 조용한 폴백 | 조회 실패 시 옛 하드코딩 값으로 **말없이** 대체 → "왜 이 목록으로 돌았지"를 사후에 못 따짐 |
| 아예 안 실리는 카탈로그 | 플래그 레지스트리(27+7종) · `policy.*` 별표 축과 적재 여부 · 업종/분류/직책 어휘 · decision→상태 매핑 · **필드 타입·설명**(경로 문자열만 던지고 있었다) |

특히 마지막이 컸다. `evidence.expense_purpose_missing`처럼 **극성이 뒤집힌 필드**가
실재하는데, 경로 이름만 주면 모델이 의미를 추측한다.

---

## 2. 설계 원칙 3개

### ① core는 사실, ai는 문장

core가 구조화 JSON을 만들고(`domain/context/sections.py`), ai가 마크다운으로 편다
(`app/context/render.py`). 프롬프트 문구를 고치려고 Django를 재배포해야 하면 아무도
프롬프트를 안 고친다.

**예외 하나** — `notes`(불변식 한 줄)는 core가 소유한다. "엔진은 최종반려를 만들지
않는다" 같은 문장은 표현이 아니라 도메인 규칙이고, ai에 두면 core가 규칙을 바꿔도
프롬프트는 옛말을 계속 한다.

### ② 프롬프트와 검증기는 같은 객체를 본다

`Bundle` 하나에서 프롬프트 블록(`ctx.prompt()`)과 검증 기준(`ctx.paths`·`ctx.operators`)이
같이 나온다. 둘이 갈리면 "모델에게 말한 것"과 "우리가 강제하는 것"이 달라진다 — 이
계층의 존재 이유가 사라진다.

### ③ 실패는 열어두되 반드시 티를 낸다

카탈로그 조회 실패가 룰 생성을 통째로 막으면 안 된다(기존 판단 유지). 대신 `stale=True`를
달고 프롬프트 맨 앞에 **"카탈로그 조회 실패"** 를 적는다. 빈 블록을 조용히 내보내면
모델은 그걸 "제약이 없다"로 읽는다.

> 사본은 **딱 하나** 남겼다: `client._STALE_ACTION_SCHEMA`. OpenAI structured output의
> `enum`은 빈 배열일 수 없어서(스키마 자체가 거부된다) decision/severity만은 로컬 기본값이
> 필요하다. 경로·플래그는 비어도 프롬프트가 "조회 실패"로 안내하면 되므로 사본을 안 둔다.

---

## 3. 구조

```
core  domain/context/
        sections.py   섹션 빌더 5종 + etag
        profiles.py   에이전트별 섹션 묶음
        views.py      GET /api/internal/agent-context/
      domain/policies/eval_context.py
        FieldSpec(type, desc, enum) · schema_catalog()   ← 설명을 코드로 승격

ai    app/context/
        client.py     조회 + TTL 캐시(180s) + Bundle
        render.py     섹션 → 마크다운
```

### 섹션 (P0 = 5개)

| id | 소스 | 무엇을 막나 |
|---|---|---|
| `dsl.grammar` | `dsl.OPERATORS`·`MAX_DEPTH` | 없는 연산자·산술 시도. **null 비교 함정**(`!=`는 모를 때 참) 명시 |
| `eval_context.paths` | `eval_context.schema_catalog()` | 없는 경로. 타입·설명·어휘 링크로 극성·단위 추측 방지 |
| `policy.vars` | `RESOLVERS` + `PolicyTable` | 한도를 숫자 리터럴로 박는 것. **`loaded=false`면 경고** — 미적재 임계값을 참조한 룰은 전건 REVIEW가 된다 |
| `action.schema` | `engine.py` + `JUDGE_MAP` | 없는 판정값. "엔진은 최종반려를 만들지 않는다" 불변식 전달 |
| `flags.registry` | `RuleFlag`(없으면 `RULE_FLAGS`) | 사유 코드를 매번 새로 지어내는 것 |

### 프로파일

- `rule_generate` — 규정 문서 → 룰 그래프 DRAFT (`rule_agent_v0/agent.py`)
- `rule_chat` — 룰 콘솔 대화형 수정 (`rule_agent_v0/chat.py`)

같은 어휘를 써야 방금 만든 그래프를 고치면서 없는 경로·플래그를 끌어오지 않는다.

### 재현성

응답의 `etag`(전 섹션 내용 해시 12자)를 `RuleGraph.generation_meta.catalog_etag`에 남긴다.
플래그가 27종이던 시절의 생성물을 지금 목록으로 설명하면 어긋난다.

### API

```
GET /api/internal/agent-context/?profile=rule_generate
GET /api/internal/agent-context/?sections=flags.registry,dsl.grammar
```
AllowAny · 다른 내부 read API와 같은 패턴. `sections`가 `profile`보다 우선(더 좁은 요청).

---

## 4. 결정 기록

**D-1. 필드 설명을 문서가 아니라 코드에 둔다.** `_SCHEMA_FIELDS`를 `dict[str, dict[str,
FieldSpec]]`로 승격했다(`type`·`desc`·`enum`). 문서는 갱신을 잊어도 조용하지만, 코드에
있으면 프롬프트가 곧바로 틀려서 눈에 띈다. `EVAL_CONTEXT_SCHEMA_PATHS`·
`empty_eval_context()` 계약은 그대로(47경로·16섹션).

**D-2. `enum` 필드는 어휘 섹션을 가리킨다.** `merchant.merchant_type`·`category.value`·
`user.job_title` 등. `in [...]` 우변을 모델이 지어내면 **에러가 아니라 조용한 미발동**이
된다(업종 어휘 통일 때 실제로 겪은 실패 양상). P0에서는 링크 표시까지, 어휘 목록 자체를
싣는 `vocab.*` 섹션은 P1.

**D-3. 렌더링은 ai.** §2-①.

**D-4. 죽은 경로를 남기지 않는다.** `/api/internal/rule-agent-v0/eval-context-schema/`·
`.../action-schema/`와 ai쪽 `django_client.get_*_schema()`는 새 엔드포인트의 부분집합이
되므로 **제거**했다. 같은 값을 주는 창구가 둘이면 하나는 반드시 뒤처진다. 룰 콘솔 화면용
`/api/rules/action-schema/`(인가 필요)는 유지 — 브라우저는 AllowAny 내부 API를 못 쓴다.

**D-5. TTL 180초, 실패는 캐시하지 않는다.** core가 잠깐 안 떠 있었다고 TTL 동안 stale에
갇히면 그 사이 생성된 룰이 전부 무제약 프롬프트로 만들어진다.

**D-6. 모르는 섹션도 버리지 않는다.** core가 먼저 늘어난 배포 상태에서 ai 렌더러가
모르는 섹션이 오면 JSON 원문 그대로 싣는다. 조용히 떨구면 core를 배포한 사람은 카탈로그가
반영됐다고 믿는다.

---

## 5. 회귀

| 위치 | 건수 | 고정하는 계약 |
|---|---|---|
| `apps/core/domain/context/tests/test_sections.py` | 13 | 카탈로그가 실제 소스와 **같은 객체**를 본다 — 연산자=`dsl.OPERATORS`, 경로=`EVAL_CONTEXT_SCHEMA_PATHS`, `policy.*`=`RESOLVERS`, 판정=`engine.py`. 모든 필드에 타입·설명 존재. REJECT가 REJECT 상태로 가지 않음. etag 결정성 |
| `apps/ai/tests/test_agent_context.py` | 10 | 프롬프트에 타입·설명·어휘·미적재 경고가 실린다 · 실패가 프롬프트에 적힌다 · 실패를 캐시하지 않는다 · 모르는 섹션 보존 |

값 자체는 단언하지 않는다 — 그러면 테스트가 또 하나의 사본이 된다.

원 구현 시 실측: core 226건 통과(기존 213 + 13), ai 330건 통과(기존 320 + 10).
`tests/rag/test_ingest_pipeline.py`·`test_docling_smoke.py` 10건 실패는 이 작업과 무관한
컨테이너 환경 문제(`libxcb.so.1` 부재).

이식 후 재실측(2026-08-22, `sub-claude`): **core 345건 전부 통과**(신규 13 포함).
ai 10건은 도커 미기동으로 **실행하지 못했다** — 대신 의존성 스텁 스모크로 같은 계약
18건(경로·연산자가 카탈로그에서 나온다 / 프롬프트에 타입·설명·어휘·미적재 경고가 실린다 /
실패가 프롬프트에 적힌다 / 실패를 캐시하지 않는다 / 모르는 섹션 보존)을 확인했다.
빈 DB 기준 `rule_generate` 렌더 실측은 **9,283자**(원 구현 9,246자와의 차이는 별표
적재 상태 — 갓 설치한 회사 상태라 전부 `미적재` 경고가 붙는다).

---

## 6. 카탈로그가 곧바로 드러낸 결함 (미해결 · 이 작업 범위 밖)

렌더 결과를 실 DB로 처음 찍자마자 나왔다. "무엇을 아는가"를 사람이 읽을 수 있게 만들면
**모르는 걸 안다고 우기던 자리**가 보인다.

1. **`user.position` 축의 별표 3종이 조용히 와일드카드로 떨어진다.**
   로컬 DB의 `pre_approval_threshold_table`·`daily_limit_table`·`monthly_limit_table`이
   `key_axes: ["user.position"]`인데, `user.position`은 EvalContext v5에서 `user.job_title`로
   교체돼 스키마에 없다. `strict_keys=False`라 `lookup()`이 `"*"` 기본값으로 폴백 →
   **직책과 무관하게 회사 기본 한도가 적용**된다(에러도 플래그도 없다).
   코드(`tiger_tables.py`)는 이미 `user.job_title`이므로 **재시드로 해소**된다.
   `seed_org_codes.check_table_keys()`가 잡도록 만들어진 바로 그 종류의 결함이다.

2. ~~**`dining_per_person_limit_table`의 축 `category.scope`가 스키마에 없다**~~ —
   **해소 (2026-08-22)**. payload에 실제로 있는 값이 단일 한도 하나뿐이라 **축을 뗐다**
   (선언을 가진 데이터에 맞춘다). 규정 원문 제14조①에 조직단위별 값이 실재한다면 그때
   `dining.org_unit` 사실을 만들고 축을 되살린다 — 값이 생긴 다음에 축을 만드는 순서다.

→ ~~제안: 축 회귀 1건~~ **적용 (2026-08-22)**: 정적 회귀(`tiger_tables.TABLES`)와 **DB 행을
보는** `check_table_axes()` 둘 다 넣었다(`policy-domain.md` §3.2). 코드만 검사하면 1번 같은
시드 드리프트를 못 잡아서다. `seed`가 별표 적재 직후 호출해 경고한다.

---

## 7. 남은 단계

**P1**
- ~~`policy.*` 동적화~~ **완료 (2026-08-22)** — 적재된 별표에서 파생. 고객이 올린 새 별표가
  코드 변경 없이 변수·프롬프트·검증·조립에 전부 반영된다(`policy-domain.md` §3.1). 이
  카탈로그의 `policy.vars`·`eval_context.paths` 두 섹션이 함께 따라온다
- `vocab.*` 3종(`industry`·`category`+scope 별칭·`org` 직책 rank) + `vocab.card_type`·
  `vocab.item_type` — D-2의 링크가 가리킬 실체
- `graph.current` — 해당 scope의 기존 ACTIVE/DRAFT 노드 요약(중복 생성 방지)
- `risk_stage2` 프로파일 — **Risk Review 2차에 플래그가 통째로 안 들어가고 있다**
  (`flags.py` docstring은 그걸 용도로 적어놨다)
- MCP tool `get_agent_context(profile, sections)` — 툴콜링 중 자가 조회.
  단발 프롬프트 경로(draft/risk)는 툴이 아니라 **서버가 항상 주입**한다(모델이 안 부르면
  없는 것과 같다)
- AI-LAB "컨텍스트" 탭 — 섹션별 렌더 결과·etag·토큰 수. AI-LAB의 "결과 대신 근거" 원칙과
  같은 자리

**P2**
- `policy.table` 온디맨드(별표 payload 원본)
- `evidence_extract` 프로파일 — 추출 허용 dot-path 화이트리스트
- 프로파일별 토큰 상한 회귀 (현재 `rule_generate` 렌더 결과 실측 **9,246자**)

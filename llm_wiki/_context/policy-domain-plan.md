# PLAN — 규정 임계값(policy) 도메인 구현 계획

> 설계 캐논은 `_context/policy-domain.md`. 이 문서는 **구현 순서·영향 범위·검증·롤백**만 다룬다.
> 착수 전 승인용. 각 단계는 독립 배포 가능하고, 앞 단계 없이 뒤 단계를 하면 안 된다.
>
> 작성: 2026-08-10 · **STEP 1~5 구현 완료 (2026-08-11)** — 인수 조건 5개 전부 실측 통과(§2).
> 잔여: `merchant.*`(MCP)·`history.*`(SoR 집계) 조립, 별표 원문 대조, 앱 리네임(비목표).

---

## 0. 목표 / 비목표

**목표**
1. 룰 엔진이 실제 정산 데이터로 한도 판정을 수행할 수 있게 한다(현재 전 한도 룰 미발동).
2. 규정 임계값의 SoT를 하나로 만든다(현재 4곳 분산, 값 불일치).
3. 규정 개정·별표 구조 변경이 **코드 변경 없이** 흡수되게 한다.

**비목표 (이번에 하지 않음)**
- `domain/policies` → `domain/rules` 앱 리네임 (임포트 파급 큼, 별도 과제)
- Chroma 임베딩·upsert 실구현 (PDF 파싱 후속, 별도 과제)
- 지도학습·자동 재학습 (post-MVP 확정 사항)
- 규정 원문 자동 파싱으로 별표 JSON 생성 (STEP 3에서 **수동 적재**, 자동화는 후속)

---

## 1. 현재 상태 스냅샷 (착수 기준선)

| 항목 | 상태 |
|---|---|
| `Policy` 모델 | 존재. 참조 0(admin 등록 1줄). 테이블 항상 비어 있음 |
| `ctx.policy.*` | 스키마 8필드 존재. **조립기 부재로 전량 `None`** |
| `build_rule_context` | **미구현** (`rule-seed-plan.md` §87에 기인지됨) |
| 한도 룰 동작 | 검증셋(TEST)·시연 3건만 동작(facts 수동 주입). **실 정산(HISTORY) 경로는 전량 미발동** |
| 임계값 위치 | `draft_agent.THRESHOLDS` / `seed.py` ctx / DSL 리터럴 / 문서 — 4곳, 값 불일치(30만 vs 50만) |
| `EVAL_CONTEXT_SCHEMA_VERSION` | `1` |

---

## STEP 1 — 미해소 가드 (가장 먼저)

**왜 먼저인가**: 나머지 단계 없이 단독으로 배포 가능하고, 배포 즉시 **"조용한 False"가 눈에 보인다.**
지금 무엇이 얼마나 죽어 있는지 계측 없이 큰 리팩터를 시작하면 개선폭을 증명할 수 없다.

| 항목 | 내용 |
|---|---|
| 변경 | `engine.run_rule_engine`에 미해소 검사 추가. `참조 policy.* − 채워진 policy.*`가 비지 않으면 결과를 `REVIEW`로 강등하고 `flags`에 `UNRESOLVED_POLICY_VAR:<field>` 추가 |
| 파일 | `apps/core/domain/policies/engine.py`, `simulation.py`(결과 행에 플래그 노출), `web` 검토/시뮬 화면 플래그 렌더 |
| 검증 | 신규 테스트: `policy.*` 미주입 컨텍스트로 기업업무추진비 v2 실행 → `decision == "REVIEW"` & 플래그 존재. 기존 `tests/test_engine.py`·`test_global_seed.py` 회귀 통과 |
| 리스크 | 시뮬레이션 HISTORY 결과가 대량 `REVIEW`로 바뀐다 → **이것이 정확한 현실이다.** 시연 자료를 쓴다면 사전 공지 필요 |
| 롤백 | 플래그 부여만 남기고 강등을 끄는 스위치(설정 상수) 1줄 |

---

## STEP 2 — EvalContext 카탈로그 재정의 (스키마 변경)

**반드시 STEP 3(데이터 적재)보다 먼저.** 저장된 스냅샷이 늘어난 뒤에 리네임하면 비용이 급증한다.

| 항목 | 내용 |
|---|---|
| 변경 A | `policy.gift_type` **제거** → 룩업 키는 `category.item_type` 사용 |
| 변경 B | 신규 6필드 추가: `evidence_threshold`·`dining_per_person_limit`·`settlement_deadline_days`·`history_window_months`·`night_meal_limit`·`business_class_min_hours` |
| 변경 C | 상수 박힌 필드명 정리: `derived.biz_days_over_7` 삭제 / `history.*_3m` → 접미사 제거 |
| 변경 D | `EVAL_CONTEXT_SCHEMA_VERSION` `1` → `2`, `BUILDER_VERSION` 갱신 |
| 파일 | `eval_context.py`, `seed_rules.py`(해당 경로 쓰는 노드 조건), `seed.py`(시연 스냅샷), `web/.../simulationTypes.ts`(변수 라벨 목록) |
| 데이터 영향 | ⚠️ **기존 `rule_hits.eval_context` 스냅샷은 v1 스키마**다. 마이그레이션하지 않고 `eval_context_schema_version`으로 구분해 읽는다(스냅샷은 불변 감사 기록이므로 소급 수정 금지) |
| 검증 | `seed_rules`의 `validate_graph_vars` 게이트가 전 그래프 통과(미정의 경로 0). `npm run build`(라벨 목록 타입). Django `check` |
| 롤백 | 스키마 버전을 되돌리고 카탈로그 복원. 신규 필드는 미사용이므로 무해 |

---

## STEP 3 — `PolicyTable` 신설 + 별표 적재

| 항목 | 내용 |
|---|---|
| 변경 A | `PolicyTable` 모델 신설(`key`·`title`·`key_axes`·`payload`·`source_doc`·`source_clause`·`effective_date`·`superseded_date`) + 마이그레이션 |
| 변경 B | `Policy` 모델 **폐기** (참조 0이므로 제거 마이그레이션만) |
| 변경 C | 시드: 별표 5종(`pre_approval_threshold`·`daily_limit`·`monthly_limit`·`kickback_limit`·`lodging_limit`) + 신규 임계값 6종을 `PolicyTable` 행으로 적재. 값 출처는 `TIGER-REG-2026-003` 별표 |
| 변경 D | Django admin에 `PolicyTable` 등록(회계 담당자가 값 확인·개정 가능하게) |
| 파일 | `policies/models.py`, `policies/migrations/00xx_*`, `policies/admin.py`, `common/management/commands/seed_policy_tables.py`(신규) |
| 주의 | 개정은 **UPDATE 아닌 INSERT**(신규 `effective_date` 행 + 구행 `superseded_date`). 시드도 이 규약을 따른다 |
| 검증 | `makemigrations --check` 통과. 시드 후 별표 5종 + 임계값 6종 조회 스모크 |
| 롤백 | 마이그레이션 역방향. `Policy` 폐기는 참조 0이라 안전 |

---

## STEP 4 — `build_rule_context` 조립기 구현 (핵심)

| 항목 | 내용 |
|---|---|
| 변경 A | `policies/context_builder.py` 신설. **이 모듈만 ORM/외부 조회를 한다**(FR-RA-08 계약) |
| 변경 B | `RESOLVERS` 상수 + 해소 루프: 표 로드(지출일 기준 유효 행) → `key_axes` 경로로 키 추출 → `payload` 중첩 룩업 → `ctx.policy.<field>` 스칼라 주입 → `ctx.tables.<key>`에 payload 원본 보존 |
| 변경 C | `simulation.case_from_settlement`가 조립기를 경유하도록 전환(현재 4필드만 채우는 얕은 플레이스홀더) |
| 변경 D | MCP 툴 `build_rule_context(tx_id)` 실구현 연결(현재 명세만 존재) |
| 파일 | `policies/context_builder.py`(신규), `policies/simulation.py`, `apps/ai/app/mcp/tools.py` |
| 검증 | ① 조립기 단위 테스트: 2키 별표(`lodging_limit`) 룩업 정확성, 유효일 경계, 키 결측 시 `None` ② 실 정산 1건으로 STEP 1 플래그가 **사라지는지**(가드 해제가 곧 성공 판정) ③ `tables` 스냅샷이 `rule_hits`에 보존되는지 |
| 리스크 | 조립기가 N+1 쿼리를 만들기 쉽다 → 별표는 요청당 1회 로드 후 메모리 룩업 |
| 롤백 | 조립기 호출 지점을 기존 얕은 조립으로 되돌림. STEP 1 가드가 다시 잡아준다 |

---

## STEP 5 — 하드코딩 임계값 제거 (SoT 일원화)

| 항목 | 내용 |
|---|---|
| 변경 A | `draft_agent.THRESHOLDS` 삭제 → `PolicyTable` 조회로 전환. `policyHints` 문구는 유지 |
| 변경 B | 시드 그래프의 DSL 리터럴(3만·5만·7일·6시간)을 `policy.*` 참조로 교체 |
| 변경 C | `rule-engine.md` 예시의 `preapproval_threshold: 300000` 등 문서 값을 별표 기준으로 정정 |
| 파일 | `settlements/draft_agent.py`, `common/management/commands/seed_rules.py`, `llm_wiki/_context/rule-engine.md` |
| 검증 | 별표 값 1개를 바꾼 뒤 **재시드·재배포 없이** 판정과 `policyHints`가 함께 따라오는지 — 이게 이 작업 전체의 인수 조건이다 |
| 롤백 | 상수 복원(단순) |

---

## 2. 인수 조건 (Definition of Done) — ✅ 전부 실측 통과 (2026-08-11)

| # | 조건 | 실측 결과 |
|---|---|---|
| 1 | 별표 값만 바꾸면 코드·재시드 없이 판정·안내가 따라온다 | ✅ `evidence_threshold` 3만→5만 변경 시 4만원 건의 증빙 안내가 즉시 사라짐 |
| 2 | 축 2개→3개 확장이 마이그레이션 0 | ✅ `test_axis_can_grow_without_code_change` |
| 3 | 실 정산 시뮬레이션에서 `UNRESOLVED_POLICY_VAR` 0건 | ✅ ACTIVE 3그래프 × 판정 120행 → **0건** |
| 4 | `validate_graph_vars` 미정의 경로 0 | ✅ `seed_rules` 전 그래프 시드 성공(게이트 통과) |
| 5 | 임계값 상수가 `draft_agent`·시드 DSL에 없음 | ✅ `THRESHOLDS` 제거, DSL 리터럴 4곳 → `policy.*` 참조 |

> 잔여 리터럴 1건: 회식 v2 초안 `M-005`의 "주류 포함 1인당 30,000" — 별표가 아니라 AI가 제안한
> 탐지 임계값이라 카탈로그로 올리지 않았다. 별표 근거가 생기면 승격 대상.

### (원문) 인수 조건

1. `PolicyTable`의 숙박 한도 행을 120,000 → 150,000으로 바꾸면, **코드 변경·재시드 없이** 룰 판정과
   제출 전 안내(`policyHints`)가 동시에 새 값으로 동작한다.
2. 별표에 축을 하나 추가(2키 → 3키)해도 **마이그레이션 0**으로 흡수된다.
3. 실 정산 데이터로 돌린 시뮬레이션에서 `UNRESOLVED_POLICY_VAR` 플래그가 0건이다.
4. `validate_graph_vars`가 전 ACTIVE 그래프에 대해 미정의 경로 0을 보고한다.
5. 임계값 문자열 상수가 `draft_agent`·시드 DSL에 남아 있지 않다.

---

## 3. 검증 루틴 (CLAUDE.local.md 정책 준수)

각 STEP 종료 시 아래까지만 자동 수행하고, 런타임 동작 확인은 사용자가 한다.

```bash
# 백엔드
PYTHONPATH=apps/core DJANGO_SETTINGS_MODULE=config.settings .venv/Scripts/python -m django makemigrations --check
PYTHONPATH=apps/core DJANGO_SETTINGS_MODULE=config.settings .venv/Scripts/python -m django check
# 프론트 (STEP 1·2에서 화면 변경 있을 때)
npm run build --prefix "C:/jw/00_skn_final/apps/web"
```

---

## 4. 리스크 등록부

| # | 리스크 | 영향 | 완화 |
|---|---|---|---|
| R1 | STEP 1 배포 직후 시뮬레이션 결과가 대량 `REVIEW`로 전환 | 시연 자료 인상 저하 | 정확한 현실 반영임을 사전 공지. 강등 스위치로 시연 중 임시 완화 가능 |
| R2 | STEP 2 리네임이 기존 `rule_hits` 스냅샷과 불일치 | 과거 감사 기록 해석 혼선 | 스냅샷 소급 수정 **금지**. `eval_context_schema_version`으로 분기 렌더 |
| R3 | 별표 값 오적재(자릿수·축 순서) | 잘못된 판정이 조용히 통과 | STEP 3 시드에 `source_clause` 필수 + admin 노출로 사람 검수. 축 순서는 `key_axes`와 payload 깊이 일치 검증 |
| R4 | 조립기 N+1 쿼리 | 배치 시뮬레이션 지연 | 요청당 별표 1회 로드 후 메모리 룩업 |
| R5 | STEP 4 범위 확대(전 필드 조립 욕심) | 일정 지연 | 이번 범위는 **`policy.*` + `tables.*`만**. `merchant.*`(MCP)·`history.*`(집계)는 별도 단계 |

---

## 5. 착수 순서 요약

```
STEP 1 가드      → 현실 계측 (단독 배포 가능, 가장 값쌈)
STEP 2 카탈로그  → 스키마 확정 (데이터 늘기 전에)
STEP 3 저장층    → 별표 적재
STEP 4 조립기    → 실제 연결 (STEP 1 플래그가 사라지면 성공)
STEP 5 정리      → SoT 일원화
```

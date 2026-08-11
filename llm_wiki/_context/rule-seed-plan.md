# Rule 시드 데이터 생성 계획 (RULE 명세서 → RuleGraph 시드)

> **파생 컨텍스트(구현 추적).** `법인카드_사용규정_기반_RULE_명세서.md`의 RULE을 백엔드 `policies` 도메인 시드로 옮기는 계획이다.
> 2026-07-31 현재 1차 범위는 명세 §8의 **GLOBAL 선행 게이트 R-002·R-003만 구현**했으며 나머지 카테고리 RULE은 미구현이다.
> SoT: 룰 스펙 = 명세서 / 도메인 모델 = `apps/core/domain/policies/models.py`.
> 최종 갱신: 2026-07-30.

---

## 1. 목적 · 범위

- **현재 목표**: 명세서의 GLOBAL 선행 게이트 R-002·R-003을 실제 JSON DSL과 결정론적 라우팅으로 시드한다. 나머지 56개 RULE은 후속 범위다.
- **비목표(중요)**: 룰 **실제 판정(매칭·순회)** 은 이번 범위 밖. 아래 §2의 "엔진 부재"를 전제로, 시드는 화면/버전/시뮬 데이터로만 유효하다.

## 2. 소스 · 타깃 · 전제

### 2.1 소스
- `llm_wiki/법인카드_사용규정_기반_RULE_명세서.md` (v1.4). 각 RULE = `ID · 제목 · 조건(자연어) · 조건(룰 엔진 표현식) · 액션·심각도 · 권장처리·확인주체 · 출처조항`.
- 공통 필드 정의서(§2)·조회테이블(§2-1)·심각도 매핑(§3)·상호작용/우선순위(§8)이 매핑 규칙의 근거.

### 2.2 타깃 모델 (`apps/core/domain/policies/models.py` — 전부 실제 스키마, 스텁 아님)
- **`RuleGraph`**: 한 행이 한 버전. `family_key · name · scope · status · version · entry_node_key ...`; `(family_key, version)` 유일, scope당 ACTIVE 하나.
- **`RuleNode`**: `graph FK · node_key · condition(JSON) · condition_text(TEXT) · action(JSON) · priority`. `unique(graph, node_key)`, `ordering=priority`.
  `condition_text` = **"이 Rule이 하는 일" 쉽게보기 문장**. Rule Agent가 조건·액션을 만들 때 함께 생성해 저장하며,
  화면은 DSL을 파싱하지 않고 이 값을 그대로 노출한다(비면 프론트 `describeDsl` 기계 번역으로 폴백).
  형식은 `언제 걸리나요? / 걸리면 어떻게 되나요?` 두 덩어리 — 시드는 `seed_rules.plain_text(when, then)`으로 만든다.
- **`RuleRouting`**: `graph FK · from_node_key · on_result(MATCH/NO_MATCH/PASS/REJECT/REVIEW) · to_node_key(공백=종단) · priority`. **노드→노드 FK가 아니라 key 문자열 평면 저장**.
- **`RuleGraphVersion`**: `graph FK · version · snapshot(JSON) · approved_at · is_active`. `unique(graph, version)`.
- **`RuleHit`**: 평가 로그(`path · decision · confidence`) — 시드 대상 아님(런타임 산출물).
- 참고: 프로젝트 문서는 `rules`/`rule_routings`로 부르지만 실제 클래스는 `RuleNode`/`RuleRouting`. DRF 직렬화는 camelCase(`nodeKey/onResult/...`).

### 2.3 구현 전제
- `dsl.py`와 `engine.py`가 구현되어 조건은 EvalContext dot-path를 참조하는 JSON-Logic 부분집합으로 저장한다.
- ACTIVE 전환과 시드는 DSL·그래프 구조·EvalContext 참조 경로를 정적으로 검증한다.
- ✅ **`build_rule_context` 조립 구현 완료**(2026-08-11, `policies/context_builder.py`). 남은 후속 범위는 `orchestrator.py`(GLOBAL→scope 선택·`RuleHit` 기록)다.

## 3. 매핑 설계

### 3.1 RULE → RuleNode 필드 매핑
| 명세서 항목 | RuleNode 필드 | 규칙 |
|---|---|---|
| `ID`(R-xxx) | `node_key` | 그대로 (`"R-106"`) |
| 조건(룰 엔진 표현식) | `condition` | `{"expr": "<원문>", "fields": [파싱된 참조필드], "source_clause": "<출처조항>"}` — expr 원문 보존 |
| 액션·심각도 | `action` | `{"decision": <§3.2>, "severity": <CRITICAL/HIGH/MEDIUM/LOW/INFO>, "flag": "<FLAG>", "title": "<제목>"}` |
| 권장처리·확인주체 | `action.decision` + `action.approver` | §3.2 매핑 + 확인주체 문자열 |
| 심각도 | `action.severity` + `priority` | CRITICAL=0 … INFO=4 (오름차순 정렬용) |
| 조건(자연어) + 권장처리 | `condition_text` | 비개발자용 쉽게보기 문장. `plain_text(when, then)` — 전문용어·DSL 경로·영문 판정코드 금지 |

### 3.2 권장처리 → `decision` 매핑 (명세 §3 기준, 룰별 override 허용)
- 자동 반려 후보 / 반려 권고 → **`REJECT`**
- 보완요청 / 승인확인 보류 / 소명 요청 → **`RETURN`**
- 승인 대기 확인(LOW) → **`REVIEW`**
- 리스크 등급 반영 / 감사실 사후검증(INFO) → **`REVIEW`** + `action.monitoring=true` (개별 건 판정 미영향 표식)
- ⇒ `OnResult`/`decision`에 **`RETURN` 값이 추가로 필요**(현재 seed는 REVIEW/REJECT/RETURN 혼용 사용 중이므로 JSONField라 스키마 변경 불필요, 다만 팀 합의 필요 — §6).

### 3.3 scope / 그래프 분할 (핵심 결정)
명세 §8 실행 모델(= CLAUDE.md 룰엔진 3단): **GLOBAL 게이트 최우선 → 카테고리 scope 선택 → 결정론적 순회**. 이를 그래프 단위로 반영:

| 그래프 | scope | 포함 RULE | status |
|---|---|---|---|
| 금지·현금성 GLOBAL 게이트 | `GLOBAL` | R-002, R-003 (CRITICAL, 카테고리 이전 평가) | **ACTIVE 구현 완료** |
| 카테고리 그래프(후속) | `접대` | R-1xx + 적용할 공통 RULE | 미시드 |
| 카테고리 그래프(후속) | `식대` | R-2xx + 적용할 공통 RULE | 미시드 |
| 카테고리 그래프(후속) | `출장` | R-3xx + 적용할 공통 RULE | 미시드 |

- scope는 `GLOBAL` 또는 `settlements.Category` 실제 값만 허용한다. `COMMON`·`기업업무추진비`·`회식` 같은 별칭은 저장하지 않는다.
- GLOBAL v1은 R-002/R-003의 `NO_MATCH`를 다음 노드로 연결하고 둘 다 불일치하면 내부 `_GLOBAL_PASS`에서 종료한다. 카테고리 노드 배치는 후속 설계에서 확정한다.
- **배타 그룹(§8)**: 금액구간 룰(R-102~105·R-201·R-312·R-313)은 상호배타 → `graph.sim_result`나 노드 `action.exclusive_group`에 메타로 기록(엔진 겹침검사용). 우선순위(R-105>R-102, R-313>R-312>R-301)도 `action.precedence` 메타로만.

### 3.4 참조 테이블(§2-1) 처리
`daily_limit_table` / `kickback_limit_table` / `lodging_limit_table` / `pre_approval_threshold_table` 는 별표 조회값. DSL은 동적 테이블 조회를 하지 않고, **`build_rule_context`가 `policy.*` 스칼라로 선해소한다(구현 완료)**. 별표 저장은 `PolicyTable` 모델 → `_context/policy-domain.md`.

## 4. 시드 산출물 형태 (1차 구현)
- 위치: `domain/common/management/commands/seed_rules.py`; 일반 `seed`에서도 호출한다.
- `GLOBAL` ACTIVE 그래프 v1 하나: R-002 →(NO_MATCH) R-003 →(NO_MATCH) 내부 `_GLOBAL_PASS` 종단.
- 고정 `family_key`와 `update_or_create`를 사용해 멱등 실행한다. 기존 다른 GLOBAL ACTIVE는 ARCHIVED 처리한다.
- `RuleGraphVersion`에 승인 스냅샷을 함께 저장한다.

## 5. 단계별 작업
1. ✅ GLOBAL R-002·R-003 실제 DSL 시드 + 정적 검증 + 멱등 커맨드.
2. **후속:** 나머지 56행 파싱표 작성 (`id, graph_scope, condition_expr, decision, severity, flag, exclusive_group, precedence, source_clause`).
3. **decision/severity 매핑 확정**(§3.2) + `RETURN`/`severity` enum 팀 합의(§6).
4. **카테고리 그래프 분할 확정**(§3.3) — 플랫 vs 부분 트리.
5. **후속 시드 및 실제 context 조립 후 통합 검증**.

## 6. 오픈 이슈 · 리스크
- ~~**조립기 미구현**~~ → ✅ **해소(2026-08-11)**: `context_builder.build_rule_context`가 정산·거래·첨부·별표를 조립한다. 시뮬레이션의 실 내역 경로도 같은 조립기를 탄다. 남은 결손은 **판정 사실의 원천**(참석 인원·2차 여부·청탁 대상 등)이며 등급표는 `_context/eval-context-sourcing.md`.
- **decision enum 확장**: `RETURN`·`severity`·`flag`·`monitoring`을 `action` JSON에 넣을지, `OnResult`에 `RETURN`을 정식 추가할지 합의 필요.
- **GLOBAL→카테고리 선택**: GLOBAL 그래프 자체 순회는 구현됐으나 두 그래프를 순서대로 선택하는 orchestrator는 후속이다.
- **프론트 정합**: `ruleConsoleMock.ts`는 flat UI 셰이프라 백엔드 graph 스키마와 미연동. 시드가 API로 노출돼도 FE가 소비하려면 rule-console 화면의 실연동 작업이 선행/병행돼야 함.
- **나머지 표현식 변환**: 명세의 `table[key]`·서수비교는 EvalContext 선해소 필드로 변환해야 한다. 단 **RULE 명세서 58종은 «참고용 예시»로 확정**됐고(제품 기본 제공은 `DEFAULT GATE` 1개, 세부 룰은 문서 업로드 시 생성) 전량 시드가 목표가 아니다. EvalContext도 v4(46필드)로 축소돼 명세서 필드와 의도된 간극이 있다.

## 7. 부록 — 매핑 참조
- 심각도→기본 권장처리(§3): CRITICAL=자동반려후보 · HIGH=반려권고/에스컬레이션 · MEDIUM=보완요청/승인보류 · LOW=승인대기확인 · INFO=모니터링(개별건 무영향).
- flag 예시: `PROHIBITED_MERCHANT` · `PROHIBITED_PAYMENT_METHOD` · `NON_DEDUCTIBLE_RISK` · `PRE_APPROVAL_REQUIRED` · `KICKBACK_LAW_LIMIT_EXCEEDED` · `RECORD_INCOMPLETE` · `HIGH_RISK_USER` · `SELF_APPROVAL_CONFLICT` · `FINANCE_DEPT_SELF_AUDIT_REQUIRED`.
- 관련 캐논: `_context/rule-engine.md`(있으면), `기술명세서.md §3.1·§4.2`, `요구사항_명세서.md FR-RB/FR-RV/FR-RA`.

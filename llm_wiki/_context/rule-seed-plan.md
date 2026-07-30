# Rule 시드 데이터 생성 계획 (RULE 명세서 → RuleGraph 시드)

> **파생 컨텍스트(계획).** `법인카드_사용규정_기반_RULE_명세서.md`(활성 58 RULE)를 백엔드 `policies` 도메인의
> 룰 그래프 시드로 넣기 위한 **설계·작업 계획**이다. **이 문서는 구현이 아니다** — 실제 seed 코드는 아직 없다.
> SoT: 룰 스펙 = 명세서 / 도메인 모델 = `apps/core/domain/policies/models.py`.
> 최종 갱신: 2026-07-30.

---

## 1. 목적 · 범위

- **목표**: 명세서의 활성 58개 RULE(공통 14 `R-001~014` · 업무추진비 14 `R-101~114` · 회식 16 `R-201~216` · 출장 14 `R-301~314`)을 Rule 콘솔(초안/시뮬/Active)·검토 워크스페이스에서 **표시·시뮬레이션·버전관리 UI로 검증**할 수 있는 시드 데이터로 구조화한다.
- **비목표(중요)**: 룰 **실제 판정(매칭·순회)** 은 이번 범위 밖. 아래 §2의 "엔진 부재"를 전제로, 시드는 화면/버전/시뮬 데이터로만 유효하다.

## 2. 소스 · 타깃 · 전제

### 2.1 소스
- `llm_wiki/법인카드_사용규정_기반_RULE_명세서.md` (v1.4). 각 RULE = `ID · 제목 · 조건(자연어) · 조건(룰 엔진 표현식) · 액션·심각도 · 권장처리·확인주체 · 출처조항`.
- 공통 필드 정의서(§2)·조회테이블(§2-1)·심각도 매핑(§3)·상호작용/우선순위(§8)이 매핑 규칙의 근거.

### 2.2 타깃 모델 (`apps/core/domain/policies/models.py` — 전부 실제 스키마, 스텁 아님)
- **`RuleGraph`**: `name · scope(기본 "GLOBAL") · status(DRAFT/SIMULATED/ACTIVE/ARCHIVED) · version · entry_node_key · sim_result(JSON) · source_clause · approved_by · activated_at`.
- **`RuleNode`**: `graph FK · node_key · condition(JSON) · action(JSON) · priority`. `unique(graph, node_key)`, `ordering=priority`.
- **`RuleRouting`**: `graph FK · from_node_key · on_result(MATCH/NO_MATCH/PASS/REJECT/REVIEW) · to_node_key(공백=종단) · priority`. **노드→노드 FK가 아니라 key 문자열 평면 저장**.
- **`RuleGraphVersion`**: `graph FK · version · snapshot(JSON) · approved_at · is_active`. `unique(graph, version)`.
- **`RuleHit`**: 평가 로그(`path · decision · confidence`) — 시드 대상 아님(런타임 산출물).
- 참고: 프로젝트 문서는 `rules`/`rule_routings`로 부르지만 실제 클래스는 `RuleNode`/`RuleRouting`. DRF 직렬화는 camelCase(`nodeKey/onResult/...`).

### 2.3 전제 — 룰 엔진 부재 (설계에 직접 영향)
- `build_rule_context` / `EvalContext` / `condition.expr` **평가기·순회 엔진이 없다**(코드 grep 0건). `apps/ai`의 `rule_agent.generate/validate/apply`는 stub. 조건 DSL 파서 없음.
- 기존 seed(`seed.py`)의 관례: `condition = {"expr": "amount > limit"}`, `action = {"decision": "REVIEW"|"REJECT"|"RETURN"}`. **`expr`은 아무도 파싱하지 않는 opaque 문자열**.
- ⇒ 이번 시드도 **표현식을 원문 문자열로 보존**하고, 실제 매칭 재현은 **post-MVP**로 명시. 시드의 가치는 (a) 콘솔 룰 목록/그래프 뷰, (b) 버전관리·롤백, (c) 시뮬레이션 통계 표시 UI 검증.

## 3. 매핑 설계

### 3.1 RULE → RuleNode 필드 매핑
| 명세서 항목 | RuleNode 필드 | 규칙 |
|---|---|---|
| `ID`(R-xxx) | `node_key` | 그대로 (`"R-106"`) |
| 조건(룰 엔진 표현식) | `condition` | `{"expr": "<원문>", "fields": [파싱된 참조필드], "source_clause": "<출처조항>"}` — expr 원문 보존 |
| 액션·심각도 | `action` | `{"decision": <§3.2>, "severity": <CRITICAL/HIGH/MEDIUM/LOW/INFO>, "flag": "<FLAG>", "title": "<제목>"}` |
| 권장처리·확인주체 | `action.decision` + `action.approver` | §3.2 매핑 + 확인주체 문자열 |
| 심각도 | `action.severity` + `priority` | CRITICAL=0 … INFO=4 (오름차순 정렬용) |

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
| 금지·현금성 GLOBAL 게이트 | `GLOBAL` | R-002, R-003 (CRITICAL, 카테고리 이전 평가) | ACTIVE |
| 공통 베이스 | `COMMON` | R-001, R-004~R-014 | ACTIVE |
| 업무추진비 | `기업업무추진비` | R-101~R-114 | ACTIVE |
| 회식 | `회식` | R-201~R-216 | ACTIVE |
| 출장 | `출장` | R-301~R-314 | ACTIVE |

- **노드 배치 옵션**: 명세는 트리 분기보다 **독립 플래그 수집형(플랫 룰셋)** 에 가깝다. → 각 RULE = 1 노드, `RuleRouting`은 `PASS`로 다음 노드에 순차 연결(마지막 노드 `to_node_key=""` 종단). `entry_node_key` = 그래프 첫 노드. 트리형(조건 분기)은 R-102~105 같은 배타 금액구간에서만 부분 적용 검토.
- **배타 그룹(§8)**: 금액구간 룰(R-102~105·R-201·R-312·R-313)은 상호배타 → `graph.sim_result`나 노드 `action.exclusive_group`에 메타로 기록(엔진 겹침검사용). 우선순위(R-105>R-102, R-313>R-312>R-301)도 `action.precedence` 메타로만.

### 3.4 참조 테이블(§2-1) 처리
`daily_limit_table` / `kickback_limit_table` / `lodging_limit_table` / `pre_approval_threshold_table` 는 별표 조회값. 엔진이 없으므로 **시드 시점엔 상수 JSON으로 문서화만**(예: `graph.sim_result.reference_tables` 또는 별도 `Policy` 행). 실제 `table[key]` 조회는 build_rule_context 구현 시(post-MVP).

## 4. 시드 산출물 형태 (구현 시)
- **위치 후보**: `seed.py` 확장 대신 **별도 커맨드 `seed_rules.py`** 또는 **JSON fixture `rules_v1_4.json`** 권장(58행 규모, 재생성·버전관리 용이).
- 그래프 5개 · 노드 58 · routing ~58(순차) + 종단. ACTIVE 그래프마다 `RuleGraphVersion(is_active=True, snapshot=_snapshot())` 1행.
- `sim_result`는 목업 통계(`matched/false_positive_rate/review_reduction`)로 채워 시뮬 탭 표시.
- 기존 `graph()` 헬퍼(`seed.py:164`) 시그니처 재사용 가능: `graph(name, scope, status, clause, sim, nodes, routings, ver, activated)`.

## 5. 단계별 작업(TODO — 미구현)
1. **명세 파싱표 작성**: 58행 CSV/표 (`id, graph_scope, condition_expr, decision, severity, flag, exclusive_group, precedence, source_clause`). 명세 §4~§7에서 기계적으로 추출.
2. **decision/severity 매핑 확정**(§3.2) + `RETURN`/`severity` enum 팀 합의(§6).
3. **그래프 분할 확정**(§3.3) — 플랫 vs 부분 트리.
4. **seed_rules 스크립트/픽스처 작성** + `--fresh` 연동.
5. **검증**: 콘솔(초안/시뮬/Active) 목록·그래프 뷰·버전 히스토리 렌더 확인. (실판정은 검증 대상 아님)

## 6. 오픈 이슈 · 리스크
- **엔진 미구현**: 시드는 UI·버전·시뮬 표시용. 명세의 우선순위/배타성/조회테이블 로직은 **재현 불가** — 메타 주석으로만 보존. 실판정은 build_rule_context + DSL 파서(post-MVP) 이후.
- **decision enum 확장**: `RETURN`·`severity`·`flag`·`monitoring`을 `action` JSON에 넣을지, `OnResult`에 `RETURN`을 정식 추가할지 합의 필요.
- **GLOBAL 게이트 우선순위**: scope 분리 + 게이트 그래프 우선 평가는 **엔진이 강제**해야 하는데 엔진이 없으므로, 시드는 scope 라벨과 문서화로만 표현. 아키텍처 전환 시 방어적 중복(R-109/R-208/R-304) 근거추적 태깅은 `action.gate_duplicate=true`로 보존.
- **프론트 정합**: `ruleConsoleMock.ts`는 flat UI 셰이프라 백엔드 graph 스키마와 미연동. 시드가 API로 노출돼도 FE가 소비하려면 rule-console 화면의 실연동 작업이 선행/병행돼야 함.
- **표현식 DSL 미정**: 명세는 `AND/OR/IN/NOT(...)/table[key]/서수비교(<직급>)` 를 쓰는데 파서 스펙이 없음. 원문 보존 후 DSL 확정 시 재파싱.

## 7. 부록 — 매핑 참조
- 심각도→기본 권장처리(§3): CRITICAL=자동반려후보 · HIGH=반려권고/에스컬레이션 · MEDIUM=보완요청/승인보류 · LOW=승인대기확인 · INFO=모니터링(개별건 무영향).
- flag 예시: `PROHIBITED_MERCHANT` · `PROHIBITED_PAYMENT_METHOD` · `NON_DEDUCTIBLE_RISK` · `PRE_APPROVAL_REQUIRED` · `KICKBACK_LAW_LIMIT_EXCEEDED` · `RECORD_INCOMPLETE` · `HIGH_RISK_USER` · `SELF_APPROVAL_CONFLICT` · `FINANCE_DEPT_SELF_AUDIT_REQUIRED`.
- 관련 캐논: `_context/rule-engine.md`(있으면), `기술명세서.md §3.1·§4.2`, `요구사항_명세서.md FR-RB/FR-RV/FR-RA`.

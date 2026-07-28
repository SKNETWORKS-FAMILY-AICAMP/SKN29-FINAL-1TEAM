# 룰엔진 캐논 (Rule Engine Canon)

> 파생 컨텍스트(에이전트 생성). 권위 규범은 **기술명세서 §4.2** / **요구사항 FR-RA-08~10**.
> 여기서는 실제 동작을 **예시 그래프 + 실행 워크스루**로 구체화한다. 규정 근거: `TIGER-REG-2026-003`.

## 1. 3단 파이프라인

```
[SUBMITTED 정산]
 ① 조립(I/O·유연)   build_rule_context(tx_id) → EvalContext(facts 스냅샷)  ← 모든 데이터 접근은 여기서만
 ② 그래프 선택       GLOBAL 필수 게이트 → (통과 시) 계정과목별(scope=category)
 ③ 순회(순수·엄격)   run_rule_engine(eval_context, graph) → decision·path·flags
[rule_hits + eval_context 스냅샷]
```
엔진(③)은 EvalContext만 참조 → 외부 I/O 0 → 재실행/시뮬/감사 결과 동일(재현성).

## 2. EvalContext (facts 스냅샷)

```jsonc
{
  "tx":       { "amount": 452000, "ts": "2026-07-18T19:20", "merchant": "강남한식당" },
  "card":     { "card_type": "SHARED", "owner_id": null },
  "user":     { "position": "사원", "dept": "AI·개발팀", "is_working_hours": false },
  "category": { "ai": "기업업무추진비", "confidence": 0.71 },
  "merchant": { "industry_code": "FD6", "forbidden": false },
  "evidence": { "has_receipt": false, "pre_approved": false,
                "fields": { "거래처": true, "참석자": false, "목적": true, "일시장소": true } },
  "policy":   { "preapproval_threshold": 300000, "position_limit": 500000 },
  "history":  { "same_merchant_7d": 1, "late_submit_count": 1 },
  "derived":  { "days_since_expense": 9, "biz_days_over_7": false,
                "is_late_night": true, "is_weekend": false }
}
```
| 섹션 | 소스 | 경로 |
|---|---|---|
| tx·card·user·evidence·history·policy | Postgres(SoT) | Django 내부 read API |
| merchant.industry/forbidden | 업종 캐시→카카오→웹 | `classify_merchant`(스냅샷) |
| policy.preapproval_threshold = `min(300000, 별표1[직책])` · derived.* | 계산 | 조립기 파생 산출 |

> **파생은 조립기가 미리 계산**한다(예: `min(30만, 직책한도)`·영업일 경과·심야). DSL은 단순 비교만.

## 3. 조건 DSL (JSON-Logic류)

- 연산자 화이트리스트: `and · or · not · == · != · > · >= · < · <= · in · var`. 임의 코드 금지.
- 평가 시맨틱(순수 재귀): `var`는 EvalContext 경로를 해석(없으면 null), 비교/논리 연산으로 boolean 산출 → **truthy면 MATCH, 아니면 NO_MATCH**.
- 노드 `action` = `{ "decision": "PASS|REJECT|REVIEW|RETURN", "flag": "...", "note": "..." }`.
- 순회: 엔트리 → condition 평가 → 결과(MATCH/NO_MATCH)에 해당하는 `next_routings`로 이동 → 단말(라우팅 없음)에서 `decision` 확정.

## 4. 예시 그래프

### (A) GLOBAL 필수 게이트 — `정산 1차 게이트 v1`

| node_key | condition (DSL 요약) | MATCH action | MATCH→ | NO_MATCH→ | 근거 |
|---|---|---|---|---|---|
| `n_forbidden` | `merchant.forbidden == true` | REVIEW·FORBIDDEN_INDUSTRY | (단말) | `n_evidence` | 제9조2호 |
| `n_evidence` | `category.ai=="기업업무추진비" & tx.amount>30000 & evidence.has_receipt==false` | REVIEW·NON_DEDUCTIBLE_RISK | (단말) | `n_preapproval` | 제11조2항 |
| `n_preapproval` | `category.ai in [식대,기업업무추진비] & tx.amount>policy.preapproval_threshold & evidence.pre_approved==false` | REVIEW·PREAPPROVAL_REQUIRED | (단말) | `n_fields` | 제10조2항 |
| `n_fields` | `category.ai=="기업업무추진비" & (evidence.fields.참석자==false or evidence.fields.거래처==false)` | RETURN·FIELDS_MISSING | (단말) | `n_deadline` | 제11조4항 |
| `n_deadline` | `derived.biz_days_over_7 == true` | RETURN·LATE_SUBMIT | (단말) | (게이트 통과 → 과목별 그래프) | 제12조1항 |

DSL 예(`n_evidence`):
```jsonc
{ "and": [ {"==":[{"var":"category.ai"},"기업업무추진비"]},
           {">" :[{"var":"tx.amount"},30000]},
           {"==":[{"var":"evidence.has_receipt"},false]} ] }
```

### (B) 계정과목별 — 예: `접대(기업업무추진비) 세부 v1`
| node_key | condition | MATCH action | MATCH→ | NO_MATCH→ |
|---|---|---|---|---|
| `n_ent_high` | `tx.amount > 500000` | REVIEW·HIGH_ENTERTAIN | (단말) | `n_ent_pass` |
| `n_ent_pass` | `true` | PASS | (단말) | — |

## 5. 실행 워크스루

### 케이스 A — 강남한식당 452,000 · 기업업무추진비 · 증빙없음 (위 EvalContext)
```
GLOBAL 게이트:
 1) n_forbidden : merchant.forbidden==true? → false → NO_MATCH → n_evidence
 2) n_evidence  : 추진비(T) & 452000>30000(T) & !has_receipt(T) → 모두 T → MATCH
                  action=REVIEW(NON_DEDUCTIBLE_RISK) → 단말 → STOP
결과: decision=REVIEW · path=[n_forbidden,n_evidence] · flags=[NON_DEDUCTIBLE_RISK] · conf=1.0
→ 정산 상태 IN_REVIEW (Risk Review 이관: 이후 anomaly_score+RAG 제11조 근거 생성)
```

### 케이스 B — 쿠팡 89,000 · 비품 · 증빙OK
```
EvalContext: category.ai=비품, tx.amount=89000, has_receipt=true, forbidden=false, biz_days_over_7=false
GLOBAL 게이트:
 1) n_forbidden   NO_MATCH → n_evidence
 2) n_evidence    category!=추진비 → NO_MATCH → n_preapproval
 3) n_preapproval 비품 ∉ [식대,추진비] → NO_MATCH → n_fields
 4) n_fields      category!=추진비 → NO_MATCH → n_deadline
 5) n_deadline    biz_days_over_7=false → NO_MATCH → 게이트 통과 → [과목별: 비품 그래프]
과목별(비품): 소액·정상 → PASS
결과: decision=PASS · conf ≥ θ_pass → 정산 상태 PENDING_CONFIRM (사람 확정 대기)
```

## 6. 결정 → 상태 매핑 & 로그

| decision | 조건 | 정산 상태 |
|---|---|---|
| PASS | conf ≥ θ_pass | PENDING_CONFIRM (사람 확정 필수, 제16조) |
| REJECT | conf ≥ θ_reject | RETURNED (보완요청 자동 안내) |
| RETURN | — | RETURNED |
| REVIEW | 그 외 | IN_REVIEW (Risk Review 이관) |

`rule_hits` 저장: `{ tx_id, graph_id, graph_version, path, eval_context(스냅샷), decision, confidence, flags }`
→ "이 판정에 어떤 값이 쓰였나"를 그대로 재현·감사할 수 있다.

## 7. 룰이 아닌 것(→ Risk Review / 대시보드)
- 항목 구분 모호(추진비 vs 복리후생 vs 회의비, 제15조) → Risk Review 1차 분류 + 사람 최종
- 업무 관련성 소명(제9조4호) → REVIEW
- 연간 추진비 손금한도(제14조)·기한 3회 초과(제13조) → 누적 집계 → 대시보드/배치

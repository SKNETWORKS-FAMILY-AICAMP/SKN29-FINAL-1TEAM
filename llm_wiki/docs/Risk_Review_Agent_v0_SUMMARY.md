# Risk Review Agent (③ 검토 에이전트) — v0 구현 정리

> 작성일: 2026-08-14 · 대상: SKN29 1팀 (정영석·김진욱·김정민·이지현·한경찬)
> 이 문서는 Risk Review Agent v0 구현 세션의 진행 내용을 팀 공유용으로 정리한 것입니다.

---

## 1. 목적과 범위

Rule Agent로 걸러지지 않은 미매칭·불확실 정산 건에 대해, **① 비지도 이상탐지로 1차 선별 → ② RAG 내규 검증으로 근거 확인**하는 2단계 파이프라인을 구현하고, 실제 Rule Agent 판정 결과와 연결해 end-to-end로 동작하는 것까지 확인했습니다.

**관련 요구사항**: FR-RR-01~08 (요구사항_명세서.md §5.5), FR-RL-01~02

---

## 2. 최종 파이프라인 (실측 검증 완료)

```
Rule Agent 실판정 (orchestrator.py: GLOBAL 게이트 → scope 게이트)
  ├─ PASS         → PENDING_CONFIRM
  ├─ REJECT       → RETURNED            ⚠️ 회식 케이스 실측 미완
  └─ REVIEW/미매칭 → IN_REVIEW 자동 전이
        │
        ▼
  [1차: 비지도 이상탐지]
  get_tx_features(tx_id)
    └─ 15개 원본 피처 → 원-핫 인코딩 후 24컬럼 (거래요일_한글 7·시간대구간 4·
       일시불할부구분코드 3) → anomaly.pkl의 feature_columns에 align
  ml_infer(feature_vector)
    └─ anomaly_score 산출 (실값, 예: −0.0127, percentile_band 80~90%)
        │
        ▼
  [2차: RAG 내규 검증 — v0은 컷오프 없이 전건 진행]
  search_policy(운영 Chroma, policy_docs 103청크)
  search_cases(case_history, 골든데이터 10건)
  LLM 대조·검증
    └─ stage2_verdict: violation_verdict / review_reasons /
       recommendation / citations / similar_cases
        │
        ▼
  risk_reviews 저장 (Django, judge 액션이 자동 호출·저장)
        │
        ▼
  risk_review_v0 Review List
    └─ GET /api/risk-review-v0/reviews/   (anomaly_score 내림차순)
    └─ POST /api/risk-review-v0/reviews/<id>/decision/
        │
        ▼
  회계 담당자 승인/보완/반려 → decision_labels 적재 (재학습에는 사용 안 함, FR-RL-02)
```

---

## 3. 단계별 구현 내용

### 3.1 1차 이상탐지 — `get_tx_features` 실구현
- 기존 상태: `feature_vector: []`를 반환하는 stub이었음(구현 자체가 없었음)
- 실구현: 15개 원본 피처 중 `취소성거래_추정`은 계산 로직(통합승인금액==0)으로 확인, 시간계열 파생 피처(최근7일사용횟수·카드누적사용액 등)는 Django `build_tx_features()`가 카드 단위 과거 거래 집계로 산출
- `일시불할부구분코드`는 카드사 원천 데이터라 조달 불가 → seed 단계에서 실거래 관측 분포(A 98.1%/B 1.3%/_ 0.6%) 그대로 랜덤 배정, 재학습 없이 포함시키기로 결정
- 단건 서빙 시 카테고리 컬럼 수 불일치 문제를 `pd.Categorical` 캐스팅으로 해결
- **컬럼 수 정정**: 15개 원본 → 13개(거래일자·거래연월 drop) + 원-핫 확장 14 = **24개** (이전에 "23"으로 잘못 인용된 적 있음, 실측으로 정정)

### 3.2 1차 이상탐지 — 모델 로드
- `anomaly.pkl` 로드 시 `AttributeError: fill_values` 크래시 발생 → `AnomalyModel.__setstate__`로 구버전 pkl의 누락 필드 방어
- 로드된 모델은 `feature_stats`(z-score 계산용) 없이 학습된 구버전이라 `feature_contribs`는 항상 빈 배열 (§5 v0 한계 참고)

### 3.3 2차 RAG 검증
- `search_policy`가 초기엔 미설정 시 로컬 격리 스토어(`./chroma_data_v0`, 실측 1건뿐)를 쓰는 실험용 코드였음 → 운영 Chroma 인덱스(policy_docs 103청크·tax_refs 730청크)로 재연결
- `case_history`는 실제로 0건이었어서 골든 데이터 10건 신규 적재
- `RiskVerdict` pydantic 스키마 고정, 프롬프트 규칙 3가지 반영: ①「문서명」제N조 전체 인용 강제 ②정보없음(INSUFFICIENT_INFO)과 판단애매 구분 가드 ③tax_refs 미사용 명시(세법 문서 미입수)
- 실제 LLM이 「업무추진비_사용규정」·「회식_운영규정」 등 조항을 인용하며 검증하는 것까지 실측 확인

### 3.4 Rule Agent ↔ Risk Review 연결
- `services.judge()`가 Rule Agent를 한 번도 호출하지 않는 하드코딩 placeholder였음이 밝혀짐 (기존 테스트 데이터는 상태머신을 거치지 않고 `IN_REVIEW`로 직접 시드된 것이었음)
- `apps/core/domain/policies/orchestrator.py` 신규 구현(당시 함수명 `judge_settlement()` — 현재는 `judge()`로 재작성됨): GLOBAL(ACTIVE) 게이트 → PASS 아니면 최종 → PASS/부재 시 scope ACTIVE 그래프 → 둘 다 없으면 IN_REVIEW. 실행마다 `RuleHit` 기록
- 실제 HTTP 경로(`/api/settlements/<id>/judge/`)로 PASS/IN_REVIEW 갈래 실측 확인

### 3.5 Review List v0
- 디렉토리 격리: `apps/core/domain/risk_review_v0/` (신규 모델 없이 `Settlement`/`RiskReview` 운영 모델 직접 import), 프론트 `apps/web/src/risk_review_v0/` (별도 라우트, Sidebar 미연결)
- **격리는 코드 위치에만 적용, 데이터 계층·권한 체크는 격리하지 않음** — Rule Agent v0 때 로컬 Chroma 격리로 "죽은 경로"가 됐던 것과 같은 함정 재발 방지
- `CanAccountingReview` 권한 그대로 적용(스킵 안 함), 기존 `services.review()` 재사용(새 상태머신 안 만듦)
- 실측: 회계 담당자(acc) 200 / 일반사원(kim) GET·POST 모두 403, 정렬 anomaly_score 내림차순 확인

### 3.6 "업무활성" → "회식" 카테고리 리네임
- `Category.OPERATION("업무활성")`이 임시 테스트 픽스처가 아니라 **실제 프로덕션 카테고리 값**이었음이 확인됨. 문서(마크다운)는 이미 "회식"으로 정정되어 있었지만, 코드(SoT) enum은 한 번도 바뀐 적 없었던 문서-코드 괴리
- `Category.OPERATION` → `Category.GATHERING("회식")` 리네임. 부수 발견 3가지:
  1. "업무활성"이 Draft Agent 미분류 캐치올(우체국·택배·인쇄 키워드)이었음 → 단순 문자열 치환 시 오분류 위험 → `비품`(SUPPLIES)으로 흡수, 회식은 새 키워드(포차·호프·이자카야)로 재설계
  2. `RuleGraph`에 DB-level `CheckConstraint` 존재 → 임의 문자열 즉시 거부 → 마이그레이션 3단계 분리(제약 넓히기 → 데이터 이관 → 좁히기)로 처리
  3. `TeamBudget`의 `(team, year_month, category)` 유니크 제약과 충돌 → 파생 데이터이므로 병합 대신 삭제
- 회식 검증 그래프가 `scope="식대"`에 잘못 매핑돼 있던 것도 함께 발견·이전 (문서에는 "정정 완료"로 기록돼 있었으나 코드는 안 고쳐져 있던 사례)
- 회식 데모 거래 3건 신규 추가, `services.judge()`로 실판정 → PENDING_CONFIRM/IN_REVIEW(한도초과)/IN_REVIEW(2차 결제, Risk Review 2차까지 실행되어 「회식_운영규정」 제8조 인용) 3케이스 실측
- 부수 발견: `upsert_policy_tables()` 실행 순서 버그 — seed 맨 끝에 있어서 판정 시점에 정책 표가 비어있어 전건 REVIEW로 강등되던 문제, 실행 순서 조정으로 해결(기존 하이라이트 케이스는 EvalContext를 손으로 채워써서 이 문제가 가려져 있었음)

---

## 4. 실측 검증 요약

| 검증 항목 | 결과 |
|---|---|
| 모델 로드 | ✅ 정상 (fitted, threshold=0.0037) |
| anomaly_score | ✅ 실값 산출 확인 |
| feature_contribs | ❌ v0 한계로 빈 배열 (§5 참고) |
| 2차 RAG 검증 | ✅ 실제 규정 조항 인용 + INSUFFICIENT_INFO 가드 동작 확인 |
| Rule Agent → IN_REVIEW 자동 전이 | ✅ PASS/REVIEW 갈래 실측 (REJECT 미실측) |
| Review List 조회·정렬 | ✅ anomaly_score 내림차순 확인 |
| 승인/보완/반려 → decision_labels | ✅ 실제 DB 적재 확인 |
| 권한(Capability) 체크 | ✅ accounting=200, employee=403 |
| 회식 카테고리 전체 흐름 | ✅ PASS/REVIEW(한도초과)/REVIEW(2차, RAG검증까지) 3케이스 |
| Django 테스트 | ✅ 56건 전체 통과 |
| 프론트 빌드 | ✅ `tsc -b && vite build` 통과 |

---

## 5. v0 알려진 한계 (의도적으로 미룬 것)

| 항목 | 내용 | 조치 |
|---|---|---|
| `feature_contribs` | 항상 빈 배열. pkl에 `feature_stats` 없는 구버전이라서 (모델 부재 아님) | 재학습 필요하지만, 발표 지표(PR-AUC 0.5865 등) 재검증 부담 커서 v0은 보류 결정 |
| θ_anomaly 컷오프 | 미적용. IN_REVIEW 전건이 2차 RAG까지 진행 (FR-RR-04와 임시 괴리) | v1에서 컷오프 산출·분기 추가 예정 |
| sklearn 버전 불일치 | pkl=1.8.0 vs 컨테이너=1.5.2 | 기록만, 현재 크래시 없이 동작 중 |
| `risk_review_v0` 미통합 | 메인 네비게이션 미연결, 직접 URL 접근만 | v1 전환 조건 |
| `case_history` | 자정 배치 아닌 수동 골든데이터 10건 | `_context/case-history-golden-data-note.md`에 기록, 팀원 원본 RAG 문서 작성 시 병합 필요 |
| Rule Agent REJECT 분기 | 회식 케이스로 아직 실측 안 됨 | 3갈래 중 2갈래만 확인된 상태 |

---

## 6. 이번 세션에서 발견한 구조적 이슈 (Review Agent 범위 밖, 별도 트래킹 필요)

- **Evidence Extraction Agent 미착수** — 첨부문서 구조화 추출이 안 되어 판정에 필요한 사실이 계속 미해소로 잡힘 → REVIEW 강등 과다 발생 가능성
- **판정 강등률 실측치 불일치** (`_index.md`: 93% vs 31%, 문서 간 수치 모순, 미해소)
- **Open Issue #17 신설** (RETURN/OnResult enum 관련, 미해결)
- **문서-코드 괴리 패턴 반복 확인** — "업무활성→회식"·"회식 그래프 scope 오매핑"·`RAG_전략_종합.md` 부재 등, 마크다운 문서가 "정정 완료"라고 기록해도 실제 코드(SoT)에는 반영 안 된 사례가 이번 세션에서만 3회 발견됨. 문서 갱신 시 코드 레벨 재확인이 필요하다는 교훈

---

## 7. 관련 코드 위치 (레포 기준)

```
apps/ai/app/agents/risk_review_v0/     — (필요 시 클로드 코드에 정확 경로 재확인)
apps/core/domain/policies/orchestrator.py   — Rule Agent GLOBAL→scope 판정
apps/core/domain/risk_review_v0/            — Review List v0 (Django)
apps/web/src/risk_review_v0/                — Review List v0 (프론트)
apps/core/domain/transactions/features.py   — 파생 피처 집계 (build_tx_features)
mcp/tools.py                                — get_tx_features, ml_infer
_context/case-history-golden-data-note.md   — case_history 골든데이터 기록
```

---

## 8. 문서 반영 완료 사항

- `요구사항_명세서.md`: FR-RR-04/05 v0 한계 각주, §9.2 Open Issue #17 신설
- `기술명세서.md`: §3.1 risk_reviews 필드 확장, §5 get_tx_features 스펙, §6.1 엔드포인트 추가, §4.3/§11.2 갱신
- `기획_확장안.md`: §1.3/§2.3 각주
- `_index.md`: orchestrator.py·get_tx_features 상태 갱신
- `RAG_전략_종합.md`: 클로드 코드가 세션 중 신규 생성했던 버전은 **삭제**(팀원이 별도로 원본 작성 중이라 충돌 방지 목적). case_history 관련 신규 발견 내용은 `_context/case-history-golden-data-note.md`로 보존, 팀원 원본 작성 시 병합 필요

---

## 9. 다음 단계 (v1 전환 조건)

1. `risk_review_v0/` 코드를 메인 라우팅·네비게이션에 정식 연결
2. θ_anomaly 컷오프 산출 및 분기 로직 추가
3. Rule Agent REJECT 분기 회식 케이스 실측
4. (선택) 모델 재학습 — feature_contribs 실값화, 단 발표 지표 재검증 필요성 감안해 시점 판단
5. 팀원 작성 `RAG_전략_종합.md` 원본과 세션 발견 내용(case_history 골든데이터) 병합

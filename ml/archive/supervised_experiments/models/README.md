# 법인카드 이상거래 탐지 — 모델 결과 정리

이 폴더의 모델들이 무엇이고, 왜 두 갈래(비지도/지도학습)로 나뉘어 있는지, 어떤 게
실제 MVP 배포 후보인지 정리한 문서. Isolation Forest 관련 내용은 `ml/mvp_isolation_forest/`(팀원 작업
노트북 4개 + `isolation_forest_modeling_결과.md`)을 기준으로 정리했다.

---

## 0. 현재 상태 요약 (재검토 중)

- **현재 MVP 후보**: Isolation Forest(비지도, 피처 Tier0+`일시불할부구분코드` 15개). 원본:
  `ml/mvp_isolation_forest/법인카드_이상거래_모델링_v2_최종test평가.ipynb`. test 기준 PR-AUC 0.5865,
  상위 3% 검토 시 recall 52.6% / precision 61.1%, 상위 10% 검토 시 recall 79.0% / precision 27.6%.
- **이 후보를 고른 원래 근거**: 지도학습 8개는 수치상 더 높지만(PR-AUC 최대 0.827), 학습에 쓴
  정답(`이상거래여부`)이 카드사 부정사용 기준일 뿐 회계 담당자의 실제 승인/반려 판단이 아니라서
  라벨 신뢰성이 검증되지 않았다(§1). 이 판단은 팀원도 요구사항명세서 조항을 근거로 독립적으로
  검토해 같은 결론(§3-3 하단 "MVP 범위 확인" 참고)을 냈다.
- **현재 재검토 중인 지점 (2가지)**:
  1. 지도학습 8개가 top3% recall 기준 74.7%로 Isolation Forest(52.6%)보다 +22%p 높게 나온
     격차가 커서, "비지도를 우선한다"는 전제 자체를 다시 검토하고 있다. 최종 판단은 라벨
     (`이상거래여부`)이 실제 정산 검토 기준과 얼마나 겹치는지 타당성이 확인돼야 내릴 수 있다.
  2. **top3% 컷오프 자체도 팀원 분석상 미확정 상태다** — recall이 52.6%뿐이라 이상거래의
     거의 절반을 놓친다. recall 90%를 확보하려면 전체의 32.7%까지 검토 범위를 넓혀야 한다
     (§3-3 "우선순위 컷오프 재검토" 참고). 즉 지금 표에 나온 "3%"는 정답이 아니라 잠정안이다.
- **강건성 확인**: 신규 카드(카드 이력 없음)에서 오히려 성능이 더 좋게 나와, "이력을 암기해 신규
  카드에 취약할 것"이라는 우려는 기우로 확인됨(§3 세그먼트 진단). 이 결과는 두 트랙 중 어느 쪽이
  최종 방향이 되든, 그리고 컷오프를 몇 %로 정하든 유효하다.
- **다음 단계**: 라벨 타당성 검증(또는 서비스 배포 후 `decision_labels` 축적)으로 비지도/지도학습/
  하이브리드 방향을 확정하고, 별도로 회계팀·PM과 목표 recall 수준(80%? 90%?)을 합의해 컷오프를
  확정한다. 확정되면 이 섹션과 `llm_wiki` 설계 문서를 함께 갱신한다.

---

## 1. 현재 문서상 MVP 방향 — 비지도 우선(재검토 중)

프로젝트 설계 문서(`CLAUDE.md`, 요구사항명세서)는 Risk Review MVP를 **비지도 이상탐지**로
규정하고, 라벨(`이상거래여부`)을 직접 학습시키는 지도학습은 **post-MVP**로 명시하고 있었다.
이유: 지금 있는 `이상거래여부`는 카드사 자체 부정사용 기준이지, 회계 담당자의 실제
승인/반려 판단(`decision_labels`, 서비스 미배포로 아직 존재하지 않음)이 아니라서
라벨 자체의 신뢰성(label bias)이 확인되지 않았기 때문. 다만 이번 모델링에서 지도학습과의
성능 격차가 예상보다 크게 나오면서, 이 전제 자체를 §0처럼 다시 검토하고 있다 — 아래
내용은 "지금까지 문서화된 방향"이지 "최종 확정"은 아니다.

- **8개 지도학습 모델(logistic_regression ~ mlp)** — `이상거래여부`를 정답으로 직접
  학습시킨 참고/비교 실험. **지금 당장 배포 대상이 아님.** "나중에 진짜 라벨이 쌓이면
  지도학습으로 바꿨을 때 얼마나 더 잘할 수 있는지" 미리 살펴본 자료.
- **Isolation Forest(비지도)** — 팀원이 `ml/mvp_isolation_forest/`에서 직접 검증한 MVP 후보.
  원본 노트북·결과 요약은 그 폴더를 참고한다.

두 트랙 모두 **동일한 데이터**(2021~2023 학습 / 2024 평가, 날짜 기준 분할)를 쓴다.

---

## 2. 두 가지 피처 세트

지도학습 8개 모델은 두 번 실행되어(아래 §3) 각각 다른 피처 세트를 쓴다.

| 세트 | 개수 | 구성 | 사용처 |
|---|---|---|---|
| A | 12개 | Tier0(거래·카드 이력) 중 가맹점 관련 2개(`가맹점평균금액_확장`,`가맹점첫거래여부`) 제외, 날짜 원본 컬럼도 제외 | `*_tuned.pkl` (1차 라운드) |
| B | 15개 | 피처 A와 동일한 12개 + `일시불할부구분코드` 1개(원-핫 후 24컬럼) | `*_topk_ranking.pkl`, Isolation Forest MVP(`mvp_isolation_forest`) |

세트 B는 팀원이 ablation(넣었다 뺐다 실험)으로 검증한 조합 — Tier0 단독 PR-AUC 0.4711(5-fold
기준선) 대비, Tier0+Tier1 전체(32컬럼)를 다 넣으면 0.2101로 오히려 55% 떨어졌고, Tier1 10개를
하나씩 넣어본 결과(leave-one-in) 9개는 마이너스, `일시불할부구분코드` 1개만 +7.2%로 도움이
됐다. 그래서 `Tier0 + 일시불할부구분코드`만 최종 채택했다(0.4946, +4.98%). 상세:
`ml/mvp_isolation_forest/isolation_forest_modeling_결과.md` §3.

> **주의**: 우리 쪽 지도학습 8개 실험(`supervised_topk_ranking.py`)이 쓰는 피처 세트 B는
> `ml/archive/supervised_experiments/pipeline/feature_set_b.py`에 구현돼 있는데, 여기엔 `거래일자`/`거래연월`을 정렬 순서를 보존하는
> 숫자(ordinal)로 변환해 2개 더 포함한다(팀원 원본 Isolation Forest에는 없는 컬럼). 즉 우리
> 지도학습 실험과 팀원의 실제 Isolation Forest는 피처 구성이 완전히 동일하지는 않다 — 아래
> §3-3 비교표를 "동일 조건 비교"로 과신하지 말 것.

---

## 3. 세 차례 실행 결과

### 3-1. 베이스라인 (기본 설정값, 피처 A, `*.pkl`)

| 모델 | PR-AUC | 파일명 | 핵심 설정 |
|---|---|---|---|
| LightGBM | 0.712 | `round1_baseline/lightgbm.pkl` | n_estimators=300, num_leaves=31, learning_rate=0.1, class_weight=balanced |
| XGBoost | 0.706 | `round1_baseline/xgboost.pkl` | n_estimators=300, max_depth=6, learning_rate=0.1, scale_pos_weight=자동계산 |
| Random Forest | 0.697 | `round1_baseline/random_forest.pkl` | n_estimators=200, max_depth=12, min_samples_leaf=20, class_weight=balanced |
| 로지스틱 회귀 | 0.617 | `round1_baseline/logistic_regression.pkl` | class_weight=balanced, max_iter=1000 |

### 3-2. 하이퍼파라미터+임계값 튜닝 (피처 A, `*_tuned.pkl`)

서브샘플(25만 건)로 하이퍼파라미터 탐색 → 2023년 4분기로 최적 임계값 선택 →
2021~2023 전체로 재학습 → 2024로 최종 평가. 8개 모델로 확장(CatBoost·ExtraTrees·MLP·BalancedRF 추가).

| 모델 | PR-AUC | ROC-AUC | Precision | Recall | 임계값 | 파일명 | 핵심 설정(탐색 결과) |
|---|---|---|---|---|---|---|---|
| CatBoost | 0.715 | 0.970 | 0.826 | 0.647 | 0.95 | `round2_tuned/catboost_tuned.pkl` | learning_rate=0.1, depth=8, l2_leaf_reg=7, iterations=200 |
| XGBoost | 0.714 | 0.969 | 0.818 | 0.651 | 0.93 | `round2_tuned/xgboost_tuned.pkl` | max_depth=6, learning_rate=0.05, subsample=0.85, n_estimators=300 |
| Random Forest | 0.713 | 0.969 | 0.833 | 0.641 | 0.90 | `round2_tuned/random_forest_tuned.pkl` | n_estimators=200, min_samples_leaf=20, max_depth=None |
| LightGBM | 0.711 | 0.968 | 0.826 | 0.647 | 0.94 | `round2_tuned/lightgbm_tuned.pkl` | num_leaves=31, n_estimators=400, learning_rate=0.1 |
| Balanced RF | 0.703 | 0.969 | 0.831 | 0.642 | 0.92 | `round2_tuned/balanced_random_forest_tuned.pkl` | n_estimators=100, min_samples_leaf=20 |
| MLP | 0.680 | 0.952 | 0.830 | 0.642 | 0.27 | `round2_tuned/mlp_tuned.pkl` | hidden_layer_sizes=(128,), learning_rate_init=0.005, alpha=0.01 |
| Extra Trees | 0.679 | 0.962 | 0.839 | 0.638 | 0.83 | `round2_tuned/extra_trees_tuned.pkl` | n_estimators=200, min_samples_leaf=20, max_depth=None |
| 로지스틱 회귀 | 0.627 | 0.914 | 0.840 | 0.636 | 0.97 | `round2_tuned/logistic_regression_tuned.pkl` | C=0.1 |

상세: `tuning_results.csv`

### 3-3. top-K% 랭킹 재실행 (피처 B, top-K% 랭킹 평가)

이전 라운드에서 찾은 최적 하이퍼파라미터를 그대로 재사용(재튜닝 없음), 피처만 B로 교체,
평가는 "상위 K% 검토" 랭킹 방식(현업 제약 — 심사 담당자가 하루에 볼 수 있는 건수)으로 변경.
임계값은 F1 최적화가 아니라 **train 분포 97번째 백분위수 고정값**.

지도학습 8개의 하이퍼파라미터는 §3-2에서 찾은 값을 그대로 재사용(재튜닝 없음) — 위 표 참고.

| 모델 | 방식 | PR-AUC | top3% recall | top3% precision | top10% recall | top10% precision | 파일명 |
|---|---|---|---|---|---|---|---|
| XGBoost | 지도학습 | 0.827 | 74.7% | 86.8% | 91.9% | 32.1% | `round3_topk_ranking/xgboost_topk_ranking.pkl` |
| CatBoost | 지도학습 | 0.826 | 74.7% | 86.8% | 91.7% | 32.0% | `round3_topk_ranking/catboost_topk_ranking.pkl` |
| Balanced RF | 지도학습 | 0.819 | 74.7% | 86.9% | 92.1% | 32.1% | `round3_topk_ranking/balanced_random_forest_topk_ranking.pkl` |
| LightGBM | 지도학습 | 0.819 | 74.5% | 86.6% | 91.7% | 32.0% | `round3_topk_ranking/lightgbm_topk_ranking.pkl` |
| Random Forest | 지도학습 | 0.816 | 74.7% | 86.8% | 91.9% | 32.1% | `round3_topk_ranking/random_forest_topk_ranking.pkl` |
| MLP | 지도학습 | 0.808 | 74.8% | 87.0% | 88.9% | 31.0% | `round3_topk_ranking/mlp_topk_ranking.pkl` |
| Extra Trees | 지도학습 | 0.802 | 74.5% | 86.7% | 89.6% | 31.3% | `round3_topk_ranking/extra_trees_topk_ranking.pkl` |
| 로지스틱 회귀 | 지도학습 | 0.753 | 74.4% | 86.5% | 82.8% | 28.9% | `round3_topk_ranking/logistic_regression_topk_ranking.pkl` |
| **Isolation Forest** | **비지도 (MVP)** | **0.5865** | 52.6% | 61.1% | 79.0% | 27.6% | `ml/mvp_isolation_forest/법인카드_이상거래_모델링_v2_최종test평가.ipynb` — n_estimators=200, max_samples=auto, contamination=auto |

상세(지도학습 8개): `topk_ranking_results.csv`. 상세(Isolation Forest): `ml/mvp_isolation_forest/isolation_forest_modeling_결과.md`.

**해석 주의**: 지도학습 8개가 PR-AUC·top-K% 지표 모두에서 Isolation Forest보다 높게 나오는 건
"정답을 직접 학습했으니 당연한 결과"이지 "지도학습이 실전에서 더 우월하다"는 뜻이 아니다.
학습에 쓴 정답(`이상거래여부`) 자체가 우리가 원하는 정답(회계담당자 판단)인지 검증되지 않았기
때문에, 점수 차이를 실제 우열로 해석하면 안 된다.

#### 임계값(고정 숫자)은 왜, 어떻게 정했나

이상탐지 결과를 실무에 적용하는 방법은 두 가지다.

| 방식 | 정하는 기준 | 문제점 |
|---|---|---|
| 상위 K% 방식 | 오늘 들어온 거래 전체를 점수순으로 줄 세워서 위에서부터 K%까지만 검토 | 하루가 다 끝나야 순위를 매길 수 있음 → 실시간 판단 불가능 |
| 고정 임계값 방식 | "점수 0.0620 이상이면 무조건 검토" 같은, 미리 정해둔 숫자 하나 | 거래 한 건 들어올 때마다 그 자리에서 즉시 비교 가능 → 실시간 판단 가능 |

§3-3 표의 top3%/top10% recall·precision은 **평가용**(상위 K% 방식으로 test를 다시 줄 세워 계산)이고,
실제 운영에 쓸 **고정 임계값**은 이것과 별개로 아래 절차로 만든다:

1. train(2021~2023)으로 학습한 모델로 **train 데이터 자체**의 이상 점수를 매김
2. 그 점수들을 줄 세워 **상위 3% 지점의 점수값**을 확인 → `threshold = 0.0620`(train 상위 3% 지점)
3. 이후 실제 거래는 이 `0.0620`과 즉시 비교만 하면 된다(매번 다시 줄 세울 필요 없음)

**§3-2(F1 방식)와의 차이**: §3-2는 **정답(라벨)을 보면서** F1이 최대인 지점을 찾았고, §3-3은
**정답을 안 보고** train 점수 분포에서 상위 3% 지점을 그대로 썼다. Isolation Forest는 애초에
라벨이 없는 모델이라 F1 방식 자체가 불가능하고, 공정 비교를 위해 지도학습 8개도 같은 방식
(97%ile 고정값)으로 통일했다.

**train 기준 임계값을 test에 적용하면 정확히 3%가 아니라 오차가 생긴다**: 고정값(0.0620)을
test(2024)에 그대로 적용하면, 의도한 3.00%가 아니라 **실제로는 3.29%**가 걸린다(오차 0.29%p —
`ml/mvp_isolation_forest/isolation_forest_modeling_결과.md` §5). train과 test의 점수 분포가 완전히 같지 않아서
생기는 자연스러운 오차이며, 이 오차가 크지 않다는 건 "임계값이 미래 시점에도 안정적으로 작동한다"는
근거로 해석된다. test 기준 연간 약 15,465건(하루 평균 약 42건)이 '검토 대상'으로 분류된다.

#### ⚠️ 우선순위 컷오프(top3%) 재검토 필요 — 아직 확정 아님

팀원 분석 결과, **위 3% 컷오프는 recall이 52.6%뿐**이라 실제 이상거래의 거의 절반을 놓친다.
"이상거래를 놓치면 안 된다"는 원칙과 맞지 않아 재검토가 필요한 상태다. recall을 얼마나 확보할지에
따라 필요한 검토 비율이 급격히 늘어난다(test 469,902건 / 이상거래 16,394건 기준):

| 목표 recall | 필요 검토 비율 | 달성 precision |
|---|---|---|
| 80% | 10.79% | 25.9% |
| 85% | 18.99% | 15.6% |
| 90% | 32.68% | 9.6% |
| 95% | 54.46% | 6.1% |
| 99% | 78.72% | 4.4% |

recall 90% 이상을 요구하면 전체 거래의 32% 이상을 검토해야 해서 회계팀 검토 용량과 정면으로
충돌한다. **대안으로 제시된 방향**: Risk Review 2단계 구조(비지도 1차 탐지 → RAG 내규 검증
2차)에서 1차 컷오프를 top3%보다 넉넉히(예: top10~15%)로 낮춰 recall을 우선 확보하고, 2차
필터(RAG/Rule)로 정밀도를 보강하는 방식. **목표 recall 수준(80%? 90%?) 자체는 아직 회계팀·PM과
합의되지 않아 미확정**이다. 상세: `ml/mvp_isolation_forest/isolation_forest_modeling_결과.md` §5.

#### 이상 점수를 "확률"로 그대로 쓰면 안 되는 이유

Isolation Forest의 점수(0~1)는 원 논문 정의상 이상 정도를 나타내지만, **통계적으로 보정된
확률이 아니다** — 정상/이상 그룹의 점수 분포가 서로 크게 겹친다(정상 평균 0.442, 이상 평균
0.570, 둘 다 0.72대까지 겹침). 그래서 raw score를 "이 거래는 이상거래일 확률 N%"로 그대로
UI·RAG에 노출하면 오도의 소지가 있다. 대신 점수 구간(백분위)별 **실제 관측 이상거래 비율**을
보정 테이블로 써야 한다(전체 기저율 3.49% 대비):

| 점수 구간(백분위) | 실제 이상거래 비율 |
|---|---|
| 하위 0~80% | 0.07~2.23% (구간별 상세는 원본 md 참고) |
| 상위 90~100% | **27.58%** |

즉 "상위 10% 안에 들어도 실제 확률은 27.6% 수준"이라, "위험도 90%" 같은 표현은 쓰면 안 되고
"이 점수대는 과거 기준 약 X% 확률로 이상거래였다"는 식으로 실측 구간표를 근거로 문구를 구성해야
한다. 이 보정 테이블은 모델·피처셋이 바뀌면 재계산이 필요하다. 전체 10구간 표: `ml/mvp_isolation_forest/isolation_forest_modeling_결과.md` §4.

#### MVP 범위 확인 — 지도학습 관련 (팀원 분석과 독립적으로 같은 결론)

§0/§1에서 다루는 "비지도 vs 지도학습" 재검토는 팀원도 이미 한 번 짚어본 사안이다. 팀원은
`요구사항_명세서.md`(§9.1, FR-RR-04, FR-RR-08, FR-RL-02), `기획_확장안_v2.md`(§2.3),
`기술명세서.md`(§7)를 근거로 "`이상거래여부`(카드사 부정사용 기준)를 지도학습 타깃으로 쓰는
것은 현재 지침과 어긋난다"고 결론 내렸다 — `decision_labels`(회계 담당자의 실제 결정)가 쌓이기
전까지는 라벨 자체를 신뢰할 수 없다는, §1과 동일한 논리다. 다만 팀원 md도 "팀 내 이견이 있으면
논의 필요"라고 열어뒀다 — 즉 이 결론은 **한 사람의 분석 결과 + 문서 근거**이지, 아직 팀 전체가
논의를 마친 최종 확정은 아니다. 상세: `ml/mvp_isolation_forest/isolation_forest_modeling_결과.md` §6.

### 세그먼트 진단 (재사용 카드 vs 신규 카드, top-K% 랭킹 방식 공통 적용)

Isolation Forest는 신규 카드(4,574건, 그중 실제 이상거래 163건)에서 오히려 성능이 더 좋게
나와(top3% recall 57.7% vs 재사용카드 52.6%) "카드 이력을 암기해 신규 카드에서 성능이 떨어질
것"이라는 우려가 기우였음을 확인. 다만 신규 카드의 실제 이상거래 표본이 163건으로 작아,
절대 수치보다 상대적 경향으로 해석해야 한다(`ml/mvp_isolation_forest/isolation_forest_modeling_결과.md` §4).
지도학습 8개 모델도 자체 세그먼트 진단을 거쳤으며 세부 수치는 `topk_ranking_results.csv`의
`seg_reused`/`seg_new` 컬럼 참고.

---

## 4. 파일 목록 — 라운드별 하위 폴더

각 라운드가 쓴 모델(§3)·결과표·스크립트(§5)를 한 폴더에서 바로 확인할 수 있도록 정리했다.
스크립트의 `MODEL_DIR`도 각각 이 경로를 가리키도록 맞춰뒀으므로, 재실행하면 같은 폴더에 다시 떨어진다.

각 폴더에는 해당 스크립트를 실행했을 때의 콘솔 로그(`*_log.txt`)도 같이 넣어뒀다 — 결과표
숫자가 어떤 과정으로 나왔는지 재확인하고 싶을 때 참고.

> **2026-07-30 폴더 재정리**: 최종 확정(비지도 Isolation Forest) 이후 `ml/` 최상위 구조가 아래처럼
> 바뀌었다. `ML_0728/`은 최종 MVP 원본으로 승격되어 `mvp_isolation_forest/`로 이름이 바뀌었고,
> 이 파일이 속한 지도학습 비교 실험(`pipeline/`+`models/`)은 참고용임을 명확히 하기 위해
> `archive/supervised_experiments/` 아래로 이동했다. 최신 요약은 `ml/ml_final_report.md` 참고.

```
ml/
├─ ml_final_report.md      최종 확정 요약 보고서 — 여기부터 읽을 것
├─ mvp_isolation_forest/   팀원 원본(구 ML_0728) — 최종 MVP: Isolation Forest 전처리·모델링 노트북 4개 + 결과 요약 md
│   ├─ 법인카드_이상거래_전처리_v2_가맹점제외.ipynb
│   ├─ 법인카드_이상거래_전처리_v3_세그먼트플래그.ipynb
│   ├─ 법인카드_이상거래_모델링_v1_Tier0vs1_비교.ipynb
│   ├─ 법인카드_이상거래_모델링_v2_최종test평가.ipynb
│   └─ isolation_forest_modeling_결과.md   ← §3-3 Isolation Forest 수치의 1차 출처
└─ archive/                참고용 보관 — 현재 배포 대상 아님
   ├─ early_eda_preprocessing/   초기 EDA·전처리 노트북(mvp_isolation_forest가 최신 기준)
   └─ supervised_experiments/    지도학습 8개 모델 비교 실험 (이 README가 속한 폴더)
      ├─ pipeline/               재현 스크립트+노트북(§5) — 이 폴더 안에서 실행
      │   ├─ common_features.py / feature_set_b.py
      │   ├─ model_training.py / .ipynb
      │   ├─ model_tuning.py / .ipynb
      │   └─ supervised_topk_ranking.py / .ipynb
      └─ models/
         ├─ round1_baseline/        §3-1 베이스라인 — pipeline/model_training.py
         │   ├─ {model}.pkl              4개(logistic_regression/random_forest/xgboost/lightgbm)
         │   ├─ model_comparison.csv
         │   └─ model_training_log.txt
         ├─ round2_tuned/           §3-2 튜닝 — pipeline/model_tuning.py, 피처 A(12개)
         │   ├─ {model}_tuned.pkl         5개(2026-08-06: random_forest·balanced_random_forest·extra_trees 3개는 용량 절감을 위해 삭제 — 수치는 tuning_results.csv/.json에 그대로 보존)
         │   ├─ tuning_results.csv / .json
         │   └─ model_tuning_log.txt
         ├─ round3_topk_ranking/    §3-3 top-K% 랭킹 재실행 — pipeline/supervised_topk_ranking.py, 피처 B(15개)
         │   ├─ {model}_topk_ranking.pkl   5개(2026-08-06: random_forest·balanced_random_forest·extra_trees 3개는 용량 절감을 위해 삭제 — 수치는 topk_ranking_results.csv/.json에 그대로 보존)
         │   ├─ topk_ranking_results.csv / .json
         │   └─ supervised_topk_ranking_log.txt
         └─ shared/                 피처 A 재현 정보(원-핫 컬럼 순서 등) — pipeline/model_training.py 산출
             └─ feature_meta.json / .pkl
```

## 5. 재현 스크립트 (`ml/archive/supervised_experiments/pipeline/` 폴더)

| 스크립트 | 역할 |
|---|---|
| `common_features.py` | 피처 A 로딩 공용 로직 |
| `feature_set_b.py` | 피처 B 로딩 공용 로직(우리 지도학습 실험 전용 — §2 주의사항 참고) |
| `model_training.py` | §3-1 베이스라인 |
| `model_tuning.py` | §3-2 튜닝 (약 90분 소요) |
| `supervised_topk_ranking.py` | §3-3, 피처 B + top-K% 평가로 8개 모델 재실행 |

반드시 `ml/archive/supervised_experiments/pipeline/` 안에서 실행할 것(상대 import·상대경로 산출물 저장 때문). 상세:
`ml/archive/supervised_experiments/pipeline/README.md`. Isolation Forest MVP의 재현·재실행 기준은 `ml/mvp_isolation_forest/`의 노트북이다.
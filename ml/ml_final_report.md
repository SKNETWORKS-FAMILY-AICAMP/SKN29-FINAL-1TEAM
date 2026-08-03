# ML 파트 최종 보고서 — 법인카드 이상거래 탐지 (Risk Review 1단계)

> Risk Review MVP의 1차 이상탐지 모델은 **비지도 학습(Isolation Forest)**, 운영 컷오프는 **상위 10%(recall≈79.0%)** 로 확정됐다. 알고리즘·피처셋·컷오프·운영 임계값(score ≥ -0.0123) 모두 확정 완료.
>
> 원본 실험 자료: [`mvp_isolation_forest/`](./mvp_isolation_forest/)(전처리·모델링 노트북 4개 + [`isolation_forest_modeling_결과.md`](./mvp_isolation_forest/isolation_forest_modeling_결과.md)), 비지도 baseline 정량 비교: [`비지도_baseline_비교_결과.md`](./mvp_isolation_forest/비지도_baseline_비교_결과.md), 지도학습 비교(참고용): [`archive/supervised_experiments/`](./archive/supervised_experiments/)

---

## 1. 결론 요약

Risk Review는 **① ML 이상탐지(1차 필터) → ② RAG 내규 검증(2차 정밀 검증) → 회계 담당자 최종 확정** 구조다. ML은 "검토가 필요해 보이는 후보"를 빠르게 추리는 역할만 맡고, 정밀한 규정 위반 판단은 RAG가 담당한다.

| 항목 | 확정 내용 |
|---|---|
| 알고리즘 | **Isolation Forest**(비지도) — 콜드스타트(라벨 0건)에서도 작동, 대용량·정형데이터에 적합 |
| 피처셋 | Tier0(14개) + `일시불할부구분코드`(1개) = **15개** |
| 하이퍼파라미터 | `n_estimators=200`, `max_samples='auto'`, `contamination='auto'`(베이스라인 유지, 튜닝 개선폭 0.26%로 노이즈 수준) |
| 운영 컷오프 | **상위 10%**(recall≈79.0%, precision≈27.6%, 연간 약 46,990건 RAG 전달) |
| 고정 임계값(운영용) | anomaly_score ≥ **-0.0123**(train 점수 분포 90번째 백분위수) |
| test 성능 | PR-AUC **0.5865**(2024년 469,902건, 기저율 3.49%) |

---

## 2. ML을 1차 필터로 두는 이유

`mvp_isolation_forest` 평가 데이터(2024년, 469,902건) 기준, 상위 10% 컷오프를 적용하면 RAG(LLM 호출)가 처리할 물량이 하루 평균 약 129건으로, **전수 처리 대비 약 10배 적다.** Isolation Forest 추론은 로컬 트리 순회 연산이라 임베딩·벡터검색·LLM 추론이 필요한 RAG 경로보다 압도적으로 가볍고, 이는 "동기 REST(MVP)" 아키텍처 원칙과도 부합한다.

**결론**: ML 단계는 완벽할 필요가 없고(정밀 판단은 RAG가 함) **recall(후보를 놓치지 않는 것)** 이 중요하다 — §3의 모델·컷오프 선택 기준이 된다.

---

## 3. Isolation Forest를 선택한 이유

- **지도학습 불가**: 정답(`decision_labels`)은 시스템 운영 후에만 쌓이므로 도입 시점엔 항상 0건(콜드스타트). 카드사 부정사용 라벨(`이상거래여부`)은 정의가 달라(회사 내규 기준 아님) 지도학습 정답으로 대체 불가 — 라벨 없이 작동하는 비지도 학습이 유일한 시작점.
- **비지도 방식 중 Isolation Forest 채택**: DBSCAN(밀도 파라미터 튜닝 난해)·PCA(선형성 가정)·Autoencoder(정형데이터엔 과한 복잡도) 대비, 분포 가정 없이 무작위 분할만으로 이상치를 판단해 가장 적은 전제를 요구함(Liu, Ting & Zhou 2008 외 참고문헌은 원 문서 §3-2 참고).
- **실측 검증**: One-Class SVM·LOF·SGDOneClassSVM과 동일 test set(2024년, 469,902건)으로 비교.

| 모델 | n_train | fit(초) | predict(초) | PR-AUC | recall@top3% |
|---|---:|---:|---:|---:|---:|
| **Isolation Forest** | 1,482,969(전체) | 1.94 | 5.38 | **0.648** | 0.591 |
| One-Class SVM(RBF) | 50,000(서브샘플) | 86.3 | 1,248.3 | 0.432 | 0.543 |
| SGDOneClassSVM | 1,482,969(전체) | 3.01 | 0.02 | 0.315 | 0.358 |
| LOF(novelty, k=20) | 50,000(서브샘플) | 11.5 | 46.1 | 0.037~0.066 | 0.051 |

정확도·연산 효율성 양쪽 모두 Isolation Forest가 우위(상세 진단: [`비지도_baseline_비교_결과.md`](./mvp_isolation_forest/비지도_baseline_비교_결과.md)). 단, 이 표의 PR-AUC(0.648)는 실행 환경(scikit-learn 1.8.0)이 §4 확정치(0.5865, 환경 `final_prj`)와 달라 절대 수치를 직접 비교하면 안 되고 **모델 간 상대 순위만** 유효하다 — 재발 방지로 [`requirements.txt`](./requirements.txt) 고정(scikit-learn 1.5.*, `apps/ai` 서빙 스펙과 일치).

---

## 4. 전처리·피처·최종 성능

- **Train/Test 분할**: 날짜 기준(2021~2023 train / 2024 test) — look-ahead 누수 구조적 차단.
- **가맹점 피처 완전 제외**: 카드 공유 구조상 시간축 정합성 문제가 재발해 제외, 관련 신호는 RAG(`case_history`)로 이관.
- **피처셋 확정(15개)**: Tier0 단독(PR-AUC 0.4711) 대비 Tier1 전체 투입은 저정보 이진 컬럼 희석으로 오히려 -55%. 개별 기여도 검증 결과 `일시불할부구분코드` 1개만 유의미(+7.2%) → 최종 Tier0+1개 조합(0.4946)으로 확정.

**최종 test 성능**(train 1,482,969건 학습 → test 469,902건 단 1회 채점):

| 지표 | 값 |
|---|---|
| PR-AUC | 0.5865 |
| recall@top1% / precision@top1% | 24.9% / 86.8% |
| recall@top3% / precision@top3% | 52.6% / 61.1% |
| recall@top5% / precision@top5% | 66.4% / 46.3% |
| recall@top10% / precision@top10% | 79.0% / 27.6% |

test 성능이 5-fold 평균(0.4946)보다 높은 것은 test 시점 카드의 97%가 이미 3년치 이력을 보유해 확장 통계 피처가 안정된 상태로 평가받기 때문(누수 아님 — pseudo-test로 재확인, 상세: [`isolation_forest_modeling_결과.md`](./mvp_isolation_forest/isolation_forest_modeling_결과.md)). 신규 카드(이력 없음) 세그먼트도 재사용 카드 대비 성능 저하 없음(top3% recall 57.7% vs 52.6%).

**anomaly_score는 확률이 아님**: 정상/이상 그룹 점수 분포가 0.72대까지 겹침. UI·RAG 노출 시 "위험도 N%"가 아니라 백분위 구간별 실측 이상거래 비율(상위 90~100%: 27.58%)로 보정해 사용.

---

## 5. 운영 컷오프 및 한계

**운영 컷오프 = 상위 10%**(recall≈79.0%, precision≈27.6%). 기존 잠정값(상위 3%)은 recall 52.6%로 "이상거래를 놓치지 않는다"는 원칙에 미달 — False Negative(누락)는 RAG·사람 어느 단계에도 닿지 못해 영구 누락되는 반면 False Positive는 사람이 한 번 더 보면 그만인 비대칭 비용 구조라 recall을 우선했다. recall 90% 이상(검토량 32.68%~)은 §2의 효율성 전제가 무너져 채택하지 않음.

**고정 임계값**: 실시간 거래 판정용 고정 threshold score는 **-0.0123**(train 점수 분포 90번째 백분위수)으로 재계산 완료 — test 적용 시 실제 분류 비율 12.79%, recall 85.1%, precision 23.2%(재현 코드·상세: [`고정_임계값_재계산.py`](./mvp_isolation_forest/고정_임계값_재계산.py), [`isolation_forest_modeling_결과.md §5`](./mvp_isolation_forest/isolation_forest_modeling_결과.md)). 알고리즘·피처셋·컷오프·운영 임계값 모두 확정되어 ML 파트는 마무리됐다.

---

## 6. 향후 시스템 통합 기대 효과

- **RAG 호출량 절감**: 전체 거래가 아닌 ML이 추린 소수 후보만 RAG로 전달(전체 대비 약 10%).
- **실시간 동기 처리 유지**: 로컬 연산으로 지연 없어 "동기 REST(MVP)" 원칙 안에서 수행 가능.
- **설명 가능한 2단계 근거**: anomaly_score(통계적 이상) + RAG 근거(내규 조항)를 함께 제시.
- **점진적 고도화 경로**: `decision_labels` 축적 후 지도학습·하이브리드 스코어링을 post-MVP로 검토 가능.

---

## 7. 참고 파일 목록

| 경로 | 내용 |
|---|---|
| [`mvp_isolation_forest/`](./mvp_isolation_forest/) | 최종 확정 MVP — 전처리·모델링 원본 노트북 4개 + [`isolation_forest_modeling_결과.md`](./mvp_isolation_forest/isolation_forest_modeling_결과.md)(§2~§5 수치의 1차 출처) |
| [`mvp_isolation_forest/비지도_baseline_비교_결과.md`](./mvp_isolation_forest/비지도_baseline_비교_결과.md) | §3 실측 비교의 1차 출처. 재현 코드: [`unsupervised_baseline_비교.py`](./mvp_isolation_forest/unsupervised_baseline_비교.py) |
| [`archive/supervised_experiments/`](./archive/supervised_experiments/) | 지도학습 8개 모델 비교(참고용, 배포 대상 아님) |
| [`archive/early_eda_preprocessing/`](./archive/early_eda_preprocessing/) | 초기 EDA·전처리 노트북(참고용, `mvp_isolation_forest/`가 최신 기준) |

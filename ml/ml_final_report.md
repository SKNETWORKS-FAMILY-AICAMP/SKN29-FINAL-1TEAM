# ML 파트 최종 보고서 — 법인카드 이상거래 탐지 (Risk Review 1단계)

> Risk Review MVP의 1차 이상탐지 모델은 **비지도 학습(Isolation Forest)**, 운영 컷오프는 **상위 10%(recall≈79.0%)** 로 확정됐다. 알고리즘·피처셋·컷오프·운영 임계값(score ≥ -0.0123) 모두 확정 완료.
>
> 원본 실험 자료: [`mvp_isolation_forest/`](./mvp_isolation_forest/)(전처리·모델링 노트북 4개 + [`isolation_forest_modeling_결과.md`](./mvp_isolation_forest/isolation_forest_modeling_결과.md)), 비지도 baseline 정량 비교: [`비지도_baseline_비교_결과.md`](./mvp_isolation_forest/비지도_baseline_비교_결과.md), 추가 비지도 모델 7종 비교(2026-08-04): [`ECOD_COPOD_비교실험.ipynb`](<./비지도학습 정리/법인카드_이상거래_ECOD_COPOD_비교실험.ipynb>), 지도학습 비교(참고용): [`archive/supervised_experiments/`](./archive/supervised_experiments/)

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

서비스 배포 전에는 회계 담당자의 실제 승인/반려 기록(`decision_labels`)이 0건이라(콜드스타트) 지도학습 자체가 불가능했다. 카드사 부정사용 라벨(`이상거래여부`)도 정의가 달라(회사 내규 기준 아님) 정답으로 쓸 수 없다 — 그래서 라벨 없이 작동하는 **비지도 학습**을 택했다. 그중 Isolation Forest는 분포 가정 없이 무작위 분할만으로 이상치를 판단해 대용량·정형데이터에 가장 적은 전제를 요구하며(DBSCAN·PCA·Autoencoder 대비, Liu, Ting & Zhou 2008), 아래처럼 비지도 대안 10종과 실측 비교해도 가장 우수했다.

| 모델 | PR-AUC | recall@top3% | 비고 |
|---|---:|---:|---|
| **Isolation Forest** | **0.5865** | 52.6% | §4 확정 test 성능 |
| COPOD | 0.5330 | 48.0% | 완전 결정론적, 튜닝 불필요 |
| One-Class SVM(RBF) | 0.432 | 54.3% | 서브샘플 5만 건, predict 1,248초(≈21분) — 정확도 근접해도 속도 열위 |
| ECOD | 0.4294 | 40.0% | 완전 결정론적, 튜닝 불필요 |
| CBLOF | 0.3858 | 44.2% | 클러스터 기반(`n_clusters=8`) |
| PCA | 0.3833 | 43.9% | 재구성 오차 기반 |
| INNE | 0.3762 | 39.3% | |
| GMM(`n_components=5`) | 0.3418 | 43.0% | |
| SGDOneClassSVM | 0.315 | 35.8% | 선형 경계 — 비선형 이상패턴 포착 부족 |
| LOF(novelty, k=20) | 0.037~0.066 | 5.1% | 서브샘플 5만 건, 저정보 원-핫 컬럼에서 거리기반 판별력 거의 없음 |
| LODA | 0.0283 | 1.6% | 기저율(3.49%) 대비 판별력 사실상 없음 |

10개 대안 모두 Isolation Forest보다 낮았고, 최근접 경쟁모델 COPOD와는 5-fold paired t-test로 유의성까지 확인했다(t=4.929, **p=0.0079** < 0.05). 상세 비교 근거: [`비지도_baseline_비교_결과.md`](./mvp_isolation_forest/비지도_baseline_비교_결과.md), [`ECOD_COPOD_비교실험.ipynb`](<./비지도학습 정리/법인카드_이상거래_ECOD_COPOD_비교실험.ipynb>)

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

test 성능이 5-fold 평균(0.4946)보다 높은 이유·신규 카드 세그먼트 분석은 [`isolation_forest_modeling_결과.md §4`](./mvp_isolation_forest/isolation_forest_modeling_결과.md) 참고(요약: test 시점 카드의 97%가 이미 3년치 이력을 보유해 누수가 아니며, 신규 카드도 성능 저하 없음).

**anomaly_score는 확률이 아님**: 정상/이상 그룹 점수 분포가 0.72대까지 겹친다. UI·RAG에는 raw score를 그대로 노출하지 않고 백분위 구간별 실측 이상거래 비율(상위 90~100%: 27.58%)로 보정해 사용한다 — 보정표 전체는 [`isolation_forest_modeling_결과.md §4`](./mvp_isolation_forest/isolation_forest_modeling_결과.md) 참고.

---

## 5. 운영 컷오프 및 한계

**운영 컷오프 = 상위 10%**(recall≈79.0%, precision≈27.6%), **고정 임계값 = anomaly_score ≥ -0.0123**(train 점수 분포 90번째 백분위수). recall을 precision보다 우선한 이유(False Negative의 비대칭 비용), 컷오프를 3%→10%로 올린 근거, recall 목표별 필요 검토 비율, fold4 변동성 조사까지의 전체 도출 과정은 [`isolation_forest_modeling_결과.md §5·§7`](./mvp_isolation_forest/isolation_forest_modeling_결과.md)에 정리돼 있다. 알고리즘·피처셋·컷오프·운영 임계값 모두 확정되어 ML 파트는 마무리됐다.

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
| [`mvp_isolation_forest/비지도_baseline_비교_결과.md`](./mvp_isolation_forest/비지도_baseline_비교_결과.md) | §3 실측 비교 중 One-Class SVM·SGD·LOF의 1차 출처(2026-07-31). 재현 코드: [`unsupervised_baseline_비교.py`](./mvp_isolation_forest/unsupervised_baseline_비교.py) |
| [`비지도학습 정리/법인카드_이상거래_ECOD_COPOD_비교실험.ipynb`](<./비지도학습 정리/법인카드_이상거래_ECOD_COPOD_비교실험.ipynb>) | §3 실측 비교 중 ECOD·COPOD·INNE·LODA·GMM·CBLOF·PCA 7종 + COPOD paired t-test(p=0.0079)의 1차 출처(2026-08-04) |
| [`archive/supervised_experiments/`](./archive/supervised_experiments/) | 지도학습 8개 모델 비교(참고용, 배포 대상 아님) |
| [`archive/early_eda_preprocessing/`](./archive/early_eda_preprocessing/) | 초기 EDA·전처리 노트북(참고용, `mvp_isolation_forest/`가 최신 기준) |

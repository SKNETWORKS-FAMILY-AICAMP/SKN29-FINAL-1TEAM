# ml/ — 법인카드 이상거래 탐지 작업 전체 안내

이 폴더에 뭐가 있는지 한눈에 찾기 위한 최상위 안내. **최종 확정(2026-07-30): 비지도 학습(Isolation Forest)** 으로
MVP 방향이 정해졌고, 그에 맞춰 폴더 구조를 재정리했다(구성 이력은 각 하위 README 상단의 "폴더 재정리" 메모 참고).

| 폴더/파일 | 내용 | 상태 |
|---|---|---|
| [`ml_final_report.md`](./ml_final_report.md) | **여기부터 읽을 것** — ML 파트 목표·모델 선정 논리·전처리 과정·향후 통합 기대효과를 정리한 최종 보고서 | 완료 |
| [`mvp_isolation_forest/`](./mvp_isolation_forest/) | **최종 확정 MVP** — Isolation Forest(비지도) 전처리·모델링 원본 노트북 4개 + 결과 요약 md·재현 스크립트 (구 `ML_0728/`) | 커밋됨 |
| [`비지도학습 정리/`](./비지도학습%20정리/) | ECOD·COPOD 등 비지도 대안 7종 추가 비교(2026-08-04) + paired t-test — `ml_final_report.md §3` 근거 | 커밋됨 |
| [`archive/supervised_experiments/`](./archive/supervised_experiments/) | 참고용 — 지도학습 8개 모델 비교 실험(재현 스크립트 `pipeline/` + 산출물 `models/`). **배포 대상 아님** | 커밋됨(참고용 보관) |
| [`archive/early_eda_preprocessing/`](./archive/early_eda_preprocessing/) | 참고용 — 초기 EDA 노트북 3개 + 전처리 노트북 + 리뷰 통합본. `mvp_isolation_forest/`가 최신 기준 | 커밋됨(참고용 보관) |

## 전체 파일 트리 (폴더·파일 1~2줄 설명)


```
ml/
├─ README.md                                            이 파일 — 전체 안내
├─ ml_final_report.md                                   ★ 최종 보고서 — 목표·모델 선정 논리·전처리 과정·성능·기대효과 총정리
├─ requirements.txt                                      ml/ 재현용 의존성 고정(scikit-learn 1.5.1 등, apps/ai 서빙 스펙에 맞춤)
│
├─ mvp_isolation_forest/                                 ★ 최종 확정 MVP — Isolation Forest(비지도) 원본 작업
│  ├─ README.md                                          이 폴더 파일별 설명
│  ├─ isolation_forest_modeling_결과.md                   실험 전체 수치·근거(운영 컷오프·임계값·fold4 조사 포함) — 노트북 다음으로 먼저 볼 문서
│  ├─ 법인카드_이상거래_전처리_v2_가맹점제외.ipynb          전처리 — 가맹점 관련 피처 제외 버전
│  ├─ 법인카드_이상거래_전처리_v3_세그먼트플래그.ipynb      전처리 — 재사용/신규 카드 구분 플래그 추가(최신)
│  ├─ 법인카드_이상거래_모델링_v1_Tier0vs1_비교.ipynb      모델링 — 피처셋(Tier0 단독 vs 전체) 비교 실험
│  ├─ 법인카드_이상거래_모델링_v2_최종test평가.ipynb       모델링 — 최종 피처셋으로 학습 후 test 평가(딱 한 번)
│  ├─ 비지도_baseline_비교_결과.md                        One-Class SVM·SGD·LOF 실측 비교(2026-07-31)
│  ├─ unsupervised_baseline_비교.py                       위 비교 실험 재현 스크립트
│  ├─ 고정_임계값_재계산.py / _result.json                 운영 임계값(-0.0123) 산정 재현 스크립트·결과
│  └─ fold4_원인조사.py / _result.json                     fold4 변동성이 버그가 아님을 검증한 재현 스크립트·결과
│
├─ 비지도학습 정리/                                        추가 비지도 모델 비교(2026-08-04)
│  └─ 법인카드_이상거래_ECOD_COPOD_비교실험.ipynb           ECOD·COPOD·INNE·LODA·GMM·CBLOF·PCA 7종 + paired t-test
│
└─ archive/                                              참고용 보관 — 현재 배포 대상 아님(지우지 않고 남긴 이유는 근거 추적용)
   ├─ README.md                                          이 폴더 안내
   │
   ├─ early_eda_preprocessing/                           참고용 — 초기 EDA·전처리(최신 아님, mvp_isolation_forest가 최신 기준)
   │  ├─ README.md                                        이 폴더 파일별 설명
   │  ├─ 법인카드_이상거래_EDA.ipynb                       최초 탐색적 데이터 분석(EDA)
   │  ├─ 법인카드_이상거래_EDA_v2.ipynb                    EDA 2차 — 추가 탐색
   │  ├─ 법인카드_이상거래_EDA_v3.ipynb                    EDA 3차 — 추가 탐색
   │  ├─ 법인카드_이상거래_전처리.ipynb                     초기 전처리(가맹점 피처 제외·시간 기준 분할 반영 전 버전)
   │  └─ 전처리_노트북_리뷰_통합본.md                       위 전처리 노트북에 대한 리뷰 정리
   │
   └─ supervised_experiments/                            참고용 — 지도학습 8개 모델 비교 실험(배포 대상 아님)
      ├─ pipeline/                                       재현 스크립트 — 반드시 이 폴더 안에서 실행
      │  ├─ README.md                                     스크립트별 역할·실행법 설명
      │  ├─ common_features.py                            피처 A(12개) 로딩 공용 로직
      │  ├─ feature_set_b.py                              피처 B(15개) 로딩 공용 로직
      │  ├─ model_training.py / .ipynb                    1라운드 — 베이스라인 4개 모델 학습
      │  ├─ model_tuning.py / .ipynb                       2라운드 — 하이퍼파라미터+임계값 튜닝(8개 모델, ~90분)
      │  └─ supervised_topk_ranking.py / .ipynb            3라운드 — 상위 K% 랭킹 재평가(8개 모델, 피처 B)
      │
      └─ models/                                         위 스크립트들의 산출물(학습된 모델·결과표·로그)
         ├─ README.md                                     ★ 지도학습 3라운드 결과·수치 총정리
         ├─ round1_baseline/                               1라운드 산출물
         │  ├─ {model}.pkl (4개)                            학습된 모델 4개(로지스틱회귀·RF·XGBoost·LightGBM)
         │  ├─ model_comparison.csv                         모델별 성능 비교표
         │  └─ model_training_log.txt                       실행 로그
         ├─ round2_tuned/                                  2라운드 산출물(피처 A, 8개 모델)
         │  ├─ {model}_tuned.pkl (8개)                      튜닝된 모델 8개
         │  ├─ tuning_results.csv / .json                   튜닝 결과표
         │  └─ model_tuning_log.txt                         실행 로그
         ├─ round3_topk_ranking/                           3라운드 산출물(피처 B, 8개 모델)
         │  ├─ {model}_topk_ranking.pkl (8개)                재실행된 모델 8개
         │  ├─ topk_ranking_results.csv / .json             top-K% 랭킹 결과표
         │  └─ supervised_topk_ranking_log.txt              실행 로그
         └─ shared/                                        피처 A 재현 정보
            └─ feature_meta.json / .pkl                     원-핫 인코딩 컬럼 순서 등 메타데이터
```

`★` 표시는 "먼저 읽을 문서" — 나머지는 필요할 때 세부 근거를 찾아보는 용도다.

## 결론만 빠르게 보고 싶다면

[`ml_final_report.md`](./ml_final_report.md) 하나만 읽으면 된다 — 왜 ML을 1차 필터로 앞세우는지, 왜 비지도
학습·Isolation Forest를 택했는지, 피처 15개는 어떻게 확정됐는지, 성능·한계·다음 단계가 모두 정리돼 있다.

## 모델링 상세 수치를 보고 싶다면

`mvp_isolation_forest/isolation_forest_modeling_결과.md` — 최종 채택된 Isolation Forest의 실험 원본(전처리 결정,
피처 ablation, 최종 test 평가, 운영 임계값 산정 근거까지 전부 포함).

지도학습과의 비교 수치가 궁금하면 `archive/supervised_experiments/models/README.md` 참고(단, 이 트랙은
MVP 배포 대상이 아니라 "나중에 라벨이 쌓이면 얼마나 더 잘할 수 있는지" 미리 살펴본 참고 자료다).

## 코드를 재현/재실행하고 싶다면

- **Isolation Forest(최종 MVP)**: `mvp_isolation_forest/`의 노트북 4개가 기준. 비지도 baseline 비교·임계값 재계산·fold4
  조사는 같은 폴더의 `.py` 스크립트(`unsupervised_baseline_비교.py`, `고정_임계값_재계산.py`, `fold4_원인조사.py`)로 재현 가능.
- **추가 비지도 모델 비교(ECOD/COPOD 등)**: `비지도학습 정리/법인카드_이상거래_ECOD_COPOD_비교실험.ipynb`.
- **지도학습 8개(참고용)**: `archive/supervised_experiments/pipeline/`의 스크립트를 그 폴더 안에서 실행한다
  (예: `cd ml/archive/supervised_experiments/pipeline && python model_training.py`).

# ml/ — 법인카드 이상거래 탐지 작업 전체 안내

이 폴더에 뭐가 있는지 한눈에 찾기 위한 최상위 안내. **최종 확정(2026-07-30): 비지도 학습(Isolation Forest)** 으로
MVP 방향이 정해졌고, 그에 맞춰 폴더 구조를 재정리했다(구성 이력은 각 하위 README 상단의 "폴더 재정리" 메모 참고).

| 폴더/파일 | 내용 | 상태 |
|---|---|---|
| [`ml_final_report.md`](./ml_final_report.md) | **여기부터 읽을 것** — ML 파트 목표·모델 선정 논리·전처리 과정·향후 통합 기대효과를 정리한 최종 보고서 | 완료 |
| [`mvp_isolation_forest/`](./mvp_isolation_forest/) | **최종 확정 MVP** — Isolation Forest(비지도) 전처리·모델링 원본 노트북 4개 + 결과 요약 md (구 `ML_0728/`) | 커밋됨 |
| [`archive/supervised_experiments/`](./archive/supervised_experiments/) | 참고용 — 지도학습 8개 모델 비교 실험(재현 스크립트 `pipeline/` + 산출물 `models/`). **배포 대상 아님** | 커밋됨(참고용 보관) |
| [`archive/early_eda_preprocessing/`](./archive/early_eda_preprocessing/) | 참고용 — 초기 EDA 노트북 3개 + 전처리 노트북 + 리뷰 통합본. `mvp_isolation_forest/`가 최신 기준 | 커밋됨(참고용 보관) |

## 결론만 빠르게 보고 싶다면

[`ml_final_report.md`](./ml_final_report.md) 하나만 읽으면 된다 — 왜 ML을 1차 필터로 앞세우는지, 왜 비지도
학습·Isolation Forest를 택했는지, 피처 15개는 어떻게 확정됐는지, 성능·한계·다음 단계가 모두 정리돼 있다.

## 모델링 상세 수치를 보고 싶다면

`mvp_isolation_forest/isolation_forest_modeling_결과.md` — 최종 채택된 Isolation Forest의 실험 원본(전처리 결정,
피처 ablation, 최종 test 평가, 운영 임계값 산정 근거까지 전부 포함).

지도학습과의 비교 수치가 궁금하면 `archive/supervised_experiments/models/README.md` 참고(단, 이 트랙은
MVP 배포 대상이 아니라 "나중에 라벨이 쌓이면 얼마나 더 잘할 수 있는지" 미리 살펴본 참고 자료다).

## 코드를 재현/재실행하고 싶다면

- **Isolation Forest(최종 MVP)**: `mvp_isolation_forest/`의 노트북 4개가 기준. 별도 재현 스크립트는 없다.
- **지도학습 8개(참고용)**: `archive/supervised_experiments/pipeline/`의 스크립트를 그 폴더 안에서 실행한다
  (예: `cd ml/archive/supervised_experiments/pipeline && python model_training.py`).

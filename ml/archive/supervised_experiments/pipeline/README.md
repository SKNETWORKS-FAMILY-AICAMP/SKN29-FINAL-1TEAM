# ml/archive/supervised_experiments/pipeline/ — 지도학습 재현 스크립트 (참고용, 배포 대상 아님)

라운드별로 어떤 파일이 뭘 하는지 바로 찾기 위한 표. 각 스크립트는 실행하면 `../models/<라운드 폴더>/`에
결과를 저장한다(자세한 결과 숫자는 `../models/README.md` 참고).

| 스크립트 | 노트북(같은 내용, 셀 단위 + 실제 실행 로그) | 라운드 | 산출물 폴더 |
|---|---|---|---|
| `model_training.py` | `model_training.ipynb` | §3-1 베이스라인(기본 설정값, 4개 모델) | `../models/round1_baseline/` |
| `model_tuning.py` | `model_tuning.ipynb` | §3-2 하이퍼파라미터+임계값 튜닝(8개 모델, 약 90분) | `../models/round2_tuned/` |
| `supervised_topk_ranking.py` | `supervised_topk_ranking.ipynb` | §3-3 top-K% 랭킹 재실행(8개 모델, 피처 B) | `../models/round3_topk_ranking/` |
| `common_features.py` | — | 피처 A 로딩 공용 로직(`model_training.py`/`model_tuning.py`가 사용) | — |
| `feature_set_b.py` | — | 피처 B 로딩 공용 로직(`supervised_topk_ranking.py`가 사용) | — |

**실행 방법**: 반드시 이 폴더 안에서 실행할 것(`cd ml/archive/supervised_experiments/pipeline && python model_training.py`) —
스크립트들이 같은 폴더의 `common_features.py`/`feature_set_b.py`를 상대 import하고, 산출물
경로도 스크립트 위치 기준 상대경로(`../models/...`)로 계산한다.

Isolation Forest(최종 MVP)는 이 폴더에 없다 — `../../../mvp_isolation_forest/`의 팀원 원본 노트북 참고.
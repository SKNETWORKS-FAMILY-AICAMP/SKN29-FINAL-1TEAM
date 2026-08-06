# mvp_isolation_forest/ — 최종 확정 MVP (구 `ML_0728/`)

**최종 확정(2026-07-30)된 Risk Review 1차 필터 모델, Isolation Forest(비지도)의 원본 작업 폴더.**
팀원이 직접 전처리·모델링·평가를 수행한 노트북과 그 결과 요약 문서가 들어있다.

| 파일 | 역할 |
|---|---|
| `법인카드_이상거래_전처리_v2_가맹점제외.ipynb` | 전처리 — 가맹점 관련 피처를 제외한 버전 |
| `법인카드_이상거래_전처리_v3_세그먼트플래그.ipynb` | 전처리 — 재사용/신규 카드 구분 플래그 추가(최신) |
| `법인카드_이상거래_모델링_v1_Tier0vs1_비교.ipynb` | 모델링 — 피처셋(Tier0 단독 vs 전체) 비교 실험 |
| `법인카드_이상거래_모델링_v2_최종test평가.ipynb` | 모델링 — 최종 확정 피처셋으로 학습 후 test 평가(딱 한 번) |
| `isolation_forest_modeling_결과.md` | 위 실험 전체의 수치·근거 요약(운영 컷오프·고정 임계값·fold4 조사 포함) — **가장 먼저 열어볼 문서** |
| `비지도_baseline_비교_결과.md` | One-Class SVM/LOF/SGDOneClassSVM과의 정량 비교(2026-07-31 추가) — PR-AUC·연산시간 실측, LOF 부호 진단, sklearn 버전차 안내 |
| `unsupervised_baseline_비교.py` | 위 비교 실험 재현 스크립트(`DATA_DIR`만 맞추면 재실행 가능) |
| `고정_임계값_재계산.py` / `_result.json` | 운영 임계값(anomaly_score ≥ -0.0123) 산정 재현 스크립트와 그 결과 |
| `fold4_원인조사.py` / `_result.json` | 5-fold 중 fold4만 낮게 나오는 현상이 버그가 아닌 정상 표본 변동임을 검증한 재현 스크립트와 그 결과 |

전체 요약·왜 이 방향으로 확정됐는지는 상위 폴더의 [`ml_final_report.md`](../ml_final_report.md) 참고.
발표용으로 더 간단히 정리한 버전은 팀 아티팩트("ML 파트 요약") 참고.

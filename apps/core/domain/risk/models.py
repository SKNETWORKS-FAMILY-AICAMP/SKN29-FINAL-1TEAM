"""Risk 결과/학습 라벨 (기술명세서 §3.1).

테이블:
- risk_reviews(tx_id, anomaly_score, reasons JSONB)
    ※ MVP: 비지도 이상탐지(1차) + RAG 내규 검증(2차) 결과.
      review_prob 컬럼은 post-MVP 지도학습 도입 시 추가.
- decision_labels(tx_id, label[승인/반려/보완/수정], actor, ts)
    ※ MVP는 '적재만' — 향후 지도학습용. 자동 재학습은 post-MVP.
TODO: 모델 구현.
"""
from django.db import models  # noqa: F401

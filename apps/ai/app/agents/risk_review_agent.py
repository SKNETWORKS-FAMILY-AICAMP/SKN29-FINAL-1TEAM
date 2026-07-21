"""③ Risk Review Agent — MVP 2단계 (요구사항 §5.5 / 기술명세서 §4.3).

  [1차] 단순 이상거래 탐지(비지도) → anomaly_score → 컷오프 이상만 '이상 후보' 선별
  [2차] RAG 내규 기반 검증(이상 후보 한정) → 내규 위반 여부 + 권장의견(출처 포함)

※ 지도학습(review_probability)·자동 재학습 피드백 루프는 post-MVP 확장.
  회계 결정(decision_labels)은 MVP에선 '적재만'.
스캐폴드: stub 반환.
"""
from app.ml.registry import get_active_model


def run(settlement_id: int, feature_vector: list[float] | None = None) -> dict:
    # [1차] 이상탐지
    model = get_active_model()
    if model and model.fitted and feature_vector:
        stage1 = model.score(feature_vector)
    else:
        stage1 = {"anomaly_score": 0.0, "is_outlier": False, "note": "no trained model (stub)"}

    # [2차] RAG 내규 검증 — 이상 후보에 한해 search_policy/search_cases + LLM (TODO)
    stage2 = {"verified": False, "recommendation": None, "refs": [], "note": "RAG 검증 stub"}

    return {
        "settlement_id": settlement_id,
        "stage1_anomaly": stage1,
        "stage2_rag_review": stage2,
        "status": "stub",
    }

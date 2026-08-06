"""anomaly_score 보정 — ml_final_report.md §9·§10 확정 로직 이식.

anomaly_score는 확률이 아니다(정상/이상 그룹 분포가 0.72대까지 겹침, §9). 이 모듈은
① train 점수 분포의 백분위수를 고정 운영 임계값으로 변환하고, ② test 점수 10분위 구간별
실측 이상거래 비율을 UI/RAG 노출용 보정표로 만든다.

출처: ml/mvp_isolation_forest/고정_임계값_재계산.py(임계값), 법인카드_이상거래_ECOD_COPOD_비교실험.ipynb
셀13 `decile_calibration_table`(보정표) — 정의를 그대로 이식.
"""
from __future__ import annotations

import numpy as np


def fixed_threshold(train_scores: np.ndarray, percentile: float = 90.0) -> float:
    """운영 임계값 = train 점수 분포의 percentile번째 백분위수(§10, 상위 10% 컷오프 → 90번째 백분위수)."""
    return float(np.percentile(train_scores, percentile))


def decile_calibration_table(y_true: np.ndarray, scores: np.ndarray) -> list[dict]:
    """점수 10분위 구간별 실측 이상거래 비율. anomaly_score를 "위험도 N%"로 직접 노출하는 대신
    이 표를 근거로 "이 점수대는 과거 기준 약 X% 확률로 이상거래였다"는 식으로 사용한다(§9).
    """
    edges = np.percentile(scores, np.arange(0, 101, 10))
    band_idx = np.clip(np.searchsorted(edges, scores, side="right") - 1, 0, 9)
    base_rate = float(y_true.mean()) if len(y_true) > 0 else 0.0

    table: list[dict] = []
    for i in range(10):
        mask = band_idx == i
        n = int(mask.sum())
        rate = float(y_true[mask].mean()) if n > 0 else 0.0
        table.append({
            "band": f"{i * 10}~{(i + 1) * 10}%",
            "score_lower_bound": float(edges[i]),
            "n": n,
            "observed_rate": round(rate, 4),
            "lift_vs_base_rate": round(rate / base_rate, 2) if base_rate > 0 else None,
        })
    return table


def lookup_calibration(score: float, calibration_table: list[dict] | None) -> dict | None:
    """score가 속하는 구간을 calibration_table(오름차순 가정)에서 찾아 반환."""
    if not calibration_table:
        return None
    matched = calibration_table[0]
    for row in calibration_table:
        if score >= row["score_lower_bound"]:
            matched = row
        else:
            break
    return matched

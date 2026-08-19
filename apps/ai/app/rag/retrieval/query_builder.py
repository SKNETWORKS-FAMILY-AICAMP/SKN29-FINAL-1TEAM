"""Risk Review 2차 검증 — policy_docs 검색 질의 조립.

retrive 브랜치 `retrieval_strategy_evaluation.ipynb` §11 실측(2026-08-16) — 지금까지 검색어에
원시 ML 피처명(model.feature_columns)을 그대로 이어붙이고 있었다("업무추진비 한정식당 청담점
거래금액_Zscore_확장"). 규정 문서 어디에도 없는 어휘라 policy_docs 검색에서 순수 잡음으로
작용해 MRR이 4가지 방식 중 최하위(0.19)였다. 아래는 그 노트북이 검증한 "자연어+판정사실"
방식(n=17 기준 블롭 대비 유의한 우세, agentic 방식 다음으로 좋음 — LLM 호출을 추가하지
않는 결정론적 방식 중 최선이라 채택).

애초에 `retrieval_strategy_evaluation.ipynb`의 슬롯→쿼리 렌더링은 "실제 구현이 생기면
`app/rag/retrieval/`로 옮긴다"고 스스로 예고해 둔 프로토타입이었다 — 이 모듈이 그 이관이다.
Risk Review Agent 전용으로 시작했지만, "질의를 어떻게 조립할지"는 검색 도메인의 관심사이지
특정 Agent의 관심사가 아니므로 여기 둔다(다른 Agent가 policy_docs를 검색할 때도 재사용 가능).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# model.feature_columns 기준 이름 → 자연어 설명. 원-핫 인코딩된 3개(거래요일_한글·시간대구간·
# 일시불할부구분코드)는 "{컬럼명}_{범주값}" 형태로 나오므로 접두 매칭한다(feature_hint_nl 참고).
FEATURE_HINT_NL: dict[str, str] = {
    "승인시간대": "결제가 일어난 시간대가 평소와 다른 점",
    "통합승인금액": "결제 금액이 평소와 다르게 크거나 작은 점",
    "거래요일_한글": "결제 요일이 이례적인 점",
    "시간대구간": "결제 시간대 구간이 평소와 다른 점",
    "월말여부": "월말 시점에 결제가 몰린 점",
    "취소성거래_추정": "취소·정정 가능성이 있는 결제로 추정되는 점",
    "최근7일사용횟수": "최근 일주일간 결제 횟수가 평소와 다른 점",
    "카드누적사용액": "카드 누적 사용 금액이 평소와 다른 점",
    "사용자평균사용액_확장": "이 사용자의 평소 평균 결제 금액과 차이가 큰 점",
    "사용자표준편차_확장": "이 사용자의 결제 금액 변동 폭이 평소와 다른 점",
    "거래금액_Zscore_확장": "평소 대비 결제 금액이 통계적으로 크게 벗어난 점",
    "카드첫거래여부": "해당 가맹점과의 첫 거래라는 점",
    "일시불할부구분코드": "일시불·할부 결제 구분이 평소와 다른 점",
}

FALLBACK_FEATURE_HINT_NL = "이례적인 결제 패턴이 감지된 점"


def feature_hint_nl(raw_feature: str) -> str:
    """원시 피처명 → 자연어. 매핑에 없는 이름은 화이트리스트 밖으로 보고 그대로 새지 않게 막는다."""
    if raw_feature in FEATURE_HINT_NL:
        return FEATURE_HINT_NL[raw_feature]
    for base, phrase in FEATURE_HINT_NL.items():
        if raw_feature.startswith(f"{base}_"):  # 원-핫 인코딩된 컬럼(예: 시간대구간_심야(00-05))
            return phrase
    logger.warning("feature_hint_nl: 매핑에 없는 피처명 %r — FEATURE_HINT_NL을 갱신할 것", raw_feature)
    return FALLBACK_FEATURE_HINT_NL


# Settlement의 판정 입력 필드(전부 null 허용 — None="모름")를 검색어 문장에 녹일 조각으로 변환.
# 모르는 값은 지어내지 않고 생략한다(§ Settlement 모델 "판정 입력 필드" 주석과 동일 계약).
_BOOL_FACT_PHRASES: dict[str, tuple[str, str]] = {
    # 필드명: (True일 때 문구, False일 때 문구)
    "preApproved": ("사전승인 받음", "사전승인 받지 않음"),
    "kickbackTarget": ("청탁금지법 대상자 참석", "청탁금지법 대상자 없음"),
    "isSecondaryVenue": ("2차 성격 지출", "2차 성격 아님"),
    "includesAlcohol": ("주류 포함", "주류 미포함"),
}


def facts_nl(summary: dict) -> str:
    parts: list[str] = []
    headcount = summary.get("headcount")
    if headcount is not None:
        parts.append(f"참석 인원 {headcount}명")
    item_type = summary.get("itemType")
    if item_type:
        parts.append(f"지출유형 {item_type}")
    for field, (if_true, if_false) in _BOOL_FACT_PHRASES.items():
        value = summary.get(field)
        if value is not None:
            parts.append(if_true if value else if_false)
    return ", ".join(parts)


def build_query(category: str, merchant: str, contribs: list[dict], summary: dict) -> str:
    """policy_docs 검색용 자연어 질의. 원시 피처명·내부 코드값을 문장에 그대로 넣지 않는다.

    [수정 ①] 실 IN_REVIEW 정산 30건 재실측(2026-08-18) — 모든 질의를 "규정 위반 여부를
    확인해야 합니다"로 맺던 고정 문구를 제거했다. 서로 무관한 지출 30건의 검색 결과 73%가
    지출 내용과 무관하게 「업무추진비_사용규정」제10조(위반 시 조치)·별표2 단 두 조문으로
    쏠리는 현상이 발견됐고, "위반"이라는 반복 토큰이 "위반 시 조치"류 조문 쪽으로 검색을
    끌어당기는 것이 유력한 원인으로 지목됐다. 고정 문구를 제거한 버전이 통계적으로 유의하게
    더 나았다(같은 30건 짝비교, ΔMRR +0.020, 95% CI [+0.005, +0.039] — 0 미포함).

    [수정 ②] contribs가 비어 있을 때(현재 배포된 이상탐지 모델의 상시 상태 — feature_stats
    부재로 feature_contribs()가 항상 빈 배열을 반환함) "이례적인 결제 패턴이 감지된 점"이라는
    채움 문구도 생략했다. ⚠️ 이건 ①과 달리 통계적으로 확정되지 않았다 — 회계 담당자 검증
    라벨(purpose 반영, 30건)로 재본 결과 MRR은 소폭 상승(0.129→0.149)했지만 Recall@1은
    오히려 하락(6.7%→3.3%)했고, 짝비교 95% CI [-0.061, +0.084]가 0을 포함한다(잡음과
    구분 안 됨). 표본이 작은 상태에서 점추정만 보고 적용한 변경이라는 점을 남겨둔다.

    ⚠️ 정답 라벨은 사람이 아니라 AI가 규정 원문을 직접 읽고 독립적으로 판단한 것이라 실제
    회계 검토를 대체하지 않는다(`.personal/RAG/stage2_검토용_실데이터_30건.csv` 참고).
    """
    if contribs:
        reasons = ", ".join(feature_hint_nl(c["feature"]) for c in contribs)
        query = f"{merchant}에서 발생한 {category} 결제가 이상거래로 탐지됐습니다. {reasons}."
    else:
        query = f"{merchant}에서 발생한 {category} 결제입니다."
    facts = facts_nl(summary)
    if facts:
        query += f" 거래 사실: {facts}."
    return query
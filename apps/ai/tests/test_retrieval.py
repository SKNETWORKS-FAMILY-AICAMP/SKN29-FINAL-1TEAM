"""검색 질의 조립 회귀 — `app/rag/retrieval/query_builder.py`.

retrive 브랜치 `retrieval_strategy_evaluation.ipynb` §11 실측(2026-08-16)이 확인한 버그를
막는다: 원시 ML 피처명(model.feature_columns)·내부 코드값이 policy_docs 검색어에 그대로
섞이면 순수 잡음이 되어 MRR이 4가지 방식 중 최하위(0.19)로 떨어졌다. 여기서는 네트워크 호출
없이(Chroma·OpenAI 둘 다 부르지 않는다) 질의 조립 로직만 고정한다.
"""
from __future__ import annotations

import re

import pytest

from app.rag.retrieval import (
    FALLBACK_FEATURE_HINT_NL,
    FEATURE_HINT_NL,
    build_query,
    facts_nl,
    feature_hint_nl,
)
from app.ml.features import FEATURE_COLUMNS, _DROP_FROM_MODEL

# 실제 모델 입력에 쓰이는 13개(날짜 원본 2개는 파생 피처로 대체돼 모델에 안 들어간다 — features.py 참고)
MODEL_INPUT_FEATURES = [c for c in FEATURE_COLUMNS if c not in _DROP_FROM_MODEL]


def test_every_model_input_feature_has_a_mapping():
    """FEATURE_COLUMNS가 나중에 늘어나도 조용히 원시 이름이 새지 않도록, 매핑 누락을 여기서 잡는다."""
    for name in MODEL_INPUT_FEATURES:
        phrase = feature_hint_nl(name)
        assert phrase != FALLBACK_FEATURE_HINT_NL, f"{name!r}이 FEATURE_HINT_NL에 없다 — 매핑을 추가할 것"
        assert name not in phrase


@pytest.mark.parametrize(
    "onehot_value",
    ["거래요일_한글_월", "시간대구간_심야(00-05)", "일시불할부구분코드_A", "일시불할부구분코드__"],
)
def test_onehot_encoded_feature_maps_via_base_column(onehot_value):
    # 접두 매칭이므로 베이스 컬럼명이 FEATURE_HINT_NL에 있어야 한다.
    matched_base = next(b for b in FEATURE_HINT_NL if onehot_value.startswith(f"{b}_"))
    assert feature_hint_nl(onehot_value) == FEATURE_HINT_NL[matched_base]


def test_unmapped_feature_falls_back_instead_of_leaking_raw_name():
    raw = "미래에_추가될_새_피처_확장"
    assert feature_hint_nl(raw) == FALLBACK_FEATURE_HINT_NL


def test_build_query_never_contains_a_raw_feature_column_token():
    """노트북의 RAW_FEATURE_NAME_LEAK 검증기와 같은 취지 — 원시 컬럼명이 문장에 그대로 없어야 한다."""
    contribs = [
        {"feature": "거래금액_Zscore_확장", "weight": 0.52},
        {"feature": "시간대구간_심야(00-05)", "weight": 0.31},
        {"feature": "카드누적사용액", "weight": 0.17},
    ]
    query = build_query("업무추진비", "한정식당 청담점", contribs, summary={})

    for raw in MODEL_INPUT_FEATURES:
        assert raw not in query, f"원시 피처명 {raw!r}이 질의에 그대로 남아 있다: {query!r}"
    assert "GLOBAL" not in query


def test_facts_nl_omits_none_fields_instead_of_inventing_them():
    """None은 '모름'이지 '아니오'가 아니다 — Settlement 모델의 계약과 동일."""
    summary = {"headcount": None, "preApproved": None, "itemType": None,
               "kickbackTarget": None, "isSecondaryVenue": None, "includesAlcohol": None}
    assert facts_nl(summary) == ""

    summary_missing = {}  # 필드 자체가 응답에 없는 경우도 동일하게 취급
    assert facts_nl(summary_missing) == ""


def test_facts_nl_renders_only_known_facts():
    summary = {"headcount": 2, "preApproved": False, "kickbackTarget": True,
               "isSecondaryVenue": None, "includesAlcohol": None, "itemType": "식사"}
    facts = facts_nl(summary)
    assert "참석 인원 2명" in facts
    assert "사전승인 받지 않음" in facts
    assert "청탁금지법 대상자 참석" in facts
    assert "지출유형 식사" in facts
    # 모르는 필드(2차 성격·주류)는 문장에 등장하지 않는다 — 지어내지 않는다.
    assert "2차" not in facts
    assert "주류" not in facts


def test_build_query_includes_facts_when_present():
    contribs = [{"feature": "카드첫거래여부", "weight": 1.0}]
    summary = {"headcount": 2}
    query = build_query("회식", "이자카야", contribs, summary)

    assert "해당 가맹점과의 첫 거래라는 점" in query
    assert "거래 사실: 참석 인원 2명." in query
    # [수정] 실측(2026-08-18)으로 "규정 위반 여부를 확인해야 합니다" 고정 문구가 검색 결과를
    # "위반 시 조치"류 조문으로 쏠리게 만드는 것으로 확인돼 제거했다 — 더는 문구가 없어야 한다.
    assert "위반" not in query


def test_build_query_never_ends_with_removed_violation_boilerplate():
    """§ 위 테스트와 같은 취지 — 문구가 다시 슬며시 들어오는 걸 막는 회귀 가드."""
    query = build_query("업무추진비", "가맹점", contribs=[{"feature": "월말여부", "weight": 1.0}],
                         summary={"headcount": 3})
    assert "위반" not in query


def test_build_query_without_contribs_or_facts_still_produces_a_sentence():
    """contribs가 비어 있으면(이상탐지 모델의 상시 상태) 채움 문구 없이 짧게 끝난다 — §의 [수정 ②]."""
    query = build_query("업무추진비", "가맹점", contribs=[], summary={})
    assert "가맹점" in query
    assert "업무추진비" in query
    assert re.search(r"결제입니다\.$", query)
    assert "이례적인 결제 패턴이 감지된 점" not in query


def test_build_query_with_contribs_states_the_reason():
    query = build_query("업무추진비", "가맹점", contribs=[{"feature": "카드첫거래여부", "weight": 1.0}], summary={})
    assert "해당 가맹점과의 첫 거래라는 점" in query
"""가맹점 업종 구분 캐스케이드 테스트 (§7-1) — 캐시 → 카카오 → LLM 재분류.

카카오·OpenAI 실 호출은 하지 않는다. `_kakao_search`/`_llm_classify`/`core_client`/`core_auth`를
monkeypatch로 대체해 캐스케이드 분기(캐시 히트/미스, 카카오 미스, LLM 성공/실패)만 검증한다.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.merchant import classify as classify_mod


# ── normalize() ──────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("스타벅스 강남점", "스타벅스"),
        ("이마트", "이마트"),
        ("메가커피 라운지점", "메가커피"),
        ("(주)한우명가 본점", "한우명가"),
        ("  스타벅스   역삼점  ", "스타벅스"),
        ("", ""),
    ],
)
def test_normalize(raw, expected):
    assert classify_mod.normalize(raw) == expected


# ── classify() 캐스케이드 ───────────────────────────────────────────────

class _RequestRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []

    def __call__(self, method, path, json=None, **_kw):
        self.calls.append((method, path, json or {}))
        return SimpleNamespace(status_code=200, json=lambda: {})


@pytest.fixture
def request_spy(monkeypatch) -> _RequestRecorder:
    recorder = _RequestRecorder()
    monkeypatch.setattr(classify_mod.core_auth, "request", recorder)
    return recorder


def test_cache_hit_skips_kakao_and_llm(monkeypatch, request_spy):
    monkeypatch.setattr(
        classify_mod.core_client, "get_merchant_category",
        lambda name: {"hit": True, "industry_code": "CAFE", "industry_label": "카페", "confidence": 0.8},
    )

    def _fail_if_called(*_a, **_kw):
        raise AssertionError("캐시 히트인데 카카오/LLM이 호출됨")

    monkeypatch.setattr(classify_mod, "_kakao_search", _fail_if_called)
    monkeypatch.setattr(classify_mod, "_llm_classify", _fail_if_called)

    result = classify_mod.classify("스타벅스 강남점")
    assert result == {"industry_code": "CAFE", "industry_label": "카페", "confidence": 0.8, "source": "CACHE"}
    assert request_spy.calls == []


def test_cache_lookup_failure_falls_back_to_kakao_instead_of_raising(monkeypatch, request_spy):
    def _raise_cache_error(name):
        raise RuntimeError("core 연결 실패")

    monkeypatch.setattr(classify_mod.core_client, "get_merchant_category", _raise_cache_error)
    fake_doc = {"id": "1", "category_name": "음식점 > 한식", "category_group_name": "음식점", "category_group_code": "FD6"}
    monkeypatch.setattr(classify_mod, "_kakao_search", lambda query: fake_doc)
    monkeypatch.setattr(
        classify_mod, "_llm_classify",
        lambda merchant, category_name, category_group_name: classify_mod._LLMIndustryOutput(
            industry_label="일반음식점", confidence=0.7,
        ),
    )

    result = classify_mod.classify("아무개식당")

    assert result == {
        "industry_code": "RESTAURANT", "industry_label": "일반음식점",
        "confidence": 0.7, "source": "KAKAO",
    }


def test_kakao_miss_returns_unresolved_without_llm(monkeypatch, request_spy):
    monkeypatch.setattr(classify_mod.core_client, "get_merchant_category", lambda name: {"hit": False})
    monkeypatch.setattr(classify_mod, "_kakao_search", lambda query: None)

    def _fail_if_called(*_a, **_kw):
        raise AssertionError("카카오 미스인데 LLM이 호출됨")

    monkeypatch.setattr(classify_mod, "_llm_classify", _fail_if_called)

    result = classify_mod.classify("존재안하는가게")
    assert result == classify_mod.UNRESOLVED
    assert request_spy.calls == []


def test_kakao_hit_llm_success_upserts_llm_label_not_raw_kakao(monkeypatch, request_spy):
    monkeypatch.setattr(classify_mod.core_client, "get_merchant_category", lambda name: {"hit": False})
    fake_doc = {
        "id": "12345",
        "category_name": "음식점 > 술집 > 호프,요리주점",
        "category_group_name": "음식점",
        "category_group_code": "FD6",  # 카카오 원시 코드 — 우리 결과엔 그대로 안 남아야 한다
    }
    monkeypatch.setattr(classify_mod, "_kakao_search", lambda query: fake_doc)
    monkeypatch.setattr(
        classify_mod, "_llm_classify",
        lambda merchant, category_name, category_group_name: classify_mod._LLMIndustryOutput(
            industry_label="주점/유흥", confidence=0.9,
        ),
    )

    result = classify_mod.classify("역삼호프")

    assert result == {
        "industry_code": "BAR_ENTERTAINMENT", "industry_label": "주점/유흥",
        "confidence": 0.9, "source": "KAKAO",
    }
    assert len(request_spy.calls) == 1
    method, path, payload = request_spy.calls[0]
    assert method == "POST"
    assert path == "/api/internal/merchant-category/"
    # 카카오 원시 라벨("음식점")이 아니라 LLM 재분류 결과가 적재돼야 한다.
    assert payload["industry_label"] == "주점/유흥"
    assert payload["industry_code"] == "BAR_ENTERTAINMENT"
    assert payload["raw"] == fake_doc


def test_llm_failure_returns_unresolved_and_does_not_leak_raw_kakao_label(monkeypatch, request_spy):
    monkeypatch.setattr(classify_mod.core_client, "get_merchant_category", lambda name: {"hit": False})
    fake_doc = {"id": "1", "category_name": "음식점 > 한식", "category_group_name": "음식점", "category_group_code": "FD6"}
    monkeypatch.setattr(classify_mod, "_kakao_search", lambda query: fake_doc)

    def _raise(*_a, **_kw):
        raise RuntimeError("모델 거부")

    monkeypatch.setattr(classify_mod, "_llm_classify", _raise)

    result = classify_mod.classify("아무개식당")
    assert result == classify_mod.UNRESOLVED
    assert request_spy.calls == []  # LLM 실패 시 캐시에 아무것도 적재하지 않는다

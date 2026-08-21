"""`POST /embeddings/cases` 회귀 — 결정 사례 적재 진입점.

고정하는 계약:
  ① `case_store.upsert_cases`에 **그대로** 넘긴다(골든 데이터와 같은 계약).
  ② **실패를 200으로 덮지 않는다** — core가 `index_error`로 남기고 나중에 다시 올린다.
     성공으로 돌려주면 밀린 사례가 「적재됨」으로 표시돼 영영 안 올라간다.
  ③ 입력 검증: 빈 배열·`case_id`/`text` 누락은 400.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api import embeddings
from app.main import app

client = TestClient(app, raise_server_exceptions=False)
URL = "/embeddings/cases"

CASE = {
    "case_id": "case-s12-1755000000",
    "text": "접대 450,000원, 강남한식당(일반음식점). AI 권고는 승인이었으나 회계 담당자는 "
            "반려로 판단. 사유: 사적 사용으로 판단됨",
    "outcome": "REJECT",
    "category": "접대",
    "citation": "과거 결정사례 #12",
}


def test_사례를_그대로_넘긴다(monkeypatch):
    seen = {}

    def _upsert(cases):
        seen["cases"] = cases
        return len(cases)

    monkeypatch.setattr(embeddings.case_store, "upsert_cases", _upsert)
    body = client.post(URL, json={"cases": [CASE]}).json()
    assert body == {"upserted": 1, "collection": "case_history"}
    assert seen["cases"] == [CASE]          # 손대지 않는다 — 계약은 core가 만든다


def test_여러_건도_한_번에(monkeypatch):
    monkeypatch.setattr(embeddings.case_store, "upsert_cases", lambda cases: len(cases))
    second = {**CASE, "case_id": "case-s13-1755000001"}
    assert client.post(URL, json={"cases": [CASE, second]}).json()["upserted"] == 2


def test_적재_실패는_502다_빈_성공이_아니다(monkeypatch):
    """성공으로 돌려주면 밀린 사례가 「적재됨」으로 표시돼 영영 안 올라간다."""
    monkeypatch.setattr(embeddings.case_store, "upsert_cases",
                        lambda cases: (_ for _ in ()).throw(RuntimeError("chroma down")))
    r = client.post(URL, json={"cases": [CASE]})
    assert r.status_code == 502
    assert "chroma down" in r.json()["detail"]


@pytest.mark.parametrize("payload", [
    {},
    {"cases": []},
    {"cases": [{"case_id": "x"}]},                       # text 없음
    {"cases": [{"text": "본문"}]},                        # case_id 없음
    {"cases": [{"case_id": "x", "text": "   "}]},        # 공백만
])
def test_입력_검증(payload):
    assert client.post(URL, json=payload).status_code == 400

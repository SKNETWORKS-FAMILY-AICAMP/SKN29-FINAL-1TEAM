"""`/agent/decision-reason` 회귀 — 결정 사유 초안 Agent.

고정하는 계약:
  ① 프롬프트에 **판정 사유의 라벨·설명**이 실린다 — 코드만 주면 모델이 없는 규정을 지어낸다.
  ② 선택지(`options`)가 프롬프트에 그대로 실린다 — 목록 밖 값을 만들지 않게 하는 장치.
  ③ **실패를 200으로 덮지 않는다** — core가 판정 플래그 폴백을 갖고 있어서, 빈 문자열을
     성공으로 돌려주면 오히려 더 나쁜 초안(빈 사유)이 화면에 뜬다.
  ④ 입력 검증: decision은 RETURN/REJECT, options는 필수.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.agents import decision_reason_agent
from app.main import app

client = TestClient(app, raise_server_exceptions=False)
URL = "/agent/decision-reason"


def _payload(**over):
    base = {
        "decision": "RETURN",
        "options": ["증빙 누락", "건당 한도 초과", "기타"],
        "settlement": {
            "id": 1, "merchant": "강남한식당", "amount": 450000, "date": "2026-08-20",
            "category": "접대", "purpose": "", "merchant_industry": "일반음식점",
            "has_receipt": False,
        },
        "judgement": {
            "decision": "REVIEW",
            "flags": [{"code": "EVIDENCE_MISSING", "label": "적격증빙 없음",
                       "description": "카드매출전표 등 적격증빙이 첨부되지 않았다.",
                       "arg": "", "owner": "지출자"}],
        },
        "reason_hints": {"EVIDENCE_MISSING": "증빙 누락"},
    }
    base.update(over)
    return base


def test_프롬프트에_사유_라벨과_설명이_실린다():
    prompt = decision_reason_agent._user_prompt(_payload())
    assert "적격증빙 없음" in prompt
    assert "카드매출전표" in prompt          # 설명까지 — 코드만 주면 규정을 지어낸다
    assert "EVIDENCE_MISSING" in prompt
    assert "해소 주체: 지출자" in prompt


def test_프롬프트에_선택지와_내역이_실린다():
    prompt = decision_reason_agent._user_prompt(_payload())
    for option in ("증빙 누락", "건당 한도 초과", "기타"):
        assert option in prompt
    assert "450,000원" in prompt
    assert "증빙 첨부: 없음" in prompt
    assert "(미기재)" in prompt              # 빈 목적을 "-"로 뭉개지 않는다


def test_사유가_없으면_그_사실을_적는다():
    prompt = decision_reason_agent._user_prompt(_payload(judgement={"decision": "", "flags": []}))
    assert "판정이 남긴 사유가 없습니다" in prompt


def test_반려_프롬프트는_재제출_안내를_금지한다():
    """실측: 시스템 규칙만으로는 모델이 반려 건에도 "다시 제출해 주세요"를 붙였다.

    반려는 재제출 불가라 그 문장이 그대로 지출자에게 나가면 잘못된 안내가 된다 —
    그래서 처리 구분별 지시를 **매 요청 프롬프트에** 다시 넣는다.
    """
    reject = decision_reason_agent._user_prompt(_payload(decision="REJECT"))
    assert "반려(최종)" in reject
    assert "재제출·보완·재업로드를 안내하지 마세요" in reject

    ret = decision_reason_agent._user_prompt(_payload(decision="RETURN"))
    assert "보완요청" in ret
    assert "다시 제출하면 되는지" in ret


def test_초안을_돌려준다(monkeypatch):
    monkeypatch.setattr(decision_reason_agent, "draft",
                        lambda p: {"reason": "증빙 누락", "detail": "영수증을 첨부해 주세요."})
    body = client.post(URL, json=_payload()).json()
    assert body == {"reason": "증빙 누락", "detail": "영수증을 첨부해 주세요."}


def test_실패는_502다_빈_성공이_아니다(monkeypatch):
    monkeypatch.setattr(decision_reason_agent, "draft",
                        lambda p: (_ for _ in ()).throw(RuntimeError("llm down")))
    r = client.post(URL, json=_payload())
    assert r.status_code == 502
    assert "llm down" in r.json()["detail"]


@pytest.mark.parametrize("payload", [
    _payload(decision="APPROVE"),   # 승인은 사유 초안 대상이 아니다
    _payload(options=[]),           # 선택지가 없으면 목록 밖 값을 만들게 된다
])
def test_입력_검증(payload):
    assert client.post(URL, json=payload).status_code == 400

"""정산 기반 초안 + 제출 전 문체 다듬기 회귀.

## 고정하는 계약

  ① **모델은 기본 내역을 낼 수 없다** — 가맹점·금액·일시·업종이 출력 스키마에 없다.
     (있으면 언젠가 덮어쓴다. 업종을 스키마에서 뺀 것과 같은 이유.)
  ② **판정을 예측하지 않는다** — 프롬프트에 엔진 dry-run 결과가 사실로 들어가고,
     모델은 설명만 쓴다. `judgement`는 LLM을 거치지 않고 그대로 화면에 간다.
  ③ **플래그 코드는 서버가 정한다** — 목록 밖 코드를 설명하면 버린다.
  ④ **LLM 자기신고를 믿지 않는다** — 다듬은 문장이 사실을 늘렸는지는 기계적으로 대조한다.
"""
from __future__ import annotations

from typing import get_args

import pytest

from app.agents import draft_agent, draft_facts, submit_polish

CTX = {
    "settlementId": 7,
    "status": "DRAFT",
    "basics": {
        "merchant": "강남한식당", "amount": 45000, "date": "2026-08-20", "time": "19:30",
        "cardType": "TEAM", "cardName": "영업팀 카드",
        "industry": "일반음식점", "industryCode": "RESTAURANT",
    },
    "current": {"category": "", "aiCategory": "식대", "aiSuggested": True,
                "purpose": "", "headcount": None},
    "categories": ["회식", "회의", "식대", "출장", "접대", "비품", "기타"],
    "attachments": [{
        "kind": "RECEIPT", "kindLabel": "영수증", "fileName": "r.png", "status": "DONE",
        "facts": [{"path": "dining.includes_alcohol", "value": True,
                   "desc": "주류 품목 포함 여부", "confidence": 0.9}],
    }],
    "facts": [
        {"path": "tx.amount", "value": 45000, "desc": "결제 금액(원)"},
        {"path": "evidence.expense_purpose_missing", "value": True,
         "desc": "참이면 지출 목적이 **없다**(극성 주의)"},
    ],
    "judgement": {
        "available": True, "decision": "RETURN", "scope": "식대", "blocking": True,
        "flags": [{"code": "EVIDENCE_MISSING", "label": "적격증빙 없음",
                   "description": "적격증빙이 첨부되지 않았습니다.",
                   "severity": "HIGH", "severityLabel": "높음",
                   "owner": "SPENDER", "ownerLabel": "지출자"}],
        "graphs": [{"scope": "GLOBAL", "name": "기본 정산 게이트", "version": 1,
                    "decision": "RETURN", "path": ["n_receipt"]}],
        "unresolved": [],
    },
    "returnContext": None,
}


# ① 모델이 기본 내역을 낼 수 없다
def test_출력_스키마에_기본내역이_없다():
    fields = set(draft_agent.LLMSettlementDraftOutput.model_fields)
    for forbidden in ("merchant", "amount", "date", "merchantIndustry", "industry"):
        assert forbidden not in fields, f"{forbidden}이 스키마에 있으면 모델이 사실을 덮어쓴다"
    assert fields == {"category", "purpose", "reasoning", "flagExplanations"}


def test_분류_enum이_서버_어휘를_따른다(monkeypatch):
    monkeypatch.setattr(draft_agent, "category_values", lambda: ["식대", "기타"])
    draft_agent._with_categories.cache_clear()
    model = draft_agent._settlement_output_model()
    assert set(get_args(model.model_fields["category"].annotation)) == {"", "식대", "기타"}


# ② 판정을 예측시키지 않는다
def test_프롬프트에_엔진_판정이_사실로_들어간다():
    rendered = draft_facts.render(CTX)
    assert "RETURN" in rendered
    assert "기본 정산 게이트 v1" in rendered
    assert "n_receipt" in rendered


def test_REVIEW는_정상이라고_알려준다():
    ctx = {**CTX, "judgement": {**CTX["judgement"], "decision": "REVIEW"}}
    block = draft_facts.judgement_block(ctx)
    assert "정상 경로" in block


def test_미리보기를_못_얻으면_추측을_금지한다():
    block = draft_facts.judgement_block({"judgement": {"available": False, "error": "boom"}})
    assert "추측하지 마라" in block


def test_사실에_설명이_함께_렌더된다():
    """경로만 주면 극성이 뒤집힌 필드를 반대로 읽는다."""
    block = draft_facts.facts_block(CTX)
    assert "expense_purpose_missing" in block
    assert "극성 주의" in block


def test_첨부는_상태를_지우지_않는다():
    ctx = {"attachments": [{"kind": "RECEIPT", "kindLabel": "영수증", "fileName": "r.png",
                            "status": "FAILED", "facts": []}]}
    block = draft_facts.attachments_block(ctx)
    assert "FAILED" in block and "읽어낸 사실 없음" in block


def test_판정은_LLM을_거치지_않고_그대로_간다():
    summary = draft_agent._judgement_summary(CTX)
    assert summary["decision"] == "RETURN"
    assert summary["blocking"] is True
    assert summary["graphs"][0]["name"] == "기본 정산 게이트"


# ③ 플래그 코드는 서버가 정한다
class _Explanation:
    def __init__(self, code, text):
        self.code, self.text = code, text


def test_목록_밖_코드는_버린다():
    notices = draft_agent._build_notices(CTX, [
        _Explanation("EVIDENCE_MISSING", "영수증을 첨부해 주세요."),
        _Explanation("MADE_UP_FLAG", "있지도 않은 문제입니다."),
    ])
    assert [n["code"] for n in notices] == ["EVIDENCE_MISSING"]
    assert notices[0]["text"] == "영수증을 첨부해 주세요."


def test_설명이_없어도_빈손으로_두지_않는다():
    """등록된 description으로 채운다 — 사유 코드를 펴는 것이지 지어내는 게 아니다."""
    notices = draft_agent._build_notices(CTX, [])
    assert notices[0]["text"] == "적격증빙이 첨부되지 않았습니다."


def test_RETURN이면_blocker_REVIEW면_info():
    assert draft_agent._build_notices(CTX, [])[0]["level"] == "blocker"
    review_ctx = {**CTX, "judgement": {**CTX["judgement"], "decision": "REVIEW"}}
    assert draft_agent._build_notices(review_ctx, [])[0]["level"] == "info"


# ④ 다듬기 — LLM 자기신고를 믿지 않는다
def test_없던_숫자가_생기면_잡는다():
    diff = submit_polish._diff("팀 회식", "팀원 8명과 회식했습니다.")
    assert diff["overRewritten"] is True
    assert diff["addedNumbers"] == ["8"]


def test_한글_수사는_같은_값으로_본다():
    """"세 명" → "3명"은 표기 변경이지 사실 추가가 아니다."""
    diff = submit_polish._diff("세 명이서 회식", "3명이 회식했습니다.")
    assert diff["addedNumbers"] == []


def test_자릿수_쉼표는_같은_값으로_본다():
    diff = submit_polish._diff("45000원 사용", "45,000원을 사용했습니다.")
    assert diff["addedNumbers"] == [] and diff["lostNumbers"] == []


def test_원문_숫자가_사라져도_잡는다():
    diff = submit_polish._diff("참석 8명 회식", "팀 회식을 진행했습니다.")
    assert diff["overRewritten"] is True
    assert diff["lostNumbers"] == ["8"]


def test_문장이_크게_길어지면_잡는다():
    diff = submit_polish._diff("회식함", "분기 실적 마감을 기념해 영업팀 전원이 참석한 저녁 식사입니다.")
    assert diff["overRewritten"] is True


def test_정상적인_다듬기는_통과한다():
    diff = submit_polish._diff("팀 점심 식대", "팀 점심 식대로 사용했습니다.")
    assert diff["overRewritten"] is False


def test_너무_짧으면_LLM을_부르지_않고_안내한다(monkeypatch):
    def _boom(*a, **kw):
        raise AssertionError("짧은 문장에 LLM을 부르면 안 된다")

    monkeypatch.setattr(submit_polish, "_get_client", _boom)
    out = submit_polish.polish("회식")
    assert out["applied"] is False
    assert out["review"][0]["code"] == "PURPOSE_TOO_SHORT"
    #  대신 채워 넣지 않는다 — 목적은 사람이 쓰는 것이다.
    assert out["polished"] == "회식"


def test_LLM_실패는_제출을_막지_않는다(monkeypatch):
    def _boom():
        raise RuntimeError("openai down")

    monkeypatch.setattr(submit_polish, "_get_client", _boom)
    out = submit_polish.polish("팀 점심 식대로 사용")
    assert out["applied"] is False
    assert out["polished"] == "팀 점심 식대로 사용"
    assert out["review"] == []


@pytest.mark.parametrize("original,polished,expected", [
    ("팀 점심 식대", "팀 점심 식대로 사용했습니다.", True),
    ("팀 점심 식대", "팀원 6명과 점심을 했습니다.", False),
])
def test_선을_넘지_않았을_때만_자동_적용(monkeypatch, original, polished, expected):
    class _Msg:
        parsed = submit_polish.PolishOutput(
            polished=polished, addedFacts=[], insufficient=False, missing=[])

    class _Resp:
        choices = [type("C", (), {"message": _Msg()})()]

    class _Client:
        class beta:
            class chat:
                class completions:
                    @staticmethod
                    def parse(**kw):
                        return _Resp()

    monkeypatch.setattr(submit_polish, "_get_client", lambda: _Client)
    assert submit_polish.polish(original)["applied"] is expected

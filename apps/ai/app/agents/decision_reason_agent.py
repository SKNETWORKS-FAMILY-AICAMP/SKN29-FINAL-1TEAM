"""결정 사유 초안 Agent — 보완요청·반려 문구를 판정 결과와 내역에서 뽑아 쓴다.

## 무엇을 하는가

회계 담당자·팀장이 「보완요청」·「반려」를 누르면 사유를 적어야 한다. 그 자리에서 매번
처음부터 쓰다 보면 실제로는 "증빙 누락" 같은 라벨만 남고 **무엇을 어떻게 보완해야 하는지**가
비어서, 지출자는 되돌아온 건을 받고도 뭘 해야 할지 모른다.

판정은 이미 사유 코드(`rule_flags`)와 내역을 갖고 있다. 그걸 문장으로 펴 주면 결정자는
**지우고 고치는 일**만 하면 된다.

## 지켜야 하는 선

  · **주어진 사실만 쓴다.** 판정이 남기지 않은 규정·조문·금액을 지어내면, 그 문장이 그대로
    지출자에게 통보되고 회사 규정인 것처럼 읽힌다. 근거는 넘어온 `judgement.flags`뿐이다.
  · **사유(`reason`)는 주어진 목록에서만 고른다.** 목록 밖 값을 만들면 화면 칩과 어긋난
    문자열이 그대로 저장돼 집계가 갈린다(core가 한 번 더 거른다).
  · **초안이지 결정이 아니다.** 승인/반려 여부를 판단하지 않는다 — 그건 이미 정해져서
    넘어온다(`decision`).
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.config import settings as core_settings

logger = logging.getLogger(__name__)

MODEL = "gpt-4o-mini"          # 짧은 문장 한 편이라 경량 모델로 충분하다.
TIMEOUT = 25

_client = None


def _openai():
    global _client
    if _client is None:
        from openai import OpenAI

        if not core_settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY 가 비어 있다")
        _client = OpenAI(api_key=core_settings.openai_api_key)
    return _client


SYSTEM_PROMPT = """당신은 법인카드 정산 담당자가 지출자에게 보낼 **처리 사유**의 초안을 쓰는 보조입니다.

반드시 지켜야 할 규칙:
1. 아래에 주어진 **판정 사유(flags)와 거래 내역만** 근거로 쓰세요. 주어지지 않은 규정·조문·
   금액 기준을 지어내지 마세요. 이 문장은 그대로 지출자에게 통보되어 회사 규정처럼 읽힙니다.
2. `reason`은 주어진 **선택지 목록에서 정확히 하나**를 그대로 골라 쓰세요. 목록에 없는
   문자열을 만들면 안 됩니다. 어느 것도 맞지 않으면 "기타"를 고르세요.
3. `detail`은 읽는 사람이 **무엇을 알아야 하는지** 씁니다.
   - 보완요청(RETURN): 무엇이 빠졌는지 + 무엇을 첨부/기재해 다시 제출하면 되는지.
   - 반려(REJECT): 무엇이 왜 규정에 어긋나는지. 재제출을 안내하지 마세요(반려는 최종입니다).
   - 승인(APPROVE): 이 자리는 **감사 기록**입니다. AI·룰이 걸어세운 건을 담당자가 승인하는
     상황이므로 "왜 기계 판단을 따르지 않았는지"를 적습니다. 지출자에게 보내는 안내가
     아니라 나중에 이 결정을 되짚을 사람이 읽습니다. **근거가 주어지지 않았으면 `detail`을
     빈 문자열로 두세요** — 담당자만 아는 사실을 지어내면 안 됩니다.
4. 2~3문장, 존댓말. 사유 코드(영문 대문자)·필드 경로 같은 내부 표기를 쓰지 마세요.
5. 판정 사유가 하나도 없으면 `detail`을 빈 문자열로 두세요 — 근거 없이 문장을 만들지 않습니다."""

_SCHEMA = {
    "name": "decision_reason",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "reason": {"type": "string"},
            "detail": {"type": "string"},
        },
        "required": ["reason", "detail"],
    },
}


def _user_prompt(payload: dict[str, Any]) -> str:
    s = payload.get("settlement") or {}
    j = payload.get("judgement") or {}
    flags = j.get("flags") or []
    flag_lines = "\n".join(
        f"- {f.get('label')}({f.get('code')}): {f.get('description', '')}"
        + (f" [대상: {f.get('arg')}]" if f.get("arg") else "")
        + (f" [해소 주체: {f.get('owner')}]" if f.get("owner") else "")
        for f in flags
    ) or "(판정이 남긴 사유가 없습니다)"

    hints = payload.get("reason_hints") or {}
    hint_line = (
        "\n".join(f"- {code} → {reason}" for code, reason in hints.items())
        if hints else "(없음)"
    )

    #  처리 구분별 지시를 **매 요청 프롬프트에** 다시 넣는다. 시스템 규칙만으로는 모델이
    #  반려 건에도 "다시 제출해 주세요"를 붙이는 게 실측으로 확인됐다(반려는 재제출 불가라
    #  그 문장이 그대로 지출자에게 나가면 잘못된 안내가 된다).
    decision = payload.get("decision")
    is_reject = decision == "REJECT"
    is_approve = decision == "APPROVE"
    if is_approve:
        div = payload.get("divergence") or {}
        expected = div.get("expected") or "판단 없음"
        instruction = (
            f"이 건은 **승인**입니다. 기계는 `{expected}`로 봤는데 담당자가 승인하는 상황이라, "
            "지출자에게 보내는 안내가 아니라 **감사 기록**을 쓰는 자리입니다. "
            "「왜 기계 판단을 따르지 않았는가」를 아래 근거만으로 쓰고, 근거가 부족하면 "
            "detail을 빈 문자열로 두세요(담당자만 아는 사실을 지어내지 마세요)."
        )
    elif is_reject:
        instruction = (
            "이 건은 **반려(최종)** 입니다. 재제출·보완·재업로드를 안내하지 마세요 - 지출자는 이 건을 "
            "다시 올릴 수 없습니다. 무엇이 왜 규정에 어긋나는지만 쓰세요."
        )
    else:
        instruction = (
            "이 건은 **보완요청**입니다. 무엇이 빠졌는지와, 무엇을 첨부·기재해 다시 제출하면 되는지 쓰세요."
        )
    label = "승인" if is_approve else ("반려(최종)" if is_reject else "보완요청")

    return (
        f"처리 구분: {label}\n"
        f"{instruction}\n\n"
        f"[사유 선택지 — 이 중 하나를 그대로 고를 것]\n"
        + "\n".join(f"- {o}" for o in payload.get("options", []))
        + f"\n\n[판정이 남긴 사유]\n{flag_lines}\n\n"
        f"[사유 코드 → 선택지 힌트]\n{hint_line}\n\n"
        f"[거래 내역]\n"
        f"가맹점: {s.get('merchant') or '-'}\n"
        f"업종: {s.get('merchant_industry') or '미확정'}\n"
        f"금액: {int(s.get('amount') or 0):,}원\n"
        f"거래일: {s.get('date') or '-'}\n"
        f"비용분류: {s.get('category') or '(미기재)'}\n"
        f"지출 목적: {s.get('purpose') or '(미기재)'}\n"
        f"증빙 첨부: {'있음' if s.get('has_receipt') else '없음'}"
    )


def draft(payload: dict[str, Any]) -> dict[str, Any]:
    """사유 초안 1건. 실패는 감추지 않고 올린다 — core가 폴백을 갖고 있다."""
    user_prompt = _user_prompt(payload)
    resp = _openai().chat.completions.create(
        model=MODEL,
        timeout=TIMEOUT,
        temperature=0.2,   # 통보 문구라 표현이 튀지 않는 편이 낫다.
        response_format={"type": "json_schema", "json_schema": _SCHEMA},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )
    out = json.loads(resp.choices[0].message.content or "{}")
    logger.info(
        "decision-reason 초안(settlement=%s, %s): reason=%r",
        (payload.get("settlement") or {}).get("id"), payload.get("decision"), out.get("reason"),
    )
    return {"reason": out.get("reason", ""), "detail": out.get("detail", "")}

"""제출 전 문체 다듬기 — **문장만 고치고, 사실이 늘었는지는 서버가 판정한다.**

## 무엇을 하는가

사용자가 지출 목적을 대충 써도(“회식”, “거래처 미팅함”) 그대로 제출되도록, 문체만
다듬어 자동 제출한다. 사용자를 멈춰 세우는 건 **정말 멈춰야 할 때만**이다.

## 왜 LLM 자기신고를 믿지 않는가

"사실을 추가하지 마라"고 지시하고 `addedFacts`를 물으면 모델은 대체로 `[]`라고 답한다 —
자기가 추가한 줄 모르거나, 지시를 지켰다고 믿기 때문이다. 이 문장은 **감사 기록으로 남고
결정 사례로 인용**되므로(`_context/decision-case-data.md`), 모델의 자기평가로 통과시킬 수
없다. 그래서 다듬은 문장을 **원문과 기계적으로 대조**한다:

  · 원문에 없던 **수(數)** 가 생겼는가 — 금액·인원·날짜가 새로 생기는 것이 가장 흔한 환각
    (“팀 회식” → “팀 회식 (참석 8명)”). 한글 수사(세 명 → 3명)는 같은 값으로 접는다.
  · 원문 대비 **과도하게 길어졌는가** — 문체를 다듬으면 길이는 비슷하다. 크게 늘었다면
    없던 내용이 붙은 것이다.
  · 원문이 통째로 **사라졌는가** — 다듬기가 아니라 새로 쓴 것이다.

검사에 걸리면 자동 적용하지 않고 사람에게 보여 준다. LLM의 `addedFacts`는 **참고로만**
싣는다(정본은 위 대조 결과다).

## 정보 부족

목적이 사실상 비어 있으면(공백 제거 후 짧음) 다듬어도 감사 기록으로 쓸 수 없다.
이때는 무엇을 적어야 하는지 안내한다 — 대신 채워 넣지 않는다.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from openai import OpenAI
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger(__name__)

MODEL = "gpt-4o-mini"

#: 이보다 짧으면 **LLM을 부를 가치도 없는 조각**이다(공백 제거 기준). 「회식」·「출장」처럼
#  단어 하나만 남은 경우를 걸러낸다.
#
#  ⚠️ 이 선은 「정보가 충분한가」를 재는 것이 **아니다.** 처음에 6자로 뒀다가 「팀 점심 식대」
#  (5자)·「거래처 접대」(5자)·「야근 간식」(4자) 같은 **실제로 쓰이는 목적**이 통째로 걸려
#  다듬기 경로에 못 들어갔다(회귀가 잡았다). 정보 충분성은 모델의 `insufficient`이 판단하고
#  안내로 나간다 — 여기서는 다듬을 문장 자체가 없는 경우만 막는다.
MIN_PURPOSE_CHARS = 4
#: 길이가 이 배수를 넘게 늘면 "다듬기"가 아니다. 짧은 원문의 과민반응을 막으려고
#: 절대 증가폭(_MIN_GROWTH_CHARS)도 함께 넘어야 걸린다.
MAX_GROWTH_RATIO = 2.0
MIN_GROWTH_CHARS = 25

_KO_NUMERALS = {
    "하나": "1", "한": "1", "둘": "2", "두": "2", "셋": "3", "세": "3", "넷": "4", "네": "4",
    "다섯": "5", "여섯": "6", "일곱": "7", "여덟": "8", "아홉": "9", "열": "10",
}

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.openai_api_key)
    return _client


class PolishOutput(BaseModel):
    polished: str
    #: 모델의 자기신고. **판정에 쓰지 않는다** — 참고로만 싣는다(모듈 docstring 참조).
    addedFacts: list[str]
    #: 목적을 쓰기에 정보가 모자란다고 모델이 판단했는가.
    insufficient: bool
    #: 무엇이 있으면 좋은지(사용자 안내용). 지어내서 채우지 말고 **비어 있는 항목만** 든다.
    missing: list[str]


SYSTEM_PROMPT = """당신은 법인카드 정산의 「지출 목적」 문장을 **다듬는** 편집자입니다.

절대 규칙:
1. **사실을 추가하지 마세요.** 원문에 없는 숫자·인원·금액·날짜·거래처명·장소를
   만들어 넣으면 안 됩니다. 원문이 짧으면 짧은 채로 다듬으세요.
2. **사실을 빼지 마세요.** 원문에 있는 정보는 표현이 바뀌어도 남아 있어야 합니다.
3. 바꾸는 것은 문체뿐입니다 — 맞춤법, 어미, 구두점, 업무 문서다운 어투.
   "회식함" → "팀 회식 목적으로 사용했습니다" 는 괜찮습니다.
   "회식함" → "팀원 8명과 회식했습니다" 는 **금지**입니다(8명은 원문에 없습니다).
4. 이미 충분히 정돈된 문장이면 그대로 두세요(polished에 원문을 그대로 넣습니다).
5. 원문만으로는 목적을 알 수 없으면 insufficient를 true로 하고, missing에 무엇이
   빠졌는지 적으세요. 그래도 polished에는 **원문을 다듬은 결과**만 넣습니다."""


def _numbers(text: str) -> set[str]:
    """텍스트에 등장하는 수의 집합. 한글 수사는 아라비아 숫자로 접는다.

    자릿수 구분 쉼표(`1,200`)는 제거해 `1200`과 같은 값으로 본다 — 표기만 바뀐 것을
    "사실이 추가됐다"고 잡으면 정상적인 다듬기가 매번 걸린다.
    """
    normalized = re.sub(r"(?<=\d),(?=\d)", "", text or "")
    found = set(re.findall(r"\d+", normalized))
    for word, digit in _KO_NUMERALS.items():
        if word in (text or ""):
            found.add(digit)
    return found


def _diff(original: str, polished: str) -> dict[str, Any]:
    """다듬기가 선을 넘었는지 **기계적으로** 판정한다."""
    original, polished = (original or "").strip(), (polished or "").strip()
    added_numbers = sorted(_numbers(polished) - _numbers(original))
    lost_numbers = sorted(_numbers(original) - _numbers(polished))

    grew = (
        len(original) > 0
        and len(polished) > len(original) * MAX_GROWTH_RATIO
        and len(polished) - len(original) >= MIN_GROWTH_CHARS
    )
    emptied = bool(original) and not polished

    reasons = []
    if added_numbers:
        reasons.append(f"원문에 없던 숫자가 생겼습니다: {', '.join(added_numbers)}")
    if lost_numbers:
        reasons.append(f"원문에 있던 숫자가 사라졌습니다: {', '.join(lost_numbers)}")
    if grew:
        reasons.append(f"문장이 원문({len(original)}자)보다 크게 길어졌습니다({len(polished)}자)")
    if emptied:
        reasons.append("다듬은 결과가 비어 있습니다")

    return {
        "overRewritten": bool(reasons),
        "reasons": reasons,
        "addedNumbers": added_numbers,
        "lostNumbers": lost_numbers,
        "originalLength": len(original),
        "polishedLength": len(polished),
    }


def polish(purpose: str, context_hint: str = "") -> dict[str, Any]:
    """지출 목적 문장 다듬기.

    반환 계약:
      · ``applied``   — 그대로 적용해도 되는가(= 다듬었고 선을 넘지 않았다)
      · ``polished``  — 다듬은 문장. `applied`가 false면 화면이 원문과 나란히 띄운다
      · ``review``    — 사람이 봐야 하는 사유 목록(비어 있으면 조용히 지나간다)
      · ``diff``      — 기계 대조 결과(감사·디버깅용)

    LLM 호출이 실패해도 제출을 막지 않는다 — 원문 그대로 두고 `applied=False`,
    `review=[]`(다듬지 못한 것은 사용자가 멈춰 설 이유가 아니다).
    """
    original = (purpose or "").strip()
    stripped = re.sub(r"\s", "", original)

    if len(stripped) < MIN_PURPOSE_CHARS:
        #  다듬을 문장 자체가 없다(단어 하나). **대신 채워 넣지 않는다** — 목적은 사람이
        #  쓰는 것이고, 여기서 지어내면 그 문장이 감사 기록이 된다.
        return {
            "applied": False,
            "original": original,
            "polished": original,
            "review": [{
                "level": "warn",
                "code": "PURPOSE_TOO_SHORT",
                "text": "지출 목적이 너무 짧아 그대로 기록으로 남기기 어렵습니다. "
                        "무엇을 위해 썼는지 한 문장만 더 적어 주세요.",
            }],
            "diff": _diff(original, original),
            "modelReported": {},
        }

    try:
        resp = _get_client().beta.chat.completions.parse(
            model=MODEL,
            temperature=0.2,
            timeout=12,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": (
                    f"[원문]\n{original}\n\n"
                    + (f"[참고 사실 — 문장에 넣으라는 뜻이 아니다. 맥락 파악용]\n{context_hint}\n\n" if context_hint else "")
                    + "위 원문을 다듬어 주세요."
                )},
            ],
            response_format=PolishOutput,
        )
        out = resp.choices[0].message.parsed
        if out is None:
            raise ValueError("구조화 응답 없음")
    except Exception as exc:  # noqa: BLE001
        logger.warning("문체 다듬기 실패 — 원문 유지: %s", exc)
        return {
            "applied": False,
            "original": original,
            "polished": original,
            "review": [],
            "diff": _diff(original, original),
            "modelReported": {"error": f"{type(exc).__name__}: {exc}"},
        }

    diff = _diff(original, out.polished)
    review: list[dict[str, Any]] = []

    if diff["overRewritten"]:
        review.append({
            "level": "warn",
            "code": "PURPOSE_OVER_REWRITTEN",
            "text": "다듬은 문장이 원문에 없던 내용을 담고 있습니다. "
                    "어느 쪽으로 제출할지 확인해 주세요. (" + " / ".join(diff["reasons"]) + ")",
        })
    if out.insufficient and out.missing:
        review.append({
            "level": "info",
            "code": "PURPOSE_INSUFFICIENT",
            "text": "지출 목적에 다음 정보가 있으면 검토가 빨라집니다: " + ", ".join(out.missing[:4]),
        })

    return {
        #  선을 넘지 않았을 때만 자동 적용한다. 넘었으면 원문을 유지한 채 사람에게 보인다.
        "applied": not diff["overRewritten"],
        "original": original,
        "polished": out.polished.strip(),
        "review": review,
        "diff": diff,
        #  모델 자기신고 — 참고용. 위 `diff`가 정본이다.
        "modelReported": {"addedFacts": out.addedFacts, "insufficient": out.insufficient,
                          "missing": out.missing},
    }

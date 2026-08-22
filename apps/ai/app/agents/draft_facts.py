"""Draft Agent 입력 렌더링 — core가 준 **사실**을 프롬프트 문장으로 편다.

core가 사실(JSON)을 만들고 ai가 문장(렌더)을 만든다 — `app/context/render.py`가
룰 에이전트 카탈로그에서 쓰는 것과 같은 분업이다. 프롬프트 문구를 고치려고 Django를
재배포해야 하면 아무도 프롬프트를 안 고친다.

## 여기서 지키는 계약

1. **판정을 문장으로 다시 계산하지 않는다.** `judgement`는 엔진 dry-run 결과 그대로다.
   모델에게는 "이렇게 판정됐다"고 알려 주고 **설명만** 시킨다.
2. **모르는 값은 지어내지 않는다.** 값이 없는 필드는 아예 안 싣고, 「모른다」는
   `unresolved`·플래그가 말한다.
3. **첨부 추출은 출처를 붙인다.** 어느 문서에서 읽었는지가 사용자 안내의 근거가 된다.
"""
from __future__ import annotations

from typing import Any

#: 판정이 사람에게 되돌아가는 결정 — core `draft_context.BLOCKING_DECISIONS`와 같은 집합.
BLOCKING_DECISIONS = {"RETURN", "REJECT"}

_DECISION_TEXT = {
    "PASS": "통과(회계 확정 대기로 넘어갑니다)",
    "REVIEW": "회계 검토 필요 — **정상 경로다**. 룰이 자동으로 판단하지 않고 담당자가 보는 건일 뿐이므로, 사용자에게 문제가 있다고 말하지 마라.",
    "RETURN": "보완요청 — 지금 제출하면 지출자에게 되돌아온다.",
    "REJECT": "반려 — 지금 제출하면 최종 반려될 수 있다.",
}


def _fmt(value: Any) -> str:
    if isinstance(value, bool):
        return "예" if value else "아니오"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:,}"
    return str(value)


def basics_block(ctx: dict[str, Any]) -> str:
    b = ctx.get("basics") or {}
    lines = [
        f"가맹점: {b.get('merchant') or '(미상)'}",
        f"금액: {_fmt(b.get('amount') or 0)}원",
        f"결제일시: {b.get('date') or '(미상)'} {b.get('time') or ''}".strip(),
        f"카드: {b.get('cardName') or '(이름 없음)'} / 구분 {b.get('cardType') or '(미상)'}",
        f"가맹점 업종(서버 조회): {b.get('industry') or '미확인'}",
    ]
    return "\n".join(lines)


def current_block(ctx: dict[str, Any]) -> str:
    c = ctx.get("current") or {}
    category = c.get("category") or ""
    ai_category = c.get("aiCategory") or ""
    lines = [
        f"확정 비용분류(사람이 고른 값): {category or '(아직 없음 — 네가 제안해야 한다)'}",
        f"AI 제안 분류(이전 실행): {ai_category or '(없음)'}",
        f"지출 목적: {c.get('purpose') or '(비어 있음)'}",
    ]
    if c.get("headcount") is not None:
        lines.append(f"참석 인원: {c['headcount']}명")
    return "\n".join(lines)


def attachments_block(ctx: dict[str, Any]) -> str:
    rows = ctx.get("attachments") or []
    if not rows:
        return "첨부된 증빙이 없다."

    out = []
    for a in rows:
        head = f"· {a.get('kindLabel') or a.get('kind')} — {a.get('fileName') or ''} [{a.get('status')}]"
        facts = a.get("facts") or []
        if not facts:
            #  「아직 안 읽었다」와 「읽었는데 없다」는 다르다 — 상태를 그대로 보여 준다.
            head += " (읽어낸 사실 없음)"
            out.append(head)
            continue
        out.append(head)
        for f in facts:
            conf = f.get("confidence")
            suffix = f" (신뢰도 {conf})" if conf is not None else ""
            desc = f" — {f['desc']}" if f.get("desc") else ""
            out.append(f"    - {f['path']} = {_fmt(f['value'])}{suffix}{desc}")
    return "\n".join(out)


def facts_block(ctx: dict[str, Any]) -> str:
    """판정이 실제로 본 사실. **설명(desc)을 반드시 함께 싣는다.**

    경로 이름만 주면 극성을 뒤집어 읽는 필드가 실재한다
    (`evidence.expense_purpose_missing` = 참이면 목적이 **없다**).
    """
    facts = ctx.get("facts") or []
    if not facts:
        return "(조립된 사실 없음)"
    return "\n".join(
        f"· {f['path']} = {_fmt(f['value'])}" + (f"  — {f['desc']}" if f.get("desc") else "")
        for f in facts
    )


def judgement_block(ctx: dict[str, Any]) -> str:
    """**엔진이 이미 낸 판정.** 모델은 이걸 다시 계산하지 않고 설명만 한다."""
    j = ctx.get("judgement") or {}
    if not j.get("available"):
        return f"판정 미리보기를 얻지 못했다({j.get('error') or '사유 불명'}) — 판정 결과를 추측하지 마라."

    decision = j.get("decision") or ""
    lines = [
        f"판정 결과: {decision} — {_DECISION_TEXT.get(decision, '')}",
        f"적용 scope: {j.get('scope') or '(분류 미확정이라 과목 그래프 선택 불가)'}",
    ]
    graphs = j.get("graphs") or []
    if graphs:
        lines.append("돌아간 그래프:")
        for g in graphs:
            path = " → ".join(g.get("path") or [])
            lines.append(f"  · {g['name']} v{g['version']} ({g['scope']}) = {g['decision']}  경로: {path}")
    else:
        lines.append("돌아간 그래프: 없음(ACTIVE 룰 그래프가 없어 판정할 수 없었다)")

    flags = j.get("flags") or []
    if flags:
        lines.append("붙은 사유 플래그(이 코드들에 대해서만 설명을 써라):")
        for f in flags:
            lines.append(
                f"  · {f['code']} — {f.get('label') or ''}"
                f" [심각도 {f.get('severityLabel') or f.get('severity') or '?'}"
                f" / 해소주체 {f.get('ownerLabel') or f.get('owner') or '?'}]"
                + (f"\n      {f['description']}" if f.get("description") else "")
            )
    else:
        lines.append("붙은 사유 플래그: 없음")

    unresolved = j.get("unresolved") or []
    if unresolved:
        lines.append(f"해소되지 않은 규정 임계값: {', '.join(unresolved)}")
    return "\n".join(lines)


def return_block(ctx: dict[str, Any]) -> str:
    r = ctx.get("returnContext")
    if not r:
        return ""
    return (
        f"이 건은 「{r.get('statusLabel') or r.get('status')}」 상태로 되돌아온 건이다.\n"
        f"처리자: {r.get('actor') or '(미상)'} / 시각: {r.get('at') or ''}\n"
        f"사유: {r.get('reason') or '(사유 없음)'}\n"
        "→ 이 사유가 해소되도록 목적·설명을 다시 써라. 해소할 수 없는 사유(첨부가 더 필요하다 등)는 "
        "지어내 해결한 척하지 말고, 무엇을 해야 하는지 안내로 남겨라."
    )


def flag_codes(ctx: dict[str, Any]) -> list[str]:
    """설명을 붙일 수 있는 플래그 코드 목록 — **이 목록 밖 코드는 서버가 버린다.**"""
    return [f["code"] for f in ((ctx.get("judgement") or {}).get("flags") or []) if f.get("code")]


def render(ctx: dict[str, Any]) -> str:
    """사용자 프롬프트 본문."""
    blocks = [
        ("[기본 내역 — 확정된 사실이다. 바꾸거나 다시 추측하지 마라]", basics_block(ctx)),
        ("[현재 저장된 값]", current_block(ctx)),
        ("[첨부 증빙에서 실제로 읽어낸 것]", attachments_block(ctx)),
        ("[판정이 본 사실(EvalContext)]", facts_block(ctx)),
        ("[룰 엔진 판정 미리보기 — 결정론적 엔진의 실제 결과다]", judgement_block(ctx)),
    ]
    ret = return_block(ctx)
    if ret:
        blocks.append(("[보완요청 맥락]", ret))
    return "\n\n".join(f"{title}\n{body}" for title, body in blocks)

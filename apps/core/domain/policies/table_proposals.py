"""별표 후보 → `PolicyTable` 승인 경로.

## 왜 승인이 필요한가

`PolicyTable`에 행이 생기는 순간 그 값은 `ctx.policy.*`가 되어 **모든 정산 판정에
들어간다**(`policy-domain.md` §3.1). 문서에서 뽑은 값을 그대로 넣으면 잘못 읽힌 숫자가
조용히 판정을 바꾼다 — 게다가 표 파싱은 셀 병합·줄바꿈 때문에 틀리기 쉬운 자리다.

## 승인이 강제하는 것 — 축

축(`key_axes`)은 **EvalContext 사실 경로**여야 한다. 스키마에 없는 축은 `resolve_path`가
늘 `None`을 돌려주고 `strict_keys=False` 표는 `"*"`로 조용히 폴백한다 — 값도 나오고
에러도 플래그도 없다(`dining_per_person_limit_table`이 실제로 그 상태였다).

그래서 여기서 **거부한다**. 경고가 아니라 거부인 이유: 경고는 승인 버튼을 누르는 사람이
읽고 넘길 수 있고, 넘기면 그 순간부터 아무도 모르게 잘못 동작한다. 축을 고치거나 축을
빼는 것 둘 중 하나를 사람이 선택해야 한다.

## 승인이 강제하지 않는 것 — 값

payload의 숫자가 원문과 맞는지는 시스템이 알 수 없다. 그래서 화면이 **표 원문을 나란히**
보여주고(`raw_markdown`), 사람이 대조한다. 승인은 "내가 대조했다"는 서명이다.
"""
from __future__ import annotations

import re
from typing import Any

from django.db import transaction
from django.utils import timezone

from .eval_context import EVAL_CONTEXT_SCHEMA_PATHS
from .models import PolicyTable, PolicyTableProposal, TableProposalStatus

#: 별표 key 표기 — `ctx.policy.<이름>` 파생에 쓰이므로 식별자로 안전해야 한다.
KEY_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")


class ProposalError(ValueError):
    """승인 거부 — 사유를 그대로 화면에 띄운다."""


def validate(proposal: PolicyTableProposal) -> list[str]:
    """승인 전 검사. 통과하지 못하는 이유를 **전부** 모아 돌려준다.

    하나씩 알려주면 고치고 누르고를 반복하게 된다 — 표 하나에 축·키·리프가 동시에
    틀려 있는 경우가 드물지 않다.
    """
    problems: list[str] = []

    key = (proposal.key or "").strip()
    if not KEY_RE.match(key):
        problems.append(
            f"별표 key `{key}`가 표기 규칙에 맞지 않습니다 — 영문 소문자·숫자·밑줄, 3자 이상"
            " (예: `daily_limit_table`)."
        )

    axes = list(proposal.key_axes or [])
    unknown = [a for a in axes if a not in EVAL_CONTEXT_SCHEMA_PATHS]
    if unknown:
        problems.append(
            "축이 판정 사실 목록에 없습니다: " + ", ".join(unknown)
            + " — 실재하는 경로로 바꾸거나, 표에 값이 하나뿐이면 축을 비우세요."
              " (없는 축은 에러 없이 항상 기본값으로 떨어져 표가 무력해집니다.)"
        )

    payload = proposal.payload
    if not isinstance(payload, dict) or not payload:
        problems.append("표 내용(payload)이 비어 있습니다.")
    else:
        problems.extend(_payload_problems(payload, axes))

    if not proposal.effective_date:
        problems.append("시행일이 없습니다 — 과거 판정을 그 시점 한도로 재현하는 축입니다.")

    return problems


def _payload_problems(payload: dict, axes: list[str]) -> list[str]:
    """축 깊이와 payload 구조가 맞는지 + 리프가 쓸 수 있는 값인지."""
    problems: list[str] = []
    if not axes:
        if "value" not in payload:
            problems.append(
                '축이 없는 표는 `{"value": <숫자>}` 형태여야 합니다 — 표가 행·열로 값을'
                ' 고른다면 값을 바꾸지 말고 **축을 먼저 고르세요**.'
            )
        elif isinstance(payload.get("value"), (dict, list)):
            problems.append("축이 없는 표의 값은 스칼라여야 합니다.")
        return problems

    #  축을 선언해 놓고 `{"value": …}`(축 없는 표의 예약 키)로 온 경우. 구조 검사는
    #  통과한다 — 축 값이 문자열 "value"인 행으로 읽히기 때문이다. 그러면 그 표는
    #  **승인은 되는데 영원히 해소되지 않는다**(직책이 "value"인 사람은 없다).
    #  실측으로 잡았다: LLM이 축은 고르고 payload는 단일값으로 낸 제안이 200으로 통과했다.
    if set(payload) == {"value"}:
        problems.append(
            f'축({", ".join(axes)})을 선언했는데 표 내용이 `{{"value": …}}` 한 칸입니다 — '
            "축 값별로 나누거나(예: `{\"부서장\": 30000, \"*\": 20000}`), 값이 하나뿐이면 "
            "축을 비우세요. 지금 형태로 승인하면 이 표는 아무 건에도 걸리지 않습니다."
        )
        return problems

    def walk(node: Any, depth: int, path: str) -> None:
        if depth == 0:
            if isinstance(node, dict):
                problems.append(f"축({len(axes)}개)보다 깊습니다: {path}")
            return
        if not isinstance(node, dict):
            problems.append(f"축({len(axes)}개)보다 얕습니다: {path or '(최상위)'}")
            return
        for key, child in node.items():
            walk(child, depth - 1, f"{path}.{key}" if path else str(key))

    walk(payload, len(axes), "")
    return problems


@transaction.atomic
def approve(proposal: PolicyTableProposal, *, actor=None, note: str = "") -> PolicyTable:
    """제안을 `PolicyTable` 행으로 승격한다.

    **개정은 UPDATE가 아니라 INSERT**다(`PolicyTable` 계약). 같은 key가 이미 있으면 새
    `effective_date` 행을 추가하고 구행에 `superseded_date`를 찍는다 — 과거 판정을 그
    시점 한도로 재현해야 하기 때문이다. 같은 (key, effective_date)면 그건 재승인이라
    덮어쓴다(유니크 제약이 있기도 하다).
    """
    problems = validate(proposal)
    if problems:
        raise ProposalError("\n".join(problems))

    key = proposal.key.strip()
    effective = proposal.effective_date

    superseded = (
        PolicyTable.objects.filter(key=key, superseded_date__isnull=True)
        .exclude(effective_date=effective)
        .filter(effective_date__lt=effective)
    )
    superseded.update(superseded_date=effective)

    table, _ = PolicyTable.objects.update_or_create(
        key=key, effective_date=effective,
        defaults={
            "title": proposal.title[:200],
            "key_axes": list(proposal.key_axes or []),
            "payload": proposal.payload,
            "strict_keys": bool(proposal.strict_keys),
            "source_doc": proposal.doc,
            "source_clause": proposal.citation[:200],
            "superseded_date": None,
        },
    )

    proposal.status = TableProposalStatus.APPROVED
    proposal.approved_table = table
    proposal.review_note = note
    proposal.reviewed_by = actor if getattr(actor, "is_authenticated", False) else None
    proposal.reviewed_at = timezone.now()
    proposal.save(update_fields=[
        "status", "approved_table", "review_note", "reviewed_by", "reviewed_at", "updated_at",
    ])
    return table


def reject(proposal: PolicyTableProposal, *, actor=None, note: str = "") -> PolicyTableProposal:
    """제안을 반려한다 — **사유가 필수**.

    "이 표는 왜 임계값이 아니지"를 나중에 묻는 사람이 반드시 나온다(조항 `SKIP`에 사유를
    강제하는 것과 같은 이유). 재색인 때 같은 표가 다시 올라오는데, 사유가 없으면 같은
    검토를 처음부터 다시 한다.
    """
    if not note.strip():
        raise ProposalError("반려 사유를 적어주세요 — 재색인 때 같은 표가 다시 올라옵니다.")
    proposal.status = TableProposalStatus.REJECTED
    proposal.review_note = note.strip()
    proposal.reviewed_by = actor if getattr(actor, "is_authenticated", False) else None
    proposal.reviewed_at = timezone.now()
    proposal.save(update_fields=[
        "status", "review_note", "reviewed_by", "reviewed_at", "updated_at",
    ])
    return proposal

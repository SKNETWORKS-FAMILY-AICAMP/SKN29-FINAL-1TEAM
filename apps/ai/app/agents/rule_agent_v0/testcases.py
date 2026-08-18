# apps/ai/app/agents/rule_agent_v0/testcases.py
"""Rule Agent — 검증셋(테스트케이스) 자동생성 (`agent-v1-upgrade-plan.md` §4).

§1-5(대화형 수정)와 다른 성격 — **대화형이 아니다.** 사람이 다듬을 기회가 없으니 결과
자체의 정확성을 스스로 담보해야 한다. 그래서 두 축으로 만든다:

  1. **커버리지 기반 결정론적 생성** — 노드 조건(JSON-Logic)을 역산해서 "이 노드가
     걸리는 값"을 계산한다. LLM에게 "적당히 만들어봐"라고 맡기지 않는다(`_solve()`).
     LLM은 생성된 값에 자연스러운 라벨(상호명 등)을 붙이는 서술 역할만 한다.
  2. **자체 검증 루프** — 후보를 실제로 그래프에 반영하고 기존 `simulate_graph()`
     (§1-3에서 이미 만든, `/simulate` 재사용 함수)로 돌려서 **의도한 노드에 실제로
     걸리는지** 확인한다. 그래프가 severity 우선순위 선형 체인이라(§1-1),
     "이 노드 조건만 보면 맞지만 그보다 먼저 걸리는 상위 노드가 있어서 실제로는
     그 노드에 안 걸리는" 경우가 생길 수 있다 — 조건 하나만 보는 역산으로는 못 잡고,
     실제로 그래프를 돌려봐야만 드러난다.

확정된 스코프(agent-v1-upgrade-plan.md §4.3):
  - **추가(append) 방식** — 기존 커스텀 케이스를 지우지 않는다. Django
    `PUT /test-cases/`가 전체 교체라, 여기서 기존 것을 먼저 읽어 합친 뒤 통째로 쓴다.
  - **노드당 2건** — ①확실히 걸리는 값(여유 마진) ②경계값(임계값 바로 위/아래 1 단위).
    `>`/`>=` 같은 연산자 실수를 경계값이 잡는다.

v1 스코프 한계(문서화, §4.4 미정 사항과 별개로 구현 시점에 정한 것):
  - 조건이 `var op 리터럴`(비교) 또는 그것들의 and/or/not 조합이 아니면(예: 산술식,
    지원 안 하는 형태) 그 노드는 건너뛰고 사유를 응답에 남긴다 — 지어내지 않는다.
  - 자체검증 실패(상위 노드 선점 등)는 1회만 재시도(마진을 좁혀서)하고, 그래도
    실패하면 그 후보는 최종 저장에서 빼고 사유(`actualDecision`/`actualPath`)를
    응답에 남긴다 — 틀린 케이스를 검증셋에 몰래 끼워넣지 않는다.
"""
from __future__ import annotations

import json
from typing import Any

from . import django_client
from .agent import SEVERITIES, _openai
from .settings import settings

CASES_PER_NODE = 2
MAX_VERIFY_ATTEMPTS = 2  # 최초 1회 + 재시도 1회 (결정론적 역산이라 §1-4의 3회보다 적게 잡음)

_UNSUPPORTED = object()
_NEGATE_OP = {">": "<=", ">=": "<", "<": ">=", "<=": ">"}


# ---------------------------------------------------------------- 조건 역산

def _value_for_leaf(op: str, literal: Any, want_match: bool, boundary: bool) -> Any:
    """단일 비교(`op`)를 만족(or 불만족)시키는 값 하나를 계산. 못 풀면 `_UNSUPPORTED`."""
    is_num = isinstance(literal, (int, float)) and not isinstance(literal, bool)

    if op in (">", ">=", "<", "<="):
        if not is_num:
            return _UNSUPPORTED
        eps = 1 if isinstance(literal, int) else 0.01
        # 여유 마진 케이스는 임계값 규모에 비례 + 최소폭 보장 — 임계값이 0에 가까워도
        # 눈에 띄게 벌어지게 한다.
        far = max(abs(literal) * 0.5, 10000) + eps
        effective = op if want_match else _NEGATE_OP[op]
        if effective == ">":
            return literal + (eps if boundary else far)
        if effective == ">=":
            return literal if boundary else literal + far
        if effective == "<":
            return literal - (eps if boundary else far)
        if effective == "<=":
            return literal if boundary else literal - far
        return _UNSUPPORTED

    if op == "==":
        if want_match:
            return literal
        return _value_for_leaf("!=", literal, True, boundary)

    if op == "!=":
        if not want_match:
            return literal
        if is_num:
            return literal + 1
        if isinstance(literal, str):
            return literal + "_다른값"
        return _UNSUPPORTED

    if op == "in":
        if not isinstance(literal, list) or not literal:
            return _UNSUPPORTED
        if want_match:
            return literal[-1] if boundary else literal[0]
        return _UNSUPPORTED  # 목록에 없는 값을 일반적으로 만들 방법이 없음 — 지원 안 함

    return _UNSUPPORTED


def _solve(cond: Any, want_match: bool, boundary: bool) -> dict[str, Any] | None:
    """조건 트리 → 그 결과를 만드는 facts(dot-path → 값). 못 풀면 None(포기, 지어내지 않음)."""
    if cond is True or cond is False:
        return {} if cond == want_match else None
    if not isinstance(cond, dict) or len(cond) != 1:
        return None
    op, args = next(iter(cond.items()))

    if op == "and":
        if not want_match:
            return _solve(args[0], False, boundary) if args else None
        facts: dict[str, Any] = {}
        for c in args:
            sub = _solve(c, True, boundary)
            if sub is None:
                return None
            facts.update(sub)
        return facts

    if op == "or":
        if want_match:
            return _solve(args[0], True, boundary) if args else None
        facts = {}
        for c in args:
            sub = _solve(c, False, boundary)
            if sub is None:
                return None
            facts.update(sub)
        return facts

    if op == "not":
        child = args[0] if isinstance(args, list) else args
        return _solve(child, not want_match, boundary)

    if op in {"==", "!=", ">", ">=", "<", "<=", "in"}:
        if not isinstance(args, list) or len(args) != 2:
            return None
        left, right = args
        if not (isinstance(left, dict) and set(left) == {"var"}):
            return None
        path = left["var"]
        if isinstance(right, dict) and set(right) == {"var"}:
            # var-vs-var(예: tx.amount > policy.dining_per_person_limit) — 참조하는
            # 쪽에 기준값을 박아넣고, 그 기준값 대비로 좌변을 계산한다.
            baseline = 30000
            value = _value_for_leaf(op, baseline, want_match, boundary)
            if value is _UNSUPPORTED:
                return None
            return {right["var"]: baseline, path: value}
        value = _value_for_leaf(op, right, want_match, boundary)
        if value is _UNSUPPORTED:
            return None
        return {path: value}

    return None


# ---------------------------------------------------------------- 후보 생성

def _candidates_for_node(node: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    """노드 1개 → 후보 최대 2건(facts만, 라벨은 아직 없음). 실패 사유도 같이 돌려준다."""
    action = node.get("action") or {}
    decision = action.get("decision")
    if decision not in {"REJECT", "RETURN", "REVIEW"}:
        return [], None  # PASS(_SCOPE_PASS) 등은 대상 아님

    far = _solve(node["condition"], True, boundary=False)
    near = _solve(node["condition"], True, boundary=True)
    if far is None and near is None:
        return [], "지원하지 않는 조건 형태(단순 비교/and/or/not 조합만 역산 가능)"

    out = []
    if far is not None:
        out.append({"kind": "definite", "facts": far, "decision": decision, "node_key": node["nodeKey"]})
    if near is not None:
        out.append({"kind": "boundary", "facts": near, "decision": decision, "node_key": node["nodeKey"]})
    return out, None


# ---------------------------------------------------------------- 라벨링(LLM, 1회 배치)

_LABEL_SCHEMA = {
    "name": "test_case_labels",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "labels": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "index": {"type": "integer"},
                        "label": {"type": "string"},
                        "merchant": {"type": "string"},
                        "amount": {"type": "integer", "description": "이 케이스에 어울리는 원화 거래 금액(표시용)"},
                    },
                    "required": ["index", "label", "merchant", "amount"],
                },
            },
        },
        "required": ["labels"],
    },
}


def _label_candidates(candidates: list[dict[str, Any]], node_titles: dict[str, str]) -> None:
    """후보 리스트에 label/merchant/amount(표시용)를 채운다(제자리 수정). 실패해도 조용히
    기본값으로 대체 — 서술일 뿐이라 이것 때문에 생성 전체를 막지 않는다.

    `amount`는 **표시용**이다 — `facts`에 이미 tx.amount/tx.per_person_amount가 있으면 그
    값과 앞뒤가 맞는 금액을, 없으면(예: 참석자 수·2차 여부만 보는 조건) 이 시나리오에
    자연스러운 금액을 채운다. `facts` 자체는 건드리지 않으므로 판정 로직에는 영향이 없다
    — 화면의 "금액 ₩0"이 마치 데이터 오류처럼 보인다는 실사용 피드백(2026-08-18)으로 추가."""
    if not candidates:
        return
    lines = []
    for i, c in enumerate(candidates):
        title = node_titles.get(c["node_key"], c["node_key"])
        kind = "확실히 걸리는 값" if c["kind"] == "definite" else "경계값(임계값 바로 근처)"
        lines.append(f"[{i}] 노드: {title} / 유형: {kind} / 조건에 쓰인 값: {c['facts']}")
    prompt = (
        "아래는 법인카드 정산 룰 검증에 쓸 테스트케이스 후보입니다. 각 항목에 "
        "회계 담당자가 읽기 자연스러운 label(짧은 설명)과 merchant(가상 가맹점명), "
        "amount(원화 거래 금액, 표시용)를 붙여주세요. 조건에 쓰인 값(tx.amount 또는 "
        "tx.per_person_amount)이 있으면 그 값과 앞뒤가 맞는 금액을 쓰고, 없으면 이 "
        "시나리오에 어울리는 현실적인 금액(대략 3만~80만원)을 지어내세요. 라벨·가맹점은 "
        "조건에 쓰인 값과 안 맞는 서술을 넣지 마세요.\n\n" + "\n".join(lines)
    )
    try:
        resp = _openai().chat.completions.create(
            model=settings.model, temperature=0.4, timeout=30,
            response_format={"type": "json_schema", "json_schema": _LABEL_SCHEMA},
            messages=[{"role": "user", "content": prompt}],
        )
        labels = json.loads(resp.choices[0].message.content).get("labels", [])
        by_index = {item["index"]: item for item in labels if isinstance(item.get("index"), int)}
        for i, c in enumerate(candidates):
            item = by_index.get(i)
            c["label"] = item["label"] if item else f"{c['node_key']} {c['kind']}"
            c["merchant"] = item["merchant"] if item else ""
            amount = item.get("amount") if item else None
            c["display_amount"] = amount if isinstance(amount, (int, float)) and amount > 0 else None
    except Exception:  # noqa: BLE001 — 라벨링 실패는 치명적이지 않다, 기본값으로 대체
        for c in candidates:
            c["label"] = f"{c['node_key']} {c['kind']}"
            c["merchant"] = ""
            c["display_amount"] = None


# ---------------------------------------------------------------- 키 배정(충돌 회피)

def _next_keys(existing: list[dict[str, Any]], count: int) -> list[str]:
    used = {str(c.get("id", "")) for c in existing}
    keys, n = [], 1
    while len(keys) < count:
        key = f"AUTO-{n}"
        if key not in used:
            keys.append(key)
            used.add(key)
        n += 1
    return keys


# ---------------------------------------------------------------- 진입점

def _facts_signature(facts: dict[str, Any]) -> frozenset:
    return frozenset(facts.items())


def generate_test_cases(graph_id: str) -> dict[str, Any]:
    """그래프의 실 노드마다 최대 2건씩 결정론적으로 만들고, 실제로 돌려서 검증한 뒤
    기존 검증셋에 추가(append)한다. 반환: 생성 요약 + 최신 시뮬레이션 보고서.

    같은 그래프에 다시 누르면(그래프가 그대로면) `_solve()`가 매번 같은 facts를
    돌려준다 — 재실행마다 라벨/가맹점만 새로 지어 사실상 똑같은 케이스를 계속
    추가하는 사고가 있었다(2026-08-18, 실사용 재현: 같은 4개 노드가 8→16건으로
    "숫자만 바뀌고 복붙"). 그래서 이미 있는 AUTO-* 케이스와 facts가 완전히 같은
    후보는 건너뛴다 — 노드 조건이 실제로 바뀌었을 때만 새 후보가 추가된다.
    """
    graph = django_client.get_graph(graph_id)
    nodes = sorted(
        (n for n in graph.get("nodes", []) if n["nodeKey"] != "_SCOPE_PASS"),
        key=lambda n: n.get("priority", 0),
    )
    node_titles = {n["nodeKey"]: (n.get("action") or {}).get("title", n["nodeKey"]) for n in nodes}

    existing = django_client.get_test_cases(graph_id)
    covered = {
        _facts_signature(case.get("facts") or {})
        for case in existing if str(case.get("id", "")).startswith("AUTO-")
    }

    all_candidates: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    already_covered = 0
    for node in nodes:
        cands, reason = _candidates_for_node(node)
        if reason:
            skipped.append({"node_key": node["nodeKey"], "reason": reason})
        for cand in cands[:CASES_PER_NODE]:
            if _facts_signature(cand["facts"]) in covered:
                already_covered += 1
                continue
            all_candidates.append(cand)

    if not all_candidates:
        return {
            "status": "NO_CANDIDATES" if not already_covered else "ALREADY_COVERED",
            "detail": (
                "역산 가능한 노드가 없습니다(전부 지원 범위 밖 조건이거나 노드가 없음)."
                if not already_covered else
                f"이미 검증셋에 있는 케이스와 조건이 같아 추가할 새 후보가 없습니다({already_covered}건 건너뜀) "
                "— 그래프 조건을 바꾼 뒤 다시 시도하세요."
            ),
            "skipped": skipped,
        }

    _label_candidates(all_candidates, node_titles)

    keys = _next_keys(existing, len(all_candidates))
    for cand, key in zip(all_candidates, keys):
        cand["id"] = key

    verified: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    pending = all_candidates

    for attempt in range(1, MAX_VERIFY_ATTEMPTS + 1):
        payload = existing + [_to_payload(c, graph["scope"]) for c in verified] + [_to_payload(c, graph["scope"]) for c in pending]
        django_client.put_test_cases(graph_id, payload)
        report = django_client.simulate_graph(graph_id)
        rows_by_id = {row["id"]: row for row in report.get("testResults", [])}

        still_pending = []
        for cand in pending:
            row = rows_by_id.get(cand["id"])
            ok = bool(row) and cand["node_key"] in (row.get("path") or []) and row.get("decision") == cand["decision"]
            if ok:
                verified.append(cand)
            elif attempt < MAX_VERIFY_ATTEMPTS:
                # 경계 마진을 좁혀서(더 boundary 쪽으로) 한 번 더 시도 — 상위 노드 선점 등으로
                # 벗어난 경우 재시도로 항상 고쳐지는 건 아니지만(결정론적이라), 마진 조정으로
                # 회복되는 경우가 있어 한 번은 시도한다.
                still_pending.append(cand)
            else:
                unresolved.append({
                    **cand,
                    "actualDecision": row.get("decision") if row else None,
                    "actualPath": row.get("path") if row else None,
                })
        pending = still_pending
        if not pending:
            break

    # 최종 저장 — 실패분은 빼고 검증된 것만 기존 것 뒤에 append.
    final_payload = existing + [_to_payload(c, graph["scope"]) for c in verified]
    django_client.put_test_cases(graph_id, final_payload)
    final_report = django_client.simulate_graph(graph_id)

    return {
        "status": "DONE",
        "generated": len(verified),
        "unresolved": [
            {"nodeKey": u["node_key"], "kind": u["kind"], "reason": "자체검증 실패",
             "actualDecision": u.get("actualDecision"), "actualPath": u.get("actualPath")}
            for u in unresolved
        ],
        "skippedNodes": skipped,
        "testCases": final_payload,
        "simulationReport": final_report,
    }


def _to_payload(cand: dict[str, Any], category: str) -> dict[str, Any]:
    fact_amount = cand["facts"].get("tx.amount")
    # 조건 자체가 tx.amount를 쓰면 그 값이 최우선(=판정 근거와 화면 표시가 반드시 일치해야
    # 함). 아니면 라벨링 단계에서 지어낸 표시용 금액을 쓴다 — `facts`엔 안 들어가므로
    # 판정에는 영향이 없다(§13.4, `rule-agent-v1-implementation.md`).
    if isinstance(fact_amount, (int, float)):
        amount = fact_amount
    elif cand.get("display_amount"):
        amount = cand["display_amount"]
    else:
        amount = 0
    return {
        "id": cand["id"],
        "label": cand.get("label", cand["node_key"]),
        "merchant": cand.get("merchant", ""),
        "amount": amount,
        "category": category,
        "expected": cand["decision"],
        "facts": cand["facts"],
    }

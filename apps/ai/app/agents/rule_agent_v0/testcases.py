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

확정된 스코프(agent-v1-upgrade-plan.md §4.3, 2026-08-18 §2-1 후속으로 갱신):
  - **교체(replace) 방식** — 수동으로 검증셋을 만들던 mock 모달을 제거해 이 함수가
    검증셋의 유일한 생성 경로가 됐다(2026-08-18). 유일한 경로면 매번 "지금 그래프
    기준 검증셋"을 새로 만드는 게 맞다 — 이전엔 기존 것 뒤에 추가(append)했는데,
    그래프를 고친 뒤에도 예전 조건 기준 낡은 케이스가 안 지워지고 남는 부작용이
    있었다. Django `PUT /test-cases/`는 원래도 전체 교체라, 이제 그대로 새 결과만
    보낸다(기존 것을 먼저 읽어 합치지 않음).
  - **노드당 최대 5건** — ①확실히 걸리는 값 ②경계값 ③분기 반대편(확실히/경계값)
    ④결측(조건이 참조하는 필드를 통째로 비움). ③④는 이 노드만 봐서는 결과를 예측할
    수 없어 실제로 한 번 돌려 나온 값을 정답으로 기록한다(`predictable=False`).

v1 스코프 한계(문서화, §4.4 미정 사항과 별개로 구현 시점에 정한 것):
  - 조건이 `var op 리터럴`(비교) 또는 그것들의 and/or/not 조합이 아니면(예: 산술식,
    지원 안 하는 형태) 그 노드는 건너뛰고 사유를 응답에 남긴다 — 지어내지 않는다.
  - **자체검증은 단회(單回)다 — 재시도하지 않는다(2026-08-19 정정).** 이전엔 실패 시
    "마진을 좁혀 재시도"한다고 되어 있었는데, 후보(facts·목표 decision)가 재시도
    사이에 전혀 안 바뀌므로 같은 입력을 결정론적 엔진에 다시 넣어도 반드시 같은
    결과가 나온다 — 그 "재시도"는 항상 첫 시도와 동일한 결과를 내는 죽은 코드였다.
    실패하면 그 후보는 최종 저장에서 빼고, 재시도 대신 **왜 실패했는지**(우선순위
    높은 다른 노드가 가로챘는지 / decision 설정이 다른지)를 `generationLog`에
    남긴다(§2-2) — 틀린 케이스를 검증셋에 몰래 끼워넣지 않는다.
"""
from __future__ import annotations

import json
from typing import Any

from . import django_client
from .agent import SEVERITIES, _openai
from .settings import settings

MAX_CANDIDATES_PER_NODE = 5  # 확실히 걸림·경계값·분기반대편(경계·확실)·결측 — 최대 5종
# 그래프 전체 최소 목표 — 실제로 역산 가능한 노드/조건이 부족하면 그보다 적을 수 있다
# (지어내진 않는다). 이 미달 시 "M/N건" 처럼 몇 건이 부족한지 응답에 남긴다
# (agent-v1-upgrade-plan.md 후속 §2-1, 2026-08-18 설계+구현).
MIN_TOTAL_TARGET = 5
# 그래프 전체 상한 — 노드가 많은 그래프(예: 4노드×5종=20)에서 검증셋이 과하게 커지는 것을
# 막는다. predictable(definite/boundary)은 노드 커버리지의 핵심이라 자르지 않고, discovery
# (분기반대편·결측)만 이 상한에 맞춰 줄인다(2026-08-18, 15건이 너무 많다는 피드백으로 도입).
MAX_TOTAL_CANDIDATES = 10

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


def _referenced_paths(cond: Any) -> list[str]:
    """조건 트리가 참조하는 EvalContext dot-path 전부(결측 케이스 생성용) — 순서 유지, 중복 제거."""
    if not isinstance(cond, dict) or len(cond) != 1:
        return []
    op, args = next(iter(cond.items()))
    if op in {"and", "or"}:
        seen: list[str] = []
        for c in args:
            for p in _referenced_paths(c):
                if p not in seen:
                    seen.append(p)
        return seen
    if op == "not":
        child = args[0] if isinstance(args, list) else args
        return _referenced_paths(child)
    if op in {"==", "!=", ">", ">=", "<", "<=", "in"} and isinstance(args, list) and len(args) == 2:
        left, right = args
        paths = []
        if isinstance(left, dict) and set(left) == {"var"}:
            paths.append(left["var"])
        if isinstance(right, dict) and set(right) == {"var"}:
            paths.append(right["var"])
        return paths
    return []


# ---------------------------------------------------------------- 후보 생성

def _candidates_for_node(node: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    """노드 1개 → 후보 최대 5건(facts만, 라벨은 아직 없음). 실패 사유도 같이 돌려준다.

    엣지케이스 4종(설계 §2-1) 중 이 노드에 적용 가능한 것만 생성한다:
      ① 확실히 걸리는 값(`definite`) ② 경계값(`boundary`) — 이 노드의 조건이 참일 때만
      의미가 있고, 예측한 대로(이 노드의 decision) 걸리는지 자체검증 루프로 확인한다
      (`predictable=True`).
      ③ 분기 반대편(`opposite`/`opposite_boundary`) — 이 노드 조건이 거짓이 될 때 그래프가
      실제로 어디로 가는지는 하위 라우팅에 달려 있어 이 함수만으로는 예측 불가하다 →
      `predictable=False`로 표시해두면 호출부가 예측 대신 **실제로 한 번 돌려 나온 값을
      정답으로 기록**한다(자체검증이 아니라 "발견 후 기록").
      ④ 결측(`missing_fact`) — 조건이 참조하는 필드를 통째로 비워 `UNRESOLVED_FACT` 가드가
      실제로 발동하는지 확인한다. 이것도 결과를 예측하지 않고 발견해서 기록한다.
    """
    action = node.get("action") or {}
    decision = action.get("decision")
    if decision not in {"REJECT", "RETURN", "REVIEW"}:
        return [], None  # PASS(_SCOPE_PASS) 등은 대상 아님

    if node["condition"] is True:
        # 조건이 항상 참인 종단(fallback) 노드 — "상위 노드들이 전부 매칭 안 됐을 때"만
        # 도달하므로, 이 노드에 실제로 도달하려면 조상 노드 조건까지 전부 같이 풀어야 한다.
        # `_solve`는 노드 하나만 보고 역산하므로 여기선 빈 facts만 나와(트리비얼) 실제
        # 경로를 못 만든다 — 시도해봐야 항상 자체검증 실패라 애초에 건너뛴다(2026-08-18
        # 실사용 발견: "출장비 검증 통과" 노드가 매번 2건씩 실패로 잡혀 검증셋이 적어 보였다).
        return [], "종단(fallback) 노드 — 상위 노드 조건까지 함께 풀어야 도달 경로를 만들 수 있어 단일 노드 역산으로는 지원하지 않습니다."

    cond = node["condition"]
    far = _solve(cond, True, boundary=False)
    near = _solve(cond, True, boundary=True)
    if far is None and near is None:
        return [], "지원하지 않는 조건 형태(단순 비교/and/or/not 조합만 역산 가능)"

    out: list[dict[str, Any]] = []
    if far is not None:
        out.append({"kind": "definite", "facts": far, "decision": decision, "node_key": node["nodeKey"], "predictable": True})
    if near is not None:
        out.append({"kind": "boundary", "facts": near, "decision": decision, "node_key": node["nodeKey"], "predictable": True})

    # ③ 분기 반대편 — 예측 불가, 발견해서 기록
    opp_far = _solve(cond, False, boundary=False)
    opp_near = _solve(cond, False, boundary=True)
    if opp_far is not None:
        out.append({"kind": "opposite", "facts": opp_far, "decision": None, "node_key": node["nodeKey"], "predictable": False})
    if opp_near is not None and _facts_signature(opp_near) != _facts_signature(opp_far or {}):
        out.append({"kind": "opposite_boundary", "facts": opp_near, "decision": None, "node_key": node["nodeKey"], "predictable": False})

    # ④ 결측 — 이 조건이 참조하는 필드를 아예 비운다(다른 필드는 안 건드림). 예측 불가.
    if _referenced_paths(cond):
        out.append({"kind": "missing_fact", "facts": {}, "decision": None, "node_key": node["nodeKey"], "predictable": False})

    return out[:MAX_CANDIDATES_PER_NODE], None


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
    kind_label = {
        "definite": "확실히 걸리는 값", "boundary": "경계값(임계값 바로 근처)",
        "opposite": "분기 반대편(조건 불충족, 확실히)", "opposite_boundary": "분기 반대편(임계값 바로 근처)",
        "missing_fact": "판단에 필요한 정보 결측(입력 누락)",
    }
    lines = []
    for i, c in enumerate(candidates):
        title = node_titles.get(c["node_key"], c["node_key"])
        kind = kind_label.get(c["kind"], c["kind"])
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
        # 경량 모델 유지 — 판정(기대 verdict)은 `_solve`+결정론적 재검증이 정하고, 여기는
        # 화면에 보일 라벨·가맹점명·표시용 금액만 지어낸다. 실패해도 기본값으로 대체되고
        # 판정 로직에는 영향이 없으므로 심층 모델(`model_heavy`)을 쓸 이유가 없다.
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


# ---------------------------------------------------------------- 진입점

def _facts_signature(facts: dict[str, Any]) -> frozenset:
    return frozenset(facts.items())


def _reachable_node_keys(graph: dict[str, Any]) -> set[str]:
    """진입 노드에서 라우팅을 따라가 도달 가능한 노드 집합(`simulation.py::_graph_shape`와
    같은 BFS). 도달 불가 노드는 실행 경로에 절대 안 잡히므로 이 노드를 겨냥한 검증셋
    후보는 몇 번을 시도해도 자체검증에서 항상 실패한다 — 헛되이 후보 예산(2건/노드)을
    태우지 않도록 애초에 건너뛴다(2026-08-18, 실사용 발견: 도달 불가 노드 1개 때문에
    6개 후보 중 2개만 살아남는 그래프에서 원인이 안 보였다)."""
    entry = graph.get("entryNodeKey") or ""
    node_keys = {n["nodeKey"] for n in graph.get("nodes", [])}
    if entry not in node_keys:
        return set()
    routings = graph.get("routings", [])
    reached = {entry}
    queue = [entry]
    while queue:
        current = queue.pop(0)
        for route in routings:
            to_key = route.get("toNodeKey")
            if route.get("fromNodeKey") == current and to_key and to_key not in reached:
                reached.add(to_key)
                queue.append(to_key)
    return reached


def generate_test_cases(graph_id: str) -> dict[str, Any]:
    """그래프의 실 노드마다 최대 5건씩 결정론적으로 만들고, 실제로 돌려서 검증한 뒤
    **검증셋을 통째로 교체**한다(예전 버전은 append였다 — 2026-08-18 replace로 전환).
    반환: 생성 요약 + 최신 시뮬레이션 보고서.

    replace인 이유: 사람이 직접 검증셋을 만들던 mock 모달을 없애(2026-08-18) 이제
    "검증셋 자동생성"이 유일한 생성 경로다. 유일한 경로라면 매번 "지금 그래프 조건
    기준으로 있어야 할 검증셋"을 새로 만드는 게 맞다 — append+dedup은 그래프를 고칠
    때마다 낡은 케이스(이전 조건 기준으로 만들어진, 지금은 안 맞을 수도 있는 facts/기대값)가
    계속 쌓이는 부작용이 있었다(실사용 발견: 그래프를 고쳤는데 예전 검증셋의 기대판정이
    낡은 값으로 남아있었다).
    """
    graph = django_client.get_graph(graph_id)
    nodes = sorted(
        (n for n in graph.get("nodes", []) if n["nodeKey"] != "_SCOPE_PASS"),
        key=lambda n: n.get("priority", 0),
    )
    node_titles = {n["nodeKey"]: (n.get("action") or {}).get("title", n["nodeKey"]) for n in nodes}

    reachable = _reachable_node_keys(graph)
    all_candidates: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for node in nodes:
        if node["nodeKey"] not in reachable:
            skipped.append({
                "node_key": node["nodeKey"],
                "reason": "도달 불가 노드 — 진입 노드에서 이어지는 라우팅이 없어 검증해도 항상 실패합니다. "
                          "라우팅을 연결한 뒤 다시 시도하세요.",
            })
            continue
        cands, reason = _candidates_for_node(node)
        if reason:
            skipped.append({"node_key": node["nodeKey"], "reason": reason})
        all_candidates.extend(cands)

    if not all_candidates:
        return {
            "status": "NO_CANDIDATES",
            "detail": "역산 가능한 노드가 없습니다(전부 지원 범위 밖 조건이거나 노드가 없음).",
            "skipped": skipped,
        }

    # predictable(definite/boundary) = "이 노드가 이 값으로 걸린다"를 미리 예측하고 자체검증
    # 루프로 확인. discovery(opposite*/missing_fact) = 예측 불가라 실제로 한 번 돌려 나온
    # 값을 정답으로 기록(§2-1 설계, 2026-08-18).
    predictable = [c for c in all_candidates if c.get("predictable", True)]
    discovery = [c for c in all_candidates if not c.get("predictable", True)]

    # 전체 상한을 넘으면 discovery만 줄인다 — 한 노드 것부터 다 자르지 않고 노드별로
    # 돌아가며 하나씩 덜어내 커버리지를 고르게 유지한다.
    budget = max(0, MAX_TOTAL_CANDIDATES - len(predictable))
    trimmed_count = 0
    if len(discovery) > budget:
        by_node: dict[str, list[dict[str, Any]]] = {}
        for c in discovery:
            by_node.setdefault(c["node_key"], []).append(c)
        kept: list[dict[str, Any]] = []
        while len(kept) < budget:
            progressed = False
            for key in list(by_node):
                if by_node[key]:
                    kept.append(by_node[key].pop(0))
                    progressed = True
                    if len(kept) >= budget:
                        break
            if not progressed:
                break
        trimmed_count = len(discovery) - len(kept)
        discovery = kept

    all_candidates = predictable + discovery
    _label_candidates(all_candidates, node_titles)

    for i, cand in enumerate(all_candidates, start=1):
        cand["id"] = f"AUTO-{i}"

    verified: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    generation_log: list[dict[str, Any]] = []

    # predictable 자체검증 — **단일 회차**다. 이전엔 실패 시 "마진을 좁혀 재시도"한다는
    # 주석과 함께 2회까지 돌렸는데, 검토 중 발견: `cand`(facts·id·목표 decision)가 재시도
    # 사이에 전혀 안 바뀐다 — 같은 입력을 결정론적 엔진에 다시 넣으면 반드시 같은 결과가
    # 나오므로 그 "재시도"는 매번 첫 시도와 완전히 동일한 결과를 내는 죽은 코드였다
    # (2026-08-19 발견·정리). 실패 원인은 재시도가 아니라 **왜 실패했는지 기록**으로 대체한다
    # (§2-2 — 예측한 노드/판정과 실제 도달한 경로/판정을 비교해 사람이 읽을 사유를 남김).
    if predictable:
        payload = [_to_payload(c, graph["scope"]) for c in predictable]
        django_client.put_test_cases(graph_id, payload)
        report = django_client.simulate_graph(graph_id, narrate=False)
        rows_by_id = {row["id"]: row for row in report.get("testResults", [])}
        for cand in predictable:
            row = rows_by_id.get(cand["id"])
            ok = bool(row) and cand["node_key"] in (row.get("path") or []) and row.get("decision") == cand["decision"]
            if ok:
                verified.append(cand)
                continue
            actual_decision = row.get("decision") if row else None
            actual_path = row.get("path") if row else None
            unresolved.append({**cand, "actualDecision": actual_decision, "actualPath": actual_path})
            if row and cand["node_key"] not in (actual_path or []):
                problem = (
                    f"이 노드({cand['node_key']})에 걸릴 값으로 만들었지만, 실제로는 우선순위가 "
                    f"더 높은 노드가 먼저 가로채 경로가 `{' → '.join(actual_path or [])}`(으)로 끝났습니다."
                )
            elif row:
                problem = (
                    f"이 노드는 거쳤지만({cand['node_key']}) 기대한 판정({cand['decision']})이 아니라 "
                    f"`{actual_decision}`(으)로 나왔습니다 — 노드의 decision 설정을 확인하세요."
                )
            else:
                problem = "시뮬레이션 응답에서 이 케이스 결과를 찾지 못했습니다."
            generation_log.append({
                "nodeKey": cand["node_key"], "kind": cand["kind"], "outcome": "제외됨",
                "problem": problem,
            })

    # discovery — 예측 없이 한 번 돌려서 실제로 나온 판정을 그대로 정답으로 채택한다.
    # (분기 반대편·결측은 이 노드만 보고는 결과를 알 수 없어 "자체검증 실패"라는 개념 자체가
    # 성립하지 않는다 — 그래프가 실제로 하는 일을 있는 그대로 기록하는 것이 목적.)
    if discovery:
        trial_payload = [_to_payload(c, graph["scope"]) for c in verified] + [_to_payload(c, graph["scope"]) for c in discovery]
        django_client.put_test_cases(graph_id, trial_payload)
        trial_report = django_client.simulate_graph(graph_id, narrate=False)
        rows_by_id = {row["id"]: row for row in trial_report.get("testResults", [])}
        kind_ko = {"opposite": "분기 반대편", "opposite_boundary": "분기 반대편(경계값)", "missing_fact": "결측"}
        for cand in discovery:
            row = rows_by_id.get(cand["id"])
            if row and row.get("decision"):
                cand["decision"] = row["decision"]
                verified.append(cand)
                generation_log.append({
                    "nodeKey": cand["node_key"], "kind": cand["kind"], "outcome": "발견·반영됨",
                    "problem": f"{kind_ko.get(cand['kind'], cand['kind'])} 케이스 — 실제로 돌려보니 "
                               f"`{' → '.join(row.get('path') or [])}` 경로로 `{row['decision']}` 판정이 나와 그대로 기록했습니다.",
                })
            else:
                unresolved.append({
                    **cand,
                    "actualDecision": row.get("decision") if row else None,
                    "actualPath": row.get("path") if row else None,
                })
                generation_log.append({
                    "nodeKey": cand["node_key"], "kind": cand["kind"], "outcome": "제외됨",
                    "problem": "시뮬레이션에서 판정을 확정하지 못해 검증셋에 넣지 않았습니다.",
                })

    # 최종 저장 — 검증셋 전체를 이번에 검증된 것으로 교체한다(replace, 기존 것은 버림).
    final_payload = [_to_payload(c, graph["scope"]) for c in verified]
    django_client.put_test_cases(graph_id, final_payload)
    final_report = django_client.simulate_graph(graph_id)

    attempted = len(all_candidates)
    below_target = attempted < MIN_TOTAL_TARGET

    return {
        "status": "DONE",
        "attempted": attempted,
        "generated": len(verified),
        "unresolved": [
            {"nodeKey": u["node_key"], "kind": u["kind"], "reason": "자체검증 실패",
             "actualDecision": u.get("actualDecision"), "actualPath": u.get("actualPath")}
            for u in unresolved
        ],
        # §2-2 — 이번 생성에서 제외되거나(자체검증 실패) 발견으로 반영된 케이스의 사유.
        # 성공한 predictable 케이스(가장 흔한 경우)는 로그에 안 남는다 — "왜"를 설명할
        # 특이사항이 없기 때문. 화면은 이 배열이 비어 있으면 "특이사항 없음"으로 보여준다.
        "generationLog": generation_log,
        "skippedNodes": skipped,
        # 그래프 구조상 애초에 5건을 채울 소스가 없을 때(역산 가능한 노드가 적음)만 True —
        # 지어내는 대신 사실대로 보고한다.
        "belowTarget": below_target,
        "minTarget": MIN_TOTAL_TARGET,
        # 전체 상한(10건)에 걸려 노드별로 고르게 덜어낸 discovery 후보 수.
        "trimmedForCap": trimmed_count,
        "maxTarget": MAX_TOTAL_CANDIDATES,
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
        # discovery(opposite*/missing_fact) 후보는 발견 전엔 decision이 None — 채점 안 함으로 제출.
        "expected": cand["decision"] or "",
        "facts": cand["facts"],
    }

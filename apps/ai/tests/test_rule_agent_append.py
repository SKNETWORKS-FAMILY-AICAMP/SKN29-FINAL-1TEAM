"""기존 초안에 **이어 붙이기** 회귀.

예전엔 생성할 때마다 새 계열이 생겨 룰 콘솔이 초안으로 뒤덮였고, 모델은 기존 초안을 못 봐서
같은 조항으로 같은 룰을 계속 다시 만들었다.

여기서 고정하는 계약 넷:

① **종단 PASS를 또 만들지 않는다.** 기존 그래프에 이미 있다 — 둘이면 뒤엣것이 도달 불가다.
② **직전 노드의 `NO_MATCH`를 새 노드로 돌린다.** 안 고치면 새 노드는 달려만 있고 아무도
   도달하지 못한다. 엔진이 순회하지 않으므로 **에러 없이 조용히 무용해진다** — 이 파일이
   막으려는 것이 정확히 그것이다.
③ **키가 겹치면 새로 짓는다.** 같은 키로 POST하면 기존 노드를 덮어쓰거나 400이 난다.
④ **체인이 끊기지 않는다.** 마지막 새 노드가 기존 종단으로 되돌아간다.
"""
from __future__ import annotations

from app.agents.rule_agent_v0.agent import PASS_NODE_KEY, _existing_summary, _plan_append


def node(key, priority=0, **action):
    return {
        "node_key": key, "condition": True, "condition_text": "",
        "action": {"decision": "REVIEW", "severity": "MEDIUM", **action},
        "priority": priority,
    }


def graph(nodes, routings, entry=""):
    return {
        "id": "g1", "entryNodeKey": entry or (nodes[0]["nodeKey"] if nodes else ""),
        "nodes": nodes, "routings": routings,
    }


def existing_chain():
    """`R-1 →NO_MATCH→ R-2 →NO_MATCH→ _SCOPE_PASS` — 생성기가 만드는 표준 모양."""
    return graph(
        nodes=[
            {"nodeKey": "R-1", "priority": 0, "action": {"decision": "REJECT", "title": "금지업종"}},
            {"nodeKey": "R-2", "priority": 1, "action": {"decision": "RETURN", "title": "증빙 없음"}},
            {"nodeKey": PASS_NODE_KEY, "priority": 99, "action": {"decision": "PASS"}},
        ],
        routings=[
            {"fromNodeKey": "R-1", "onResult": "MATCH", "toNodeKey": ""},
            {"fromNodeKey": "R-1", "onResult": "NO_MATCH", "toNodeKey": "R-2"},
            {"fromNodeKey": "R-2", "onResult": "MATCH", "toNodeKey": ""},
            {"fromNodeKey": "R-2", "onResult": "NO_MATCH", "toNodeKey": PASS_NODE_KEY},
            {"fromNodeKey": PASS_NODE_KEY, "onResult": "MATCH", "toNodeKey": ""},
        ],
    )


# ── ①②④ 체인 잇기 ───────────────────────────────────────────────────────

def test_기존_꼬리_뒤에_붙고_종단으로_되돌아간다():
    nodes, routings, rewire = _plan_append(existing_chain(), [node("N-1"), node("N-2", 1)])

    assert [n["node_key"] for n in nodes] == ["N-1", "N-2"]
    #  ④ 마지막 새 노드는 기존 종단으로.
    assert routings["N-1"] == [
        {"onResult": "MATCH", "toNodeKey": ""},
        {"onResult": "NO_MATCH", "toNodeKey": "N-2"},
    ]
    assert routings["N-2"][-1] == {"onResult": "NO_MATCH", "toNodeKey": PASS_NODE_KEY}
    #  ② 직전 꼬리(R-2)가 새 노드를 가리키도록 고쳐진다.
    assert len(rewire) == 1
    assert rewire[0]["node_key"] == "R-2"
    assert rewire[0]["routings"][-1] == {"onResult": "NO_MATCH", "toNodeKey": "N-1"}


def test_실패_시_되돌릴_대상을_남긴다():
    """안 남기면 롤백이 「원래 어디를 가리켰는지」를 모르고 체인이 끊긴 채로 남는다."""
    _, _, rewire = _plan_append(existing_chain(), [node("N-1")])
    assert rewire[0]["restore_to"] == PASS_NODE_KEY


def test_종단_PASS를_또_만들지_않는다():
    """생성기가 붙인 PASS는 호출부가 빼고 넘긴다 — 계획에도 들어오면 안 된다."""
    nodes, routings, _ = _plan_append(existing_chain(), [node("N-1")])
    assert PASS_NODE_KEY not in [n["node_key"] for n in nodes]
    assert PASS_NODE_KEY not in routings


# ── ③ 키 충돌 ────────────────────────────────────────────────────────────

def test_키가_겹치면_새로_짓는다():
    nodes, routings, rewire = _plan_append(existing_chain(), [node("R-1"), node("R-2", 1)])
    keys = [n["node_key"] for n in nodes]
    assert keys == ["R-1-2", "R-2-2"]
    #  체인도 새 키로 이어져야 한다 — 옛 키로 이으면 자기 자신을 가리킨다.
    assert routings["R-1-2"][-1] == {"onResult": "NO_MATCH", "toNodeKey": "R-2-2"}
    assert rewire[0]["routings"][-1]["toNodeKey"] == "R-1-2"


def test_충돌이_연달아_나면_번호가_는다():
    base = existing_chain()
    base["nodes"].append({"nodeKey": "R-1-2", "priority": 2, "action": {}})
    nodes, _, _ = _plan_append(base, [node("R-1")])
    assert nodes[0]["node_key"] == "R-1-3"


# ── 경계 ─────────────────────────────────────────────────────────────────

def test_노드가_없는_빈_초안에도_붙는다():
    """사람이 만들어만 두고 비워 둔 초안 — 꼬리도 종단도 없다."""
    nodes, routings, rewire = _plan_append(graph([], []), [node("N-1")])
    assert [n["node_key"] for n in nodes] == ["N-1"]
    #  이을 곳이 없으면 라우팅을 걸지 않는다(그 노드의 액션이 곧 판정).
    assert routings["N-1"] == [{"onResult": "MATCH", "toNodeKey": ""}]
    assert rewire == []


def test_PASS가_없는_사람_그래프에도_붙는다():
    """룰 콘솔에서 손으로 만든 그래프엔 `_SCOPE_PASS`가 없을 수 있다."""
    hand = graph(
        nodes=[{"nodeKey": "H-1", "priority": 0, "action": {"decision": "REVIEW"}}],
        routings=[{"fromNodeKey": "H-1", "onResult": "MATCH", "toNodeKey": ""}],
    )
    nodes, routings, rewire = _plan_append(hand, [node("N-1")])
    assert rewire[0]["node_key"] == "H-1"
    assert rewire[0]["routings"][-1] == {"onResult": "NO_MATCH", "toNodeKey": "N-1"}
    #  종단이 없으니 마지막 노드는 되돌아갈 곳이 없다.
    assert routings["N-1"] == [{"onResult": "MATCH", "toNodeKey": ""}]


# ── 프롬프트에 실리는 요약 ───────────────────────────────────────────────

def test_요약은_종단_PASS를_빼고_보여준다():
    """`_SCOPE_PASS`는 시스템이 붙인 것이라 「이미 만든 룰」이 아니다."""
    text = _existing_summary(existing_chain())
    assert "R-1" in text and "금지업종" in text
    assert PASS_NODE_KEY not in text


def test_요약에_근거_조항이_실린다():
    """같은 조항으로 또 만들지 말라고 하려면 어떤 조항을 썼는지 보여야 한다."""
    g = existing_chain()
    g["nodes"][0]["action"]["source_clause"] = "법인카드_사용규정 제9조"
    assert "제9조" in _existing_summary(g)


def test_빈_그래프_요약은_빈_문자열이다():
    assert _existing_summary(graph([], [])) == ""

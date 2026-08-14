"""룰 그래프 실행 스냅샷 — 판정과 시뮬레이션이 **같은 모양**을 보게 하는 한 곳.

엔진(`engine.py`)은 ORM을 모른다(순수함수, FR-RA-08). 그래서 누군가는 `RuleGraph`를
평범한 dict로 펴 줘야 하는데, 그 변환이 두 벌 존재하면 "시뮬에선 통과인데 실판정은
다르다"가 조용히 생긴다 — 실제로 시드(`seed.py`)와 시뮬레이터가 각자 펴고 있었다.

스냅샷은 `rule_hits.eval_context`와 함께 **재현의 두 축**이다: 그때의 사실(EvalContext)과
그때의 규칙(snapshot)이 모두 있어야 판정을 다시 돌려볼 수 있다.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


def graph_snapshot(graph) -> dict[str, Any]:
    """`RuleGraph` → 엔진이 먹는 dict. 필드 집합이 곧 엔진과의 계약이다."""
    return {
        "nodes": list(graph.nodes.values("node_key", "condition", "action", "priority")),
        "routings": list(graph.routings.values("from_node_key", "on_result", "to_node_key", "priority")),
        "entry_node_key": graph.entry_node_key,
    }


def snapshot_hash(snapshot: dict[str, Any]) -> str:
    """내용 해시 — 저장된 시뮬 결과가 지금 그래프의 것인지(stale) 가리는 데 쓴다."""
    payload = json.dumps(snapshot, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

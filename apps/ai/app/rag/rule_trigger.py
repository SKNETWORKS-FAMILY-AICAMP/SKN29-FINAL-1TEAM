"""적재 완료 → 룰 생성 트리거 (§1.2-2, 구현 완료 2026-08-16).

제품 설계상 룰은 사전 탑재하지 않고 "고객이 자사 규정 문서를 업로드하면 Rule Agent가
생성"한다(CLAUDE.md §2). 적재가 끝나면 여기서 `rule_agent_v0.agent.generate()`를
실제로 호출한다.

## 왜 여기가 트리거 자리인가 (순서 의존)

적재가 **끝난 뒤에** 불려야 한다. 그 전에 부르면 `search_policy`가 0건이라 Rule Agent가
`NO_SOURCE`로 조용히 끝난다. 적재 파이프라인과 같은 백그라운드 태스크 안에서 순차로
부르면 이 순서가 공짜로 보장된다.

## 확정된 범위 (`llm_wiki/_context/agent-v1-upgrade-plan.md` §1.2-2)

  1. **scope 범위 = 업로드 시 고른 1개만.** 문서에서 탐지되는 전 scope를 만드는 건
     하지 않는다 — LLM 호출이 곱절로 늘고 아무도 요청하지 않은 DRAFT가 쌓인다.
     `scope`가 비어 있으면(업로드 시 비용분류를 안 골랐으면) 아예 생성을 건너뛴다.
  2. **재색인 때는 자동 생성하지 않는다.** 같은 문서를 다시 넣을 때마다 새 그래프
     계열이 생기면 룰 콘솔이 초안으로 뒤덮인다(기존 계열에 버전을 얹는 경로가 아직
     없음). `is_reindex`는 Django `policy_doc_views.py`가 `create`(최초 업로드)와
     `reembed`(재색인) 중 어느 경로로 왔는지 보고 정확히 넘겨준다.

실패(생성 자체의 실패든 예외든) 해도 적재를 실패로 만들지 않는다 — 문서는 이미 검색
가능한 상태이고, 룰 생성은 룰 콘솔에서 수동으로 다시 시도할 수 있다.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

SKIPPED_NO_SCOPE = "SKIPPED_NO_SCOPE"
SKIPPED_REINDEX = "SKIPPED_REINDEX"
SKIPPED_NO_AUTO_CLAUSE = "SKIPPED_NO_AUTO_CLAUSE"

#: 자동 생성 질의에 실을 조항 수 상한. 전부 이어 붙이면 질의가 문서 전체가 되어
#  검색이 아무것도 좁히지 못한다.
AUTO_QUERY_CLAUSES = 6


def trigger(
    *, doc_id: str, doc_name: str, scope: str, collection: str, is_reindex: bool = False,
    auto_clauses: list[dict[str, Any]] | None = None, triaged: bool = False,
) -> dict[str, Any]:
    """적재 완료 문서에 대해 룰 생성을 트리거한다.

    **분류(triage)가 돌았으면 그 결과를 따른다.** `AUTO`로 분류된 조항이 하나도 없으면
    자동 생성을 하지 않는다 — 조건이 명확한 조항이 없다는 뜻이고, 그런 상태에서 만든
    초안은 사람이 어차피 전부 고쳐야 한다(분류가 화면 장식이 아니라 실제로 무엇을 만들지
    정한다). 분류가 안 돌았으면(법령 등) 예전대로 scope 기본 질의로 만든다.
    """
    if not scope:
        return {
            "status": SKIPPED_NO_SCOPE,
            "detail": "이 문서에는 대상 비용분류가 지정되지 않아 자동 생성을 건너뜁니다.",
            "hint": "룰 콘솔 → 신규 그래프 생성 → '규정 문서에서 생성'으로 지금 바로 만들 수 있습니다.",
            "scope": "",
        }
    if is_reindex:
        return {
            "status": SKIPPED_REINDEX,
            "detail": f"재색인이라 자동 생성을 건너뜁니다 — `{scope}` 룰은 최초 적재 때만 자동 생성됩니다.",
            "hint": "규정 내용이 바뀌어 룰도 다시 반영해야 하면 룰 콘솔에서 수동으로 생성하세요.",
            "scope": scope,
            "docId": doc_id,
            "docName": doc_name,
            "collection": collection,
        }

    picked = list(auto_clauses or [])
    if triaged and not picked:
        return {
            "status": SKIPPED_NO_AUTO_CLAUSE,
            "detail": (
                "지금 바로 규칙으로 만들 만큼 조건이 명확한 조항을 찾지 못해 자동 생성을 "
                "건너뜁니다 — 조항 목록의 우선순위를 보고 직접 만들어 주세요."
            ),
            "scope": scope, "docId": doc_id, "docName": doc_name, "collection": collection,
        }

    from app.agents.rule_agent_v0 import agent as rule_agent
    from app.agents.rule_agent_v0.api import RuleGenerateRequest

    # 분류가 고른 조항이 있으면 그것으로 질의를 만든다 — scope 기본 질의보다 이 문서의
    # 실제 조항에 가깝고, "무엇을 근거로 만들어졌는지"가 트리거 결과에 남는다.
    query = None
    if picked:
        query = " ".join(
            " ".join(filter(None, [c.get("label", ""), c.get("title", ""), c.get("summary", "")]))
            for c in picked[:AUTO_QUERY_CLAUSES]
        ).strip()[:900]

    try:
        result = rule_agent.generate(
            RuleGenerateRequest(scope=scope, query=query, name=f"{doc_name} 자동생성 초안")
        )
    except Exception as exc:  # noqa: BLE001 — 트리거 실패가 적재 자체를 실패로 만들면 안 된다
        logger.warning("룰 자동생성 실패 doc=%s scope=%s: %s", doc_id, scope, exc)
        return {
            "status": "ERROR",
            "detail": f"자동 생성 중 오류: {type(exc).__name__}: {exc}",
            "scope": scope,
            "docId": doc_id,
            "docName": doc_name,
            "collection": collection,
        }

    # rule_agent.generate()의 상태값(NO_SOURCE/DRAFT_SAVED/NO_VALID_NODES_EXHAUSTED/
    # STRUCTURE_INVALID_EXHAUSTED)을 그대로 노출한다 — 여기서 별도로 뭉개지 않는다.
    # DRAFT_SAVED는 실패 케이스와 달리 "detail" 필드가 원래 없어서(성공 응답 계약,
    # agent.py 비침습 원칙) 화면에 보여줄 문구를 여기서 하나 만들어 채운다.
    detail = result.get("detail", "")
    if result.get("status") == "DRAFT_SAVED":
        detail = f"자동 생성 완료 — 그래프 #{result['graph']['graph_id']} (DRAFT, 시도 {result.get('attempts')}회)"

    return {
        "status": result.get("status"),
        "detail": detail,
        "generateResult": result,
        "scope": scope,
        "docId": doc_id,
        "docName": doc_name,
        "collection": collection,
        # 무엇을 근거로 자동 생성했는지 — 화면이 "이 조항들로 만들었다"를 보여준다.
        "autoClauses": [c.get("label", "") for c in picked[:AUTO_QUERY_CLAUSES]],
    }

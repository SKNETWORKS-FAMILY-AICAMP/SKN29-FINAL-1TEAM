"""적재 완료 → 룰 생성 트리거 — **연결 지점(seam)만 잡아둔 상태**.

제품 설계상 룰은 사전 탑재하지 않고 "고객이 자사 규정 문서를 업로드하면 Rule Agent가
생성"한다(CLAUDE.md §2). 그 자동 트리거가 붙을 자리가 여기다. 지금은 **호출만 되고 실제
생성은 하지 않는다** — 응답으로 "개발 중"을 돌려주고, 그 결과가 `PolicyDoc.rule_trigger`에
저장돼 화면에 그대로 뜬다.

## 왜 여기가 트리거 자리인가 (순서 의존)

적재가 **끝난 뒤에** 불려야 한다. 그 전에 부르면 `search_policy`가 0건이라 Rule Agent가
`NO_SOURCE`로 조용히 끝난다. 적재 파이프라인과 같은 백그라운드 태스크 안에서 순차로
부르면 이 순서가 공짜로 보장된다 — 이벤트로 각자 구독하면 순서 보장이 곧 내 문제가 된다.

## 켤 때 해야 할 일

`trigger()`의 본문을 아래로 바꾸면 된다. 호출 계약(입출력)은 이미 맞춰져 있다.

    from app.agents.rule_agent_v0 import agent as rule_agent
    from app.agents.rule_agent_v0.api import RuleGenerateRequest
    out = rule_agent.generate(RuleGenerateRequest(scope=scope, name=f"{doc_name} 자동생성 초안"))

켜기 전에 정해야 할 것 두 가지 — 둘 다 제품 판단이라 코드로 정하지 않았다:
  1. **범위**: 업로드 시 고른 scope 1개만 생성할지, 문서에서 탐지된 전 scope를 만들지.
     전 scope는 LLM 호출이 곱절로 늘고 아무도 요청하지 않은 DRAFT가 쌓인다.
  2. **재색인 때도 돌릴지**: 같은 문서를 다시 넣을 때마다 새 그래프 계열이 생기면
     룰 콘솔이 초안으로 뒤덮인다. 기존 계열에 버전을 얹는 경로가 먼저 필요하다.
"""
from __future__ import annotations

from typing import Any

NOT_IMPLEMENTED = "NOT_IMPLEMENTED"


def trigger(*, doc_id: str, doc_name: str, scope: str, collection: str) -> dict[str, Any]:
    """적재 완료 문서에 대해 룰 생성을 트리거한다. **현재는 개발 중 안내만 돌려준다.**

    실패해도 적재를 실패로 만들지 않는다 — 문서는 이미 검색 가능한 상태이고, 룰 생성은
    룰 콘솔에서 수동으로 다시 시도할 수 있다.
    """
    if not scope:
        return {
            "status": NOT_IMPLEMENTED,
            "detail": "룰 자동 생성은 개발 중입니다. (이 문서에는 대상 비용분류가 지정되지 않았습니다)",
            "hint": "룰 콘솔 → 신규 그래프 생성 → '규정 문서에서 생성'으로 지금 바로 만들 수 있습니다.",
            "scope": "",
        }
    return {
        "status": NOT_IMPLEMENTED,
        "detail": f"룰 자동 생성은 개발 중입니다 — 적재는 끝났고 `{scope}` 룰 생성만 남았습니다.",
        "hint": "룰 콘솔 → 신규 그래프 생성 → '규정 문서에서 생성'으로 지금 바로 만들 수 있습니다.",
        "scope": scope,
        "docId": doc_id,
        "docName": doc_name,
        "collection": collection,
    }

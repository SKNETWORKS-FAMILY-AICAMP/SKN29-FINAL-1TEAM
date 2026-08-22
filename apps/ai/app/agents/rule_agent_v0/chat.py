# apps/ai/app/agents/rule_agent_v0/chat.py
"""Rule Agent — 대화형 자연어 수정 (§1.2-5, `agent-v1-upgrade-plan.md`).

룰 콘솔에서 사용자가 자연어로 지시("이 노드 지워줘", "3만원 이상으로 바꿔줘", "왜 이렇게
됐어?")하면, MCP 툴콜링 루프(§1.2-1과 동일 패턴)로 의도를 해석해 **기존 그래프 CRUD
API**(`update_node`/`create_node`/`delete_node`)를 직접 호출한다. 새 저장 경로를 만들지
않는다(§3 비침습 원칙) — 사람이 룰 콘솔에서 직접 고치는 것과 최종적으로 같은 API를 탄다.

`RuleAuthoringMessage`(대화 로그)는 이전부터 존재했지만 쓰는 쪽이 없었다 — 이 모듈이
`django_client.post_messages()`로 사용자 발화와 AI 응답을 남기는 최초의 실제 쓰기 경로다.

v1 스코프 결정(구현 시점, 2026-08-16):
  - DRAFT 그래프만 대상으로 한다 — Django의 `update_node`/`create_node`/`delete_node`
    자체가 이미 DRAFT 아니면 400을 낸다(별도 가드 불필요, 자연스럽게 막힘).
  - "노드 재생성"은 별도 전용 툴을 만들지 않는다 — LLM이 `search_policy`로 근거를
    다시 찾아본 뒤 `update_node`를 호출하는 것으로 충분히 커버된다.
  - 편집 직후 자동으로 시뮬레이션을 돌리지 않는다 — 사람이 콘솔에서 직접 고칠 때도
    검증은 별도 명시적 단계(①테스트검증)라 이 기본 동작과 맞춘다.

수정(2026-08-18) — 컨텍스트 버그: 화면이 지금 보고 있는 노드와 이전 대화 이력을 전혀
안 넘기고 있었다. 매 `converse()` 호출이 그래프 전체 덤프 + 이번 메시지만 갖고 완전히
새로 시작하는 무상태 호출이라, "금액 30만원으로 바꿔줘" 같은 모호한 지시를 받으면 LLM이
그래프를 훑어서 "그럴듯한" 노드를 추측했다 — 실측: 조건에 금액이 들어간 노드가 여럿이면
의도 안 한 노드까지 같이 고치는 사고가 실제로 남(엔드투엔드 검증 중 재현). 수정:
`converse(graph_id, message, node_key=None)`로 화면에서 선택 중인 노드를 받아 프롬프트에
"지금 보고 있는 노드"로 명시하고, `django_client.get_messages()`로 최근 대화 이력을
실제 메시지 히스토리(`role: user/assistant`)로 재구성해 넘긴다 — 이전엔 화면에는
이력이 보여도 LLM은 그걸 전혀 몰랐다.

수정(2026-08-18) — 정성적 판단을 갖다 붙이는 문제: "목적이 부실하게 작성된 것도 걸러줘"
처럼 EvalContext의 어떤 var로도 참/거짓을 가릴 수 없는 주관적 요청을 받으면, 처음엔
의미가 비슷해 보이는 엉뚱한 var(`evidence.has_supporting_evidence` — 증빙 첨부 여부,
"목적 문구 품질"과 무관. 이 경로는 v6에서 종류별 불린으로 갈라지며 없어졌다)를 갖다 붙이거나, 같은 var를 논리적으로 동어반복인 조건으로
덧붙이고 "이제 이것도 걸러진다"고 답하는 사고가 실측됐다(둘 다 사용자에게 거짓 결과를
알리는 것과 같다). `_SYSTEM_PROMPT` 규칙 8을 "표현할 var가 없으면 답만 하고 조건은
건드리지 마라"로 강하게 명시해 고침 — 온화한 지침(1차 시도)으로는 재현율이 안 잡혀서,
금지 행동을 구체적으로 나열하는 강한 지침(2차 시도)으로 바꿔서야 3/3 재현에서 막혔다.
"""
from __future__ import annotations

import json
from typing import Any

from app.context import Bundle, get_context

from .. import mcp_client
from . import django_client
from .agent import _CONDITION_NODE_SCHEMA, _build_condition, _openai, _validate_condition, decisions, severities
from .settings import settings

# 대화 1턴에 허용하는 최대 툴 호출 라운드. 조회 없이 바로 답하는 경우가 대부분이라
# 생성 루프(MAX_TOOL_TURNS=6)보다 여유를 더 준다 — 여러 노드를 한 번에 고치라는
# 지시("전부 3만원으로 바꿔줘")도 한 대화 턴 안에서 끝나야 하므로.
MAX_CHAT_TURNS = 10

# 프롬프트에 실어 보낼 최근 대화 이력 개수. 대화가 길어져도 프롬프트가 무한정 안
# 커지게 최근 것만 — 오래된 맥락은 어차피 그래프 전체 덤프(현재 상태)가 대신한다.
MAX_HISTORY_MESSAGES = 20

_SYSTEM_PROMPT = """당신은 법인카드 정산 룰 콘솔의 편집 보조입니다. 사용자가 자연어로
지시하는 대로 현재 룰 그래프를 수정하거나, 질문에 답하세요.

원칙:
1. 그래프를 바꾸는 지시면 `update_node`/`create_node`/`delete_node` 중 맞는 툴을
   호출하세요. 여러 노드를 고쳐야 하면 여러 번 호출해도 됩니다.
2. 규정 근거가 더 필요하면 `search_policy`로 찾아보세요.
3. 조건(condition)은 재귀 구조화 필드(comparison/group)로 채우세요 — JSON 문자열을
   직접 조립하지 마세요. var 경로·연산자·판정값·플래그는 [도메인 카탈로그]에 있는 것만
   쓰세요(카탈로그는 이 시스템의 실제 모델에서 생성된 것이라, 거기 없는 어휘는 없는 것입니다).
   한도·기준액은 숫자로 박지 말고 카탈로그 [규정 임계값]의 policy.* 변수를 쓰세요.
4. 그래프를 바꾸지 않는 질문(예: "왜 이렇게 판정돼?", "이 조건이 뭐야?")이면 그래프를
   건드리지 말고 바로 `answer`로 답하세요.
5. 작업이 끝나면(변경을 했든 안 했든) 반드시 `answer` 툴을 호출해 사용자에게 보여줄
   요약을 제출하세요 — 이 툴을 호출해야 대화 턴이 끝납니다.
6. 존재하지 않는 노드를 고치라고 하면 지어내지 말고 `answer`로 그 사실을 알리세요.
7. 사용자 지시가 어느 노드를 말하는지 불명확하면([사용자가 지금 보고 있는 노드]가
   주어졌다면) 그 노드를 우선 적용하세요. 노드 이름이 명시되지 않았는데 여러 노드가
   똑같이 그럴듯해 보이면, 지어맞추지 말고 `answer`로 "어느 노드를 말씀하시는 건가요?"
   라고 되물으세요 — 애매할 때 여러 노드를 동시에 고치지 마세요.
8. **조건을 고치기 전에 먼저 스스로에게 물으세요: "[도메인 카탈로그]에 이 요청의 뜻을
   정확히 담은 var가 있는가?"** 없으면(예: "목적이 부실하게 작성됐는지", "설명이
   성의없는지" — 사람이 읽고 판단해야 하는 정성적 평가) 그 자리에서 멈추세요.
   금지된 행동: (a) 의미가 비슷해 보이는 다른 var를 대신 갖다 붙이는 것
   (b) 같은 var를 형태만 바꿔 반복해서(`A==true` OR `NOT(A==false)`처럼 논리적으로
   똑같은 식을 덧붙이고) "이제 이것도 걸러진다"고 주장하는 것. 이 두 가지는 실제로는
   아무것도 안 바꾸면서 바꿨다고 사용자를 속이는 것과 같습니다. 이런 요청은
   `update_node`/`create_node`를 아예 호출하지 말고, `answer`로만 "이건 참/거짓
   사실이 아니라 사람의 판단이 필요한 부분이라 룰 조건으로 표현할 수 없습니다"라고
   답하세요.
9-A. [최근 시뮬레이션 결과]가 주어졌다면 참고하세요 — "왜 위험해?", "이 노드 좀 이상한데"
   처럼 애매한 질문을 받으면 사용자에게 되묻기 전에 먼저 이 결과(권장 처리 사유·위험
   변경건 예시)를 확인하고, 관련이 있으면 답변에 근거로 인용하세요. 다만 이 결과는
   직전 실행 시점 스냅샷일 뿐입니다 — 그래프를 수정한 뒤에는 다시 시뮬레이션해야 최신
   상태를 반영한다는 것을 사용자에게 알려주세요.
9. 숫자(임계값·인원수·금액 등)를 바꾸라는 지시를 받으면, 그 값이 법인카드 정산
   업무의 상식적인 범위를 크게 벗어나 보이는지(예: 회식 참석 인원 제한을 수십~수백
   명 단위로, 결제 금액 한도를 비현실적으로 크거나 작게) 스스로 판단하세요. 벗어나
   보이면 **그 자리에서 바로 적용하지 마세요** — `update_node`/`create_node`를
   호출하지 말고, `answer`로만 "OOO은(는) 통상적인 범위를 크게 벗어난 값으로
   보입니다 — 의도하신 게 맞나요? 확인해주시면 반영하겠습니다"처럼 되묻고 이번
   턴은 끝내세요. 이전 대화(이력)에서 사용자가 이미 그 값을 명확히 확인해준
   경우에만 적용하세요. 이 판단은 이 그래프의 다른 노드들이 쓰는 값의 규모와
   비교해서 하세요 — 확신이 없을 땐 되묻는 쪽을 택하세요."""


def _format_graph(graph: dict[str, Any]) -> str:
    lines = [f"scope={graph.get('scope')} status={graph.get('status')} entry={graph.get('entryNodeKey')}"]
    for n in graph.get("nodes", []):
        action = n.get("action") or {}
        lines.append(
            f"- node_key={n['nodeKey']!r} title={action.get('title', '')!r} "
            f"decision={action.get('decision', '')} severity={action.get('severity', '')}\n"
            f"  condition_text: {n.get('conditionText', '')}\n"
            f"  condition(dsl): {json.dumps(n.get('condition'), ensure_ascii=False)}"
        )
    for r in graph.get("routings", []):
        lines.append(f"  routing: {r['fromNodeKey']} --{r['onResult']}--> {r['toNodeKey'] or '(단말)'}")
    return "\n".join(lines)


def _format_simulation(report: dict[str, Any] | None) -> str:
    """최근 시뮬레이션 결과를 대화 컨텍스트용으로 요약 — "이 노드가 위험건을 만들고
    있다"를 사용자가 매번 설명하지 않아도 Agent가 알게 한다(§4, 2026-08-19).

    통계 전부를 덤프하지 않는다 — 프롬프트가 무거워지고, 대화형 수정에 실제로 쓸모있는
    건 "지금 뭐가 문제인가"뿐이다: 등급·원인, 그리고 위험 변경건 상위 몇 개(어느 노드가
    근거인지 포함)만 추린다."""
    if not report:
        return "(이 그래프는 아직 시뮬레이션을 실행한 적이 없습니다 — 실행 결과 컨텍스트 없음)"
    grades = report.get("grades") or {}
    action = grades.get("action") or {}
    stats = report.get("stats") or {}
    lines = [
        f"실행 #{report.get('runId')} ({report.get('ranAt')}"
        f"{', 그래프 변경 이후 낡은 결과' if report.get('stale') else ''})",
        f"권장 처리: {action.get('label')} — {action.get('note')}",
        f"테스트 {stats.get('testPassed')}/{stats.get('testGraded')} 통과, "
        f"위험 변경 {stats.get('riskChangedCount')}건(완전 반전 {stats.get('reversalChangedCount', 0)}건 포함), "
        f"자동처리율 {stats.get('autoRate', 0) * 100:.1f}%",
    ]
    risky = [row for row in report.get("historyResults", []) if row.get("changed") and row.get("risk")][:3]
    if risky:
        lines.append("위험 변경건 예시(최대 3건):")
        for row in risky:
            lines.append(f"  - {row.get('label') or row.get('merchant')}: {row.get('aiComment', '')}")
    return "\n".join(lines)


def _build_user_prompt(
    graph: dict[str, Any], ctx: Bundle, message: str,
    node_key: str | None = None, simulation: dict[str, Any] | None = None,
) -> str:
    focus_block = ""
    if node_key:
        node = next((n for n in graph.get("nodes", []) if n["nodeKey"] == node_key), None)
        title = (node.get("action") or {}).get("title", node_key) if node else node_key
        focus_block = f"\n\n[사용자가 지금 화면에서 보고 있는 노드]\nnode_key={node_key!r} ({title})"
    return (
        f"[현재 그래프 상태]\n{_format_graph(graph)}\n\n"
        f"[도메인 카탈로그 — 이 시스템의 실제 어휘]\n{ctx.prompt()}"
        f"{focus_block}\n\n"
        f"[최근 시뮬레이션 결과]\n{_format_simulation(simulation)}\n\n"
        f"[사용자 지시]\n{message}"
    )


_SEARCH_POLICY_TOOL = {
    "type": "function",
    "function": {
        "name": "search_policy",
        "description": "사내 규정 조항을 RAG로 검색한다(MCP `search_policy` 경유). 수정 근거가 더 필요할 때.",
        "parameters": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "query": {"type": "string"},
                "top_k": {"type": "integer", "minimum": 1, "maximum": 20},
                "include_law": {"type": "boolean"},
            },
            "required": ["query", "top_k", "include_law"],
        },
    },
}

def _update_node_tool() -> dict[str, Any]:
    """decision/severity enum이 Django `engine.py` 카탈로그를 따른다(§8 후속,
    2026-08-19) — 이전엔 이 파일이 `["PASS","REJECT","RETURN","REVIEW"]`를 별도로
    하드코딩했다(`agent.py`가 쓰던 목록과도, 실제 엔진 소스와도 독립적으로 존재하던
    3번째 사본). 호출 시점에 조립해야 캐시된 최신 카탈로그를 반영한다."""
    return {
        "type": "function",
        "function": {
            "name": "update_node",
            "description": "기존 노드의 조건/액션을 수정한다.",
            "parameters": {
                "type": "object", "additionalProperties": False,
                "$defs": {"condition_node": _CONDITION_NODE_SCHEMA},
                "properties": {
                    "node_key": {"type": "string"},
                    "condition": {"$ref": "#/$defs/condition_node"},
                    "when": {"type": "string", "description": "언제 걸리나요? (사람이 읽는 설명)"},
                    "then": {"type": "string", "description": "걸리면 어떻게 되나요? (사람이 읽는 설명)"},
                    "decision": {"type": "string", "enum": decisions()},
                    "severity": {"type": "string", "enum": severities()},
                    "title": {"type": "string"},
                },
                "required": ["node_key"],
            },
        },
    }


def _create_node_tool() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "create_node",
            "description": "새 노드를 추가한다. node_key는 영문/숫자/`_`/`-`로 새로 짓는다.",
            "parameters": {
                "type": "object", "additionalProperties": False,
                "$defs": {"condition_node": _CONDITION_NODE_SCHEMA},
                "properties": {
                    "node_key": {"type": "string"},
                    "condition": {"$ref": "#/$defs/condition_node"},
                    "when": {"type": "string"},
                    "then": {"type": "string"},
                    "decision": {"type": "string", "enum": decisions()},
                    "severity": {"type": "string", "enum": severities()},
                    "title": {"type": "string"},
                },
                "required": ["node_key", "condition", "when", "then", "decision", "severity", "title"],
            },
        },
    }

_DELETE_NODE_TOOL = {
    "type": "function",
    "function": {
        "name": "delete_node",
        "description": "노드를 삭제한다.",
        "parameters": {
            "type": "object", "additionalProperties": False,
            "properties": {"node_key": {"type": "string"}},
            "required": ["node_key"],
        },
    },
}

_ANSWER_TOOL = {
    "type": "function",
    "function": {
        "name": "answer",
        "description": "대화 턴을 마친다. 무엇을 했는지/왜 못 했는지 사용자에게 보여줄 요약.",
        "parameters": {
            "type": "object", "additionalProperties": False,
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
}

def _all_tools() -> list[dict[str, Any]]:
    return [_SEARCH_POLICY_TOOL, _update_node_tool(), _create_node_tool(), _DELETE_NODE_TOOL, _ANSWER_TOOL]


def _condition_and_text(
    args: dict[str, Any], schema_paths: set[str], allowed_ops: set[str] | None = None,
) -> tuple[Any, str, list[str]]:
    """LLM 인자의 condition/when/then → (DSL, condition_text, 검증 문제). 생성 파이프라인의
    `_sanitize_nodes`와 같은 방어 — 존재하지 않는 EvalContext 경로 등을 여기서도 거른다."""
    problems: list[str] = []
    cond = None
    if "condition" in args and args["condition"] is not None:
        try:
            cond = _build_condition(args["condition"])
            problems.extend(_validate_condition(cond, schema_paths, allowed_ops or set()))
        except (KeyError, TypeError, ValueError) as exc:
            problems.append(f"condition 조립 실패: {exc}")
    text = ""
    if args.get("when") or args.get("then"):
        text = f"언제 걸리나요? {args.get('when', '')}\n걸리면 어떻게 되나요? {args.get('then', '')}"
    return cond, text, problems


def _load_history(graph_id: str) -> list[dict[str, str]]:
    """최근 대화 이력을 실제 LLM 메시지로 재구성. 화면엔 늘 보였지만 LLM은 이걸 몰랐다."""
    try:
        rows = django_client.get_messages(graph_id)
    except Exception:  # noqa: BLE001 — 이력 조회 실패가 대화 자체를 막으면 안 된다
        return []
    out: list[dict[str, str]] = []
    for row in rows[-MAX_HISTORY_MESSAGES:]:
        text = (row.get("text") or "").strip()
        if not text:
            continue
        out.append({"role": "assistant" if row.get("role") == "ai" else "user", "content": text})
    return out


def converse(graph_id: str, message: str, node_key: str | None = None) -> dict[str, Any]:
    """대화 1턴 실행. 그래프를 실제로 고치고(툴 호출 즉시 반영), 대화 로그를 남긴다.

    `node_key`: 화면에서 지금 선택 중인 노드 — 모호한 지시("금액 30만원으로 바꿔줘")를
    엉뚱한 노드에 적용하지 않도록 프롬프트에 힌트로 얹는다(2026-08-18 수정, 위 모듈
    docstring 참조).
    """
    graph = django_client.get_graph(graph_id)
    # 생성과 **같은 카탈로그**를 쓴다 — 대화형 수정이 다른 어휘를 알고 있으면 방금 만든
    # 그래프를 고치면서 없는 경로·플래그를 끌어온다.
    ctx = get_context("rule_chat")
    schema_paths = ctx.paths
    try:
        simulation = django_client.get_latest_simulation(graph_id)
    except Exception:  # noqa: BLE001 — 시뮬레이션 컨텍스트 조회 실패가 대화 자체를 막으면 안 된다
        simulation = None

    messages: list[dict[str, Any]] = [{"role": "system", "content": _SYSTEM_PROMPT}]
    messages.extend(_load_history(graph_id))
    messages.append({"role": "user", "content": _build_user_prompt(graph, ctx, message, node_key, simulation)})
    applied: list[dict[str, Any]] = []
    final_answer = ""
    graph_gone = False  # dedup 원복으로 DRAFT가 삭제되면 True — 이후 그래프 접근 금지

    for _ in range(MAX_CHAT_TURNS):
        resp = _openai().chat.completions.create(
            # gpt-5-mini류는 커스텀 temperature 미지원(기본 1만 허용) — 2026-08-18 실측.
            model=settings.model_heavy, reasoning_effort=settings.model_heavy_reasoning_effort, timeout=60,
            tools=_all_tools(), tool_choice="auto", messages=messages,
        )
        msg = resp.choices[0].message
        tool_calls = msg.tool_calls or []

        if not tool_calls:
            messages.append({"role": "assistant", "content": msg.content or ""})
            messages.append({"role": "user", "content": "반드시 `answer` 툴을 호출해 마무리하세요."})
            continue

        messages.append({
            "role": "assistant", "content": msg.content,
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in tool_calls
            ],
        })

        done = False
        for tc in tool_calls:
            args = json.loads(tc.function.arguments or "{}")
            name = tc.function.name

            if name == "answer":
                final_answer = args.get("text", "")
                done = True
                tool_content = "ok"

            elif graph_gone:
                # dedup 원복으로 그래프가 이미 삭제됨 — 같은 배치의 나머지 편집/검색을
                # 404로 보내지 말고 명확한 사유로 막는다(answer만 허용).
                tool_content = "그래프가 이미 삭제(활성 버전으로 원복)됐습니다 — 추가 작업 없이 answer로 마무리하세요."

            elif name == "search_policy":
                result = mcp_client.call_tool(
                    "search_policy", query=args.get("query", ""),
                    top_k=args.get("top_k") or 6, include_law=bool(args.get("include_law")),
                )
                chunks = result.get("chunks", [])
                tool_content = (
                    "\n\n".join(f"[{c['citation']}] {c['text']}" for c in chunks)
                    if chunks else "검색 결과 0건"
                )

            elif name == "update_node":
                node_key = args.get("node_key", "")
                cond, text, problems = _condition_and_text(args, set(schema_paths), ctx.operators)
                existing = next((n for n in graph.get("nodes", []) if n["nodeKey"] == node_key), None)
                if problems:
                    tool_content = f"반영 실패 — {'; '.join(problems)}"
                elif existing is None:
                    tool_content = f"반영 실패 — 존재하지 않는 노드: {node_key}"
                else:
                    # Django update_node는 action을 통째로 교체한다(부분 병합 아님) —
                    # LLM이 severity만 바꾸라고 하면 나머지 필드(title/decision 등)가
                    # 사라지는 사고가 생긴다(실측 2026-08-16). 기존 action에 변경분만
                    # 덮어써서 보낸다.
                    action = dict(existing.get("action") or {})
                    if args.get("decision"):
                        action["decision"] = args["decision"]
                    if args.get("severity"):
                        action["severity"] = args["severity"]
                    if args.get("title"):
                        action["title"] = args["title"]
                    try:
                        saved = django_client.update_node(
                            graph_id, node_key,
                            condition=cond, condition_text=text or None,
                            action=action,
                        )
                        if saved.get("revertedToGraphId"):
                            # Django dedup: 이 편집으로 DRAFT 내용이 같은 계열의 ACTIVE와
                            # 동일해지면 DRAFT 자체가 삭제되고 ACTIVE로 원복된다(콘솔의
                            # `update_node` 액션 동작). 그래프가 사라졌으므로 더 편집하면
                            # 전부 404다 — 여기서 대화를 종료시킨다.
                            graph_gone = True
                            applied.append({"action": "reverted_to_active",
                                            "node_key": node_key,
                                            "active_graph_id": saved["revertedToGraphId"]})
                            tool_content = (
                                "이 수정으로 초안이 활성(ACTIVE) 버전과 완전히 같아져, "
                                "초안이 삭제되고 활성 버전으로 원복됐습니다. 그래프가 더 이상 "
                                "존재하지 않으니 추가 편집 없이 이 사실을 answer로 알리세요."
                            )
                        else:
                            # 같은 턴 안에서 같은 노드를 또 건드릴 수도 있으니 로컬 스냅샷도 갱신.
                            existing["action"] = action
                            if cond is not None:
                                existing["condition"] = cond
                            if text:
                                existing["conditionText"] = text
                            applied.append({"action": "update_node", "node_key": node_key})
                            tool_content = f"{node_key} 수정 완료"
                    except Exception as exc:  # noqa: BLE001
                        tool_content = f"반영 실패 — {type(exc).__name__}: {exc}"

            elif name == "create_node":
                node_key = args.get("node_key", "")
                cond, text, problems = _condition_and_text(args, set(schema_paths), ctx.operators)
                if problems:
                    tool_content = f"생성 실패 — {'; '.join(problems)}"
                elif any(n["nodeKey"] == node_key for n in graph.get("nodes", [])):
                    # Django create_node는 get_or_create라 기존 키로 부르면 200이 나고,
                    # 이어지는 update가 **기존 노드를 통째로 덮어쓴다** — 새 노드를 만들
                    # 의도였는데 조용히 다른 노드가 파괴되는 사고. 여기서 막는다.
                    tool_content = (
                        f"생성 실패 — node_key {node_key!r}는 이미 존재합니다. "
                        "기존 노드를 고치려면 update_node를, 새 노드면 다른 키를 쓰세요."
                    )
                else:
                    new_action = {
                        "decision": args.get("decision", "REVIEW"),
                        "severity": args.get("severity", "MEDIUM"),
                        "title": args.get("title", ""),
                        "origin": "rule-agent-chat", "workflow_status": "DRAFT",
                    }
                    try:
                        django_client.create_node(graph_id, node_key)
                        try:
                            django_client.update_node(
                                graph_id, node_key, condition=cond, condition_text=text,
                                action=new_action,
                            )
                        except Exception:
                            # 빈 노드만 만들어지고 내용 채우기가 실패하면 "(제목 미설정)"
                            # 반쪽 노드가 그래프에 남는다 — 지우고 실패로 보고한다.
                            try:
                                django_client.delete_node(graph_id, node_key)
                            except Exception:  # noqa: BLE001 — 정리 실패는 원인 예외를 가리지 않게 무시
                                pass
                            raise
                        # 같은 턴에서 방금 만든 노드를 바로 또 고칠 수도 있으니 로컬 반영.
                        graph.setdefault("nodes", []).append({
                            "nodeKey": node_key, "condition": cond,
                            "conditionText": text, "action": new_action,
                        })
                        applied.append({"action": "create_node", "node_key": node_key})
                        tool_content = f"{node_key} 생성 완료"
                    except Exception as exc:  # noqa: BLE001
                        tool_content = f"생성 실패 — {type(exc).__name__}: {exc}"

            elif name == "delete_node":
                node_key = args.get("node_key", "")
                try:
                    django_client.delete_node(graph_id, node_key)
                    graph["nodes"] = [n for n in graph.get("nodes", []) if n["nodeKey"] != node_key]
                    applied.append({"action": "delete_node", "node_key": node_key})
                    tool_content = f"{node_key} 삭제 완료"
                except Exception as exc:  # noqa: BLE001
                    tool_content = f"삭제 실패 — {type(exc).__name__}: {exc}"

            else:
                tool_content = f"알 수 없는 툴: {name}"

            messages.append({"role": "tool", "tool_call_id": tc.id, "content": tool_content})

        if done:
            break
    else:
        final_answer = final_answer or f"{MAX_CHAT_TURNS}턴 안에 마무리하지 못했습니다 — 다시 시도해주세요."

    # 대화 로그 적재 — 기존 RuleAuthoringMessage 저장소(신규 저장 경로 아님).
    # dedup 원복으로 그래프가 삭제됐으면 로그를 남길 곳도 사라진 것 — 404가 나고 무시된다.
    applied_note = ", ".join(f"{a['action']}:{a['node_key']}" for a in applied)[:200]
    try:
        django_client.post_messages(graph_id, [
            {"role": "user", "text": message},
            {"role": "ai", "text": final_answer, "appliedNote": applied_note},
        ])
    except Exception:  # noqa: BLE001 — 로그 실패가 대화 응답 자체를 막으면 안 된다
        pass

    if graph_gone:
        final_graph = None
    elif applied:
        final_graph = django_client.get_graph(graph_id)
    else:
        final_graph = graph
    return {
        "answer": final_answer,
        "applied_changes": applied,
        "graph": final_graph,
    }

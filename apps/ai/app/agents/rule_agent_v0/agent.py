# apps/ai/app/agents/rule_agent_v0/agent.py
"""Rule Agent — 생성(Generate) v0/v1.

기술명세서 §4.2(a) 생성 Flow 구현:
    search_policy(MCP 툴콜링) → LLM 노드 초안(submit_rule_nodes 툴 호출로 종료) →
    그래프 조립 → DRAFT 저장 → 구조검증 → (실패 시) 이전 실패 사유를 피드백으로
    재시도, 최대 MAX_GENERATE_ATTEMPTS회

MCP 툴콜링 전환(v1, `llm_wiki/_context/agent-v1-upgrade-plan.md` §1.2-1):
  - RAG 검색은 더 이상 파이썬이 미리 실행해 프롬프트에 박아넣지 않는다. LLM이
    `search_policy` MCP 툴을 직접 호출해 근거를 가져온다(부족하면 다른 질의로
    추가 호출 가능) — `mcp_client.call_tool()`이 `fastmcp.Client`로 `app.mcp.server`에
    in-process 접속한다(HTTP 왕복 없음, `/mcp` 마운트와는 별개 경로).
  - 최종 결과는 `response_format=json_schema` 단발 출력이 아니라 **`submit_rule_nodes`
    툴 호출**로 받는다 — 이 툴이 호출돼야 루프가 끝난다(최대 MAX_TOOL_TURNS 턴, 초과
    시 빈 결과로 안전 종료).
  - 단, "RAG 청크는 시도 전체(재시도 3회)에서 재사용"이라는 기존 결정(§1.2-4)은 유지한다
    — outer 재시도 루프가 넘겨주는 `initial_chunks`를 대화 맥락에 고정으로 심어두고,
    모델이 부족하다고 판단할 때만 **추가** 검색을 하게 한다. 매 outer 시도마다 처음부터
    다른 검색 결과로 시작하면 "피드백이 통했는지 vs 우연히 다른 근거가 걸렸는지"를
    구분할 수 없어져 재시도 루프의 신뢰성이 무너지기 때문.

검증→재생성 루프(v1, §1.2-4, MCP 전환과 별개로 유지):
  - sanitize 전멸과 저장 후 구조검증(`/simulate`) 실패를 하나의 시도 카운터로 묶는다.
  - 새 검증 엔드포인트는 만들지 않는다 — 기존 `POST /api/rules/{id}/simulate`를
    재사용(`django_client.simulate_graph`). 구조검증 실패 시 `discard_draft`로 그
    시도의 그래프를 지우고 재시도, 최종 실패해도 흔적을 안 남긴다(A안).
  - 종료 상태값은 기존(`NO_SOURCE`/`DRAFT_SAVED`)과 겹치지 않는 신규 이름을 쓴다:
    `NO_VALID_NODES_EXHAUSTED`(sanitize 전멸이 N회 반복)/
    `STRUCTURE_INVALID_EXHAUSTED`(구조검증 실패가 N회 반복).

기존 초안에 이어 붙이기(2026-08-25):
  - 생성 전에 그 scope의 **편집 중인 초안**을 찾아(`find_open_draft`) 있으면 거기에 노드를
    잇는다. 예전엔 호출마다 새 계열이 생겨 룰 콘솔이 초안으로 뒤덮였고, 사람이 어느 것을
    보고 있는지도 흐려졌다.
  - 모델에게 **기존 초안 목록을 보여준다**(`_existing_summary`). 안 보여주면 같은 조항으로
    같은 룰을 계속 다시 만든다 — 중복 노드가 쌓이던 원인이 이것이다.
  - 체인 잇기는 `_plan_append`가 결정론적으로 계획한다: 종단 PASS를 또 만들지 않고, 직전
    꼬리의 `NO_MATCH`를 새 노드로 돌리며(안 돌리면 새 노드는 **도달 불가**가 되어 조용히
    무용해진다), 키가 겹치면 새로 짓는다.
  - **구조검증 실패 시 초안을 지우지 않는다.** 사람이 편집하던 그래프이므로 우리가 만든
    노드만 걷어낸다(`_rollback_append`) — 자동 생성이 실패했다고 남의 작업을 지우지 않는다.

v0 단순화 결정(의도적, GAPS.md 참조):
  - LLM은 "노드"만 생성한다. 그래프 위상(라우팅)은 파이썬이 결정론적으로 조립한다
    — 시드 GLOBAL 그래프와 동일한 선형 체인(우선순위순 NO_MATCH→NO_MATCH→…→_PASS 종단).
    LLM에게 위상까지 맡기면 검증 실패 모드가 늘어난다. "Rule First, AI Assisted."
  - decision은 노드 생성 시점에 action.decision으로 직접 지정(기술명세서 §4.2 확정,
    θ_pass/θ_reject 방식은 deprecated).
  - 2-hop 확장·조건 간 배타그룹 메타는 v1.
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.context import Bundle, get_context

from .. import mcp_client
from . import django_client
from .settings import settings

_client = None


def _openai():
    """OpenAI 클라이언트는 **첫 호출 때** 만든다.

    import 시점에 만들면 `OPENAI_API_KEY`가 비어 있는 환경에서 라우터 import가 터져
    FastAPI 전체가 안 뜬다 — 룰 생성과 무관한 화면까지 같이 죽는다. 팀 정본
    (`rag/embedding/encoder.py`)이 지연 생성 + 명시적 에러 메시지를 쓰는 이유와 같다.
    """
    global _client
    if _client is None:
        from openai import OpenAI

        from app.config import settings as core_settings

        if not core_settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY 가 비어 있다 — 레포 루트 `.env`에 넣을 것")
        _client = OpenAI(api_key=core_settings.openai_api_key)
    return _client


# 도메인 카탈로그(DSL 문법·허용 경로·판정 선택지·플래그·별표 축)는 **전부 core가 만든다**
# (`domain/context`). 이 파일이 갖고 있던 사본 두 개 — decision/severity 하드코딩과
# `_ALLOWED_OPS` — 는 그래서 없어졌다. 사본이 문제인 이유는 값이 틀려서가 아니라,
# 틀려도 아무 신호가 없어서다(프롬프트가 `EvalContext v4`라고 말하는 동안 코드는 v5였다).
#
# 프롬프트에 실리는 목록과 아래 검증기(`_validate_condition`·`_sanitize_nodes`)가 쓰는
# 기준은 **같은 Bundle 객체**에서 나온다. 갈리면 "모델에게 말한 것"과 "우리가 강제하는 것"이
# 달라진다.
CATALOG_PROFILE = "rule_generate"


def catalog(profile: str = CATALOG_PROFILE) -> Bundle:
    """카탈로그 조회(TTL 캐시). 실패해도 stale Bundle을 돌려주고 멈추지 않는다."""
    return get_context(profile)


def severities() -> list[str]:
    return catalog().severities


def decisions() -> list[str]:
    return catalog().decisions


def severity_priority() -> dict[str, int]:
    return {s: i for i, s in enumerate(severities())}  # CRITICAL=0 … INFO=4

# 검증→재생성 루프 최대 시도 횟수(최초 1회 + 재시도 2회). agent-v1-upgrade-plan.md §1.2-4
# 결정 근거: LLM 자기수정은 2~3회 이후 수확체감이 커서 그 이상은 비용 대비 이득이 적다.
MAX_GENERATE_ATTEMPTS = 3

# MCP 툴콜링 루프(§1.2-1) 안전판 — 모델이 몇 턴 안에 submit_rule_nodes를 호출해야
# 하는지 상한. search_policy 추가 호출 2~3번 + 최종 제출 정도면 충분하다고 보고 여유
# 있게 잡음. 초과하면 빈 결과로 종료해 outer 재생성 루프(§1.2-4)가 이어받는다.
MAX_TOOL_TURNS = 6


# ---------------------------------------------------------------- LLM 호출

_SYSTEM_PROMPT = """당신은 법인카드 정산 규정을 실행 가능한 룰(rule)로 변환하는 보조입니다.
아래에 제공되는 "규정 조항 청크"만 근거로, 결정론적 룰 엔진이 평가할 룰 노드 후보를 생성하세요.

반드시 지켜야 할 규칙:
1. condition은 재귀 구조화 필드(comparison/group)로 채우세요. JSON 문자열을 직접
   조립하지 마세요 — 스키마가 이미 구조를 정의합니다.
   - "kind": "comparison"이면 left_path/op/negate/right_kind와, right_kind에
     맞는 right_* 필드 하나만 채우세요(나머지 right_*는 null).
     예: tx.amount > policy.preapproval_threshold
     → {"kind":"comparison","left_path":"tx.amount","op":">","negate":false,
        "right_kind":"var","right_var_path":"policy.preapproval_threshold",
        "right_number":null,"right_string":null,"right_bool":null,"right_string_list":null,
        "combinator":null,"children":null}
   - 여러 조건을 and/or로 묶으려면 "kind":"group"과 combinator/children을
     쓰세요. children은 comparison 또는 group을 재귀적으로 담을 수 있습니다.
   - in 연산자는 right_kind="string_list", right_string_list에 값 목록을 넣으세요.
     예: category.ai in [식대,기업업무추진비]
   - not이 필요하면 negate:true로 표시하세요(연산자를 감쌉니다).
   - **「값을 모른다」와 「값이 없다/아니다」는 다른 사실입니다.** 예를 들어 사전승인 여부는
     `false`(확인했고 안 받았다)와 「모름」(아무도 적지 않았다)이 다릅니다.
     · 「받지 않았다」 → op:"==", right_bool:false
     · 「적혀 있지 않다·확인할 수 없다」 → op:"is_null" (단항 — right_* 는 전부 null)
     · 「값이 있다」 → op:"is_null" + negate:true
     헷갈리면 `==`/`!=` 쪽을 쓰세요. 다른 모든 비교는 값을 모르면 **자동으로 걸리지 않고**
     시스템이 그 건을 「판단에 필요한 정보 없음」으로 사람에게 넘깁니다 — 모르는 경우를
     따로 처리하지 않아도 됩니다. `is_null`은 **모름 자체를 사유로 삼고 싶을 때만** 쓰세요.
   - 산술 연산 금지. 필요한 계산값은 이미 컨텍스트에 선계산되어 있다고 가정하세요.

2. var 경로(left_path/right_var_path)·연산자·판정값·플래그·임계값 변수는 모두 아래
   [도메인 카탈로그]에 있는 것만 사용하세요. 카탈로그는 이 시스템의 실제 모델에서 생성된
   것이라, 거기 없는 사실·어휘는 존재하지 않습니다. 필요한 것이 없으면 그 룰은 만들지 말고
   skipped에 사유를 남기세요.
3. 임계값 숫자는 조항에 명시된 경우에만 사용하되, 별표(한도표) 조회값이면 숫자 리터럴 대신
   policy.* 경로(right_kind="var")를 사용하세요 — 어떤 변수가 어느 별표에서 오는지, 지금
   적재돼 있는지는 카탈로그의 [규정 임계값] 섹션에 있습니다.
4. decision은 카탈로그 [판정·심각도 선택지]에서 고르세요.
   - 규정상 명백한 금지·위반: REJECT
   - 기재·증빙 보완이 필요한 경우: RETURN
   - 사람 검토가 필요한 경우: REVIEW
   (PASS 노드는 만들지 마세요 — 종단 PASS는 시스템이 자동 추가합니다.)
5. severity도 카탈로그 목록에서 고르세요.
5-A. flag는 "왜 걸렸는가"를 나타내는 사유 코드입니다. **카탈로그 [사유 플래그 어휘]에서 뜻이
   맞는 코드를 먼저 찾아 그대로 쓰세요.** 정말 맞는 것이 하나도 없을 때만 새 코드를 만들되
   같은 표기 규칙(영문 대문자·언더스코어)을 따르세요. 뜻이 어긋난 코드를 갖다 붙이면 검토
   화면이 엉뚱한 담당자에게 일을 보냅니다.
6. source_citation에는 제공된 청크의 citation 문자열을 그대로 복사하세요.
   「문서명」 제N조 형태 전체를 유지하고, 제공되지 않은 조항을 지어내지 마세요.
7. when/then은 비개발자(회계 담당자)용 쉬운 문장입니다. DSL 경로·영문 판정코드를 쓰지 마세요.
   when="언제 걸리나요?"에 대한 답, then="걸리면 어떻게 되나요?"에 대한 답.
8. 반드시 지정된 JSON 형식으로만 답하세요."""

_CONDITION_NODE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "kind": {"type": "string", "enum": ["comparison", "group"]},
        "left_path": {"type": ["string", "null"]},
        # `is_null`은 **단항**이다 — right_* 를 전부 null로 두고 left_path만 채운다.
        #  「모름」과 「없음」은 다른 사실이라 이 연산자 없이는 「값을 안 적었다」를 표현할 수 없다.
        "op": {"type": ["string", "null"],
               "enum": ["==", "!=", ">", ">=", "<", "<=", "in", "is_null", None]},
        "negate": {"type": "boolean"},
        "right_kind": {"type": ["string", "null"], "enum": ["var", "number", "string", "boolean", "string_list", None]},
        "right_var_path": {"type": ["string", "null"]},
        "right_number": {"type": ["number", "null"]},
        "right_string": {"type": ["string", "null"]},
        "right_bool": {"type": ["boolean", "null"]},
        "right_string_list": {"type": ["array", "null"], "items": {"type": "string"}},
        "combinator": {"type": ["string", "null"], "enum": ["and", "or", None]},
        "children": {
            "type": ["array", "null"],
            "items": {"$ref": "#/$defs/condition_node"},
        },
    },
    "required": ["kind", "left_path", "op", "negate", "right_kind",
                 "right_var_path", "right_number", "right_string",
                 "right_bool", "right_string_list", "combinator", "children"],
}

def _response_schema() -> dict[str, Any]:
    """호출 시점에 조립 — `severity` enum이 카탈로그(Django `engine.py` 소스)를 따라야
    해서 모듈 로드 시점 상수로 못 둔다. `decision`은 이 생성 흐름이 만드는 노드가 항상
    비-PASS 종단이라는 v0 설계(모듈 docstring 참조)에 따라 의도적으로 서브셋
    (REJECT/RETURN/REVIEW만, 전체 카탈로그의 PASS·PASS_THROUGH 제외)이다."""
    return {
        "name": "rule_nodes",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "$defs": {
                "condition_node": _CONDITION_NODE_SCHEMA,
            },
            "properties": {
                "nodes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "node_key": {"type": "string"},
                            "title": {"type": "string"},
                            "condition": {"$ref": "#/$defs/condition_node"},
                            "when": {"type": "string"},
                            "then": {"type": "string"},
                            "decision": {"type": "string", "enum": ["REJECT", "RETURN", "REVIEW"]},
                            "severity": {"type": "string", "enum": severities()},
                            "flag": {"type": "string"},
                            "source_citation": {"type": "string"},
                        },
                        "required": [
                            "node_key", "title", "condition", "when", "then",
                            "decision", "severity", "flag", "source_citation",
                        ],
                    },
                },
                "skipped": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "reason": {"type": "string"},
                            "source_citation": {"type": "string"},
                        },
                        "required": ["reason", "source_citation"],
                    },
                },
            },
            "required": ["nodes", "skipped"],
        },
    }


def _format_chunks(chunks: list[dict]) -> str:
    chunk_lines = []
    for i, c in enumerate(chunks, 1):
        block = f"[청크 {i}] citation: {c['citation']}\n{c['text']}"
        # 부모(조 전문)는 항 단위 조각이 놓친 맥락을 채운다 — 다만 인용은 잎의 citation을
        # 쓰게 해야 한다(부모를 인용하면 "제N조" 통째로가 근거로 찍혀 근거가 뭉툭해진다).
        if c.get("parent_text") and c["parent_text"] != c["text"]:
            block += f"\n  (같은 조 전문 — 맥락 참고용, 인용은 위 citation을 쓸 것)\n  {c['parent_text']}"
        chunk_lines.append(block)
    return "\n\n".join(chunk_lines) if chunk_lines else "(없음)"


def _build_user_prompt(
    scope: str, chunks: list[dict], ctx: Bundle, feedback: str | None = None,
    existing: dict | None = None,
) -> str:
    """카탈로그 블록은 core가 만든 것을 **그대로** 싣는다.

    여기서 요약하거나 손으로 다시 적으면 그 순간 사본이 된다 — 프롬프트가 스키마 버전을
    직접 적고 있던 시절(`EvalContext v4`, 코드는 이미 v5)이 그 결과였다.
    """
    #  편집 중인 초안이 있으면 **무엇이 이미 있는지** 알려준다. 안 알려주면 모델이 같은
    #  조항으로 같은 룰을 다시 만든다 — 생성할 때마다 중복 노드가 쌓이던 원인이다.
    existing_block = ""
    if existing:
        listing = _existing_summary(existing) or "(아직 노드가 없습니다)"
        existing_block = (
            f"[현재 편집 중인 초안 — 여기에 **이어 붙입니다**]\n{listing}\n"
            "위 목록과 **뜻이 겹치는 룰은 만들지 마세요.** 같은 조항을 근거로 이미 만들어진 "
            "것이 있으면 그 조항은 skipped에 「이미 초안에 있음」으로 남기고, 빠진 요건만 "
            "새로 만드세요.\n\n"
        )
    prompt = (
        f"대상 scope(비용 분류): {scope}\n\n"
        f"{existing_block}"
        f"[도메인 카탈로그 — 이 시스템의 실제 어휘]\n{ctx.prompt()}\n\n"
        f"[규정 조항 청크 — 1차 검색 결과]\n{_format_chunks(chunks)}\n\n"
        "위 청크만으로 부족하면 `search_policy` 툴을 다른 질의로 호출해 추가 근거를 "
        "확보하세요. 준비되면 `submit_rule_nodes` 툴을 호출해 최종 결과를 제출하세요 "
        "— 이 툴을 호출해야 생성이 끝납니다."
    )
    if feedback:
        prompt += f"\n\n[이전 시도 피드백 — 아래 문제를 반복하지 말 것]\n{feedback}"
    return prompt


_SEARCH_POLICY_TOOL = {
    "type": "function",
    "function": {
        "name": "search_policy",
        "description": (
            "사내 규정 조항을 RAG로 검색한다(MCP `search_policy` 경유). "
            "1차 검색 결과만으로 조건을 만들기 부족할 때, 다른 질의로 다시 불러 "
            "추가 근거를 확보하는 용도."
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "query": {"type": "string", "description": "검색 질의"},
                "top_k": {"type": "integer", "minimum": 1, "maximum": 20},
                "include_law": {"type": "boolean", "description": "세법(tax_refs)도 함께 검색할지"},
            },
            "required": ["query", "top_k", "include_law"],
        },
    },
}

def _submit_nodes_tool() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "submit_rule_nodes",
            "description": "최종 룰 노드 목록을 제출한다. 이 툴을 호출해야 생성이 끝난다.",
            "strict": True,
            "parameters": _response_schema()["schema"],
        },
    }


def _run_generation_loop(
    scope: str, initial_chunks: list[dict], ctx: Bundle, feedback: str | None = None,
    existing: dict | None = None,
) -> dict:
    """MCP 툴콜링 멀티턴 루프. `submit_rule_nodes` 호출 시 그 인자를 최종 결과로 반환.

    `initial_chunks`는 outer 재시도 루프(§1.2-4)가 재사용하는 고정 근거 — 대화 맥락에
    박아두고, 모델이 부족하다고 판단할 때만 `search_policy`로 추가 검색하게 한다.
    """
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user",
         "content": _build_user_prompt(scope, initial_chunks, ctx, feedback, existing)},
    ]

    for _ in range(MAX_TOOL_TURNS):
        resp = _openai().chat.completions.create(
            # gpt-5-mini류 심층 모델은 커스텀 temperature를 지원하지 않는다(기본값 1만 허용,
            # 다른 값을 주면 400). 그래서 temperature를 아예 안 넘긴다 — 2026-08-18 실측.
            model=settings.model_heavy,
            reasoning_effort=settings.model_heavy_reasoning_effort,
            timeout=60,
            tools=[_SEARCH_POLICY_TOOL, _submit_nodes_tool()],
            tool_choice="auto",
            messages=messages,
        )
        msg = resp.choices[0].message
        tool_calls = msg.tool_calls or []

        if not tool_calls:
            # 모델이 툴 호출 없이 일반 텍스트로 답함 — 반드시 submit_rule_nodes를
            # 호출하라고 다시 알려주고 한 턴 더 준다(카운터는 그대로 소모).
            messages.append({"role": "assistant", "content": msg.content or ""})
            messages.append({
                "role": "user",
                "content": "반드시 `submit_rule_nodes` 툴을 호출해 최종 결과를 제출하세요.",
            })
            continue

        messages.append({
            "role": "assistant", "content": msg.content,
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in tool_calls
            ],
        })

        for tc in tool_calls:
            args = json.loads(tc.function.arguments or "{}")
            if tc.function.name == "submit_rule_nodes":
                return args
            if tc.function.name == "search_policy":
                # scope는 LLM 툴 인자에 없다 — 이 그래프가 만들어지는 scope를 서버가
                # 고정해서 넘긴다(모델이 검색 중 다른 scope로 새는 걸 막는다).
                result = mcp_client.call_tool(
                    "search_policy",
                    query=args.get("query", scope),
                    top_k=args.get("top_k") or 6,
                    include_law=bool(args.get("include_law")),
                    scope=scope,
                )
                chunks = result.get("chunks", [])
                tool_content = (
                    f"검색 결과 {len(chunks)}건:\n\n{_format_chunks(chunks)}" if chunks
                    else "검색 결과 0건 — 다른 질의를 시도하거나, 그 조항은 skipped 처리하세요."
                )
            else:
                tool_content = f"알 수 없는 툴: {tc.function.name}"
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": tool_content})

    # 턴 소진 — outer 재시도 루프가 "노드 없음"으로 이어받게 안전 종료.
    return {
        "nodes": [],
        "skipped": [{
            "reason": f"모델이 {MAX_TOOL_TURNS}턴 안에 submit_rule_nodes를 호출하지 않음",
            "source_citation": "",
        }],
    }


def _build_sanitize_feedback(rejected: list[dict]) -> str:
    """sanitize 반려 사유를 다음 LLM 호출 피드백 문장으로 변환."""
    lines = ["생성한 노드 중 아래 항목이 검증에서 반려됐습니다:"]
    for r in rejected:
        node = r["node"]
        problems = "; ".join(r["problems"])
        lines.append(f"- node_key={node.get('node_key')!r}: {problems}")
    lines.append("특히 존재하지 않는 EvalContext 경로를 참조하지 않았는지 다시 확인하세요.")
    return "\n".join(lines)


def _build_structure_feedback(structure_error: str) -> str:
    """구조검증(validate_graph) 실패 사유를 다음 LLM 호출 피드백 문장으로 변환."""
    return f"직전 시도로 조립한 그래프가 구조검증에 실패했습니다: {structure_error}"


# ---------------------------------------------------------------- 1차 방어(FastAPI측)

def _build_condition(node: dict) -> dict:
    """LLM이 채운 재귀 구조화 조건을 JSON-Logic으로 결정론적으로 조립.
    rule-engine.md 캐논의 and/or/not/==/!=/>/>=/</<=/in/var 전체를 커버."""
    if node["kind"] == "group":
        children = [_build_condition(c) for c in (node["children"] or [])]
        if not children:
            # Django dsl은 빈 and/or를 거부한다. 여기서 잡아야 rejected 사유가 남는다 —
            # 그대로 보내면 저장 단계에서 422가 나고 어느 노드 탓인지 흐려진다.
            raise ValueError(f"group 조건에 children이 없음(combinator={node.get('combinator')})")
        if len(children) == 1:
            return children[0]
        if node["combinator"] not in ("and", "or"):
            raise ValueError(f"group combinator 불량: {node.get('combinator')}")
        return {node["combinator"]: children}

    left = {"var": node["left_path"]}
    if node["op"] == "is_null":
        # 우변이 없다. 모델이 right_*를 채워 보내도 무시한다 — 단항이라 쓸 자리가 없다.
        result = {"is_null": left}
        return {"not": result} if node["negate"] else result

    kind = node["right_kind"]
    if kind == "var":
        right = {"var": node["right_var_path"]}
    elif kind == "number":
        right = node["right_number"]
    elif kind == "string":
        right = node["right_string"]
    elif kind == "string_list":
        right = node["right_string_list"]
    else:
        right = node["right_bool"]

    result = {node["op"]: [left, right]}
    if node["negate"]:
        result = {"not": result}
    return result


def _validate_condition(cond: Any, schema_paths: set[str], allowed_ops: set[str]) -> list[str]:
    """DSL 화이트리스트 + 경로 사전검증. 최종 게이트는 Django validate_expr/
    validate_graph_vars — 여기서는 명백한 불량만 걸러 왕복을 줄인다.

    `allowed_ops`/`schema_paths`는 **프롬프트에 실린 것과 같은 카탈로그**에서 온다. 비어
    있으면(카탈로그 조회 실패) 그 항목의 검사를 건너뛴다 — 조회 장애로 전건 반려가 되면
    생성 자체가 멈춘다. 어차피 Django `validate_expr`가 저장 시점에 다시 막는다."""
    errors: list[str] = []

    def walk(node: Any, depth: int = 0) -> None:
        if depth > 32:
            errors.append("중첩 깊이 초과(>32)")
            return
        if isinstance(node, dict):
            if len(node) != 1:
                errors.append(f"연산자 객체는 키 1개여야 함: {list(node.keys())}")
                return
            op, args = next(iter(node.items()))
            if allowed_ops and op not in allowed_ops:
                errors.append(f"허용되지 않은 연산자: {op}")
                return
            if op == "var":
                if not isinstance(args, str):
                    errors.append("var 인자는 문자열 경로여야 함")
                elif schema_paths and args not in schema_paths:
                    errors.append(f"미정의 EvalContext 경로: {args}")
                return
            if isinstance(args, list):
                for a in args:
                    walk(a, depth + 1)
            else:
                walk(args, depth + 1)
        elif isinstance(node, list):
            for a in node:
                walk(a, depth + 1)
        # 리터럴(number/str/bool/None)은 통과

    walk(cond)
    return errors


_NODE_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]{0,63}$")


def _sanitize_nodes(
    raw_nodes: list[dict], schema_paths: set[str], allowed_ops: set[str] | None = None
) -> tuple[list[dict], list[dict]]:
    """LLM 출력 → 저장 후보 노드. 불량은 rejected로 분리(조용한 통과 금지)."""
    accepted, rejected = [], []
    seen_keys: set[str] = set()
    for n in raw_nodes:
        problems: list[str] = []
        key = n.get("node_key", "")
        if not _NODE_KEY_RE.match(key):
            problems.append(f"node_key 형식 불량: {key!r}")
        if key in seen_keys:
            problems.append(f"node_key 중복: {key}")
        try:
            cond = _build_condition(n["condition"])
        except (KeyError, TypeError, ValueError) as exc:
            cond = None
            problems.append(f"condition 조립 실패: {exc}")
        if cond is not None:
            problems.extend(_validate_condition(cond, schema_paths, allowed_ops or set()))
        if n.get("decision") not in {"REJECT", "RETURN", "REVIEW"}:
            problems.append(f"decision 불량: {n.get('decision')}")

        if problems:
            rejected.append({"node": n, "problems": problems})
            continue
        seen_keys.add(key)
        accepted.append(
            {
                "node_key": key,
                "condition": cond,
                "condition_text": f"언제 걸리나요? {n['when']}\n걸리면 어떻게 되나요? {n['then']}",
                "action": {
                    "decision": n["decision"],
                    "severity": n["severity"],
                    "flag": n["flag"],
                    "title": n["title"],
                    "source_clause": n["source_citation"],
                    # 기존 create_node의 기본 action({"origin":"new","workflow_status":"DRAFT"})과
                    # 정합 — _graph_content()의 dedup 비교에서 origin/source_clause는 무시되므로
                    # (comparison keys ignored) 안전하게 넣는다.
                    "origin": "rule-agent-v0",
                    "workflow_status": "DRAFT",
                },
                "priority": severity_priority().get(n["severity"], 4),
            }
        )
    return accepted, rejected


# ---------------------------------------------------------------- 결정론적 조립

PASS_NODE_KEY = "_SCOPE_PASS"


def _assemble_linear_graph(nodes: list[dict]) -> tuple[list[dict], list[dict], str]:
    """선형 체인 조립 — 시드 GLOBAL 패턴(R-002 →NO_MATCH→ R-003 →NO_MATCH→ 종단)과 동일.

    - severity 우선순위(CRITICAL 먼저) 오름차순 정렬 후 체인 연결
    - 각 노드 MATCH → 단말(to="") : 해당 노드 action.decision 확정
    - 각 노드 NO_MATCH → 다음 노드, 마지막 노드 NO_MATCH → _SCOPE_PASS
    - _SCOPE_PASS: condition=true, action.decision=PASS, MATCH → 단말
    """
    ordered = sorted(nodes, key=lambda n: (n["priority"], n["node_key"]))
    pass_node = {
        "node_key": PASS_NODE_KEY,
        "condition": True,  # DSL 리터럴 true — 항상 MATCH
        "condition_text": "언제 걸리나요? 앞의 모든 확인 항목에 해당하지 않을 때\n걸리면 어떻게 되나요? 규칙 검사를 통과한 것으로 처리합니다",
        "action": {
            "decision": "PASS", "severity": "INFO", "flag": "", "title": "게이트 통과",
            "origin": "rule-agent-v0", "workflow_status": "DRAFT",
        },
        "priority": 99,
    }
    all_nodes = ordered + [pass_node]

    routings: list[dict] = []
    for i, n in enumerate(ordered):
        routings.append(
            {"from_node_key": n["node_key"], "on_result": "MATCH", "to_node_key": "", "priority": 0}
        )
        next_key = ordered[i + 1]["node_key"] if i + 1 < len(ordered) else PASS_NODE_KEY
        routings.append(
            {"from_node_key": n["node_key"], "on_result": "NO_MATCH", "to_node_key": next_key, "priority": 0}
        )
    routings.append(
        {"from_node_key": PASS_NODE_KEY, "on_result": "MATCH", "to_node_key": "", "priority": 0}
    )
    entry = ordered[0]["node_key"] if ordered else PASS_NODE_KEY
    return all_nodes, routings, entry


def _existing_summary(graph: dict) -> str:
    """편집 중인 초안을 프롬프트에 실을 문장으로. **중복 생성을 막는 것이 목적**이다.

    지금까지는 모델이 기존 초안을 못 봐서 같은 조항으로 같은 룰을 계속 새로 만들었다
    (그리고 생성마다 새 계열이 생겨 초안이 쌓였다).
    """
    rows = []
    for node in sorted(graph.get("nodes") or [], key=lambda n: n.get("priority", 0)):
        action = node.get("action") or {}
        if node.get("nodeKey") == PASS_NODE_KEY:
            continue
        title = action.get("title") or node.get("nodeKey")
        clause = action.get("source_clause") or ""
        rows.append(
            f"- {node.get('nodeKey')} · {title} → {action.get('decision', '')}"
            + (f" (근거: {clause})" if clause else "")
        )
    return "\n".join(rows)


def _plan_append(existing: dict, ordered: list[dict]) -> tuple[list[dict], dict, list[dict]]:
    """기존 초안 **끝에** 새 노드를 잇는 계획 — `(nodes, routings_by_node, rewire)`.

    선형 체인이라 세 가지를 맞춰야 한다:
      ① **종단 PASS를 또 만들지 않는다.** 기존 그래프에 이미 있다.
      ② **직전 노드의 `NO_MATCH`를 새 노드로 돌린다.** 안 고치면 새 노드는 달려만 있고
         아무도 도달하지 못한다 — 엔진이 순회하지 않으므로 **조용히 무용해진다**.
      ③ **키가 겹치면 새로 짓는다.** 같은 키로 POST하면 400이거나 기존 노드를 덮어쓴다.
    """
    taken = {n.get("nodeKey") for n in (existing.get("nodes") or [])}
    routings = existing.get("routings") or []

    #  체인의 꼬리 = 종단 PASS를 가리키는 노드. PASS가 없는(사람이 만든) 그래프면
    #  NO_MATCH가 없는 노드가 꼬리다.
    pass_key = next(
        (n.get("nodeKey") for n in (existing.get("nodes") or [])
         if n.get("nodeKey") == PASS_NODE_KEY
         or (n.get("action") or {}).get("decision") == "PASS"),
        "",
    )
    has_no_match = {r["fromNodeKey"] for r in routings if r.get("onResult") == "NO_MATCH"}
    tail = next(
        (r["fromNodeKey"] for r in routings
         if r.get("onResult") == "NO_MATCH" and r.get("toNodeKey") == pass_key),
        "",
    )
    if not tail:
        tail = next(
            (n.get("nodeKey") for n in (existing.get("nodes") or [])
             if n.get("nodeKey") not in has_no_match and n.get("nodeKey") != pass_key),
            "",
        )

    renamed: list[dict] = []
    for node in ordered:
        key = node["node_key"]
        if key in taken:
            suffix = 2
            while f"{key}-{suffix}" in taken:
                suffix += 1
            key = f"{key}-{suffix}"
        taken.add(key)
        renamed.append({**node, "node_key": key})

    routings_by_node: dict[str, list[dict[str, str]]] = {}
    for i, node in enumerate(renamed):
        nxt = renamed[i + 1]["node_key"] if i + 1 < len(renamed) else pass_key
        routings_by_node[node["node_key"]] = [
            {"onResult": "MATCH", "toNodeKey": ""},
            #  마지막 새 노드는 기존 종단으로 되돌아간다. 종단이 없으면(빈 그래프 등)
            #  라우팅을 걸지 않아 그 노드의 액션이 곧 판정이 된다.
            *([{"onResult": "NO_MATCH", "toNodeKey": nxt}] if nxt else []),
        ]

    rewire = []
    if tail and renamed:
        rewire.append({
            "node_key": tail,
            "routings": [
                {"onResult": "MATCH", "toNodeKey": ""},
                {"onResult": "NO_MATCH", "toNodeKey": renamed[0]["node_key"]},
            ],
            #  실패 시 되돌릴 값 — 지금 이 노드가 가리키던 곳. 안 적어 두면 롤백이
            #  "원래 어디를 가리켰는지"를 모르고, 체인이 끊긴 채로 남는다.
            "restore_to": pass_key,
        })
    return renamed, routings_by_node, rewire


def _rollback_append(graph_id: str, created: list[str], rewire: list[dict]) -> None:
    """이어 붙이기 실패 시 **우리가 만든 것만** 되돌린다.

    `discard_draft`를 쓰면 사람이 편집하던 초안이 통째로 사라진다 — 자동 생성이 실패했다고
    남의 작업을 지우는 것은 이 시스템이 절대 하면 안 되는 종류의 일이다.

    순서가 중요하다: **라우팅을 먼저 원복**하고 노드를 지운다. 반대로 하면 직전 노드가
    없는 노드를 가리키는 잠깐이 생기고, 그 사이 판정이 돌면 그래프가 깨진 채로 보인다.
    되돌리기 자체가 실패해도 예외를 올리지 않는다 — 여기서 터지면 원래 반환하려던 실패
    사유마저 사라진다.
    """
    for fix in (rewire or []):
        try:
            django_client.update_node(
                graph_id, fix["node_key"],
                routings=[{"onResult": "MATCH", "toNodeKey": ""},
                          {"onResult": "NO_MATCH", "toNodeKey": fix.get("restore_to", "")}],
            )
        except Exception:  # noqa: BLE001
            pass
    for node_key in created:
        try:
            django_client.delete_node(graph_id, node_key)
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------- 진입점

DEFAULT_QUERIES = {
    # scope → 규칙화 가능 조항을 끌어올 기본 질의. 사용자가 query를 주면 그것을 우선.
    # 키는 GLOBAL ∪ settlements.Category. **없어도 동작한다** — 아래 `generate()`가
    # `f"{scope} 관련 규정"`으로 떨어지므로, 어휘 정본(core)에 분류가 추가돼도 여기에
    # 항목이 없다는 이유로 막히지 않는다(이건 허용 목록이 아니라 질의 힌트다).
    # [2026-08-14] "회식"이 정식 독립 카테고리가 되며 유효한 scope가 됐다(회식 규정
    # 그래프도 scope="식대"→"회식"으로 이전됨 — seed_rules.py `_seed_dining`). "업무활성"은
    # Category에서 폐지됐고(TEST 픽스처는 scope="TEST_DEMO"로 이동) 더는 유효 scope가 아니다.
    "GLOBAL": "법인카드 사용 금지 항목 및 결제 수단 제한",
    "접대": "기업업무추진비 한도 사전승인 증빙 기재사항",
    "식대": "식대 한도 증빙 요건",
    "출장": "출장비 숙박비 한도 사전승인",
    "회의": "회의비 한도 증빙 참석자",
    "회식": "회식비 한도 증빙 요건 승인권자 야간 주류",
    "기타": "법인카드 사용 범위 증빙 요건 일반 기준",
}


def _group_routings_by_node(routings: list[dict]) -> dict[str, list[dict[str, str]]]:
    """flat 라우팅 리스트 → {node_key: [{"onResult":..,"toNodeKey":..}]} (camelCase,
    기존 update_node action이 request.data를 그대로 읽으므로 프론트와 동일 표기)."""
    grouped: dict[str, list[dict[str, str]]] = {}
    for r in routings:
        grouped.setdefault(r["from_node_key"], []).append(
            {"onResult": r["on_result"], "toNodeKey": r["to_node_key"]}
        )
    return grouped


def generate(req: Any) -> dict[str, Any]:
    """req: api.RuleGenerateRequest (scope, query, top_k, name)

    v0는 항상 새 계열(v1)만 만든다 — family_key로 기존 계열에 버전을 추가하는 것은
    v1 범위(POST /api/rules/{id}/versions 오케스트레이션 필요, GAPS.md 참조).
    """
    query = req.query or DEFAULT_QUERIES.get(req.scope, f"{req.scope} 관련 규정")

    # ① RAG — 규칙화 가능 조항 추출. MCP `search_policy` 툴을 in-process로 호출한다
    #    (§1.2-1) — outer 재시도 루프가 재사용할 "1차 근거"만 여기서 확보하고, 부족하면
    #    LLM이 `_run_generation_loop` 안에서 같은 툴을 추가로 호출한다.
    chunks = mcp_client.call_tool(
        "search_policy", query=query, top_k=req.top_k, include_law=req.include_law,
        scope=req.scope,
    ).get("chunks", [])
    if not chunks:
        return {
            "status": "NO_SOURCE",
            "detail": (
                "policy_docs 검색 결과 0건 — 규정 문서가 아직 적재되지 않았습니다. "
                "관리자 배치로 먼저 인덱싱하세요: "
                "`docker compose exec ai python -m app.rag.embedding.index "
                "--dump /data/docling_eval/output`"
            ),
            "query": query,
        }

    # ② 도메인 카탈로그 확보 — **프롬프트에 실리는 목록과 검증 기준이 같은 객체**여야 한다.
    #    (`domain/context` 프로파일 `rule_generate`. 조회 실패해도 stale 표시만 하고 진행)
    ctx = catalog()
    schema_paths = ctx.paths

    #  이 scope에 **편집 중인 초안**이 있으면 거기에 이어 붙인다. 예전엔 생성할 때마다 새
    #  계열이 생겨 룰 콘솔이 초안으로 뒤덮였고(사람이 어느 걸 보고 있는지도 흐려졌다),
    #  모델은 기존 초안을 못 봐서 같은 조항으로 같은 룰을 계속 다시 만들었다.
    existing = django_client.find_open_draft(req.scope)

    # ③~⑤ 검증→재생성 루프 (agent-v1-upgrade-plan.md §1.2-4, A안).
    #   - RAG 청크(①)는 시도 전체에서 재사용한다 — 재조회하면 "피드백이 통했는지"와
    #     "우연히 다른 청크가 걸렸는지"를 구분할 수 없어져 루프의 신뢰성이 무너진다.
    #   - sanitize 전멸(노드 후보가 전부 반려)과 저장 후 구조검증(/simulate) 실패를
    #     하나의 카운터로 묶는다. 둘 다 "이번 시도가 실패해서 LLM을 다시 부른다"는
    #     본질이 같다.
    feedback: str | None = None
    attempt_history: list[dict[str, Any]] = []

    for attempt_no in range(1, MAX_GENERATE_ATTEMPTS + 1):
        llm_out = _run_generation_loop(req.scope, chunks, ctx, feedback, existing=existing)
        accepted, rejected = _sanitize_nodes(
            llm_out.get("nodes", []), set(schema_paths), ctx.operators
        )

        if not accepted:
            attempt_history.append({
                "attempt": attempt_no, "stage": "sanitize",
                "rejected_nodes": rejected, "llm_skipped": llm_out.get("skipped", []),
            })
            if attempt_no == MAX_GENERATE_ATTEMPTS:
                return {
                    "status": "NO_VALID_NODES_EXHAUSTED",
                    "detail": f"{MAX_GENERATE_ATTEMPTS}회 시도 모두 유효한 노드를 생성하지 못함 — attempts 참조",
                    "query": query,
                    "attempts": attempt_history,
                    "sources": [c["citation"] for c in chunks],
                }
            feedback = _build_sanitize_feedback(rejected)
            continue

        # ④ 결정론적 조립 (선형 체인)
        nodes, routings, entry = _assemble_linear_graph(accepted)
        routings_by_node = _group_routings_by_node(routings)

        # ⑤ Django 룰 콘솔 API 3종 오케스트레이션 (drafts → nodes → nodes/{key} PATCH).
        #    인증은 서비스 계정 JWT(django_client) — 실패는 감추지 않고 그대로 올린다.
        generation_meta = {
            "agent": "rule-agent-v0",
            "model": settings.model_heavy,
            "query": query,
            "requested_scope": req.scope,
            "include_law": req.include_law,
            # 노드별 출처는 action.source_clause에 있다. 여기 남기는 건 **그래프 단위**
            # 근거 — 어떤 조문 묶음을 보고 이 그래프가 나왔는지.
            "sources": [
                {"citation": c["citation"], "chunk_id": c["chunk_id"], "score": c["score"]}
                for c in chunks
            ],
            # 어떤 어휘로 만들어졌는지 — 플래그가 27종이던 시절의 생성물을 지금 목록으로
            # 설명하면 어긋난다. 카탈로그 해시를 함께 남겨 나중에 되짚게 한다.
            "catalog_etag": ctx.etag,
            "catalog_stale": ctx.stale,
            "rejected_node_count": len(rejected),
            "llm_skipped": llm_out.get("skipped", []),
            "generation_attempts": attempt_no,
        }
        rewire: list[dict] = []
        if existing:
            #  기존 초안에 **이어 붙인다**. `_assemble_linear_graph`가 만든 종단 PASS는
            #  빼고 보낸다 — 기존 그래프에 이미 있고, 둘이면 뒤엣것이 도달 불가가 된다.
            appended, append_routings, rewire = _plan_append(
                existing, [n for n in nodes if n["node_key"] != PASS_NODE_KEY],
            )
            django_client.append_to_draft(
                existing["id"], appended, append_routings, rewire,
            )
            saved = {
                "graph_id": existing["id"],
                "family_key": existing.get("familyKey"),
                "version": existing.get("version"),
                "scope": existing.get("scope"),
                "status": existing.get("status"),
                "created_nodes": [n["node_key"] for n in appended],
                "appended_to_existing": True,
            }
        else:
            saved = django_client.create_rule_graph_draft(
                name=req.name or f"{req.scope} 자동생성 초안",
                scope=req.scope,
                nodes=nodes,
                routings_by_node=routings_by_node,
                generation_meta=generation_meta,
            )

        # ⑥ 구조검증 — 저장된 그래프를 대상으로만 돌릴 수 있다(사전 dry-validate
        #    엔드포인트는 없음, §1.2-3). 실패하면 이 시도의 그래프를 지우고 재시도.
        sim = django_client.simulate_graph(saved["graph_id"])
        structure_error = sim.get("structureError", "")

        if not structure_error:
            return {
                "status": "DRAFT_SAVED",
                "graph": saved,
                "entry_node_key": entry,
                "query": query,
                "sources": [c["citation"] for c in chunks],
                "rejected_nodes": rejected,
                "llm_skipped": llm_out.get("skipped", []),
                "attempts": attempt_no,
            }

        attempt_history.append({
            "attempt": attempt_no, "stage": "structure",
            "structure_error": structure_error, "graph_id": saved["graph_id"],
        })
        #  ⚠️ 이어 붙인 경우에는 **그래프를 지우면 안 된다** — 사람이 편집하던 초안이다.
        #     우리가 만든 노드만 걷어내 원래 상태로 되돌린다(라우팅은 append 전 값이
        #     기존 그래프에 그대로 남아 있으므로 노드만 지우면 체인이 복구된다).
        if saved.get("appended_to_existing"):
            _rollback_append(saved["graph_id"], saved["created_nodes"], rewire)
        else:
            django_client.discard_draft(saved["graph_id"])

        if attempt_no == MAX_GENERATE_ATTEMPTS:
            return {
                "status": "STRUCTURE_INVALID_EXHAUSTED",
                "detail": f"{MAX_GENERATE_ATTEMPTS}회 시도 모두 구조검증 실패 — attempts 참조",
                "query": query,
                "attempts": attempt_history,
                "sources": [c["citation"] for c in chunks],
            }
        feedback = _build_structure_feedback(structure_error)

    # 루프는 항상 위에서 return 한다 — 도달 불가(방어적 표기).
    raise AssertionError("generate() 재시도 루프가 값을 반환하지 않고 종료됨")

# apps/ai/app/agents/rule_agent_v0/api.py
"""Rule Agent 생성 라우터.

엔드포인트는 `/agent/rule-v0/...` 네임스페이스에 있다. 기술명세서 §6.2의 정식 경로
(`/agent/rule/generate`)로 옮기려던 계획은 폐기했다 — 그 경로를 잡고 있던
`agents/rule_agent.py`(전부 stub, 아무도 안 부름)를 2026-08-21 전수 점검에서 삭제했다.
`rule-v0` 네임스페이스가 사실상 정식 경로다(승격 이관은 불필요 — 이름만 남은 구분).

**FastAPI는 내부 전용이다.** 브라우저는 이 경로를 직접 부르지 않고 Django
`POST /api/rules/generate/`(capability `rule_view`)를 거친다 — AI-LAB 프록시와 같은 구조.

임베딩 적재(`/embeddings/upsert`)는 **제거했다.** 그 엔드포인트는 자체 임베딩 사본으로
Chroma에 직접 써서 `embedder_version`을 남기지 않았고(=`assert_single_embedder`가 못
잡는 사각지대), 컬렉션을 `embedding_function=None` 없이 만들 수 있었다. 규정 적재의
정본 경로는 관리자 CLI 하나다:

    docker compose exec ai python -m app.rag.embedding.index --dump /data/docling_eval/output
"""
from __future__ import annotations

from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.clients import core_client

from . import agent as rule_agent
from . import chat as rule_chat
from . import narrate as rule_narrate
from . import testcases as rule_testcases
from .django_client import ServiceAuthError

router = APIRouter(prefix="/agent/rule-v0", tags=["rule-agent"])

# scope 허용값 = GLOBAL ∪ settlements.Category. **정본은 core**이고
# (`domain/policies/models.py` RULE_SCOPE_CHOICES = [GLOBAL, *Category.choices]),
# 여기서는 `core_client.get_categories()`로 받아 검증한다 — 예전엔 이 파일에 Literal로
# 박아 뒀는데 "업무활성"→"회식" 리네임 때 두 번(한 번은 틀린 방향으로) 손댔던 자리다.
#
# 형식 검증이 아니라 **호출 시점 검증**인 이유: Literal로 두면 core가 분류를 늘렸을 때
# ai만 옛 목록으로 남아 정상 scope가 422로 막힌다. 반대로 검증을 아예 빼면 오타 scope가
# RAG 검색·LLM 호출을 다 태운 뒤 마지막 Django 저장에서 400으로 죽는다(비싸다).
def _validate_scope(scope: str) -> None:
    allowed = {"GLOBAL", *core_client.get_categories()}
    if scope not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"알 수 없는 scope입니다: {scope} (가능한 값: {', '.join(sorted(allowed))})",
        )


class RuleGenerateRequest(BaseModel):
    scope: str
    query: Optional[str] = None          # 미지정 시 scope별 기본 질의
    top_k: int = Field(default=6, ge=1, le=20)
    name: Optional[str] = None
    include_law: bool = False            # 세법(tax_refs)도 근거로 함께 검색할지
    # family_key(기존 계열에 새 버전 추가)는 아직 미지원 — 항상 새 계열 v1로 생성한다.


@router.post("/generate")
def generate_rules(req: RuleGenerateRequest):
    """RAG → LLM 노드 초안 → 결정론적 조립 → Django DRAFT 저장.

    실패 사유를 502로 뭉개지 않는다. Django가 400(예: scope 불량)을 주면 400을 그대로
    올려야 화면이 "왜 안 되는지"를 보여줄 수 있다 — 전부 502로 덮으면 인증 문제와
    입력 문제가 구분되지 않는다(v0에서 실제로 그랬다).
    """
    _validate_scope(req.scope)
    try:
        return rule_agent.generate(req)
    except ServiceAuthError as exc:
        raise HTTPException(status_code=401, detail=f"서비스 계정 인증 실패: {exc}") from exc
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:500]
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=f"Django 저장 실패({exc.request.url.path}): {detail}",
        ) from exc
    except httpx.HTTPError as exc:          # 연결 실패·타임아웃
        raise HTTPException(status_code=503, detail=f"내부 서비스 연결 실패: {exc}") from exc
    except Exception as exc:                # noqa: BLE001  # Chroma·OpenAI 등
        raise HTTPException(status_code=502, detail=f"rule generate 실패: {type(exc).__name__}: {exc}") from exc


class RuleConverseRequest(BaseModel):
    graph_id: str
    message: str
    # 화면에서 지금 선택 중인 노드 — 모호한 지시를 엉뚱한 노드에 적용하지 않도록 하는
    # 힌트(2026-08-18 추가, chat.py 모듈 docstring 참조). 없어도 동작은 한다.
    node_key: Optional[str] = None


@router.post("/converse")
def converse_rule(req: RuleConverseRequest):
    """대화형 자연어 수정(§1.2-5) — MCP 툴콜링으로 의도를 해석해 기존 그래프 CRUD API를
    직접 호출한다. 실패 처리 방침은 `/generate`와 동일(원인별 상태코드를 그대로 올림)."""
    try:
        return rule_chat.converse(req.graph_id, req.message, node_key=req.node_key)
    except ServiceAuthError as exc:
        raise HTTPException(status_code=401, detail=f"서비스 계정 인증 실패: {exc}") from exc
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:500]
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=f"Django 호출 실패({exc.request.url.path}): {detail}",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"내부 서비스 연결 실패: {exc}") from exc
    except Exception as exc:                # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"rule converse 실패: {type(exc).__name__}: {exc}") from exc


class GenerateTestCasesRequest(BaseModel):
    graph_id: str


@router.post("/test-cases/generate")
def generate_test_cases(req: GenerateTestCasesRequest):
    """검증셋 자동생성(§4) — 대화형 아님, 완제품을 한 번에 만들어 기존 검증셋에 추가한다.
    실패 처리 방침은 `/generate`와 동일."""
    try:
        return rule_testcases.generate_test_cases(req.graph_id)
    except ServiceAuthError as exc:
        raise HTTPException(status_code=401, detail=f"서비스 계정 인증 실패: {exc}") from exc
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:500]
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=f"Django 호출 실패({exc.request.url.path}): {detail}",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"내부 서비스 연결 실패: {exc}") from exc
    except Exception as exc:                # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"test-case 생성 실패: {type(exc).__name__}: {exc}") from exc


class NarrateReportRequest(BaseModel):
    facts: dict


@router.post("/narrate-report")
def narrate_report(req: NarrateReportRequest):
    """시뮬레이션 결과 서술 생성(§13.3) + 권장 처리 판단(2026-08-19) — Django가 이미 계산한
    통계/구조·실행결과 등급(`facts`)을 바탕으로 문장을 쓰고, 권장 처리(action) 등급도 다시
    판단한다(구조 등급이 poor면 Django가 서버 측에서 poor로 강제 — LLM 응답과 무관).
    LLM 호출이 실패해도 500을 주지 않고 `report: null`을 돌려준다 — 호출부(Django)가
    템플릿 폴백 + 결정론적 action을 유지하는 정상 경로이지 에러가 아니다."""
    result = rule_narrate.narrate_report(req.facts)
    if result is None:
        return {"report": None, "action": None}
    return result

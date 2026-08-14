# apps/ai/app/agents/rule_agent_v0/api.py
"""Rule Agent 생성 라우터.

엔드포인트는 `/agent/rule-v0/...` 네임스페이스에 있다. 기술명세서 §6.2의 정식 경로
(`/agent/rule/generate`)는 아직 `agents/rule_agent.py` stub이 잡고 있어 경로가 겹치지
않도록 분리해 둔 것이다 — 정식 경로로 승격할 때 이 라우터를 지우고 옮긴다.

**FastAPI는 내부 전용이다.** 브라우저는 이 경로를 직접 부르지 않고 Django
`POST /api/rules/generate/`(capability `rule_view`)를 거친다 — AI-LAB 프록시와 같은 구조.

임베딩 적재(`/embeddings/upsert`)는 **제거했다.** 그 엔드포인트는 자체 임베딩 사본으로
Chroma에 직접 써서 `embedder_version`을 남기지 않았고(=`assert_single_embedder`가 못
잡는 사각지대), 컬렉션을 `embedding_function=None` 없이 만들 수 있었다. 규정 적재의
정본 경로는 관리자 CLI 하나다:

    docker compose exec ai python -m app.rag.embedding.index --dump /data/docling_eval/output
"""
from __future__ import annotations

from typing import Literal, Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import agent as rule_agent
from .django_client import ServiceAuthError

router = APIRouter(prefix="/agent/rule-v0", tags=["rule-agent"])

# scope 허용값 = GLOBAL ∪ settlements.Category. **SoT는 Django 코드**(`Category`)다.
# 규정 문서 표기(기업업무추진비·회식 등)는 여기가 아니라 Django `normalize_scope`가
# Category 값으로 접는다 — 회식은 별도 Category가 없어 식대 그래프에 편성된다(scope.py).
Scope = Literal["GLOBAL", "업무활성", "회의", "식대", "출장", "접대", "비품"]


class RuleGenerateRequest(BaseModel):
    scope: Scope
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

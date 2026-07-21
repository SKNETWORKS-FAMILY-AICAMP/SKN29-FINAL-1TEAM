from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class UpsertRequest(BaseModel):
    collection: str  # policy_docs / case_history / tax_refs
    documents: list[str] = []


@router.post("/upsert")
def upsert(req: UpsertRequest):
    """규정문서 임베딩 upsert (관리자 트리거). TODO: 청킹→임베딩→Chroma upsert."""
    return {"collection": req.collection, "upserted": 0, "status": "stub"}

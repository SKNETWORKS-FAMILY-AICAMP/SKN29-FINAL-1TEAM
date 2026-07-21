from fastapi import APIRouter

from app.rag import chroma_client

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok", "service": "ai", "chroma": chroma_client.heartbeat()}

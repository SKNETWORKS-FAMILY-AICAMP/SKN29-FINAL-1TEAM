"""Chroma(RAG 벡터 스토어) 접근 (기술명세서 §3.2, §8).

컬렉션: policy_docs / case_history / tax_refs
스캐폴드에서는 httpx로 heartbeat만 확인. 실제 upsert/query는
공식 chromadb 클라이언트로 교체 예정(TODO).
"""
import httpx

from app.config import settings

COLLECTIONS = ("policy_docs", "case_history", "tax_refs")


def base_url() -> str:
    return f"http://{settings.chroma_host}:{settings.chroma_port}"


def heartbeat() -> bool:
    """Chroma 연결 확인 (v2 → v1 순서로 시도)."""
    for path in ("/api/v2/heartbeat", "/api/v1/heartbeat"):
        try:
            resp = httpx.get(f"{base_url()}{path}", timeout=3)
            if resp.status_code == 200:
                return True
        except Exception:  # noqa: BLE001
            continue
    return False

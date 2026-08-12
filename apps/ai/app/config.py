"""FastAPI(ai) 설정. 환경변수(CORE_BASE_URL, CHROMA_*, OPENAI_API_KEY 등) 로드."""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 컨테이너에서는 `/app/.env`, 로컬 CLI에서는 **레포 루트** `.env`가 진짜다.
# CWD 기준 `.env` 하나만 보면 `apps/ai`에서 실행할 때 조용히 빈 설정으로 뜬다.
_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(_REPO_ROOT / ".env", ".env"), extra="ignore"
    )

    # Django 내부 read API (관계형 데이터는 반드시 Django 경유)
    core_base_url: str = "http://core:8000"
    # Chroma (벡터 RAG)
    chroma_host: str = "chroma"
    chroma_port: int = 8000
    # 설정 시 HTTP 대신 로컬 영속 클라이언트를 쓴다 (docker 없는 개발 환경용)
    chroma_persist_dir: str = ""
    # OpenAI (LLM·비전) — 실제 Agent 동작 시 필요
    openai_api_key: str = ""
    # 로컬 모델 레지스트리 경로
    model_dir: str = "/app/var/models"


settings = Settings()

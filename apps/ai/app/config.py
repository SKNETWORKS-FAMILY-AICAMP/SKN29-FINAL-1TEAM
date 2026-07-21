"""FastAPI(ai) 설정. 환경변수(CORE_BASE_URL, CHROMA_*, OPENAI_API_KEY 등) 로드."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Django 내부 read API (관계형 데이터는 반드시 Django 경유)
    core_base_url: str = "http://core:8000"
    # Chroma (벡터 RAG)
    chroma_host: str = "chroma"
    chroma_port: int = 8000
    # OpenAI (LLM·비전) — 실제 Agent 동작 시 필요
    openai_api_key: str = ""
    # 로컬 모델 레지스트리 경로
    model_dir: str = "/app/var/models"


settings = Settings()

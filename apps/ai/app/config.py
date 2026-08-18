"""FastAPI(ai) 설정. 환경변수(CORE_BASE_URL, CHROMA_*, OPENAI_API_KEY 등) 로드."""
from pydantic_settings import BaseSettings, SettingsConfigDict

# 실행 경로는 docker 하나다 — 값은 compose `environment:`(루트 `.env`를 `${}`로 치환)가
# 주입하고 여기선 `os.environ`만 읽는다. `.env` 파일을 직접 찾아 읽지 않는 이유:
# 파일 위치가 호스트/컨테이너에서 달라져 경로 계산이 깨진다(컨테이너는 `/app/app/config.py`).
# docker 밖에서 돌리는 노트북은 자체 `load_dotenv()`로 os.environ을 채우므로 그대로 동작한다.
class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    # Django 내부 read API (관계형 데이터는 반드시 Django 경유)
    core_base_url: str = "http://core:8000"
    # Chroma (벡터 RAG)
    chroma_host: str = "chroma"
    chroma_port: int = 8000
    # 설정 시 HTTP 대신 로컬 영속 클라이언트를 쓴다 (docker 없는 개발 환경용)
    chroma_persist_dir: str = ""
    # OpenAI (LLM·비전) — 실제 Agent 동작 시 필요
    openai_api_key: str = ""
    # 카카오 로컬(지도) API — 가맹점 업종 구분 캐스케이드 2단계(§7-1)
    kakao_rest_api_key: str = ""
    # 로컬 모델 레지스트리 경로
    model_dir: str = "/app/var/models"


settings = Settings()

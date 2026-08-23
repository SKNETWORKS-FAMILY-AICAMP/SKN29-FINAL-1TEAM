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

    # ── LLM 모델 2종 — **이름은 여기서만 정한다** (`app/llm.py`가 유일한 소비처) ──
    #  호출부는 모델 이름 대신 **역할**("fast"/"heavy")로 부른다. 이름을 각 Agent가 들고
    #  있으면 모델을 바꿀 때 전부 고쳐야 하고, 실제로 그렇게 흩어져 있었다(6곳 하드코딩).
    #
    #  fast   빠른-효율성. 표시용 변환·문체 다듬기·분류처럼 지연이 사용자에게 보이는 자리.
    #  heavy  무거운 추론. 결과가 판단으로 쓰이는 자리(위험 검토 보고서·룰 생성).
    #         ⚠️ 커스텀 `temperature`를 지원하지 않는다(기본 1만 허용, 다른 값은 400) —
    #            그 차이는 `app/llm.py`가 흡수하므로 호출부는 신경 쓰지 않는다.
    llm_fast_model: str = "gpt-4o-mini"
    llm_heavy_model: str = "gpt-5-mini"
    #  실측(2026-08-18, rule_agent_v0): minimal/low ~23초 · medium 41초. 품질 차이는
    #  뚜렷하지 않아 low를 기본으로 둔다.
    llm_heavy_reasoning_effort: str = "low"


settings = Settings()

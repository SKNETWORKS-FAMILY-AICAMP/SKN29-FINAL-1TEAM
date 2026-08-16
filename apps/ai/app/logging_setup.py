"""FastAPI(ai) 로깅 — 콘솔 + (설정 시) 파일.

`LOG_DIR`이 있으면 그 아래 `ai.log`에도 남긴다. compose가 `/logs`를 호스트 `./logs`에
바인드하므로 컨테이너 밖에서 바로 열어볼 수 있다. **비어 있으면 콘솔만** — 노트북·테스트가
컨테이너 경로를 못 만들어 죽는 것을 막는다(core의 `LOG_DIR` 규약과 같다).

uvicorn은 자기 로깅을 먼저 구성하고 그다음 앱을 import한다. 그래서 여기서 핸들러를
**root와 uvicorn 로거 양쪽에 붙여야** 접근 로그·에러 로그가 같은 파일에 모인다.
"""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
DATEFMT = "%Y-%m-%d %H:%M:%S"
# 무한히 커지면 볼륨을 채운다 — core와 같은 정책(5MB × 3).
MAX_BYTES = 5 * 1024 * 1024
BACKUPS = 3

_configured = False


def setup() -> Path | None:
    """로깅을 구성하고 로그 파일 경로를 돌려준다(파일 미사용이면 None). 멱등."""
    global _configured
    if _configured:
        return None
    _configured = True

    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    formatter = logging.Formatter(FORMAT, datefmt=DATEFMT)

    root = logging.getLogger()
    root.setLevel(level)
    if not root.handlers:
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        root.addHandler(console)

    log_dir = os.environ.get("LOG_DIR", "").strip()
    if not log_dir:
        return None

    path = Path(log_dir)
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:      # 권한·읽기전용 마운트 — 로깅 때문에 앱이 죽지는 않게 한다
        root.warning("로그 디렉터리를 만들지 못했다(%s): %s — 콘솔 로깅만 사용한다", log_dir, exc)
        return None

    target = path / "ai.log"
    handler = RotatingFileHandler(target, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8")
    handler.setFormatter(formatter)
    root.addHandler(handler)

    # uvicorn 로거는 propagate=False로 자기 핸들러만 쓴다 — 명시적으로 붙여줘야 파일에 남는다.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.setLevel(level)
        if not any(isinstance(h, RotatingFileHandler) for h in logger.handlers):
            logger.addHandler(handler)

    return target

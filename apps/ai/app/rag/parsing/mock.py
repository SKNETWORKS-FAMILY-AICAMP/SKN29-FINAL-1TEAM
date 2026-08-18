"""docling 모킹 — 파싱만 **미리 떠둔 덤프로 대체**하는 개발용 스위치.

docling은 모델을 올리고(수십 초~분) 버전 드리프트에 민감하다. 그래서 파싱이 깨지면
그 뒤 체인(교정→청킹→임베딩→적재→조항→룰 트리거) 전체를 시험할 방법이 없어진다.
이 모듈은 **파싱 단계만** 갈아끼워 나머지를 그대로 돌릴 수 있게 한다.

## 왜 안전한가 — 새 경로가 아니다

`dump.load_all()`은 이미 `ParsedDoc`을 돌려주고, 관리자 CLI(`embedding/index.py`)가
**이미 그 경로로 청킹·임베딩을 돌린다**(회귀 테스트 175건이 그 경로를 덮는다).
그래서 여기서 하는 일은 어댑터를 만드는 게 아니라 검증된 로더를 부르는 것뿐이고,
파싱 이후 단계는 운영과 **바이트 단위로 같은 코드**를 지난다.

## 켜는 법

    DOCLING_MOCK=1                                # 끄면(기본) 아무 영향 없다
    DOCLING_MOCK_DUMP=/data/docling_eval/output   # 기본값. compose가 :ro로 마운트한다

## 안전장치 — 진짜 위험은 파싱이 아니라 "켜둔 걸 잊는 것"

  1. **부를 때마다 WARNING 로그**를 남긴다.
  2. 적재 결과 경고에 실려 **화면에 노란 배너로 뜬다**(`PolicyDoc.error` 경유).
  3. `doc_id`가 `dump:<문서명>`이라 **Chroma에서 실물 벡터와 눈으로 구분된다**
     (실물은 파일 해시). 모킹으로 넣은 벡터를 나중에 골라낼 수 있다.
  4. **이름이 안 맞으면 실패시킨다** — 실제 docling으로 조용히 폴백하지 않고,
     비슷한 이름으로 넘겨짚지도 않는다. 넘겨짚으면 A 문서 내용이 B 문서 레코드에
     적재되는데, 그건 조용히 틀린 데이터를 만드는 최악의 실패다.

⚠️ 모킹 중에는 **업로드한 파일의 내용이 무시된다** — 이름만 보고 덤프를 고른다.
그게 이 스위치의 목적이지만, 운영 환경에서는 절대 켜면 안 되는 이유이기도 하다.
"""
from __future__ import annotations

import logging
import os
import threading
import unicodedata
from pathlib import Path

from app.rag.parsing.model import ParsedDoc

logger = logging.getLogger(__name__)

DEFAULT_DUMP = "/data/docling_eval/output"
_TRUTHY = {"1", "true", "yes", "on"}

_lock = threading.Lock()
_cache: dict[str, ParsedDoc] | None = None
_cache_key: str | None = None


class MockDocumentNotFound(RuntimeError):
    """덤프에 그 이름의 문서가 없다 — 넘겨짚지 않고 여기서 멈춘다."""


def enabled() -> bool:
    return os.environ.get("DOCLING_MOCK", "").strip().lower() in _TRUTHY


def dump_root() -> Path:
    return Path(os.environ.get("DOCLING_MOCK_DUMP", "").strip() or DEFAULT_DUMP)


def _norm(value: str) -> str:
    """이름 비교용 정규화 — **정규화만 하고 유사도 매칭은 하지 않는다.**

    NFC 통일이 필요한 이유: macOS에서 만든 한글 파일명은 NFD(자모 분리)로 저장돼
    바이트가 달라도 눈에는 똑같이 보인다. 그건 정규화로 풀 문제지 유사도로 풀 문제가 아니다.
    """
    return unicodedata.normalize("NFC", (value or "").strip()).casefold()


def _load(root: Path) -> dict[str, ParsedDoc]:
    """덤프를 읽어 캐시한다. CSV 4,388행을 업로드마다 다시 읽을 이유가 없다."""
    global _cache, _cache_key
    key = str(root)
    with _lock:
        if _cache is not None and _cache_key == key:
            return _cache
        from app.rag.parsing import dump as dump_mod

        docs = dump_mod.load_all(root / "layout" / "layout_result.csv", root / "tables")
        _cache, _cache_key = docs, key
        logger.info("docling 모킹 덤프 로드: %s (문서 %d종)", root, len(docs))
        return docs


def available(root: Path | None = None) -> list[str]:
    return sorted(_load(root or dump_root()).keys())


def parse(pdf_path: str | Path, *, name: str | None = None) -> tuple[ParsedDoc, str]:
    """이름으로 덤프에서 `ParsedDoc`을 꺼낸다. `(doc, 경고문구)`.

    후보 이름은 **업로드 제목**과 **파일명(확장자 제외)** 둘뿐이다. 순서대로 정확히
    일치하는 것만 쓴다 — 부분 일치·접두 일치는 쓰지 않는다(§ docstring 안전장치 4).
    """
    root = dump_root()
    docs = _load(root)
    index = {_norm(key): key for key in docs}

    candidates = [c for c in (name, Path(pdf_path).stem) if c]
    for candidate in candidates:
        matched = index.get(_norm(candidate))
        if matched:
            doc = docs[matched]
            warning = (
                f"⚠ docling 모킹 모드 — 파일 내용이 아니라 덤프 `{matched}`를 적재했다 "
                f"(DOCLING_MOCK=1). 실제 파싱 결과가 아니다."
            )
            logger.warning(
                "docling 모킹 사용: 요청 '%s' → 덤프 '%s' (doc_id=%s, 요소 %d개)",
                candidates[0], matched, doc.doc_id, len(doc.elements),
            )
            return doc, warning

    raise MockDocumentNotFound(
        f"docling 모킹이 켜져 있는데 덤프에 맞는 문서가 없다 — 시도한 이름: {candidates}\n"
        f"  덤프 위치: {root}\n"
        f"  사용 가능한 이름({len(docs)}종): {', '.join(sorted(docs))}\n"
        "  업로드 제목이나 파일명을 위 이름 중 하나와 **정확히** 같게 맞출 것 "
        "(비슷한 이름으로 넘겨짚으면 다른 문서 내용이 적재된다)."
    )

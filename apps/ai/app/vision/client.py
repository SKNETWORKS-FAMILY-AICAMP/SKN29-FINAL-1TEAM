"""비전 모델 호출 공용 계층 — 이미지/PDF를 LLM에 넘기는 유일한 지점.

두 도구(`receipt`·`document`)가 입력 형태만 다르고 나머지는 같다: 이미지를 data URI로
만들어 structured output으로 받는다. 그 공통부를 여기 둔다.

**PDF도 이미지로 만든다.** 텍스트 레이어만 뽑으면 결재 도장·서명·손글씨 확인란처럼
"승인받았는가"를 판별하는 결정적 단서가 통째로 빠진다. 텍스트가 있는 PDF든 스캔본이든
같은 경로로 다루기 위해 페이지를 렌더한다(`pypdfium2` — docling이 이미 쓰는 백엔드).

⚠️ 비용: 페이지 수만큼 이미지 토큰이 붙는다. `MAX_PAGES`로 상한을 두고, 넘으면
**조용히 자르지 않고** 잘랐다는 사실을 결과 경고에 남긴다.
"""
from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 비전 지원 모델. Draft/Rule Agent와 따로 바꿔 끼울 수 있게 별도 env로 둔다.
#: 비전 판독 모델. **`gpt-4o-mini`로는 서식을 못 읽는다**(실측 2026-08-25):
#  「주류 포함: 예」를 false로, 참석 인원 「5명」을 58로 — 확신도 1.00으로 틀렸다.
#  같은 서식·같은 프롬프트를 `gpt-4o`로 돌리니 11/11 정확했다. 판독값은 곧 판정 사실이라
#  틀리면 조용히 잘못된 한도가 적용된다 — 여기서 아끼면 안 되는 자리다.
MODEL = os.environ.get("VISION_MODEL", "gpt-4o")
# 증빙 문서 한 건에서 읽을 최대 페이지. 사전승인·회의록은 보통 1~3장이다.
MAX_PAGES = int(os.environ.get("VISION_MAX_PAGES", "8"))
# 렌더 배율. 2.0이면 대략 144DPI — 도장·작은 표까지 읽히면서 토큰이 과하지 않은 지점.
RENDER_SCALE = float(os.environ.get("VISION_RENDER_SCALE", "2.0"))
TIMEOUT = 90

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
         ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp"}

_client = None


class VisionError(RuntimeError):
    """비전 판독 실패 — 폴백으로 덮지 않고 사유를 그대로 올린다."""


def _openai():
    """첫 호출 때 만든다 — 키가 없는 환경에서 import만으로 앱이 죽지 않게."""
    global _client
    if _client is None:
        from openai import OpenAI

        from app.config import settings

        if not settings.openai_api_key:
            raise VisionError("OPENAI_API_KEY 가 비어 있다 — 비전 판독을 할 수 없다.")
        _client = OpenAI(api_key=settings.openai_api_key)
    return _client


def _data_uri(raw: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(raw).decode()}"


def render_pdf(path: Path, max_pages: int = MAX_PAGES) -> tuple[list[str], list[str]]:
    """PDF → 페이지 이미지 data URI 목록. `(images, warnings)`."""
    import pypdfium2 as pdfium

    warnings: list[str] = []
    pdf = pdfium.PdfDocument(str(path))
    try:
        total = len(pdf)
        if total > max_pages:
            warnings.append(
                f"{total}쪽 중 앞 {max_pages}쪽만 판독했다 — 뒤쪽에 있는 내용은 반영되지 않았다."
            )
        images = []
        for index in range(min(total, max_pages)):
            bitmap = pdf[index].render(scale=RENDER_SCALE)
            buffer = bitmap.to_pil()
            from io import BytesIO

            out = BytesIO()
            buffer.save(out, format="PNG")
            images.append(_data_uri(out.getvalue(), "image/png"))
        return images, warnings
    finally:
        pdf.close()


def load_images(path: Path, max_pages: int = MAX_PAGES) -> tuple[list[str], list[str]]:
    """파일 → 비전에 넘길 이미지 목록. PDF는 페이지 렌더, 이미지는 그대로."""
    if not path.exists():
        raise VisionError(f"파일이 없습니다: {path}")
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return render_pdf(path, max_pages)
    if suffix in IMAGE_SUFFIXES:
        return [_data_uri(path.read_bytes(), _MIME.get(suffix, "image/jpeg"))], []
    raise VisionError(f"지원하지 않는 형식입니다: {path.name} (이미지 또는 PDF)")


def ask(system: str, instruction: str, images: list[str], schema: dict) -> dict[str, Any]:
    """이미지 + 지시 → structured output(dict).

    `strict` json_schema를 쓰는 이유는 Rule Agent에서와 같다 — 모델이 JSON을 손으로 짜게
    두면 문법 변종이 계속 나온다. 구조를 스키마로 못 박고 조립은 파이썬이 한다.
    """
    if not images:
        raise VisionError("판독할 이미지가 없습니다.")
    content: list[dict[str, Any]] = [{"type": "text", "text": instruction}]
    content += [{"type": "image_url", "image_url": {"url": uri}} for uri in images]

    try:
        resp = _openai().chat.completions.create(
            model=MODEL,
            temperature=0,          # 판독은 창작이 아니다 — 같은 이미지면 같은 결과여야 한다
            timeout=TIMEOUT,
            response_format={"type": "json_schema", "json_schema": schema},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
        )
    except Exception as exc:  # noqa: BLE001
        raise VisionError(f"비전 모델 호출 실패: {type(exc).__name__}: {exc}") from exc

    try:
        return json.loads(resp.choices[0].message.content)
    except (ValueError, TypeError, IndexError) as exc:
        raise VisionError(f"비전 응답을 해석하지 못했습니다: {exc}") from exc

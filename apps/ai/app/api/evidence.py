"""증빙 판독 REST — Django가 업로드 직후 부르는 진입점.

비전 도구(`app/vision/`)는 이미 있었지만 **MCP 도구로만** 노출돼 있었다. MCP는 LLM이
툴콜링 중 부르는 통로라, "파일이 올라오면 무조건 판독한다"처럼 **결정론적으로 항상
돌아야 하는 경로**에는 맞지 않는다(모델이 안 부르면 없는 것과 같다). 그래서 같은 함수를
REST로도 연다 — 구현은 공유하고 진입점만 둘이다.

종류에 따라 갈린다:
  · `RECEIPT`  → `read_receipt` (사용내역 + 판정 사실). 초안 화면이 금액·가맹점도 쓴다.
  · 그 외      → `read_evidence_document` (판정 사실만). 뽑을 항목이 정의되지 않은
                 종류(계약서·기타)는 LLM을 태우지 않고 `SKIPPED`로 돌려준다.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Body, HTTPException

from app.media import UnsafeMediaPath
from app.vision import document, receipt

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/extract-evidence")
def extract_evidence(payload: dict = Body(...)) -> dict:
    file_ref = str(payload.get("file_ref") or "").strip()
    kind = str(payload.get("kind") or "OTHER").upper()
    if not file_ref:
        raise HTTPException(status_code=400, detail="file_ref가 필요합니다.")

    try:
        if kind == "RECEIPT":
            result = receipt.read_receipt(file_ref)
            #  영수증 판독기는 `extraction_status`를 따로 내지 않는다(항상 판독을 시도한다).
            #  Django 저장 계약에 맞춰 여기서 채운다 — 호출부가 종류별로 분기하지 않게.
            result.setdefault("extraction_status", "DONE")
            result.setdefault("kind", kind)
            return result
        return document.read_evidence_document(file_ref, kind)
    except UnsafeMediaPath as exc:
        # 경로가 미디어 루트를 벗어났다 — 잘라내 열지 않고 사실대로 거부한다.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"파일을 찾을 수 없습니다: {file_ref}") from exc
    except Exception as exc:  # noqa: BLE001
        # 폴백으로 덮지 않는다 — 빈 결과를 200으로 돌려주면 Django가 "판독 완료, 사실 0건"
        # 으로 저장하고, 화면은 "확인했는데 없음"으로 읽는다(관측 계약이 깨진다).
        logger.exception("extract-evidence 실패 (%s, kind=%s)", file_ref, kind)
        raise HTTPException(status_code=502, detail=f"판독 실패: {exc}") from exc

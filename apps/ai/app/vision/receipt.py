"""① 영수증 판독 — 실물 사진·캡처·PDF 전표 → 사용내역 + 판정 사실 (FR-DA-02).

별도 OCR 엔진 없이 **비전 모델이 이미지에서 바로 필드를 뽑는다**(기술명세서 §2 확정).

## 왜 품목까지 읽는가

총액만으로는 판정할 수 없는 사실이 품목에 있다:
  · `dining.includes_alcohol` — 주류 품목이 있으면 회식 규정의 판단이 달라진다
  · `category.item_type`      — 식사/선물/경조사 구분은 청탁금지 한도 룩업 키다
그래서 이 도구는 "금액 읽기"가 아니라 **"판정에 쓸 사실 뽑기"** 다. 화면이 보여줄
사용내역(가맹점·금액·일시)과, 룰이 쓸 facts를 함께 낸다.

## 관측 계약 (증빙 추출 Agent와 동일)

facts는 **관측한 것만** 낸다. 영수증에 주류가 없다고 확인했으면 `false`를, 품목 자체가
안 보이면 **경로를 아예 내지 않는다**. 「확인했는데 없음」과 「안 보임」을 섞으면
미해소 가드가 잡아야 할 것을 놓친다(`_context/evidence-extraction-agent.md`).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app import media
from app.vision import client

logger = logging.getLogger(__name__)

EXTRACTOR_VERSION = "vision-receipt-1"

# 이 도구가 낼 수 있는 EvalContext 경로. 영수증에서 **실제로 보이는** 것만 둔다.
ALLOWED_FACT_PATHS = {
    "dining.includes_alcohol",      # 주류 품목 유무
    "category.item_type",           # 식사·선물·경조사 (청탁금지 한도 룩업 키)
    "tx.payment_time",              # 영수증 인쇄 시각
    "participants.participant_count",  # "인원 4" 같은 표기가 찍힌 경우만
}

ITEM_TYPES = ["식사", "선물", "경조사", "기타"]

_SYSTEM = """당신은 법인카드 영수증을 판독하는 보조입니다. 이미지에 **실제로 보이는 것만**
읽고, 보이지 않는 값은 지어내지 마세요.

규칙:
1. 금액은 숫자만(원 단위 정수). 통화기호·콤마 제거.
2. 날짜는 YYYY-MM-DD, 시각은 HH:MM(24시간). 안 보이면 빈 문자열.
3. 품목(line_items)은 영수증에 적힌 그대로 옮기세요. 품목 줄이 없으면 빈 배열.
4. facts는 **관측한 것만** 담습니다:
   - `dining.includes_alcohol`: 품목에 주류(맥주·소주·와인·양주 등)가 있으면 true,
     품목이 보이는데 주류가 없으면 false. **품목 자체가 안 보이면 이 항목을 넣지 마세요.**
   - `category.item_type`: 식사/선물/경조사 중 명확할 때만. 애매하면 넣지 마세요.
   - `tx.payment_time`: 영수증에 시각이 찍혀 있을 때만.
   - `participants.participant_count`: "인원 N", "N인" 표기가 있을 때만.
5. 읽기 어려운 부분은 warnings에 남기세요(찢어짐·흐림·잘림 등).
6. 반드시 지정된 JSON 형식으로만 답하세요."""

_SCHEMA = {
    "name": "receipt_reading",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "merchant": {"type": "string"},
            "amount": {"type": ["integer", "null"]},
            "date": {"type": "string"},
            "time": {"type": "string"},
            "payment_method": {"type": "string"},
            "approval_no": {"type": "string"},
            "line_items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "name": {"type": "string"},
                        "quantity": {"type": ["number", "null"]},
                        "unit_price": {"type": ["integer", "null"]},
                        "amount": {"type": ["integer", "null"]},
                        "is_alcohol": {"type": "boolean"},
                    },
                    "required": ["name", "quantity", "unit_price", "amount", "is_alcohol"],
                },
            },
            "totals": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "subtotal": {"type": ["integer", "null"]},
                    "vat": {"type": ["integer", "null"]},
                    "service_charge": {"type": ["integer", "null"]},
                    "total": {"type": ["integer", "null"]},
                },
                "required": ["subtotal", "vat", "service_charge", "total"],
            },
            # 관측한 사실만. 경로를 빼는 것이 "안 보였다"의 표현이다.
            "facts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "path": {"type": "string", "enum": sorted(ALLOWED_FACT_PATHS)},
                        "value_kind": {"type": "string", "enum": ["boolean", "number", "string"]},
                        "boolean": {"type": ["boolean", "null"]},
                        "number": {"type": ["number", "null"]},
                        "string": {"type": ["string", "null"]},
                        "confidence": {"type": "number"},
                        "quote": {"type": "string"},
                    },
                    "required": ["path", "value_kind", "boolean", "number", "string",
                                 "confidence", "quote"],
                },
            },
            "warnings": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["merchant", "amount", "date", "time", "payment_method", "approval_no",
                     "line_items", "totals", "facts", "warnings"],
    },
}


def _value_of(finding: dict) -> Any:
    return {"boolean": finding.get("boolean"),
            "number": finding.get("number"),
            "string": finding.get("string")}.get(finding.get("value_kind"))


def _collect_facts(findings: list[dict]) -> tuple[dict, dict, list, list]:
    """모델이 낸 관측 → `(extracted, field_confidence, evidence_spans, dropped)`.

    허용 목록 밖 경로·값 없는 항목은 **버리되 버렸다고 남긴다** — 조용히 사라지면
    "왜 이 사실이 안 잡혔지"를 나중에 되짚을 수 없다.
    """
    extracted, confidence, spans, dropped = {}, {}, [], []
    for finding in findings:
        path = finding.get("path", "")
        value = _value_of(finding)
        if path not in ALLOWED_FACT_PATHS or value is None:
            dropped.append(f"{path}={value!r}")
            continue
        if path == "category.item_type" and value not in ITEM_TYPES:
            dropped.append(f"{path}={value!r}(허용값 아님)")
            continue
        extracted[path] = value
        confidence[path] = float(finding.get("confidence") or 0.0)
        if finding.get("quote"):
            spans.append({"path": path, "quote": finding["quote"], "source": "receipt"})
    return extracted, confidence, spans, dropped


def read_receipt(file_ref: str) -> dict[str, Any]:
    """영수증 이미지·PDF에서 사용내역과 판정 사실을 뽑는다.

    `file_ref`는 media 볼륨 기준 상대경로(`Receipt.file_ref`·`Attachment.file_ref`).
    실패는 폴백으로 덮지 않고 사유를 그대로 돌려준다 — 초안이 조용히 빈 값으로 채워지면
    사용자가 "AI가 읽었다"고 믿고 그대로 제출한다.
    """
    path: Path = media.resolve(file_ref)
    images, warnings = client.load_images(path)
    raw = client.ask(_SYSTEM, "이 영수증을 판독해 주세요.", images, _SCHEMA)

    extracted, confidence, spans, dropped = _collect_facts(raw.get("facts") or [])
    warnings = [*warnings, *(raw.get("warnings") or [])]
    if dropped:
        warnings.append(f"허용되지 않은 추출 항목 {len(dropped)}건을 버렸다: {', '.join(dropped[:5])}")

    items = raw.get("line_items") or []
    logger.info(
        "read_receipt %s → merchant=%r amount=%s 품목 %d건 facts %d개",
        path.name, raw.get("merchant"), raw.get("amount"), len(items), len(extracted),
    )
    return {
        "file_ref": file_ref,
        # ── 사용내역 (화면·초안이 쓰는 값)
        "merchant": raw.get("merchant", ""),
        "amount": raw.get("amount"),
        "date": raw.get("date", ""),
        "time": raw.get("time", ""),
        "payment_method": raw.get("payment_method", ""),
        "approval_no": raw.get("approval_no", ""),
        "line_items": items,
        "totals": raw.get("totals") or {},
        # ── 판정 사실 (Attachment.extracted 계약과 같은 모양)
        "extracted": extracted,
        "field_confidence": confidence,
        "evidence_spans": spans,
        "extractor_version": EXTRACTOR_VERSION,
        "warnings": warnings,
    }

"""② 증빙 문서 판독 — 사전승인·회의록·참석자명단·출장계획서 PDF → 판정 사실.

`_context/evidence-extraction-agent.md`의 증빙자료 추출 Agent 본체. 판정에 필요한 사실의
상당수는 사람이 타이핑할 값이 아니라 **문서 안에 있다**(결재 도장, 회의록의 참석자 수,
출장계획서의 지역등급).

## 출력이 `Attachment` 필드와 같은 모양인 이유

`extracted`(dot-path→값)·`field_confidence`·`evidence_spans`는 **변환 없이 그대로 저장**된다.
조립기가 `apply_facts()`로 EvalContext에 얹으므로 중간 계층이 없다.

## 관측 계약 — 이 도구의 핵심

  · 경로가 **있으면** 관측한 것이다. 부재를 확인했으면 명시값(0/false)을 쓴다.
  · 경로가 **없으면** 관측하지 않은 것이다 → EvalContext에서 `None`으로 남고
    미해소 가드가 REVIEW로 강등한다.

그래서 스키마를 "선택적 키를 가진 객체"가 아니라 **관측 목록(array)** 으로 뒀다. 객체로 두면
모델이 빈칸을 채우려 들지만, 목록이면 **넣지 않는 것이 기본값**이 된다.

## 종류별로 뽑을 것을 좁히는 이유

회의록에서 출장 지역등급을 찾게 두면 없는 걸 지어낸다. `kind`별 허용 경로를 프롬프트와
후처리 양쪽에서 제한한다(캐논 §종류별 추출 대상).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app import media
from app.vision import client
from app.vision.uncertainty import is_uncertain

logger = logging.getLogger(__name__)

EXTRACTOR_VERSION = "vision-doc-1"

# 종류 → 뽑을 EvalContext 경로 (`evidence-extraction-agent.md` §종류별 추출 대상).
# 여기 없는 종류는 추출 대상이 아니다 — 계약서·기타는 판정 사실이 정해져 있지 않다.
TARGETS: dict[str, dict[str, str]] = {
    "PRE_APPROVAL": {
        "approval.pre_approval_obtained": "사전승인을 실제로 받았는가(결재 완료·승인 도장/서명 확인). 반려·미결이면 false",
    },
    "MEETING_MINUTES": {
        "participants.verified_participant_count": "참석자 총 인원수",
        "participants.verified_external_count": "외부(사외) 참석 인원수. 전원 내부면 0",
        "participants.has_kickback_law_target": "공직자·언론인·교직원 등 청탁금지법 대상이 포함됐는가",
    },
    "PARTICIPANT_LIST": {
        "participants.verified_participant_count": "명단에 오른 총 인원수",
        "participants.verified_external_count": "외부(사외) 인원수. 전원 내부면 0",
        "participants.has_kickback_law_target": "공직자·언론인·교직원 등 청탁금지법 대상이 포함됐는가",
    },
    "TRIP_PLAN": {
        "trip.trip_type": "출장 구분(국내/해외)",
        "trip.region_grade": "지역 등급 표기(가/나/다 또는 A/B/C 등 문서 표기 그대로)",
        "trip.lodging_amount_per_night": "1박당 숙박비(원 단위 정수)",
    },
    # RECEIPT은 여기 없다 — `app/api/evidence.py`·`app/api/lab.py` 둘 다 kind=="RECEIPT"를
    # `receipt.py::read_receipt`로 분기해 이 함수는 호출되지 않는다(별도 도구·별도 프롬프트).
}

# 숫자여야 하는 경로 — 모델이 "미정"·"?" 같은 자리표시자 문자열을 value_kind="string"으로
# 내면 여기서 걸러진다(실측: T04에서 지역등급·숙박비에 "?"/"미정" 문자열이 그대로 저장됨).
_NUMERIC_PATHS = {"trip.lodging_amount_per_night", "participants.verified_participant_count",
                  "participants.verified_external_count"}

_SYSTEM = """당신은 법인카드 정산 증빙 문서를 판독하는 보조입니다.
문서 이미지에 **실제로 보이는 근거만** 사용하고, 추측하지 마세요.

가장 중요한 규칙 — 「확인했는데 없음」과 「안 보임」을 구분합니다:
  · 문서에서 확인했고 해당 사실이 없으면 → 명시값(false, 0)으로 **담습니다**.
  · 문서에 그 항목에 대한 언급 자체가 없으면 → **findings에 넣지 마세요.**
    (모르는 것을 false로 적으면 시스템이 "확인됨"으로 오해합니다.)

그 외:
1. 아래 [뽑을 항목]에 있는 경로만 사용하세요. 목록에 없는 사실은 무시합니다.
2. 각 항목마다 근거가 된 문구를 quote에 원문 그대로 옮기세요. 근거를 못 대면 넣지 마세요.
3. confidence는 판독 확신도(0~1)입니다. 흐리거나 가려진 부분은 낮게 주세요.
4. 사전승인은 **결재가 완료됐는지**로 판단하세요.
   - 기안만 되어 있고 승인 흔적(도장·서명·승인일)이 전혀 없으면 false입니다.
   - **전결(단독 위임결재)도 완료로 인정합니다** — 결재선이 한 명뿐이고 그 한 명의
     도장·서명·전자서명 완료 표시가 있으면, 다단계 결재함이 전부 안 채워졌다는 이유로
     false 처리하지 마세요. "전자서명 완료" 같은 문구 자체가 승인 근거입니다.
   - 다단계 결재선인데 일부 단계만 승인되고 나머지가 대기/미결이면, **전체가 완료된 게
     아니므로** false입니다(일부 승인 ≠ 전체 승인).
5. 반드시 지정된 JSON 형식으로만 답하세요."""


def _schema(paths: list[str]) -> dict:
    return {
        "name": "evidence_extraction",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "path": {"type": "string", "enum": paths},
                            "value_kind": {"type": "string",
                                           "enum": ["boolean", "number", "string"]},
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
                "document_summary": {"type": "string"},
                "warnings": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["findings", "document_summary", "warnings"],
        },
    }


def _value_of(finding: dict) -> Any:
    return {"boolean": finding.get("boolean"),
            "number": finding.get("number"),
            "string": finding.get("string")}.get(finding.get("value_kind"))


def _collect(findings: list[dict], allowed: set[str]) -> tuple[dict, dict, list, list]:
    extracted, confidence, spans, dropped = {}, {}, [], []
    for finding in findings:
        path = finding.get("path", "")
        value = _value_of(finding)
        if path not in allowed or value is None:
            dropped.append(f"{path}={value!r}")
            continue
        # 근거 없는 추출은 받지 않는다 — 감사 때 "왜 그렇게 읽었나"를 되짚을 수 없다.
        quote = (finding.get("quote") or "").strip()
        if not quote:
            dropped.append(f"{path}(근거 문구 없음)")
            continue
        # 숫자여야 할 경로에 문자열 자리표시자("미정"·"?")가 들어오면 버린다 — 하류가
        # 숫자로 파싱을 시도하다 조용히 깨지거나, "미정"을 실제 값으로 오인한다.
        if path in _NUMERIC_PATHS and not isinstance(value, (int, float)):
            dropped.append(f"{path}={value!r}(숫자 아님)")
            continue
        # quote·문자열값이 스스로 "모른다"를 말하는데 값은 확정적으로 낸 자기모순 —
        # 모델이 프롬프트 지시(안 보이면 넣지 말라)를 안 지킨 경우의 방어선.
        string_value = value if isinstance(value, str) else None
        if is_uncertain(quote, string_value):
            dropped.append(f"{path}={value!r}(근거 문구가 불확실성을 표시함)")
            continue
        # 인원수는 정수여야 한다(모델이 4.0을 낼 수 있다).
        if path.endswith("_count") and isinstance(value, float):
            value = int(value)
        extracted[path] = value
        confidence[path] = float(finding.get("confidence") or 0.0)
        spans.append({"path": path, "quote": finding["quote"], "source": "document"})
    return extracted, confidence, spans, dropped


def read_evidence_document(file_ref: str, kind: str) -> dict[str, Any]:
    """증빙 문서에서 판정 사실을 뽑는다. 결과는 `Attachment` 필드에 그대로 저장 가능.

    `kind`가 추출 대상이 아니면(계약서·기타) 호출하지 않고 `SKIPPED`로 돌려준다 —
    뽑을 것이 정해지지 않은 문서에 LLM을 태우면 없는 사실을 지어낸다.
    """
    kind = (kind or "").upper()
    targets = TARGETS.get(kind)
    if not targets:
        return {
            "file_ref": file_ref, "kind": kind,
            "extraction_status": "SKIPPED",
            "extracted": {}, "field_confidence": {}, "evidence_spans": [],
            "extractor_version": EXTRACTOR_VERSION,
            "warnings": [f"`{kind}`는 추출 대상 종류가 아닙니다(뽑을 사실이 정의돼 있지 않음)."],
        }

    path: Path = media.resolve(file_ref)
    images, warnings = client.load_images(path)
    listing = "\n".join(f"- {p}: {desc}" for p, desc in targets.items())
    raw = client.ask(
        _SYSTEM,
        f"문서 종류: {kind}\n\n[뽑을 항목]\n{listing}\n\n위 항목만 판독해 주세요.",
        images,
        _schema(sorted(targets)),
    )

    extracted, confidence, spans, dropped = _collect(raw.get("findings") or [], set(targets))
    warnings = [*warnings, *(raw.get("warnings") or [])]
    if dropped:
        warnings.append(f"근거 부족·허용 밖 항목 {len(dropped)}건을 버렸다: {', '.join(dropped[:5])}")

    logger.info("read_evidence_document %s kind=%s → facts %d개", path.name, kind, len(extracted))
    return {
        "file_ref": file_ref,
        "kind": kind,
        "extraction_status": "DONE",
        "extracted": extracted,
        "field_confidence": confidence,
        "evidence_spans": spans,
        "document_summary": raw.get("document_summary", ""),
        "extractor_version": EXTRACTOR_VERSION,
        "warnings": warnings,
    }

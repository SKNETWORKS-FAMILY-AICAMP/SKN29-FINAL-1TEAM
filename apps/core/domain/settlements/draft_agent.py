"""초안 작성 Agent 플레이스홀더 (FR-DA-01~03).

실제 구현은 FastAPI(ai)의 Draft Agent — 영수증 비전 판독 + LLM 분류/사유 생성 — 이 담당한다.
여기서는 그 계약(요청·응답 셰이프)을 먼저 고정하고, **가맹점 업종 캐시·정책 임계값 같은 실제
데이터**로 그럴듯한 초안을 만들어 돌려준다. LLM 호출은 없다.

두 가지 모드:
- **생성**: 영수증/거래를 읽어 초안 필드를 채운다. (`instruction` 없음)
- **수정**: 자연어 지시로 기존 초안을 고친다. (`instruction` 있음)

두 모드 모두 ``comments``(AI 작업 로그)와 ``policyHints``(제출 전 규정 안내)를 함께 돌려주므로,
화면은 "AI가 무엇을 왜 채웠는지"를 그대로 보여줄 수 있다.
"""

from __future__ import annotations

import random
import re
from typing import Any

from domain.transactions.models import MerchantCategory

# 업종·가맹점명 키워드 → 비용분류 추론 (가맹점 업종 캐시가 없을 때의 폴백)
KEYWORD_CATEGORY = [
    (("호텔", "리조트", "스테이", "항공", "KTX", "코레일", "렌터카", "주유"), "출장", "숙박·교통"),
    (("한우", "일식", "룸", "다이닝", "라운지", "바"), "접대", "접대성 업소"),
    (("카페", "커피", "스타벅스", "투썸", "메가"), "회의", "카페·다과"),
    (("김밥", "백반", "국밥", "식당", "분식", "배달", "푸드"), "식대", "일반 식사"),
    (("문구", "오피스", "다이소", "쿠팡", "마트", "이마트", "전자"), "비품", "소모품·비품"),
    (("우체국", "등기", "택배", "인쇄", "복사"), "업무활성", "일반 업무비"),
]

# 규정 임계값 — 실제 운영에서는 policy 테이블에서 읽는다.
THRESHOLDS = {
    "receipt": (30000, "TIGER-REG-2026-003 제11조②", "3만원을 초과하면 적격증빙(세금계산서·카드전표)이 필요합니다."),
    "preapproval": (500000, "TIGER-REG-2026-003 제12조①", "건당 50만원을 초과하면 사전승인 기록이 필요합니다."),
    "dining_per_person": (50000, "TIGER-REG-2026-003 제14조①", "회식비는 참석자 1인당 5만원을 넘을 수 없습니다."),
}

PURPOSE_TEMPLATE = {
    "접대": "{merchant} — 거래처 {counterpart} 미팅 후 식사 (참석 {headcount}명: 내부 {inside}명 / 외부 {outside}명)",
    "회의": "{merchant} — {topic} 회의 다과 (참석 {headcount}명)",
    "식대": "{merchant} — {topic} 관련 팀 식대 (참석 {headcount}명)",
    "출장": "{merchant} — {region} 출장 {expense_kind}",
    "비품": "{merchant} — {topic} 용도 소모품 구매",
    "업무활성": "{merchant} — {topic} 관련 일반 업무비",
}


def _clean_amount(value: Any) -> int:
    return int(re.sub(r"[^0-9]", "", str(value or "0")) or 0)


def _industry_of(merchant: str) -> str:
    """가맹점 업종 캐시(실데이터) 조회 → 없으면 빈 문자열."""
    if not merchant:
        return ""
    hit = MerchantCategory.objects.filter(normalized_name__in=[merchant, merchant.split()[0]]).first()
    if hit:
        return hit.industry_label
    for row in MerchantCategory.objects.all()[:200]:
        if row.normalized_name and row.normalized_name in merchant:
            return row.industry_label
    return ""


def _guess_category(merchant: str, industry: str) -> tuple[str, float, str]:
    """(분류, 신뢰도, 근거) — 업종 캐시를 우선 쓰고 키워드로 보완한다."""
    haystack = f"{merchant} {industry}"
    for keywords, category, label in KEYWORD_CATEGORY:
        if any(word in haystack for word in keywords):
            confidence = 0.93 if industry else 0.78
            source = f"가맹점 업종 '{industry}'" if industry else f"가맹점명 키워드"
            return category, confidence, f"{source} 기준 {label}로 판단해 '{category}'로 분류했습니다."
    return "업무활성", 0.52, "업종·가맹점명으로 분류를 특정하지 못해 기본값으로 두었습니다. 직접 확인해주세요."


def _policy_hints(category: str, amount: int, has_receipt: bool, headcount: int) -> list[dict[str, Any]]:
    """제출 전 규정 안내 — 반려를 미리 막기 위한 사전 힌트."""
    hints: list[dict[str, Any]] = []
    limit, clause, text = THRESHOLDS["receipt"]
    if amount > limit:
        hints.append({
            "level": "warn" if not has_receipt else "info", "clause": clause, "text": text,
            "status": "증빙 첨부됨" if has_receipt else "증빙 미첨부 — 지금 첨부하면 보완요청을 피할 수 있습니다.",
        })
    limit, clause, text = THRESHOLDS["preapproval"]
    if amount > limit:
        hints.append({"level": "warn", "clause": clause, "text": text,
                      "status": "사전승인 문서를 함께 첨부해주세요."})
    if category in ("식대", "접대") and headcount:
        limit, clause, text = THRESHOLDS["dining_per_person"]
        per_person = amount // max(headcount, 1)
        hints.append({
            "level": "warn" if per_person > limit else "info", "clause": clause, "text": text,
            "status": f"1인당 {per_person:,}원 (참석 {headcount}명) — "
                      + ("한도 초과" if per_person > limit else "한도 이내"),
        })
    if category == "접대":
        hints.append({"level": "info", "clause": "TIGER-REG-2026-003 제11조④",
                      "text": "접대성 지출은 참석자 명단·목적이 함께 기록돼야 업무관련성을 인정받습니다.",
                      "status": "참석자 정보를 사유에 포함했는지 확인해주세요."})
    return hints


def suggest_draft(payload: dict[str, Any]) -> dict[str, Any]:
    """영수증·거래 정보로 정산 초안을 만든다(생성 모드)."""
    rng = random.Random(str(payload.get("merchant", "")) + str(payload.get("amount", "")))
    merchant = str(payload.get("merchant") or "").strip() or _sample_merchant(rng)
    amount = _clean_amount(payload.get("amount")) or rng.choice([18000, 42000, 68000, 132000, 264000])
    industry = str(payload.get("merchantIndustry") or "") or _industry_of(merchant)
    category, confidence, reason = _guess_category(merchant, industry)
    headcount = int(payload.get("headcount") or (rng.randint(3, 8) if category in ("식대", "접대", "회의") else 0))
    has_receipt = str(payload.get("evidence", "OK")) == "OK"

    purpose = PURPOSE_TEMPLATE.get(category, "{merchant} — 업무 관련 지출").format(
        merchant=merchant,
        counterpart=rng.choice(["A사", "B물산", "C테크"]),
        headcount=headcount or 1,
        inside=max(headcount - 2, 1), outside=min(2, headcount),
        topic=rng.choice(["주간 스프린트", "분기 실적 리뷰", "신규 제안", "결산 마감"]),
        region=rng.choice(["대전", "부산", "광주", "제주"]),
        expense_kind=rng.choice(["숙박비", "교통비", "식대"]),
    )

    return {
        "mode": "create",
        "draft": {
            "merchant": merchant, "amount": amount, "category": category, "aiCategory": category,
            "aiSuggested": True, "merchantIndustry": industry, "purpose": purpose,
            "evidence": "OK" if has_receipt else "MISSING", "headcount": headcount,
        },
        "confidence": round(confidence, 2),
        "comments": [
            {"icon": "ocr", "text": f"영수증 판독 — 가맹점 “{merchant}” · 금액 {amount:,}원 · "
                                    f"결제일 {payload.get('date') or '자동 인식'}을 읽었습니다."},
            {"icon": "ai", "text": reason},
            {"icon": "doc", "text": f"지출 목적 초안을 작성했습니다. 참석자·안건 등 실제 내용에 맞게 수정해주세요."},
        ],
        "policyHints": _policy_hints(category, amount, has_receipt, headcount),
        "placeholder": True,
    }


# 자연어 지시 → 초안 필드 패치 규칙 (Draft Agent 수정 모드의 계약 예시)
_AMOUNT = re.compile(r"([\d,]+)\s*(만원|원)")
_HEADCOUNT = re.compile(r"(?:참석|인원)\s*([\d]+)\s*명")
_CATEGORIES = ("접대", "회의", "식대", "출장", "비품", "업무활성")


def revise_draft(payload: dict[str, Any]) -> dict[str, Any]:
    """자연어 지시로 초안을 수정한다(수정 모드)."""
    instruction = str(payload.get("instruction", "")).strip()
    current = dict(payload.get("current") or {})
    changes: list[str] = []

    hit = _AMOUNT.search(instruction)
    if hit:
        value = int(hit.group(1).replace(",", "")) * (10000 if hit.group(2) == "만원" else 1)
        current["amount"] = value
        changes.append(f"금액 → {value:,}원")

    for category in _CATEGORIES:
        if category in instruction:
            current["category"] = current["aiCategory"] = category
            changes.append(f"비용분류 → {category}")
            break

    hit = _HEADCOUNT.search(instruction)
    if hit:
        current["headcount"] = int(hit.group(1))
        changes.append(f"참석 인원 → {hit.group(1)}명")

    if re.search(r"증빙.*(없|누락|미첨부)", instruction):
        current["evidence"] = "MISSING"
        changes.append("증빙 → 미첨부")
    elif "증빙" in instruction:
        current["evidence"] = "OK"
        changes.append("증빙 → 첨부됨")

    if re.search(r"(사유|목적).*(다시|자세|보강|구체)", instruction) or "사유 써" in instruction:
        base = current.get("purpose") or ""
        current["purpose"] = (base + " · 업무 관련성: 계약 협의 목적, 결과는 별도 회의록 참조").strip(" ·")
        changes.append("지출 목적 보강")
    elif "목적" in instruction or "사유" in instruction:
        cleaned = re.sub(r"^(사유|목적)[은는를]?\s*", "", instruction).strip()
        if cleaned:
            current["purpose"] = cleaned
            changes.append("지출 목적 직접 반영")

    amount = _clean_amount(current.get("amount"))
    category = str(current.get("category") or "업무활성")
    headcount = int(current.get("headcount") or 0)
    has_receipt = str(current.get("evidence", "OK")) == "OK"

    if changes:
        text = "지시를 반영했습니다.\n" + "\n".join(f"· {c}" for c in changes)
    else:
        text = ("아직 해석하지 못한 지시입니다. 예) “금액 12만원으로 바꿔줘”, “분류는 접대로”, "
                "“참석 6명으로”, “증빙 누락으로 표시”, “사유 더 자세히”")

    return {
        "mode": "revise",
        "draft": current,
        "changes": changes,
        "comments": [{"icon": "ai", "text": text}],
        "policyHints": _policy_hints(category, amount, has_receipt, headcount),
        "placeholder": True,
    }


def _sample_merchant(rng: random.Random) -> str:
    known = list(MerchantCategory.objects.values_list("normalized_name", flat=True)[:20])
    return rng.choice(known) if known else "스타벅스 강남점"

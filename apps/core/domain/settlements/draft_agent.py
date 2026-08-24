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

from domain.settlements.models import Category
from domain.transactions import industry as industry_vocab
from domain.transactions.models import MerchantCategory

# 업종·가맹점명 키워드 → 비용분류 추론 (가맹점 업종 캐시가 없을 때의 폴백)
#  [2026-08-14] "업무활성"(캐치올) 폐지 → 비품(SUPPLIES)으로 흡수. "회식"은 새 독립 카테고리라
#  회식성 업소(포차·호프·노래방 등, 식당/카페 키워드와 겹치지 않는 것 위주) 키워드를 추가했다.
#  [2026-08-22] 업무활성 폐지 때 비품이 떠안았던 캐치올(우체국·택배·인쇄)을 `기타`로 옮겼다.
#  [2026-08-24] **「비품」 과목 자체가 폐기**됐다(과목을 회식·회의·식대·출장·접대 다섯으로
#  단순화). 소모품·사무용품 키워드도 `기타`로 간다 — 나열된 다섯 어디에도 안 맞는 지출이다.
KEYWORD_CATEGORY = [
    (("호텔", "리조트", "스테이", "항공", "KTX", "코레일", "렌터카", "주유"), "출장", "숙박·교통"),
    (("한우", "일식", "룸", "다이닝", "라운지", "바"), "접대", "접대성 업소"),
    (("포차", "호프", "노래방", "코인노래"), "회식", "회식성 업소"),
    (("카페", "커피", "스타벅스", "투썸", "메가"), "회의", "카페·다과"),
    (("김밥", "백반", "국밥", "식당", "분식", "배달", "푸드"), "식대", "일반 식사"),
    (("문구", "오피스", "다이소", "쿠팡", "마트", "이마트", "전자"), "기타", "소모품·비품"),
    (("우체국", "등기", "택배", "인쇄", "복사"), "기타", "일반 업무비"),
]

# 규정 임계값은 **별표(PolicyTable)에서 읽는다** — 여기에 숫자를 두지 않는다.
#  (`_context/policy-domain.md` §4 — 임계값이 여러 곳에 흩어져 값이 갈라진 것이 이 도메인의 원인 결함)
#  안내 문구만 여기서 관리하고, 숫자는 표에서 읽어 문구에 끼워 넣는다.
HINT_SPECS = {
    "receipt": ("evidence_threshold_table",
                "{limit:,}원을 초과하면 적격증빙(세금계산서·카드전표)이 필요합니다."),
    "preapproval": ("pre_approval_threshold_table",
                    "건당 {limit:,}원을 초과하면 사전승인 기록이 필요합니다."),
    "dining_per_person": ("dining_per_person_limit_table",
                          "회식비는 참석자 1인당 {limit:,}원을 넘을 수 없습니다."),
}

PURPOSE_TEMPLATE = {
    "접대": "{merchant} — 거래처 {counterpart} 미팅 후 식사 (참석 {headcount}명: 내부 {inside}명 / 외부 {outside}명)",
    "회의": "{merchant} — {topic} 회의 다과 (참석 {headcount}명)",
    "식대": "{merchant} — {topic} 관련 팀 식대 (참석 {headcount}명)",
    "출장": "{merchant} — {region} 출장 {expense_kind}",
    "회식": "{merchant} — {topic} 팀 회식 (참석 {headcount}명)",
    "기타": "{merchant} — 업무 관련 지출",
}


def _clean_amount(value: Any) -> int:
    return int(re.sub(r"[^0-9]", "", str(value or "0")) or 0)


# 지점명·법인 표기 제거 — ai(`app/merchant/classify.normalize`)와 **같은 규칙**이어야 한다.
#  캐시 키는 그쪽이 정규화해서 넣으므로, 여기서 원문으로 찾으면 "(주)한우명가 본점" 같은
#  표기가 영원히 미스가 된다(예전 결함).
_CORP_PREFIX = re.compile(r"\(주\)|㈜")
_STRIP_CHARS = re.compile(r"[()（）※]")
_BRANCH_SUFFIX = re.compile(r"^(.+\S)\s+\S*(?:점|지점|본점|직영점)$")


def _normalize_merchant(name: str) -> str:
    n = _CORP_PREFIX.sub("", name or "")
    n = _STRIP_CHARS.sub(" ", n)
    n = re.sub(r"\s+", " ", n).strip()
    m = _BRANCH_SUFFIX.match(n)
    return (m.group(1) if m else n).strip()


def _industry_of(merchant: str) -> tuple[str, str]:
    """가맹점 업종 캐시(실데이터) 조회 → 정본 `(code, label)`. 없으면 `("", "")`.

    이 폴백은 ai가 죽었을 때만 도는 경로라 카카오·LLM은 부르지 않는다(캐시만 본다).
    """
    if not merchant:
        return ("", "")
    keys = [merchant, _normalize_merchant(merchant)]
    hit = MerchantCategory.objects.filter(normalized_name__in=[k for k in keys if k]).first()
    if hit is None:
        for row in MerchantCategory.objects.all()[:200]:
            if row.normalized_name and row.normalized_name in merchant:
                hit = row
                break
    if hit is None:
        return ("", "")
    return industry_vocab.resolve(hit.industry_code or hit.industry_label)


def _guess_category(merchant: str, industry: str) -> tuple[str, float, str]:
    """(분류, 신뢰도, 근거) — 업종 캐시를 우선 쓰고 키워드로 보완한다.

    **못 정하면 빈 값을 돌려준다.** 예전엔 `비품`(구 캐치올 잔재)으로 밀었는데, 그러면
    확인하지 않은 건이 실제 과목의 예산·룰 집계에 섞이고 사람은 "AI가 정했다"고 믿는다.
    빈 값이면 기본 게이트가 `CATEGORY_MISSING`으로 잡아 검토로 보내고, 화면은 「선택 필요」로
    표시해 사람이 직접 고르게 한다. `기타`로 밀지 않는 것도 같은 이유다 — `기타`는
    "6개 중 어디에도 안 맞는다"는 **확정**이지 "모른다"가 아니다.
    """
    haystack = f"{merchant} {industry}"
    for keywords, category, label in KEYWORD_CATEGORY:
        if any(word in haystack for word in keywords):
            confidence = 0.93 if industry else 0.78
            source = f"가맹점 업종 '{industry}'" if industry else f"가맹점명 키워드"
            return category, confidence, f"{source} 기준 {label}로 판단해 '{category}'로 분류했습니다."
    return "", 0.0, "업종·가맹점명으로 비용분류를 특정하지 못했습니다 — 직접 골라주세요."


def _resolve_hint_limits(category: str) -> dict[str, tuple[int, str, str]]:
    """별표에서 안내용 임계값을 읽는다 — (한도, 근거조항, 문구).

    표가 없거나 값을 못 찾으면 그 항목을 **생략**한다. 숫자를 지어내 안내하지 않는다.
    """
    from domain.policies.context_builder import load_tables, lookup
    from domain.policies.eval_context import empty_eval_context

    tables = load_tables()
    ctx = empty_eval_context()
    ctx["category"]["value"] = category
    ctx["category"]["scope"] = category

    resolved: dict[str, tuple[int, str, str]] = {}
    for name, (table_key, template) in HINT_SPECS.items():
        table = tables.get(table_key)
        limit = lookup(table, ctx) if table else None
        if isinstance(limit, (int, float)):
            resolved[name] = (int(limit), table.source_clause, template.format(limit=int(limit)))
    return resolved


def _policy_hints(category: str, amount: int, has_receipt: bool, headcount: int) -> list[dict[str, Any]]:
    """제출 전 규정 안내 — 반려를 미리 막기 위한 사전 힌트."""
    hints: list[dict[str, Any]] = []
    limits = _resolve_hint_limits(category)

    if "receipt" in limits:
        limit, clause, text = limits["receipt"]
        if amount > limit:
            hints.append({
                "level": "warn" if not has_receipt else "info", "clause": clause, "text": text,
                "status": "증빙 첨부됨" if has_receipt else "증빙 미첨부 — 지금 첨부하면 보완요청을 피할 수 있습니다.",
            })
    if "preapproval" in limits:
        limit, clause, text = limits["preapproval"]
        if amount > limit:
            hints.append({"level": "warn", "clause": clause, "text": text,
                          "status": "사전승인 문서를 함께 첨부해주세요."})
    if category in ("식대", "접대") and headcount and "dining_per_person" in limits:
        limit, clause, text = limits["dining_per_person"]
        per_person = amount // max(headcount, 1)
        hints.append({
            "level": "warn" if per_person > limit else "info", "clause": clause, "text": text,
            "status": f"1인당 {per_person:,}원 (참석 {headcount}명) — "
                      + ("한도 초과" if per_person > limit else "한도 이내"),
        })
    if category == "접대":
        hints.append({"level": "info", "clause": "법인카드 사용 규정 제11조④",
                      "text": "접대성 지출은 참석자 명단·목적이 함께 기록돼야 업무관련성을 인정받습니다.",
                      "status": "참석자 정보를 사유에 포함했는지 확인해주세요."})
    return hints


def suggest_draft(payload: dict[str, Any]) -> dict[str, Any]:
    """영수증·거래 정보로 정산 초안을 만든다(생성 모드)."""
    rng = random.Random(str(payload.get("merchant", "")) + str(payload.get("amount", "")))
    merchant = str(payload.get("merchant") or "").strip() or _sample_merchant(rng)
    amount = _clean_amount(payload.get("amount")) or rng.choice([18000, 42000, 68000, 132000, 264000])
    industry_code, industry = industry_vocab.resolve(payload.get("merchantIndustry"))
    if not industry:
        industry_code, industry = _industry_of(merchant)
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
            "aiSuggested": True, "merchantIndustry": industry, "merchantIndustryCode": industry_code,
            "purpose": purpose,
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
#  자연어 지시에서 찾을 분류 어휘. 정본(`Category`)에서 받아 온다 — 여기에 손으로 적어
#  두면 분류가 늘어날 때 "지시는 했는데 안 바뀐다"가 조용히 생긴다.
_CATEGORIES = tuple(Category.values)


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
    category = str(current.get("category") or "비품")
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

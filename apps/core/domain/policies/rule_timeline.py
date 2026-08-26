"""활성 룰 그래프의 **도입 타임라인** — 회계가 규칙을 쌓아 온 기록.

## 무엇을 담나

도입 직후에는 제품이 그 회사 규정을 모르므로 **거의 모든 건이 검토로 간다**. 회계가
자사 규정을 올려 룰을 만들수록 확정 비율이 오르고 검토가 준다 — 그게 도입 진척도다
([[rule-engine-semantics]] §3).

이 모듈은 그 진척을 **실제 그래프 버전의 연속**으로 정의한다. 각 단계는 그 시점에
활성이던 룰 전체(게이트 + 과목별)이고, `seed_adopted`가 이 순서대로 `activated_at`을
찍어 심는다 — 룰 콘솔의 버전 이력이 곧 도입 서사가 된다.

## 게이트는 화이트리스트다

**「위반에 안 걸렸으니 통과」는 디폴트 PASS다.** 규칙이 보지 않은 것은 「문제없음」이
아니라 「모름」이고, 모름은 검토다. 그래서 모든 게이트 버전이 **자동 통과 요건을 명시한
화이트리스트 종단**으로 끝난다 — 요건을 하나라도 못 채우면 검토로 간다.

실측(2026-08-25): 블랙리스트 게이트를 쓰던 동안 **판정 182건 중 122건(67%)이
「위반 못 찾음 → 승인대기」**로 확정되고 있었다.
"""
from __future__ import annotations

from typing import Any

REG_CARD = "법인카드 사용 규정"
REG_ENT = "업무추진비 사용 규정"
REG_DINE = "회식 운영규정"
REG_TRIP = "출장비 사용 규정"


def plain_text(when: str, then: str) -> str:
    """쉽게보기 문장 — 조건식을 읽을 수 없는 사람이 판단 근거를 확인하는 자리."""
    parts = []
    if when:
        parts.append(f"**이럴 때**  {when}")
    if then:
        parts.append(f"**이렇게 합니다**  {then}")
    return (chr(10) * 2).join(parts)


def node(key: str, title: str, condition: Any, decision: str, description: str,
         priority: int, *, status: str = "ACTIVE", clause: str = "",
         when: str = "", then: str = "", **extra: Any) -> dict[str, Any]:
    """룰 노드 1개. **`RuleNode` 필드 모양과 같아야 한다**(`seed_rules.node`와 동일 계약).

    제목·설명·조항은 `action` 안에 들어간다 — 모델에 그 이름의 컬럼이 없다.
    """
    return {
        "node_key": key,
        "condition": condition,
        "condition_text": plain_text(when, then) if (when or then) else "",
        "action": {
            "decision": decision,
            "title": title,
            "description": description,
            "source_clause": clause,
            "workflow_status": status,
            "origin": "existing",
            **extra,
        },
        "priority": priority,
    }


def branch(from_key: str, match_to: str = "", no_match_to: str = "") -> list[dict]:
    """MATCH/NO_MATCH 이진 분기. 빈 문자열은 단말(그 노드의 액션으로 종결)."""
    return [
        {"from_node_key": from_key, "on_result": "MATCH", "to_node_key": match_to, "priority": 0},
        {"from_node_key": from_key, "on_result": "NO_MATCH", "to_node_key": no_match_to, "priority": 1},
    ]


def chain(keys: list[str], tail: str = "") -> list[dict]:
    """위반 노드들을 일렬로 잇는다 — MATCH면 그 자리에서 종결, 아니면 다음."""
    out: list[dict] = []
    for i, key in enumerate(keys):
        nxt = keys[i + 1] if i + 1 < len(keys) else tail
        out += branch(key, "", nxt)
    return out


# ════════════════════════════════════════════════════════════════
#  공통 게이트 — 위반 검사 → **화이트리스트 종단**
# ════════════════════════════════════════════════════════════════

G_FORBIDDEN = node(
    "G-01", "금지업종 결제", {"==": [{"var": "merchant.forbidden"}, True]},
    "RETURN", "주점·유흥·노래연습장·사행성 업종은 법인카드 사용이 금지됩니다.", 0,
    clause=f"{REG_CARD} 제9조 2호", severity="CRITICAL", flag="PROHIBITED_MERCHANT",
    when="결제한 가맹점이 규정에서 금지한 업종일 때",
    then="쓴 사람에게 돌려보냅니다. 업종 자체가 금지라 금액과 무관합니다.",
)
G_VOUCHER = node(
    "G-02", "현금성 자산 구매", {"==": [{"var": "category.item_type"}, "상품권"]},
    "RETURN", "상품권 등 유가증권은 법인카드로 구매할 수 없습니다.", 1,
    clause=f"{REG_CARD} 제9조 3호", severity="HIGH", flag="CASH_EQUIVALENT",
    when="상품권처럼 현금과 같은 것을 샀을 때",
    then="쓴 사람에게 돌려보냅니다. 현금성 자산은 용도를 추적할 수 없어 금지입니다.",
)
G_ACTUAL_USER_UNKNOWN = node(
    "G-03", "실사용자 확인 불가", {"is_null": {"var": "card.actual_user_recorded"}},
    "REVIEW", "공용·팀 카드인데 실사용자 기록 여부를 알 수 없습니다.", 2,
    clause=f"{REG_CARD} 제7조③", severity="LOW", flag="ACTUAL_USER_UNKNOWN",
    when="공용카드인지 아닌지, 실사용자를 적었는지조차 알 수 없을 때",
    then="모르는 것을 통과시키지 않고 사람에게 넘깁니다.",
)
G_ACTUAL_USER = node(
    "G-04", "공용카드 실사용자 미기재",
    {"==": [{"var": "card.actual_user_recorded"}, False]},
    "RETURN", "공용·팀 카드는 실제로 쓴 사람을 기록해야 합니다.", 3,
    clause=f"{REG_CARD} 제7조③", severity="MEDIUM", flag="ACTUAL_USER_REQUIRED",
    when="여러 사람이 쓰는 카드인데 이번에 누가 썼는지 안 적혀 있을 때",
    then="쓴 사람에게 실사용자를 채워 달라고 돌려보냅니다.",
)
G_EVIDENCE = node(
    "G-05", "적격증빙 없음", {"==": [{"var": "evidence.has_valid_receipt"}, False]},
    "RETURN", "적격증빙(카드매출전표·세금계산서)이 첨부되지 않았습니다.", 4,
    clause=f"{REG_CARD} 제11조", severity="HIGH", flag="EVIDENCE_MISSING",
    when="영수증·전표 같은 정식 증빙이 없을 때",
    then="쓴 사람에게 증빙을 붙여 달라고 돌려보냅니다. 없으면 비용으로 인정받지 못합니다.",
)

#: **화이트리스트 종단.** 요건을 전부 만족해야 `PASS`, 하나라도 어긋나면 `REVIEW`.
#  ⛔ 「위반에 안 걸렸으니 PASS」로 바꾸면 그 순간 디폴트 승인대기가 된다.
def gate_pass(extra: list[Any] | None = None, note: str = "") -> dict[str, Any]:
    requirements = [
        {"==": [{"var": "evidence.has_valid_receipt"}, True]},
        {"==": [{"var": "evidence.expense_purpose_missing"}, False]},
        {"not": {"is_null": {"var": "category.value"}}},
        {"==": [{"var": "merchant.merchant_info_resolved"}, True]},
        {"==": [{"var": "merchant.forbidden"}, False]},
        {"==": [{"var": "card.actual_user_recorded"}, True]},
        *(extra or []),
    ]
    return node(
        "G-PASS", "자동 통과 요건", {"and": requirements},
        "PASS", "자동 통과 요건을 모두 만족한 건입니다." + (f" {note}" if note else ""), 9,
        clause=f"{REG_CARD} 제5조", severity="INFO", flag="",
        when="증빙·목적·분류·업종확인·실사용자를 모두 갖췄을 때" + (f" ({note})" if note else ""),
        then="규정상 승인해도 되는 건으로 봅니다. 회계 담당자의 확정만 남습니다. "
             "요건을 하나라도 못 채우면 통과시키지 않고 검토로 넘깁니다.",
    )


GATE_NODES = [G_FORBIDDEN, G_VOUCHER, G_ACTUAL_USER_UNKNOWN, G_ACTUAL_USER, G_EVIDENCE]
GATE_KEYS = [n["node_key"] for n in GATE_NODES]


#: 화이트리스트를 **못 채운** 건이 가는 자리.
#
#  ⚠️ 이 노드가 없으면 화이트리스트가 무력해진다. 엔진은 다음 노드가 없을 때 「조건이
#  맞았는가」와 무관하게 **그 노드의 액션**을 돌려주므로, `G-PASS`(액션 PASS)를 단말로
#  두면 요건을 못 채운 건까지 `PASS`가 된다(실측 2026-08-25: 상한을 3만으로 좁혀도
#  자동처리율이 100% 그대로였다). NO_MATCH를 여기로 보내야 검토로 간다.
G_REVIEW = node(
    "G-REVIEW", "자동 통과 요건 미충족", True,
    "REVIEW", "자동 통과 요건을 만족하지 못해 사람이 확인합니다.", 10,
    clause=f"{REG_CARD} 제5조", severity="LOW", flag="AUTO_PASS_NOT_MET",
    when="자동 통과 요건 중 하나라도 못 채웠을 때",
    then="회계 담당자가 직접 봅니다. **잘못됐다는 뜻이 아니라** 규칙만으로 승인 결정을 "
         "내리기에는 근거가 부족하다는 뜻입니다.",
)


def gate(*, extra_requirements: list[Any] | None = None, note: str = "",
         nodes: list[dict] | None = None, keys: list[str] | None = None) -> dict[str, Any]:
    body = nodes if nodes is not None else GATE_NODES
    order = keys if keys is not None else GATE_KEYS
    terminal = gate_pass(extra_requirements, note)
    return {
        "entry": order[0],
        "nodes": [*body, terminal, G_REVIEW],
        #  요건 충족(MATCH) → 단말(PASS) / 미충족(NO_MATCH) → G-REVIEW
        "routings": [*chain(order, "G-PASS"), *branch("G-PASS", "", "G-REVIEW")],
    }


# ════════════════════════════════════════════════════════════════
#  과목별 그래프 — tiger_inc 규정 반영
# ════════════════════════════════════════════════════════════════

def scope_pass(key: str, label: str) -> dict[str, Any]:
    return node(
        f"{key}-PASS", f"{label} 검증 통과", True, "PASS",
        f"{label} 세부 규정에 걸리는 조건이 없는 건입니다.", 9,
        severity="INFO", flag="",
        #  `condition: True`라 항상 MATCH — 위 함정(NO_MATCH 단말)에 걸리지 않는다.
        when="앞의 세부 점검에 하나도 걸리지 않았을 때",
        then="이 과목의 규정상 문제없는 지출로 봅니다. 회계 확정만 남습니다.",
    )


#  ── 접대(업무추진비) ────────────────────────────────────────────
E_EVIDENCE = node(
    "E-01", "기준액 초과 적격증빙 없음",
    {"and": [{">": [{"var": "tx.amount"}, {"var": "policy.evidence_threshold"}]},
             {"==": [{"var": "evidence.has_valid_receipt"}, False]}]},
    "RETURN", "적격증빙 기준액을 넘는 업무추진비인데 증빙이 없습니다.", 0,
    clause=f"{REG_ENT} 제11조②", severity="HIGH", flag="NON_DEDUCTIBLE_RISK",
    when="접대비를 기준액(3만원) 넘게 썼는데 정식 증빙이 없을 때",
    then="쓴 사람에게 돌려보냅니다. 증빙이 없으면 전액 손금불산입 대상입니다.",
)
E_PREAPPROVAL = node(
    "E-02", "사전승인 기준액 초과 · 승인 없음",
    {"and": [{">": [{"var": "tx.amount"}, {"var": "policy.preapproval_threshold"}]},
             {"==": [{"var": "approval.pre_approval_obtained"}, False]}]},
    "RETURN", "사전승인 기준 금액을 넘겼는데 승인 기록이 없습니다.", 1,
    clause=f"{REG_ENT} 제12조①", severity="HIGH", flag="PRE_APPROVAL_MISSING",
    when="사전승인이 필요한 금액을 넘겼는데 미리 받은 승인이 없을 때",
    then="쓴 사람에게 돌려보냅니다. 사전승인 문서를 붙이거나 사후 승인을 받으면 됩니다.",
)
E_KICKBACK = node(
    "E-03", "청탁금지법 대상자 · 1인당 한도 초과",
    {"and": [{"==": [{"var": "participants.has_kickback_law_target"}, True]},
             {">": [{"var": "tx.verified_per_person_amount"},
                    {"var": "policy.kickback_limit"}]}]},
    #  **여기만 `REVIEW`다.** 한도 초과 자체는 규칙으로 확정할 수 있지만, 법 위반 소지가
    #  있는 건을 자동 반려하면 되돌릴 방법이 없고 자동 승인하면 회사가 책임을 진다.
    #  **둘 다 위험한 자리는 규칙이 결론을 내지 않는다** — 그게 검토의 본래 쓰임이다.
    "REVIEW", "청탁금지법 대상자가 참석했고 1인당 금액이 법정 한도를 넘었습니다.", 2,
    clause=f"{REG_ENT} 별표1 · 청탁금지법 제8조", severity="CRITICAL", flag="KICKBACK_LAW_RISK",
    when="공직자처럼 청탁금지법을 받는 사람이 있었고 1인당 금액이 법 한도를 넘었을 때",
    then="회계 담당자가 직접 봅니다. 법에 걸릴 수 있는 사안이라 시스템이 자동으로 "
         "승인하지도 반려하지도 않습니다.",
)
E_PARTICIPANTS = node(
    "E-04", "참석자 명단 없음",
    {"==": [{"var": "participants.participant_count"}, 0]},
    "RETURN", "업무추진비는 참석자가 기록돼야 업무관련성을 소명할 수 있습니다.", 3,
    clause=f"{REG_ENT} 제11조④", severity="MEDIUM", flag="PARTICIPANT_LIST_REQUIRED",
    when="누구와 함께한 자리였는지가 비어 있을 때",
    then="쓴 사람에게 참석자를 적어 달라고 돌려보냅니다. 세무조사 때 핵심 소명 자료입니다.",
)

ENTERTAIN_KEYS = ["E-01", "E-02", "E-03", "E-04"]
ENTERTAIN_NODES = [E_EVIDENCE, E_PREAPPROVAL, E_KICKBACK, E_PARTICIPANTS]


def entertain(keys: list[str]) -> dict[str, Any]:
    picked = [n for n in ENTERTAIN_NODES if n["node_key"] in keys]
    return {"entry": keys[0], "nodes": [*picked, scope_pass("E", "업무추진비")],
            "routings": chain(keys, "E-PASS")}


#  ── 회식 ────────────────────────────────────────────────────────
M_PER_PERSON = node(
    "M-01", "1인당 식대 한도 초과",
    {">": [{"var": "tx.verified_per_person_amount"},
           {"var": "policy.dining_per_person_limit"}]},
    "RETURN", "회식 1인당 식대 권장 한도를 초과했습니다.", 0,
    clause=f"{REG_DINE} 제7조 · 별표4", severity="MEDIUM", flag="PER_PERSON_LIMIT_OVER",
    when="참석 인원으로 나눈 1인당 금액이 한도를 넘었을 때",
    then="쓴 사람에게 돌려보냅니다. 참석 인원이 잘못 적혔다면 고쳐서 다시 올리면 됩니다.",
)
M_SECONDARY = node(
    "M-02", "2차 비용", {"==": [{"var": "dining.is_secondary_venue"}, True]},
    "RETURN", "2차 비용(노래방·단란주점 등 별도 결제)은 회식비로 처리할 수 없습니다.", 1,
    clause=f"{REG_DINE} 제5조", severity="HIGH", flag="SECONDARY_VENUE",
    when="1차 이후 다른 가맹점에서 이어 결제한 2차 비용일 때",
    then="쓴 사람에게 돌려보냅니다. 규정상 회식비로 인정하지 않는 항목입니다.",
)
M_PREAPPROVAL = node(
    "M-03", "총액 기준 초과 · 사전승인 없음",
    {"and": [{">": [{"var": "tx.amount"}, 300_000]},
             {"==": [{"var": "approval.pre_approval_obtained"}, False]}]},
    "RETURN", "건당 총액 30만원을 초과하는 회식은 사전승인이 필요합니다.", 2,
    clause=f"{REG_DINE} 제7조 · 별표4", severity="MEDIUM", flag="PRE_APPROVAL_MISSING",
    when="회식비 총액이 30만원을 넘었는데 사전승인 기록이 없을 때",
    then="쓴 사람에게 돌려보냅니다. 사전승인 문서를 붙이면 됩니다.",
)

DINING_KEYS = ["M-01", "M-02", "M-03"]
DINING_NODES = [M_PER_PERSON, M_SECONDARY, M_PREAPPROVAL]


def dining(keys: list[str]) -> dict[str, Any]:
    picked = [n for n in DINING_NODES if n["node_key"] in keys]
    return {"entry": keys[0], "nodes": [*picked, scope_pass("M", "회식비")],
            "routings": chain(keys, "M-PASS")}


#  ── 출장 ────────────────────────────────────────────────────────
#: **숙박 청구가 없는 건을 먼저 가른다.** 안 그러면 숙박비가 null인 당일 출장이 전부
#  미해소 가드에 걸려 검토로 간다(실측: 출장 그래프를 켜는 순간 27/27이 검토였다).
T_NO_LODGING = node(
    "T-01", "숙박비 청구 없음", {"is_null": {"var": "trip.lodging_amount_per_night"}},
    #  ⚠️ `PASS_THROUGH`가 아니라 `PASS`다. `PASS_THROUGH`는 **다음 노드로 흘려보내기**용이라
    #  단말에서는 `REVIEW`가 된다(엔진: `decision = "PASS" if not candidates else "REVIEW"`).
    #  MATCH가 단말인 이 노드에 쓰면 숙박 없는 출장이 전부 검토로 간다 — 실측 2026-08-25에
    #  출장 정상 30건이 통째로 그렇게 됐고, 자동처리율이 90%에 묶여 있던 이유였다.
    "PASS", "숙박비를 청구하지 않은 출장이라 1박 한도 검사를 건너뜁니다.", 0,
    clause=f"{REG_TRIP} 제17조②", severity="INFO", flag="",
    when="출장인데 숙박비 청구가 없을 때(당일 출장 등)",
    then="숙박비 한도 검사를 건너뜁니다. 청구하지 않은 비용에 한도를 적용할 수 없습니다.",
)
T_LODGING = node(
    "T-02", "1박 숙박비 상한 초과",
    {">": [{"var": "trip.lodging_amount_per_night"}, {"var": "policy.lodging_limit"}]},
    "RETURN", "지역 등급별 1박 숙박비 상한을 초과했습니다.", 1,
    clause=f"{REG_TRIP} 제17조② · 별표1·2", severity="HIGH", flag="LODGING_LIMIT_OVER",
    when="하룻밤 숙박비가 그 지역 등급의 상한을 넘었을 때",
    then="쓴 사람에게 돌려보냅니다. 초과분은 본인 부담이거나 따로 승인을 받아야 합니다.",
)

TRIP_KEYS = ["T-01", "T-02"]


def trip(keys: list[str]) -> dict[str, Any]:
    nodes = [n for n in (T_NO_LODGING, T_LODGING) if n["node_key"] in keys]
    #  T-01은 MATCH면 통과(PASS_THROUGH), NO_MATCH면 T-02로.
    return {"entry": keys[0], "nodes": [*nodes, scope_pass("T", "출장비")],
            "routings": chain(keys, "T-PASS")}


# ════════════════════════════════════════════════════════════════
#  타임라인 — 회계가 규칙을 쌓아 온 순서
# ════════════════════════════════════════════════════════════════
#: `(단계, 설명, 게이트, {scope: 그래프}, 활성 시점 D-N)`.
#  **D-N은 오늘로부터 N일 전**이다. `seed_adopted`가 이 값으로 `activated_at`을 찍는다.
#: **자동 통과 금액 상한** — 게이트가 회사 규정 없이 승인 결정을 낼 수 있는 범위.
#
#  도입 직후에는 제품이 그 회사 규정을 모른다. 그래서 **소액만** 자동 통과시키고 나머지는
#  검토로 넘긴다 — 「10만원짜리 접대가 규정에 맞는가」는 그 회사 규정을 봐야 알 수 있고,
#  모르는 것을 통과시키면 그게 디폴트 PASS다.
#
#  과목 규칙이 쌓일수록 그 과목은 자기 그래프가 판단하므로 게이트의 상한을 넓힐 수 있다.
#  **자동처리율이 오르는 진짜 이유**가 이것이다 — 룰이 늘어서가 아니라, 늘어난 룰이
#  「판단할 수 있는 범위」를 넓혀서다.
def under(limit: int) -> dict[str, Any]:
    return {"<": [{"var": "tx.amount"}, limit]}


TIMELINE: list[tuple[str, str, dict, dict[str, dict], int]] = [
    ("v1", "도입 — 제품 기본 게이트만. 회사 규정을 모르니 **3만원 미만 소액**만 자동 통과시키고 "
     "나머지는 전부 검토로 넘긴다.",
     gate(extra_requirements=[under(30_000)], note="소액(3만 미만)만 자동 통과"), {}, 88),
    ("v2", "금지업종·현금성에 이어 **공용카드 실사용자**를 게이트에 넣고, 자동 통과 상한을 "
     "10만원으로 넓혔다.",
     gate(extra_requirements=[under(100_000)], note="10만 미만"), {}, 74),
    ("v3", "업무추진비 규정 반영 — 증빙·사전승인·참석자. 접대는 과목 그래프가 보므로 "
     "게이트 상한을 30만원으로.",
     gate(extra_requirements=[under(300_000)], note="30만 미만"),
     {"접대": entertain(["E-01", "E-02", "E-04"])}, 60),
    ("v4", "업무추진비 **별표1**(청탁금지법 대상자 1인당 한도) 추가.",
     gate(extra_requirements=[under(300_000)], note="30만 미만"),
     {"접대": entertain(ENTERTAIN_KEYS)}, 46),
    ("v5", "회식 운영규정 반영 — 1인당 한도·2차 비용. 게이트 상한 50만원.",
     gate(extra_requirements=[under(500_000)], note="50만 미만"),
     {"접대": entertain(ENTERTAIN_KEYS), "회식": dining(["M-01", "M-02"])}, 32),
    ("v6", "회식 **제7조**(총액 30만 초과 사전승인) 추가.",
     gate(extra_requirements=[under(500_000)], note="50만 미만"),
     {"접대": entertain(ENTERTAIN_KEYS), "회식": dining(DINING_KEYS)}, 18),
    ("v7", "출장비 규정 반영 — 1박 상한 + **숙박 미청구 선분기**. 네 과목이 모두 자기 규칙을 "
     "갖게 되어 **게이트의 금액 상한을 뗐다**.",
     gate(note="금액 상한 없음 — 과목 규칙이 판단한다"),
     {"접대": entertain(ENTERTAIN_KEYS), "회식": dining(DINING_KEYS),
      "출장": trip(TRIP_KEYS)}, 4),
]


def snapshots(stage: tuple) -> tuple[dict, dict[str, dict]]:
    """단계 → (게이트 스냅샷, {scope: 스냅샷}). 엔진에 바로 먹일 수 있는 모양."""
    _label, _note, g, scoped, _days = stage

    def snap(spec: dict) -> dict:
        return {"entry_node_key": spec["entry"], "nodes": spec["nodes"],
                "routings": spec["routings"]}

    return snap(g), {scope: snap(spec) for scope, spec in scoped.items()}

"""룰 그래프 시연 시드 — 실제 규정 기반 4개 계열 + 구조 검증용 TEST 그래프.

    python manage.py seed_rules [--no-test]

근거: ``llm_wiki/법인카드_사용규정_기반_RULE_명세서.md`` §4·§8, 구성 계획: ``llm_wiki/_context/rule-seed-plan.md``.

시연에서 보여줄 상태 조합:

| 계열 | scope | 상태 | 비고 |
|---|---|---|---|
| 공통 필수 게이트 | GLOBAL | v1·v2 보관 / **v3 활성** | 버전 이력·롤백 시연 |
| 기업업무추진비 | 접대 | v1 보관 / **v2 활성** | 규정 개정 반영 이력 |
| 회식비 | 식대 | **v1 활성** + **v2 수정중(초안)** | 초안 편집·시뮬레이션 시연 |
| 출장비 | 출장 | **v1 승인대기** | 검토보고서·ACTIVE 승인 시연 |
| TEST(구조 검증용) | TEST_DEMO | 초안 | 플로우차트 시각화 시연(2026-08-14: `업무활성`→`TEST_DEMO`. `업무활성`은 Category에서 폐지됐고, `회식`이 독립 카테고리가 되며 더 이상 "아무도 안 쓰는 안전한 scope"가 아니게 됐다) |

노드 `action.workflow_status`: `ACTIVE`(활성) / `WAITING`(검증대기) / `VERIFIED`(검증완료) / `DRAFT`(초안).
"""

import uuid

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from domain.policies.engine import validate_graph
from domain.policies.eval_context import validate_graph_vars
from domain.policies.models import (
    OnResult,
    RuleAuthoringMessage,
    RuleGraph,
    RuleGraphStatus,
    RuleGraphVersion,
    RuleNode,
    RuleRouting,
)

REG = "TIGER-REG-2026-003"


# ── 공용 헬퍼 ────────────────────────────────────────────────────
def plain_text(when, then):
    """`RuleNode.condition_text` — 비개발자용 "이 Rule이 하는 일" 문장.

    Rule Agent가 조건·액션을 만들 때 함께 써 두는 값으로, 화면은 DSL을 파싱하지 않고 이 문장을
    그대로 보여준다. 전문용어(DSL 경로·플래그명·영문 판정코드)를 쓰지 않고 "언제 / 그러면"
    두 덩어리로만 설명한다.
    """
    return f"언제 걸리나요?\n· {when}\n\n걸리면 어떻게 되나요?\n· {then}"


def node(key, title, condition, decision, description, priority, *,
         status="ACTIVE", clause="", when="", then="", **extra):
    """룰 노드 1개. ``when``/``then``은 쉽게보기 문장, ``extra``는 severity·flag·note·approver."""
    return {
        "node_key": key,
        "condition": condition,
        "condition_text": plain_text(when, then) if when or then else "",
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


def branch(from_key, match_to="", no_match_to=""):
    """MATCH/NO_MATCH 이진 분기. 빈 문자열은 단말(그 노드의 액션으로 종결)."""
    return [
        {"from_node_key": from_key, "on_result": OnResult.MATCH, "to_node_key": match_to, "priority": 0},
        {"from_node_key": from_key, "on_result": OnResult.NO_MATCH, "to_node_key": no_match_to, "priority": 1},
    ]


# ════════════════════════════════════════════════════════════════
#  ① GLOBAL — 공통 필수 게이트 (v1 → v2 → v3)
# ════════════════════════════════════════════════════════════════
GLOBAL_FAMILY_KEY = uuid.UUID("66df750e-26b3-4c9f-8af4-721a11c245f1")

G_FORBIDDEN = node(
    "R-002", "금지업종·사행성업종 사용",
    # 정본 업종 어휘(`transactions.industry`) 표기로만 비교한다 — 조립기가 그 어휘로 접어 올린다.
    {"in": [{"var": "merchant.merchant_type"}, ["주점/유흥", "사행성업종", "노래연습장", "이·미용"]]},
    "REJECT", "카테고리 분류 전에 금지 업종 결제를 차단하는 최우선 공통 게이트입니다.", 0,
    clause=f"{REG} 제9조②", severity="CRITICAL", flag="PROHIBITED_MERCHANT",
    note="유흥·사행성 업종 결제는 자동 반려 후보로 표시하고 관리자가 최종 확인합니다.",
    ai_reason="법인카드 사용 규정 제9조②의 사용 금지 업종을 결정론적으로 선판정하기 위해 생성했습니다.",
    approver="관리자(최종 확정)",
    when="결제한 가게의 업종이 주점·유흥·사행성업종·노래연습장·이미용업 중 하나일 때",
    then="회사가 법인카드로 쓸 수 없다고 정해 둔 업종이라, 이 지출은 '반려 후보'로 표시되고 관리자가 최종 확인합니다.",
)
G_CASH_VOUCHER = node(
    "R-003", "상품권 등 유가증권 현금구매",
    {"and": [{"==": [{"var": "category.item_type"}, "상품권"]},
             {"==": [{"var": "tx.payment_method"}, "현금"]}]},
    "REJECT", "상품권 등 유가증권을 현금으로 구입한 거래를 카테고리와 무관하게 탐지합니다.", 1,
    clause=f"{REG} 제9조③", severity="CRITICAL", flag="PROHIBITED_PAYMENT_METHOD",
    note="현금 구매는 적격증빙 확보 원칙에 어긋나므로 자동 반려 후보로 표시합니다.",
    ai_reason="법인카드 사용 규정 제9조③의 유가증권 현금 구매 금지 조건을 실행 가능한 DSL로 변환했습니다.",
    approver="관리자(최종 확정)",
    when="산 물건이 상품권인데, 결제 수단이 현금일 때",
    then="현금으로 사면 세금계산서 같은 정식 증빙을 남길 수 없어서, '반려 후보'로 표시되고 관리자가 최종 확인합니다.",
)
G_SHARED_CARD = node(
    "R-004", "공용카드 실사용자 미기재",
    {"and": [{"in": [{"var": "card.card_type"}, ["SHARED", "TEAM"]]},
             {"==": [{"var": "card.actual_user_recorded"}, False]}]},
    "RETURN", "공용·팀 카드로 결제했는데 실사용자가 기록되지 않은 건입니다.", 2,
    clause="요구사항 §4.1", severity="HIGH", flag="ACTUAL_USER_REQUIRED",
    note="실사용자와 사용 목적을 입력하면 자동으로 재판정됩니다.",
    ai_reason="공용/팀 카드는 실사용자·목적 지정이 필요하다는 요구사항을 공통 게이트로 올렸습니다.",
    approver="지출 담당자(본인 보완)",
    when="여러 사람이 함께 쓰는 공용카드·팀 카드로 결제했는데, 실제로 누가 썼는지 적혀 있지 않을 때",
    then="쓴 사람에게 보완을 요청합니다. 실사용자와 사용 목적만 채워 넣으면 다시 자동으로 판정됩니다.",
)
G_PERSONAL_USE = node(
    "R-006", "심야·휴일 사적사용 의심",
    # 「사적사용 의심」은 결론이지 사실이 아니다. EvalContext는 원자 사실(단어)만 주고,
    # 판단은 여기서 조합한다 — 심야 결제 AND (휴일 OR 가맹점 업종 미확인).
    #  심야 기준(22~06)도 **여기 상수로 둔다**(v6 결정) — 조립기에 박으면 회사마다 다른
    #  값을 바꾸려고 재배포해야 한다. `payment_time`은 제로패딩 `HH:MM`이라 문자열 비교가
    #  곧 시각 순서다.
    {"and": [{"or": [{">=": [{"var": "tx.payment_time"}, "22:00"]},
                     {"<": [{"var": "tx.payment_time"}, "06:00"]}]},
             {"or": [{"==": [{"var": "derived.is_weekend"}, True]},
                     {"==": [{"var": "merchant.merchant_info_resolved"}, False]}]}]},
    "REVIEW", "심야 결제이면서 휴일이거나 가맹점 업종을 확인할 수 없는 건을 사람 검토로 넘깁니다.", 3,
    clause=f"{REG} 제7조①", severity="HIGH", flag="PERSONAL_USE_SUSPECTED",
    note="이상탐지 점수와 함께 회계 담당자가 최종 판단합니다.",
    ai_reason="'사적사용 의심'이라는 결론을 그대로 입력받지 않고, 심야·휴일·업종미확인이라는 "
              "확인 가능한 사실 세 개의 조합으로 바꿨습니다. 조합 규칙이 화면에 보이므로 근거를 따질 수 있습니다.",
    approver="회계 담당자",
    when="늦은 밤에 결제했고, 그날이 휴일이거나 어떤 가게인지 확인이 안 될 때",
    then="한 가지만으로는 판단하지 않고, 두 가지가 겹칠 때만 회계 담당자가 직접 보도록 검토 목록에 올립니다.",
)
G_PASS = node(
    "_GLOBAL_PASS", "공통 게이트 통과", True, "PASS",
    "앞선 공통 금지 조건에 해당하지 않은 거래를 비용분류별 그래프로 전달합니다.", 9,
    clause="RULE 명세서 §8", note="GLOBAL 검사를 통과했으며 이후 비용분류별 세부 룰을 평가합니다.",
    ai_reason="모든 공통 조건이 불일치할 때 명시적으로 PASS를 반환하기 위한 내부 종단 노드입니다.",
    when="앞의 공통 금지 조건에 하나도 걸리지 않았을 때 (여기까지 온 거래는 모두 해당됩니다)",
    then="모든 지출에 공통으로 적용되는 검사는 통과입니다. 이어서 접대비·회식비처럼 비용 종류별 룰로 넘어갑니다.",
)

GLOBAL_V1 = {
    "nodes": [G_FORBIDDEN, G_CASH_VOUCHER, G_PASS],
    "routings": [*branch("R-002", "", "R-003"), *branch("R-003", "", "_GLOBAL_PASS")],
    "note": "최초 배포 — 금지업종·유가증권 현금구매 2종",
}
GLOBAL_V2 = {
    "nodes": [G_FORBIDDEN, G_CASH_VOUCHER, G_SHARED_CARD, G_PASS],
    "routings": [*branch("R-002", "", "R-003"), *branch("R-003", "", "R-004"),
                 *branch("R-004", "", "_GLOBAL_PASS")],
    "note": "공용카드 실사용자 확인(R-004) 추가 — 공용카드 오남용 대응",
}
GLOBAL_V3 = {
    "nodes": [G_FORBIDDEN, G_CASH_VOUCHER, G_SHARED_CARD, G_PERSONAL_USE, G_PASS],
    "routings": [*branch("R-002", "", "R-003"), *branch("R-003", "", "R-004"),
                 *branch("R-004", "", "R-006"), *branch("R-006", "", "_GLOBAL_PASS")],
    "note": "심야·휴일 사적사용 의심(R-006) 추가 — 이상탐지 연계 강화",
}


def global_snapshot() -> dict:
    """현재 활성(v3) GLOBAL 게이트 스냅샷."""
    return {"entry_node_key": "R-002", "nodes": GLOBAL_V3["nodes"], "routings": GLOBAL_V3["routings"]}


# ════════════════════════════════════════════════════════════════
#  ② 기업업무추진비(접대) — v1 보관 / v2 활성
# ════════════════════════════════════════════════════════════════
ENTERTAIN_FAMILY_KEY = uuid.UUID("2b7c1f04-9a5e-4b26-8d3a-51f0c7a91b02")

E_RECEIPT = node(
    "E-001", "3만원 초과 적격증빙 미수취",
    {"and": [{">": [{"var": "tx.amount"}, {"var": "policy.evidence_threshold"}]},
             {"==": [{"var": "evidence.has_valid_receipt"}, False]}]},
    "RETURN", "적격증빙 기준액을 초과하는 기업업무추진비인데 적격증빙이 없는 건입니다.", 0,
    clause=f"{REG} 제11조②", severity="HIGH", flag="NON_DEDUCTIBLE_RISK",
    note="적격증빙(세금계산서·신용카드매출전표)을 첨부하면 자동 재판정됩니다.",
    ai_reason="3만원 초과 적격증빙 미수취 시 손금불산입 대상이라는 조항을 그대로 판정 조건으로 옮겼습니다.",
    approver="지출 담당자(본인 보완)",
    when="접대비를 3만원 넘게 썼는데, 세금계산서나 신용카드매출전표 같은 정식 증빙이 없을 때",
    then="쓴 사람에게 보완을 요청합니다. 증빙 없이 그냥 넘어가면 회사가 비용으로 인정받지 못해 세금을 더 내게 됩니다.",
)
E_PREAPPROVAL = node(
    "E-002", "건당 50만원 초과 사전승인 누락",
    {"and": [{">": [{"var": "tx.amount"}, {"var": "policy.preapproval_threshold"}]},
             {"==": [{"var": "approval.pre_approval_obtained"}, False]}]},
    "RETURN", "사전승인 기준 금액을 넘겼는데 승인 기록이 없는 건입니다.", 1,
    clause=f"{REG} 제12조①", severity="HIGH", flag="PRE_APPROVAL_MISSING",
    note="사전승인 문서를 첨부하거나 사후 승인 절차를 진행해주세요.",
    ai_reason="한도를 코드에 고정하지 않고 정책 테이블(policy.preapproval_threshold)을 참조하도록 만들어 규정 개정에 대응합니다.",
    approver="본부장",
    when="결제 금액이 '사전승인이 필요한 기준 금액'(현재 50만원)을 넘었는데, 미리 받아 둔 승인 기록이 없을 때",
    then="쓴 사람에게 보완을 요청합니다. 사전승인 문서를 첨부하거나 사후 승인 절차를 밟으면 됩니다. "
         "기준 금액은 규정 표에서 읽어오므로, 규정이 바뀌면 이 룰을 고치지 않아도 자동으로 따라갑니다.",
)
E_KICKBACK = node(
    "E-003", "청탁금지법 대상자 참석 · 한도 초과",
    # 1인당 금액은 **문서로 확인된 인원** 기준이다(신고값 아님) — 법정 한도 판정이라
    #  본인이 적은 인원으로 나누면 인원을 부풀리는 것만으로 한도를 피할 수 있다.
    #  명단이 없으면 `verified_per_person_amount`가 null이라 판정이 검토로 넘어간다(의도).
    {"and": [{"==": [{"var": "participants.has_kickback_law_target"}, True]},
             {">": [{"var": "tx.verified_per_person_amount"},
                    {"var": "policy.kickback_limit"}]}]},
    "REVIEW", "공직자 등 청탁금지법 대상자가 참석했고 1인당 금액이 법정 한도를 넘은 건입니다.", 2,
    clause=f"{REG} 제12조③ · 청탁금지법 제8조", severity="CRITICAL", flag="KICKBACK_LAW_RISK",
    note="법률 리스크가 있어 자동 처리하지 않고 반드시 사람이 판단합니다.",
    ai_reason="법률 위반 소지가 있는 조건은 자동 반려·자동 승인 모두 위험해 REVIEW로 고정했습니다.",
    approver="회계팀장",
    when="공무원처럼 청탁금지법(김영란법) 적용을 받는 사람이 자리에 있었고, 1인당 금액이 법에서 정한 한도를 넘었을 때",
    then="법에 걸릴 수 있는 사안이라 시스템이 알아서 결정하지 않습니다. 무조건 회계팀장이 직접 보고 판단합니다.",
)
E_PARTICIPANTS = node(
    "E-004", "참석자 명단 누락",
    # 「명단 누락」이라는 별도 불린을 두지 않는다 — 참석 인원이 0(=기록 없음)이면 곧 누락이다.
    # 인원을 아예 안 물어본 경우는 None이 남아 미해소 가드가 잡는다(모름 ≠ 0명).
    {"==": [{"var": "participants.participant_count"}, 0]},
    "RETURN", "기업업무추진비는 참석자·목적이 함께 기록돼야 업무관련성을 입증할 수 있습니다.", 3,
    clause=f"{REG} 제11조④", severity="MEDIUM", flag="PARTICIPANT_LIST_REQUIRED",
    note="참석자 명단(소속·인원)과 목적을 입력해주세요.",
    ai_reason="세무조사 시 업무관련성 소명의 핵심 자료라 누락을 사전에 차단합니다.",
    approver="지출 담당자(본인 보완)",
    when="누구와 함께한 자리였는지(참석자 명단)가 비어 있을 때",
    then="쓴 사람에게 보완을 요청합니다. 나중에 세무조사를 받을 때 '업무 때문에 쓴 돈'이라고 설명할 핵심 자료가 참석자 명단입니다.",
)
E_PASS = node(
    "E-PASS", "기업업무추진비 검증 통과", True, "PASS",
    "증빙·사전승인·참석자·법률 리스크 조건에 모두 해당하지 않은 건입니다.", 9,
    clause="RULE 명세서 §4", note="자동 통과 후보이나 최종 확정은 회계 담당자가 수행합니다.",
    ai_reason="모든 조건 불일치 시 명시적 PASS를 반환하는 종단 노드입니다.",
    when="앞의 접대비 점검 항목에 하나도 걸리지 않았을 때",
    then="문제없는 지출로 봅니다. 다만 시스템이 마음대로 확정하지는 않고, 회계 담당자가 마지막으로 확정 버튼을 눌러야 끝납니다.",
)

ENTERTAIN_V1 = {
    "nodes": [E_RECEIPT, E_PREAPPROVAL, E_PARTICIPANTS, E_PASS],
    "routings": [*branch("E-001", "", "E-002"), *branch("E-002", "", "E-004"),
                 *branch("E-004", "", "E-PASS")],
    "note": "최초 배포 — 증빙·사전승인·참석자 3종",
}
ENTERTAIN_V2 = {
    "nodes": [E_RECEIPT, E_PREAPPROVAL, E_KICKBACK, E_PARTICIPANTS, E_PASS],
    "routings": [*branch("E-001", "", "E-002"), *branch("E-002", "", "E-003"),
                 *branch("E-003", "", "E-004"), *branch("E-004", "", "E-PASS")],
    # E-005(봉사료 10% 이상)는 v3 다이어트에서 제거 — 영수증에 봉사료가 표기되지 않는 경우가
    # 많아 원천을 확보할 수 없고, 판정 기여도 대비 부차적이다.
    "note": "청탁금지법 대상(E-003) 추가",
}


# ════════════════════════════════════════════════════════════════
#  ③ 회식비 — v1 활성 / v2 수정중(초안, 전 노드 검증대기)
# ════════════════════════════════════════════════════════════════
DINING_FAMILY_KEY = uuid.UUID("8f3d5a71-6c42-4f19-9b07-2ad4e6c85f13")


def _dining_nodes(status):
    return {
        "per_person": node(
            "M-001", "1인당 한도 초과",
            {">": [{"var": "tx.per_person_amount"}, {"var": "policy.dining_per_person_limit"}]},
            "REVIEW", "회식비 1인당 한도를 초과한 건입니다.", 0,
            clause=f"{REG} 제14조①", severity="MEDIUM", flag="PER_PERSON_LIMIT_OVER", status=status,
            note="참석 인원과 실제 지출 목적을 확인해주세요.",
            ai_reason="회식비는 총액이 아니라 1인당 금액으로 판단해야 한다는 규정을 반영했습니다.",
            approver="회계 담당자",
            when="회식비를 참석 인원수로 나눈 '1인당 금액'이 5만원을 넘을 때",
            then="회계 담당자 검토 목록에 올립니다. 총액이 아니라 1인당 금액으로 보기 때문에, 인원이 많으면 총액이 커도 걸리지 않습니다.",
        ),
        "secondary": node(
            "M-002", "2차 이상 연속 결제",
            {"==": [{"var": "dining.is_secondary_venue"}, True]},
            "REVIEW", "같은 행사에서 2차 이상으로 이어진 결제입니다.", 1,
            clause=f"{REG} 제14조③", severity="MEDIUM", flag="SECONDARY_VENUE", status=status,
            note="2차 비용은 원칙적으로 인정하지 않으나 예외 사유가 있으면 기재해주세요.",
            ai_reason="회식 2차는 규정상 원칙적 불인정이라 자동 반려 대신 사유 확인 후 판단하도록 REVIEW로 두었습니다.",
            approver="회계 담당자",
            when="같은 회식에서 1차에 이어 2차, 3차로 이어진 결제일 때",
            then="2차부터는 원칙적으로 인정하지 않지만 예외 사유가 있을 수 있어, 바로 반려하지 않고 회계 담당자가 사유를 보고 판단합니다.",
        ),
        "participants": node(
            "M-003", "참석자 명단 누락",
            # 「명단 누락」이라는 별도 불린을 두지 않는다 — 참석 인원이 0(=기록 없음)이면 곧 누락이다.
    # 인원을 아예 안 물어본 경우는 None이 남아 미해소 가드가 잡는다(모름 ≠ 0명).
    {"==": [{"var": "participants.participant_count"}, 0]},
            "RETURN", "참석자 명단이 없으면 1인당 한도 자체를 계산할 수 없습니다.", 2,
            clause=f"{REG} 제14조②", severity="HIGH", flag="PARTICIPANT_LIST_REQUIRED", status=status,
            note="참석자 명단을 입력하면 1인당 금액이 자동 계산됩니다.",
            ai_reason="후속 판정(1인당 한도)의 입력값이 되는 필수 항목이라 앞단에서 막습니다.",
            approver="지출 담당자(본인 보완)",
            when="회식에 누가 참석했는지(참석자 명단)가 비어 있을 때",
            then="쓴 사람에게 보완을 요청합니다. 인원수를 모르면 1인당 금액 자체를 계산할 수 없어서, 다른 검사보다 먼저 확인합니다.",
        ),
        "alcohol": node(
            "M-005", "주류 과다 포함",
            {"and": [{"==": [{"var": "dining.includes_alcohol"}, True]},
                     {">": [{"var": "tx.per_person_amount"}, 30000]}]},
            "REVIEW", "주류가 포함되고 1인당 3만원을 넘는 회식 건입니다.", 4,
            clause=f"{REG} 제14조④", severity="LOW", flag="ALCOHOL_HEAVY", status=status,
            note="부서 회식 성격이 맞는지 확인해주세요.",
            ai_reason="v2 초안 — 주류 비중이 큰 회식을 별도로 표시해달라는 요청을 반영했습니다.",
            approver="회계 담당자",
            when="술이 포함된 회식이면서, 1인당 금액이 3만원을 넘을 때",
            then="부서 회식 성격이 맞는지 확인하려고 회계 담당자 검토 목록에 올립니다. "
                 "1인당 5만원을 넘는 건은 앞의 한도 검사에서 이미 걸러지므로 여기까지 오지 않습니다.",
        ),
        "pass": node(
            "M-PASS", "회식비 검증 통과", True, "PASS",
            "회식비 규정 조건에 모두 해당하지 않은 건입니다.", 9,
            clause="RULE 명세서 §4", status=status,
            note="자동 통과 후보이나 최종 확정은 회계 담당자가 수행합니다.",
            ai_reason="모든 조건 불일치 시 명시적 PASS를 반환하는 종단 노드입니다.",
            when="앞의 회식비 점검 항목에 하나도 걸리지 않았을 때",
            then="문제없는 회식비로 봅니다. 다만 시스템이 마음대로 확정하지는 않고, 회계 담당자가 마지막으로 확정해야 끝납니다.",
        ),
    }


_D_ACTIVE = _dining_nodes("ACTIVE")
_D_DRAFT = _dining_nodes("WAITING")

DINING_V1 = {
    "nodes": [_D_ACTIVE["participants"], _D_ACTIVE["per_person"], _D_ACTIVE["secondary"], _D_ACTIVE["pass"]],
    "routings": [*branch("M-003", "", "M-001"), *branch("M-001", "", "M-002"),
                 *branch("M-002", "", "M-PASS")],
    "note": "최초 배포 — 참석자·1인당 한도·2차 3종",
}
DINING_V2 = {
    "nodes": [_D_DRAFT["participants"], _D_DRAFT["per_person"], _D_DRAFT["secondary"],
              _D_DRAFT["alcohol"], _D_DRAFT["pass"]],
    "routings": [*branch("M-003", "", "M-001"), *branch("M-001", "", "M-002"),
                 *branch("M-002", "", "M-005"), *branch("M-005", "", "M-PASS")],
    # M-004(동일 행사 분할결제 의심)는 v3 다이어트에서 제거 — 패턴 탐지는 룰이 아니라
    # 비지도 이상탐지(Risk Review 1차)의 영역이다.
    "note": "주류 과다(M-005) 추가 — 검증 대기",
}


# ════════════════════════════════════════════════════════════════
#  ④ 출장비 — v1 승인대기(검토보고서 포함)
# ════════════════════════════════════════════════════════════════
TRIP_FAMILY_KEY = uuid.UUID("a41e9d68-0b73-4c85-9f22-6e17d5a3c904")

TRIP_V1 = {
    "nodes": [
        node("T-102", "숙박비 1박 한도 초과",
             {">": [{"var": "trip.lodging_amount_per_night"}, {"var": "policy.lodging_limit"}]},
             "RETURN", "지역 등급별 1박 숙박비 한도를 초과한 건입니다.", 1,
             clause=f"{REG} 제17조②", severity="HIGH", flag="LODGING_LIMIT_OVER", status="VERIFIED",
             note="초과분은 개인 부담이거나 사전 승인이 필요합니다.",
             ai_reason="지역 등급별 한도를 정책 테이블에서 읽어 비교하도록 만들어 지역·직급 변경에 대응합니다.",
             approver="지출 담당자(본인 보완)",
             when="하룻밤 숙박비가 그 지역에 정해진 한도를 넘었을 때",
             then="쓴 사람에게 보완을 요청합니다. 넘은 금액은 본인 부담이거나 따로 승인을 받아야 합니다. "
                  "지역·직급별 한도는 규정 표에서 읽어오므로, 규정이 바뀌면 이 룰을 고치지 않아도 됩니다."),
        node("T-PASS", "출장비 검증 통과", True, "PASS",
             "출장 신청·숙박·항공·일정 조건에 모두 해당하지 않은 건입니다.", 9,
             clause="RULE 명세서 §4", status="VERIFIED",
             note="자동 통과 후보이나 최종 확정은 회계 담당자가 수행합니다.",
             ai_reason="모든 조건 불일치 시 명시적 PASS를 반환하는 종단 노드입니다.",
             when="앞의 출장비 점검 항목에 하나도 걸리지 않았을 때",
             then="문제없는 출장비로 봅니다. 다만 시스템이 마음대로 확정하지는 않고, 회계 담당자가 마지막으로 확정해야 끝납니다."),
    ],
    "routings": [*branch("T-102", "", "T-PASS")],
    # T-101(신청 선행일수)·T-103(비즈니스석)·T-104(일정 불일치)는 v3 다이어트에서 제거 —
    # 출장 도메인(신청서·항공 예약) 모델이 없어 원천을 만들 수 없다. 모델이 생기면 함께 되살린다.
    "note": "최초 작성 — 숙박비 한도 1종(출장 도메인 확보 후 확장)",
}

TRIP_REVIEW_COMMENT = """## 검토 의견

출장비 그래프 v1을 검증셋 5건과 직전 기간 실제 내역으로 시뮬레이션한 결과, 판정 분포가
기존 회계팀 처리 이력과 크게 어긋나지 않는 것을 확인했습니다.

## 확인한 위험·변경건

- **숙박비 한도 초과(T-102)** — 지역 등급 B 지역 건 2개가 새로 보완요청으로 분류됐습니다.
  실제로 한도를 넘긴 건이 맞아 의도된 변경으로 판단합니다.
- **단거리 비즈니스석(T-103)** — 임원 출장 1건이 검토로 분류됐습니다. 직급 예외는 규정상
  사람이 판단해야 하므로 REVIEW 유지가 적절합니다.
- **일정 불일치(T-104)** — 이번 표본에서는 매칭 건이 없어 실데이터 검증이 더 필요합니다.

## 활성화 판단

- 자동 반려(REJECT)로 끝나는 경로가 없어 과잉 차단 위험이 낮습니다.
- 한도 값을 코드가 아닌 정책 테이블에서 읽으므로 규정 개정 시 그래프 수정 없이 대응 가능합니다.
- **활성화를 권장**합니다. 다만 T-104는 다음 달 실적으로 재시뮬레이션해 매칭 여부를 확인하겠습니다.
"""

TRIP_TEST_CASES = [
    {"key": "TC-1", "label": "정상 국내 출장 숙박", "merchant": "신라스테이 동탄", "amount": 98000,
     "category": "출장", "expected": "PASS",
     "facts": {"trip.trip_request_submitted_days_before": 5, "trip.lodging_amount_per_night": 98000,
               "policy.lodging_limit": 120000, "trip.itinerary_mismatch": False}},
    {"key": "TC-2", "label": "숙박 한도 초과", "merchant": "그랜드호텔", "amount": 210000,
     "category": "출장", "expected": "RETURN",
     "facts": {"trip.trip_request_submitted_days_before": 7, "trip.lodging_amount_per_night": 210000,
               "policy.lodging_limit": 120000}},
    {"key": "TC-3", "label": "출장 신청 지연", "merchant": "코레일 KTX", "amount": 59800,
     "category": "출장", "expected": "REVIEW",
     "facts": {"trip.trip_request_submitted_days_before": 1}},
    {"key": "TC-4", "label": "단거리 비즈니스석", "merchant": "대한항공 김포-제주", "amount": 320000,
     "category": "출장", "expected": "REVIEW",
     "facts": {"trip.trip_request_submitted_days_before": 6, "trip.flight_class": "BUSINESS",
               "trip.flight_duration_hours": 1.2}},
    {"key": "TC-5", "label": "일정 불일치", "merchant": "속초 리조트", "amount": 180000,
     "category": "출장", "expected": "REVIEW",
     "facts": {"trip.trip_request_submitted_days_before": 4, "trip.lodging_amount_per_night": 90000,
               "policy.lodging_limit": 120000, "trip.itinerary_mismatch": True}},
]


# ════════════════════════════════════════════════════════════════
#  ⑤ TEST 그래프 — 구조 시각화 검증용(대형·비정형)
# ════════════════════════════════════════════════════════════════
TEST_FAMILY_KEY = uuid.UUID("0c1d7a2e-5f43-4a11-9d7c-8e2f6b0a4c31")


def _test_node(node_key, title, condition, decision, description, priority, **extra):
    return node(node_key, title, condition, decision, description, priority,
                status="WAITING", clause="TEST 픽스처 (규정 근거 없음)",
                note="TEST 픽스처 노드 — 실제 판정에 사용하지 않습니다.",
                ai_reason="Rule 콘솔 화면(구조 시각화·시뮬레이션) 검증을 위해 만든 테스트 노드입니다.",
                **extra)


TEST_NODES = [
    _test_node("T-00", "진입 게이트 (전체 통과)", True, "PASS_THROUGH",
               "모든 거래가 통과하는 진입 노드. 이후 분기를 두 갈래로 나눕니다.", 0, severity="INFO",
               when="모든 지출이 여기를 거칩니다 (걸러내는 조건이 없습니다)",
               then="아무 판정도 하지 않고 다음 검사로 넘깁니다. 검사가 시작되는 출발점입니다."),
    _test_node("T-10", "고액 결제 감지 (사전승인 기준액 초과)",
               {">": [{"var": "tx.amount"}, {"var": "policy.preapproval_threshold"}]}, "REVIEW",
               "사전승인 기준액을 초과한 결제를 잡아냅니다.", 1, severity="HIGH", flag="HIGH_AMOUNT",
               when="한 번에 결제한 금액이 규정이 정한 사전승인 기준액을 넘을 때",
               then="금액이 큰 지출이라 회계 담당자가 직접 보도록 검토 목록에 올립니다."),
    _test_node("T-11", "심야·주말 결제 감지",
               {"or": [{">=": [{"var": "tx.payment_time"}, "22:00"]},
                       {"<": [{"var": "tx.payment_time"}, "06:00"]},
                       {"==": [{"var": "derived.is_weekend"}, True]}]}, "REVIEW",
               "심야 또는 주말에 발생한 결제를 잡아냅니다.", 2, severity="MEDIUM", flag="OFF_HOURS",
               when="늦은 밤에 결제했거나, 주말에 결제했을 때 (둘 중 하나만 해당해도 걸립니다)",
               then="업무 시간 밖의 지출이라 회계 담당자 검토 목록에 올립니다."),
    _test_node("T-20", "사전승인 누락", {"==": [{"var": "approval.pre_approval_obtained"}, False]}, "RETURN",
               "사전승인이 필요한데 승인 기록이 없는 건입니다.", 3, severity="HIGH", flag="PRE_APPROVAL_MISSING",
               when="미리 승인을 받아야 하는 지출인데 승인 기록이 없을 때",
               then="쓴 사람에게 보완을 요청합니다. 승인 내역을 첨부하면 다시 판정합니다."),
    # 「없음」을 묻는 것이므로 `== False`로 **명시**한다. `not(var)`는 v6 이전엔 모름까지
    #  참으로 만들어 확인 안 한 건에 EVIDENCE_MISSING을 달았다(지금은 False로 안 걸린다).
    _test_node("T-21", "적격증빙 누락",
               {"==": [{"var": "evidence.has_valid_receipt"}, False]}, "RETURN",
               "적격증빙이 첨부되지 않은 건입니다. 두 갈래에서 함께 도달하는 수렴 노드입니다.", 4,
               severity="HIGH", flag="EVIDENCE_MISSING",
               when="세금계산서·카드전표 같은 정식 증빙이 첨부되지 않았을 때",
               then="쓴 사람에게 보완을 요청합니다. 증빙을 올리면 다시 판정합니다."),
    # 「형식적 기재(purpose_is_generic)」는 AI의 텍스트 품질 판정이라 v3에서 제거했다.
    # 목적 문구의 품질은 룰이 아니라 초안 작성(Draft Agent) 단계에서 다루는 것이 맞다.
    _test_node("T-22", "사용 목적 누락",
               {"==": [{"var": "evidence.expense_purpose_missing"}, True]}, "RETURN",
               "목적이 비어 있는 건입니다.", 5, severity="MEDIUM", flag="PURPOSE_UNCLEAR",
               when="사용 목적이 비어 있을 때",
               then="쓴 사람에게 보완을 요청합니다. 무슨 일로 썼는지 구체적으로 적어주세요."),
    _test_node("T-30", "참석자 과다 (8인 초과)", {">": [{"var": "participants.participant_count"}, 8]}, "REVIEW",
               "참석 인원이 많아 목적·성격 확인이 필요한 건입니다.", 6, severity="MEDIUM",
               when="참석한 사람이 8명을 넘을 때",
               then="어떤 성격의 자리였는지 확인이 필요해 회계 담당자 검토 목록에 올립니다."),
    _test_node("T-31", "외부 참석자 포함", {">": [{"var": "participants.external_participant_count"}, 0]}, "REVIEW",
               "외부 참석자가 포함되어 접대성 여부 판단이 필요한 건입니다.", 7, severity="MEDIUM",
               when="회사 밖 사람이 한 명이라도 참석했을 때",
               then="접대성 지출인지 아닌지 갈리는 지점이라 회계 담당자 검토 목록에 올립니다."),
    _test_node("T-40", "동일 가맹점 반복 결제 5회 이상", {">=": [{"var": "history.same_vendor_count"}, 5]}, "REVIEW",
               "같은 가맹점에서 반복 결제된 패턴입니다. 참석자 과다 갈래에서만 도달합니다.", 8,
               severity="MEDIUM", flag="REPEATED_VENDOR",
               when="최근 3개월 동안 같은 가게에서 5번 이상 결제했을 때",
               then="특정 가게에 몰리는 패턴이라 회계 담당자 검토 목록에 올립니다."),
    _test_node("T-41", "일일 누적 한도 초과",
               {">": [{"var": "history.daily_cumulative_amount"}, {"var": "policy.position_daily_limit"}]}, "REVIEW",
               "직책별 일일 한도를 넘어선 누적 사용액입니다.", 9, severity="HIGH", flag="DAILY_LIMIT_OVER",
               when="하루에 쓴 금액을 모두 더한 값이 직책별 하루 한도를 넘을 때",
               then="회계 담당자 검토 목록에 올립니다. 한도는 규정 표에서 직책에 따라 읽어옵니다."),
    _test_node("T-50", "주의 업종 결제",
               {"in": [{"var": "merchant.merchant_type"}, ["주점/유흥", "노래연습장", "골프장", "면세점"]]}, "REVIEW",
               "업무 관련성 확인이 필요한 업종입니다.", 10, severity="HIGH", flag="WATCH_MERCHANT",
               when="결제한 가게의 업종이 주점·노래연습장·골프장·면세점 중 하나일 때",
               then="금지 업종은 아니지만 업무와 관련이 있는지 확인이 필요해 회계 담당자 검토 목록에 올립니다."),
    _test_node("T-51", "법인카드 외 결제수단", {"!=": [{"var": "tx.payment_method"}, "법인카드"]}, "RETURN",
               "법인카드가 아닌 수단으로 결제된 건입니다.", 11, severity="MEDIUM", flag="NON_CORPORATE_CARD",
               when="법인카드가 아닌 다른 수단(현금·개인카드 등)으로 결제했을 때",
               then="쓴 사람에게 보완을 요청합니다."),
    _test_node("T-60", "수동 검토 종결", True, "REVIEW",
               "라우팅이 없는 리프 노드 — 이 노드의 액션으로 판정이 끝납니다.", 12, severity="LOW", approver="회계담당",
               when="여기까지 온 모든 지출 (걸러내는 조건이 없습니다)",
               then="회계 담당자 검토 목록에 올리고 판정을 끝냅니다. 뒤에 이어지는 검사가 없습니다."),
    _test_node("T-61", "정산 지연 (기한 초과)",
               {">": [{"var": "derived.business_days_since_expense"}, {"var": "policy.settlement_deadline_days"}]},
               "RETURN",
               "정산 제출이 늦어진 건입니다.", 13, severity="MEDIUM", flag="LATE_SETTLEMENT",
               when="결제한 뒤 규정이 정한 정산 기한(영업일 기준)을 넘기도록 정산을 올리지 않았을 때",
               then="쓴 사람에게 보완을 요청합니다. 기한 일수는 규정 표에서 읽어오므로 규정이 바뀌면 이 룰을 고치지 않아도 따라갑니다."),
    _test_node("T-70", "최종 통과 후보", True, "PASS", "가장 깊은 레벨의 리프 노드입니다.", 14, severity="INFO",
               when="여기까지 온 모든 지출 (걸러내는 조건이 없습니다)",
               then="문제없는 지출로 보고 판정을 끝냅니다. 최종 확정은 회계 담당자가 합니다."),
    _test_node("T-90", "[고아] 분류 신뢰도 낮음", {"<": [{"var": "category.confidence"}, 0.5]}, "REVIEW",
               "진입 노드에서 도달할 수 없는 고아 노드입니다. 첫 행에 따로 표시됩니다.", 15, severity="LOW",
               when="AI가 매긴 비용분류 확신 정도가 50%에 못 미칠 때",
               then="분류가 맞는지 사람이 확인하도록 검토 목록에 올립니다."),
    _test_node("T-91", "[고아] 분류 재확인 요청", True, "RETURN",
               "고아 노드에서만 도달 가능한 하위 노드입니다.", 16, severity="LOW",
               when="여기까지 온 모든 지출 (걸러내는 조건이 없습니다)",
               then="쓴 사람에게 비용분류를 다시 확인해 달라고 요청합니다."),
]

TEST_ROUTINGS = [
    *branch("T-00", "T-10", "T-11"),
    *branch("T-10", "T-20", "T-11"),
    *branch("T-11", "T-22", "T-21"),
    *branch("T-20", "", "T-21"),
    *branch("T-21", "", "T-30"),
    *branch("T-22", "", "T-31"),
    *branch("T-30", "T-40", "T-31"),
    *branch("T-31", "T-50", "T-41"),
    *branch("T-40", "", "T-41"),
    *branch("T-41", "", "T-51"),
    *branch("T-50", "T-60", "T-51"),
    *branch("T-51", "", "T-61"),
    *branch("T-61", "", "T-70"),
    *branch("T-90", "T-91", ""),
]

TEST_GRAPH = {"nodes": TEST_NODES, "routings": TEST_ROUTINGS, "note": "구조 시각화 검증용 픽스처"}


def test_snapshot() -> dict:
    return {"entry_node_key": "T-00", "nodes": TEST_NODES, "routings": TEST_ROUTINGS}


# ════════════════════════════════════════════════════════════════
#  대화 로그 — Rule Agent가 실제로 무엇을 바꿨는지 보이도록
# ════════════════════════════════════════════════════════════════
def _chat(node_key, pairs):
    """(사용자 지시, Agent 응답, 반영 요약) 튜플 목록 → 메시지 dict 목록."""
    rows = []
    for user_text, ai_text, applied in pairs:
        rows.append({"node_key": node_key, "role": "user", "text": user_text, "applied_note": ""})
        rows.append({"node_key": node_key, "role": "ai", "text": ai_text, "applied_note": applied})
    return rows


ENTERTAIN_CHAT = [
    *_chat("E-005", [
        ("접대비에서 봉사료가 과하게 붙는 업소를 걸러내고 싶어. 10% 넘으면 표시해줘.",
         "봉사료 비율 조건을 새 노드로 추가했습니다.\n"
         "· 조건: tx.service_charge_ratio >= 0.10\n"
         "· 액션: REVIEW / 심각도 MEDIUM / 플래그 SERVICE_CHARGE_HIGH\n"
         "· 근거: 제12조② (업무관련성 엄격 심사 대상)\n"
         "참석자 확인(E-004) 다음 순서로 배치했습니다.",
         "노드 E-005 신규 생성 · 조건·액션·라우팅 반영"),
        ("반려까지는 말고 사람이 보게만 해줘.",
         "액션을 RETURN → REVIEW로 낮췄습니다. 자동 반려 대신 회계 담당자 검토 대상으로 분류됩니다.",
         "액션(결정) 필드 변경: RETURN → REVIEW"),
    ]),
    *_chat("E-003", [
        ("청탁금지법 대상자가 있는 접대는 별도로 잡아야 해. 1인당 법정 한도 넘으면 검토로.",
         "청탁금지법 조건 노드를 추가했습니다.\n"
         "· 조건: participants.has_kickback_law_target == true AND tx.per_person_amount > policy.kickback_limit\n"
         "· 액션: REVIEW / 심각도 CRITICAL / 승인 주체: 회계팀장\n"
         "한도를 숫자로 박지 않고 정책 테이블(policy.kickback_limit)을 참조하도록 만들어, "
         "법 개정 시 그래프를 고치지 않아도 됩니다.",
         "노드 E-003 신규 생성 · 정책 테이블 참조 조건 적용"),
        ("이건 절대 자동 반려되면 안 돼.",
         "확인했습니다. E-003은 MATCH 시 REVIEW로 종결되며, 자동 반려(REJECT) 경로가 없습니다. "
         "시뮬레이션에서도 이 노드로 도달한 건은 모두 사람 검토 큐로 들어갑니다.",
         "라우팅 점검 완료 — 자동 반려 경로 없음"),
    ]),
]

DINING_CHAT = [
    *_chat("M-004", [
        ("회식비에서 한도 바로 아래로 여러 번 나눠 결제하는 패턴이 자꾸 보여. 이거 잡아줘.",
         "동일 행사 분할 결제 의심 노드를 추가했습니다.\n"
         "· 조건: dining.same_event_multiple_merchants == true\n"
         "· 액션: REVIEW / 심각도 HIGH / 플래그 SPLIT_PAYMENT_SUSPECTED\n"
         "· 근거: 제8조 (분할결제 의심 시 원거래 통합 검토)\n"
         "2차 확인(M-002) 다음에 배치했습니다.",
         "노드 M-004 신규 생성 · 조건·액션·라우팅 반영"),
        ("승인 주체는 회계팀장으로 해줘.",
         "확인·승인 주체를 '회계팀장'으로 변경했습니다.",
         "액션(확인·승인 주체) 변경: 회계 담당자 → 회계팀장"),
    ]),
    *_chat("M-005", [
        ("주류 포함된 회식도 표시가 필요해. 1인당 3만원 넘고 술 있으면.",
         "주류 과다 조건을 추가했습니다.\n"
         "· 조건: dining.includes_alcohol == true AND tx.per_person_amount > 30000\n"
         "· 액션: REVIEW / 심각도 LOW\n"
         "M-004 다음, 통과 노드(M-PASS) 직전에 배치했습니다.",
         "노드 M-005 신규 생성 · 조건·액션·라우팅 반영"),
        ("1인당 기준이 M-001이랑 겹치는 거 아냐?",
         "겹치지 않습니다. M-001은 5만원 초과(한도 위반) 판정이고, M-005는 3만원 초과 + 주류 포함이라는 "
         "다른 조건입니다. 다만 5만원을 넘는 주류 회식은 M-001에서 먼저 REVIEW로 종결되므로 "
         "M-005까지 도달하지 않습니다 — 중복 판정은 발생하지 않습니다.",
         ""),
        ("좋아. 이대로 검증 돌려볼게.",
         "M-001~M-005 전 노드를 '검증 대기'로 전환했습니다. 시뮬레이션 탭에서 검증셋과 "
         "직전 달 실제 내역으로 실행할 수 있습니다.",
         "노드 상태 일괄 전환: 초안 → 검증대기"),
    ]),
]

TRIP_CHAT = [
    *_chat("T-102", [
        ("출장 숙박비는 지역마다 한도가 달라. 지역 등급별 한도표를 보고 판단하게 해줘.",
         "숙박비 한도 조건을 정책 테이블 참조 방식으로 만들었습니다.\n"
         "· 조건: trip.lodging_amount_per_night > policy.lodging_limit\n"
         "· 액션: RETURN / 심각도 HIGH / 플래그 LODGING_LIMIT_OVER\n"
         "policy.lodging_limit은 지역 등급·직급에 따라 조립 단계에서 채워지므로, "
         "지역별 금액을 조건에 직접 쓰지 않아도 됩니다.",
         "노드 T-102 신규 생성 · 정책 테이블 참조 조건 적용"),
    ]),
    *_chat("T-103", [
        ("단거리인데 비즈니스석 타는 건 확인이 필요해. 6시간 기준으로.",
         "단거리 비즈니스석 조건을 추가했습니다.\n"
         "· 조건: trip.flight_class == \"BUSINESS\" AND trip.flight_duration_hours < 6\n"
         "· 액션: REVIEW / 승인 주체: 회계팀장",
         "노드 T-103 신규 생성 · 조건·액션 반영"),
        ("임원은 예외인데 그것도 조건에 넣을까?",
         "권장하지 않습니다. 직급 예외를 조건에 넣으면 인사 규정이 바뀔 때마다 그래프를 수정해야 하고, "
         "예외 판단 자체가 규정 해석 영역이라 결정론적 룰로 굳히기에 적합하지 않습니다. "
         "현재처럼 REVIEW로 넘겨 사람이 판단하는 편이 안전합니다.",
         ""),
        ("그럼 그대로 두고 검증 완료로 바꿔줘.",
         "T-101~T-PASS 전 노드를 '검증 완료'로 전환했습니다. 시뮬레이션 결과를 첨부해 "
         "Active 요청을 보낼 수 있습니다.",
         "노드 상태 일괄 전환: 검증대기 → 검증완료"),
    ]),
]


class Command(BaseCommand):
    help = "시연용 룰 그래프 시드 — GLOBAL(v3)·기업업무추진비(v2)·회식비(v1+초안)·출장비(승인대기) + TEST 그래프"

    def add_arguments(self, parser):
        parser.add_argument("--no-test", action="store_true", help="TEST 그래프는 시드하지 않습니다.")

    @transaction.atomic
    def handle(self, *args, **options):
        users = {u.username: u for u in get_user_model().objects.all()}
        lead = users.get("acclead")
        acc = users.get("acc")

        self._seed_global(lead)
        self._seed_entertain(lead, acc)
        self._seed_dining(lead, acc)
        self._seed_trip(lead, acc)
        if not options.get("no_test"):
            self._seed_test_graph()

    # ── 계열 공통 ────────────────────────────────────────────────
    def _upsert(self, family_key, version, *, name, scope, status, entry, clause, spec,
                activated=False, approver=None, reviewer=None, review_comment="", days_ago=0):
        """그래프 한 버전을 멱등 생성/갱신하고 노드·라우팅을 재구성한다."""
        snapshot = {"entry_node_key": entry, "nodes": spec["nodes"], "routings": spec["routings"]}
        validate_graph(snapshot)
        missing = validate_graph_vars(snapshot)
        if missing:
            raise ValueError(f"{name} v{version} 시드가 미정의 EvalContext 경로를 참조합니다: {sorted(missing)}")

        stamp = timezone.now() - timezone.timedelta(days=days_ago)
        if status == RuleGraphStatus.ACTIVE:
            RuleGraph.objects.filter(scope=scope, status=RuleGraphStatus.ACTIVE).exclude(
                family_key=family_key, version=version
            ).update(status=RuleGraphStatus.ARCHIVED)

        graph, _ = RuleGraph.objects.update_or_create(
            family_key=family_key, version=version,
            defaults={
                "name": name, "scope": scope, "status": status, "entry_node_key": entry,
                "source_clause": clause,
                "activated_at": stamp if activated else None,
                "approved_by": approver if activated else None,
                "reviewed_by": reviewer, "reviewed_at": stamp if reviewer else None,
                "review_comment": review_comment,
            },
        )
        graph.nodes.all().delete()
        graph.routings.all().delete()
        RuleNode.objects.bulk_create([RuleNode(graph=graph, **item) for item in spec["nodes"]])
        RuleRouting.objects.bulk_create([RuleRouting(graph=graph, **item) for item in spec["routings"]])

        if activated:
            RuleGraphVersion.objects.update_or_create(
                graph=graph, version=version,
                defaults={"snapshot": snapshot, "approved_by": approver, "approved_at": stamp,
                          "is_active": status == RuleGraphStatus.ACTIVE},
            )
        return graph

    def _messages(self, graph, rows):
        graph.messages.all().delete()
        RuleAuthoringMessage.objects.bulk_create([
            RuleAuthoringMessage(
                graph=graph, node_key=row["node_key"], role=row["role"], text=row["text"],
                applied_note=row["applied_note"], order=index,
            )
            for index, row in enumerate(rows)
        ])

    # ── ① GLOBAL ────────────────────────────────────────────────
    def _seed_global(self, lead):
        common = dict(name="법인카드 공통 필수 게이트", scope="GLOBAL", entry="R-002",
                      clause=f"{REG} 제9조②·③", approver=lead)
        self._upsert(GLOBAL_FAMILY_KEY, 1, status=RuleGraphStatus.ARCHIVED, spec=GLOBAL_V1,
                     activated=True, days_ago=120, **common)
        self._upsert(GLOBAL_FAMILY_KEY, 2, status=RuleGraphStatus.ARCHIVED, spec=GLOBAL_V2,
                     activated=True, days_ago=60, **common)
        self._upsert(GLOBAL_FAMILY_KEY, 3, status=RuleGraphStatus.ACTIVE, spec=GLOBAL_V3,
                     activated=True, days_ago=14, reviewer=lead,
                     review_comment="심야 사적사용 의심(R-006) 추가분 검증 완료 — 과탐 없음 확인 후 활성화.",
                     **common)
        self.stdout.write(self.style.SUCCESS("GLOBAL 게이트 v1·v2(보관) / v3(활성) 시드 완료"))

    # ── ② 기업업무추진비 ─────────────────────────────────────────
    def _seed_entertain(self, lead, acc):
        common = dict(name="기업업무추진비 검증 그래프", scope="접대", entry="E-001",
                      clause=f"{REG} 제11조②·제12조", approver=lead)
        self._upsert(ENTERTAIN_FAMILY_KEY, 1, status=RuleGraphStatus.ARCHIVED, spec=ENTERTAIN_V1,
                     activated=True, days_ago=90, **common)
        graph = self._upsert(ENTERTAIN_FAMILY_KEY, 2, status=RuleGraphStatus.ACTIVE, spec=ENTERTAIN_V2,
                             activated=True, days_ago=21, reviewer=acc,
                             review_comment="청탁금지법 대상(E-003)은 자동 반려 경로 없음을 확인. 봉사료 조건은 "
                                            "과탐 우려가 있어 REVIEW로 낮춘 뒤 활성화 요청합니다.",
                             **common)
        self._messages(graph, ENTERTAIN_CHAT)
        self.stdout.write(self.style.SUCCESS("기업업무추진비 v1(보관)/v2(활성) + 작성 대화 시드 완료"))

    # ── ③ 회식비 ────────────────────────────────────────────────
    # [2026-08-14] scope="식대"→"회식". 회식이 Category.MEAL의 별칭이던 시절엔 식대 그래프에
    # 얹혀갈 수밖에 없었지만(그러면 순수 식대 정산까지 전부 이 회식 전용 룰에 걸렸다), 이제
    # Category.GATHERING("회식")으로 독립했으니 그 scope로 옮긴다.
    def _seed_dining(self, lead, acc):
        common = dict(name="회식비 검증 그래프", scope="회식", entry="M-003",
                      clause=f"{REG} 제14조", approver=lead)
        self._upsert(DINING_FAMILY_KEY, 1, status=RuleGraphStatus.ACTIVE, spec=DINING_V1,
                     activated=True, days_ago=45, **common)
        draft = self._upsert(DINING_FAMILY_KEY, 2, status=RuleGraphStatus.DRAFT, spec=DINING_V2, **common)
        self._messages(draft, DINING_CHAT)
        self.stdout.write(self.style.SUCCESS("회식비 v1(활성)/v2(수정중·검증대기) + 작성 대화 시드 완료"))

    # ── ④ 출장비 ────────────────────────────────────────────────
    def _seed_trip(self, lead, acc):
        graph = self._upsert(
            TRIP_FAMILY_KEY, 1, name="출장비 검증 그래프", scope="출장", entry="T-102",
            clause=f"{REG} 제16조·제17조", status=RuleGraphStatus.SIMULATED, spec=TRIP_V1,
            reviewer=acc, review_comment=TRIP_REVIEW_COMMENT, days_ago=2,
        )
        self._messages(graph, TRIP_CHAT)
        self._seed_trip_simulation(graph, acc)
        self.stdout.write(self.style.SUCCESS("출장비 v1(승인대기) + 검토보고서·검증셋·시뮬레이션 시드 완료"))

    def _seed_trip_simulation(self, graph, actor):
        """검증셋을 저장하고 실제 엔진으로 시뮬레이션을 1회 돌려 보고서를 남긴다."""
        from domain.policies import simulation

        simulation.replace_test_cases(graph, [
            {"id": case["key"], "label": case["label"], "merchant": case["merchant"],
             "amount": case["amount"], "category": case["category"], "merchantType": "",
             "paymentMethod": "법인카드", "expected": case["expected"], "facts": case["facts"]}
            for case in TRIP_TEST_CASES
        ], actor)
        graph.simulation_runs.all().delete()
        simulation.run_and_save(graph, simulation.test_cases_of(graph), actor)

    # ── ⑤ TEST 그래프 ───────────────────────────────────────────
    def _seed_test_graph(self):
        self._upsert(TEST_FAMILY_KEY, 1, name="구조 검증용 TEST 그래프", scope="TEST_DEMO",
                     entry="T-00", clause="TEST 픽스처 (규정 근거 없음, RULE_SCOPE_CHOICES 밖 값이라 실거래와 절대 매칭되지 않는다)",
                     status=RuleGraphStatus.DRAFT, spec=TEST_GRAPH)
        self.stdout.write(self.style.SUCCESS(
            f"TEST 그래프 시드 완료: 노드 {len(TEST_NODES)} / 라우팅 {len(TEST_ROUTINGS)} (전부 검증대기)"
        ))

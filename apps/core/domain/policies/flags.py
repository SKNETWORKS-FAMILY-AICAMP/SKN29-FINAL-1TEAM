"""네임드 플래그 레지스트리 — 판정이 남기는 **사유 코드**의 단일 진실 원천.

## 플래그는 무엇이고, 무엇이 아닌가

플래그는 "왜 걸렸는가"다. 판정 결과(`decision`)에 딸린 **설명**이지 결정 자체가 아니다.

> **불변식: 플래그는 상태머신을 움직이지 않는다.**

정산 상태는 `decision`(PASS/RETURN/REJECT/REVIEW) **한 축**이 정한다
(`settlements/services.py::JUDGE_MAP`). 플래그가 상태를 바꾸기 시작하면 세 가지가 깨진다:

  ① **두 축이 충돌한다** — `decision=PASS`인데 `flag=PRE_APPROVAL_MISSING`이면 뭐가 이기나.
     룰 작성자에게 `decision`은 의도해서 고른 드롭다운이고 `flag`는 사유를 적는 텍스트 칸이다.
     설명하려고 적은 글자가 자기가 고른 판정을 덮어쓰면 안 된다.
  ② **보이지 않는 간선이 생긴다** — 노드 B가 "A가 걸렸을 때만" 돌아야 하면 그건 라우팅
     간선(`A --MATCH--> B`)이다. 플래그 조건으로 만들면 룰 콘솔 플로우차트에 안 그려진다.
     (지금은 `validate_graph_vars`가 `EVAL_CONTEXT_SCHEMA_PATHS` 밖 참조를 막아 문법적으로도 불가능하다.)
  ③ **재현이 깨진다** — 판정은 `rule_hits.eval_context` + `graph_snapshot` 둘로 완전히
     되돌릴 수 있게 설계돼 있다. 이 레지스트리가 **행동**을 가지면 스냅샷되지 않는 세 번째
     입력이 생겨, admin에서 행 하나 고치면 과거 판정을 설명할 수 없게 된다.

그래서 레지스트리 행이 갖는 건 **표시·분류 속성**(라벨·설명·심각도·해소 주체)뿐이다.
그 선 안에서 쓰임은 넓다 — 화면 강조, 큐 정렬·묶음, 사유 프리셋, 집계·거버넌스 지표,
Risk Review 2차 프롬프트 입력, 룰 정밀도 측정, ERP 전표 적요.

## 두 계층

  · **시스템 플래그**(`SystemFlag`) — 엔진·오케스트레이터가 만든다. 고객이 못 만든다.
    → **닫힌 enum**. 여기 코드가 SoT다.
  · **룰 플래그**(`RuleFlag` 테이블) — 룰 노드 `action.flag`가 만든다. 고객 규정에서
    Rule Agent가 생성하므로 **새 코드가 생길 수 있다** → **열린 레지스트리**.
    미등록 플래그도 **동작은 한다**(원문 표시) — 닫으면 고객 룰 생성이 막힌다.
    대신 ACTIVE 전환 시 경고로 남긴다(`unknown_flags`).

## ⚠️ `code`는 불변이다

플래그는 Risk Review 프롬프트 입력이자 룰 정밀도 집계의 키가 된다 — 즉 **데이터 계약**이다.
이름을 바꾸면 과거 통계와 비교가 끊긴다. `Position`/`JobTitle`과 같은 규율을 쓴다:
**`code`는 키(불변), `label`만 수정 가능.**
"""
from __future__ import annotations

from django.db import models


class SystemFlag(models.TextChoices):
    """엔진·오케스트레이터가 스스로 붙이는 플래그 (닫힌 집합).

    룰이 만드는 게 아니라 **판정 자체가 불가능하거나 불완전했다**는 신고다. 그래서 고객
    규정과 무관하고, 새 값은 코드 변경으로만 생긴다.

    `UNRESOLVED_*`만 인자를 갖는다(`UNRESOLVED_FACT:approval.pre_approval_obtained`).
    인자가 **경로 문자열**이라 코드 안에서만 의미가 있고 사람이 바꿀 일이 없어서 괜찮다
    — 직책·과목처럼 사람이 표기를 바꾸는 값을 플래그 문자열에 박으면 대조가 안 되는
    사본이 하나 더 생긴다(그때는 별도 구조 필드를 쓴다).
    """
    UNRESOLVED_POLICY_VAR = "UNRESOLVED_POLICY_VAR", "규정 임계값 미적재"
    UNRESOLVED_FACT = "UNRESOLVED_FACT", "판정 정보 부족"
    NO_ACTIVE_RULE_GRAPH = "NO_ACTIVE_RULE_GRAPH", "적용할 규칙 없음"
    NO_SCOPE_RULE_GRAPH = "NO_SCOPE_RULE_GRAPH", "과목 규칙 없음"
    INVALID_RULE_GRAPH = "INVALID_RULE_GRAPH", "규칙 그래프 오류"
    RULE_GRAPH_CYCLE = "RULE_GRAPH_CYCLE", "규칙 순환"
    NO_TERMINAL_DECISION = "NO_TERMINAL_DECISION", "판정 미종결"


#: 인자를 붙여 쓰는 시스템 플래그 접두사 — `<코드>:<인자>` 꼴.
PARAMETERIZED = (SystemFlag.UNRESOLVED_POLICY_VAR, SystemFlag.UNRESOLVED_FACT)

SEPARATOR = ":"


def split_flag(flag: str) -> tuple[str, str]:
    """`CODE:인자` → `(CODE, 인자)`. 인자가 없으면 `("CODE", "")`."""
    code, sep, arg = flag.partition(SEPARATOR)
    return (code, arg) if sep else (flag, "")


class FlagCategory(models.TextChoices):
    """화면 묶음·집계 축. 회계 담당자가 "같은 성격끼리 모아 처리"할 수 있게 한다."""
    EVIDENCE = "EVIDENCE", "증빙·기재"
    APPROVAL = "APPROVAL", "결재·승인"
    LIMIT = "LIMIT", "한도"
    MERCHANT = "MERCHANT", "가맹점·분류"
    PATTERN = "PATTERN", "시점·패턴"
    TAX = "TAX", "세무·법령"
    JUDGEMENT = "JUDGEMENT", "종합 판단"
    SYSTEM = "SYSTEM", "판정 불능"


class FlagSeverity(models.TextChoices):
    """검토 큐 정렬의 2차 키. `anomaly_score` 단일 정렬만으로는 성격이 안 보인다."""
    INFO = "INFO", "참고"
    LOW = "LOW", "낮음"
    MEDIUM = "MEDIUM", "보통"
    HIGH = "HIGH", "높음"
    CRITICAL = "CRITICAL", "심각"


class FlagOwner(models.TextChoices):
    """**누가 이걸 해소하는가.** 화면이 "고쳐주세요"와 "결재해주세요"를 구분하려면 필요하다.

    상태를 정하지 않는다 — 어느 버튼을 보여줄지에만 쓴다.
    """
    SPENDER = "SPENDER", "지출자"
    TEAM_LEAD = "TEAM_LEAD", "팀장"
    APPROVER = "APPROVER", "결재권자"
    ACCOUNTING = "ACCOUNTING", "회계"
    SYSTEM = "SYSTEM", "관리자(시스템)"


# ─────────────────────────────────────────────────────────────────────────────
#  기준 레지스트리
#
#  ⚠️ 이 목록은 **제품 기본 어휘**지 고객 규정이 아니다. 고객 문서에서 Rule Agent가
#     새 플래그를 만들면 레지스트리에 추가된다(닫지 않는다, 모듈 docstring 참조).
#
#  (code, label, category, severity, owner, description)
# ─────────────────────────────────────────────────────────────────────────────
_C, _S, _O = FlagCategory, FlagSeverity, FlagOwner

RULE_FLAGS: list[tuple[str, str, str, str, str, str]] = [
    # ── 증빙·기재 ─────────────────────────────────────────────────────────
    ("EVIDENCE_MISSING", "적격증빙 없음", _C.EVIDENCE, _S.HIGH, _O.SPENDER,
     "카드매출전표 등 적격증빙이 첨부되지 않았다. 세법상 손금 요건과 직결된다."),
    ("PURPOSE_UNCLEAR", "지출 목적 불명확", _C.EVIDENCE, _S.MEDIUM, _O.SPENDER,
     "목적이 비어 있거나 업무관련성을 판단할 수 없다."),
    ("ACTUAL_USER_REQUIRED", "실사용자 미등록", _C.EVIDENCE, _S.MEDIUM, _O.SPENDER,
     "공용·팀 카드 결제인데 실사용자가 기록되지 않았다(「법인카드 사용 규정」 제6조)."),
    ("PARTICIPANT_LIST_REQUIRED", "참석자 명단 필요", _C.EVIDENCE, _S.MEDIUM, _O.SPENDER,
     "기업업무추진비·회식 등 참석자 확인이 필요한 지출인데 명단이 없다."),
    ("RECEIPT_ILLEGIBLE", "영수증 판독 불가", _C.EVIDENCE, _S.MEDIUM, _O.SPENDER,
     "첨부는 있으나 비전 판독으로 금액·가맹점을 읽어내지 못했다."),

    # ── 결재·승인 ─────────────────────────────────────────────────────────
    ("PRE_APPROVAL_MISSING", "사전승인 누락", _C.APPROVAL, _S.HIGH, _O.APPROVER,
     "별표1 직책별 기준액을 넘는 지출인데 사전승인 기록이 없다."),
    ("POST_APPROVAL_REQUIRED", "사후승인 필요", _C.APPROVAL, _S.MEDIUM, _O.APPROVER,
     "긴급 집행 등으로 사전승인 없이 지출돼 사후 결재가 필요하다."),
    ("APPROVER_RANK_INSUFFICIENT", "결재자 직책 미달", _C.APPROVAL, _S.HIGH, _O.APPROVER,
     "결재자의 직책이 그 금액대의 승인권자에 못 미친다."),
    ("SELF_APPROVAL", "자기결재", _C.APPROVAL, _S.HIGH, _O.ACCOUNTING,
     "지출자와 결재자가 같다."),

    # ── 한도 ─────────────────────────────────────────────────────────────
    ("DAILY_LIMIT_OVER", "1일 한도 초과", _C.LIMIT, _S.HIGH, _O.ACCOUNTING,
     "별표1 직책별 1일 사용 한도를 넘었다."),
    ("MONTHLY_LIMIT_OVER", "월 한도 초과", _C.LIMIT, _S.HIGH, _O.ACCOUNTING,
     "별표1 직책별 월 사용 한도를 넘었다."),
    ("PER_PERSON_LIMIT_OVER", "1인당 한도 초과", _C.LIMIT, _S.MEDIUM, _O.ACCOUNTING,
     "회식·식대의 1인당 한도를 넘었다."),
    ("LODGING_LIMIT_OVER", "숙박비 한도 초과", _C.LIMIT, _S.MEDIUM, _O.ACCOUNTING,
     "출장 지역등급별 1박 한도를 넘었다."),
    ("HIGH_AMOUNT", "고액 지출", _C.LIMIT, _S.LOW, _O.ACCOUNTING,
     "한도 위반은 아니나 금액대가 높아 확인이 권장된다."),

    # ── 가맹점·분류 ───────────────────────────────────────────────────────
    ("PROHIBITED_MERCHANT", "금지 업종", _C.MERCHANT, _S.CRITICAL, _O.ACCOUNTING,
     "금지업종·사행성업종 결제(「법인카드 사용 규정」 제9조)."),
    ("WATCH_MERCHANT", "주의 업종", _C.MERCHANT, _S.MEDIUM, _O.ACCOUNTING,
     "금지는 아니나 업무관련성 소명이 필요한 업종이다."),
    ("MERCHANT_UNRESOLVED", "업종 미확정", _C.MERCHANT, _S.LOW, _O.SYSTEM,
     "가맹점 업종을 확정하지 못했다(카카오 조회·LLM 재분류 모두 실패)."),
    ("LOW_CATEGORY_CONFIDENCE", "분류 저신뢰", _C.MERCHANT, _S.LOW, _O.SPENDER,
     "AI 비용분류 신뢰도가 낮아 사용자 확인이 필요하다."),

    # ── 시점·패턴 ─────────────────────────────────────────────────────────
    ("OFF_HOURS", "심야·주말 결제", _C.PATTERN, _S.LOW, _O.ACCOUNTING,
     "업무시간 외 결제. 그 자체로 위반은 아니며 맥락 확인 신호다."),
    ("LATE_SETTLEMENT", "정산 지연", _C.PATTERN, _S.LOW, _O.SPENDER,
     "지출일로부터 규정 기한을 넘겨 정산됐다."),
    ("REPEATED_VENDOR", "동일 가맹점 반복", _C.PATTERN, _S.LOW, _O.ACCOUNTING,
     "짧은 기간 같은 가맹점에서 반복 결제됐다."),
    ("SECONDARY_VENUE", "2차 성격 지출", _C.PATTERN, _S.MEDIUM, _O.ACCOUNTING,
     "같은 날 연속된 2차 결제로 보인다(「회식 운영규정」)."),
    ("ALCOHOL_HEAVY", "주류 비중 과다", _C.PATTERN, _S.MEDIUM, _O.ACCOUNTING,
     "품목 판독 결과 주류 비중이 높다."),
    ("SPLIT_PAYMENT_SUSPECTED", "분할결제 의심", _C.PATTERN, _S.HIGH, _O.ACCOUNTING,
     "한도를 피하려 한 건을 나눠 결제한 정황이다."),

    # ── 세무·법령 ─────────────────────────────────────────────────────────
    ("NON_DEDUCTIBLE_RISK", "손금불산입 위험", _C.TAX, _S.HIGH, _O.ACCOUNTING,
     "적격증빙 미수취 등으로 손금 부인 소지가 있다(법인세법)."),
    ("KICKBACK_LAW_RISK", "청탁금지법 위험", _C.TAX, _S.CRITICAL, _O.ACCOUNTING,
     "청탁금지법 대상자 접대이며 유형별 한도가 걸린다."),
    ("NON_CORPORATE_CARD", "법인카드 아님", _C.TAX, _S.HIGH, _O.SPENDER,
     "법인카드가 아닌 수단으로 결제됐다."),
    ("PROHIBITED_PAYMENT_METHOD", "금지 결제수단", _C.TAX, _S.HIGH, _O.SPENDER,
     "현금·상품권 등 규정이 금지한 결제수단이다."),

    # ── 종합 판단 ─────────────────────────────────────────────────────────
    #  `personal_use_suspected`는 EvalContext v3에서 **입력**으로 있다가 "결론을 입력받고
    #  있었다"는 이유로 삭제된 필드다. 룰 그래프가 조합해 내놓는 **출력**으로는 여기가 제자리다.
    ("PERSONAL_USE_SUSPECTED", "사적 사용 의심", _C.JUDGEMENT, _S.HIGH, _O.ACCOUNTING,
     "여러 신호가 겹쳐 업무 외 사용으로 의심된다."),
]


def seed_rule_flags() -> int:
    """룰 플래그 기준 어휘를 멱등 적재한다. Returns 적재 후 총 행 수.

    `code`가 키다 — `label`을 고쳐도 과거 `rule_hits`·집계가 끊기지 않는다.
    고객 규정에서 생긴 플래그는 지우지 않는다(여기 없다고 남의 어휘를 치우면 안 된다).
    """
    from .models import RuleFlag

    for code, label, category, severity, owner, description in RULE_FLAGS:
        RuleFlag.objects.update_or_create(
            code=code,
            defaults={
                "label": label, "category": category, "severity": severity,
                "owner": owner, "description": description, "is_system": False,
            },
        )
    for choice in SystemFlag:
        RuleFlag.objects.update_or_create(
            code=choice.value,
            defaults={
                "label": choice.label, "category": FlagCategory.SYSTEM,
                "severity": FlagSeverity.MEDIUM, "owner": FlagOwner.SYSTEM,
                "description": "엔진이 판정 자체의 한계를 신고하는 플래그다. 룰이 만들지 않는다.",
                "is_system": True,
            },
        )
    return RuleFlag.objects.count()


def unknown_flags(snapshot: dict) -> list[str]:
    """그래프가 쓰는 `action.flag` 중 레지스트리에 없는 코드.

    **거부가 아니라 경고용이다.** 고객 규정에서 생성된 룰이 새 어휘를 쓸 수 있고, 여기서
    막으면 룰 생성 자체가 멈춘다(제품 원칙: 룰은 고객 문서에서 만들어진다). 대신 ACTIVE
    전환 응답에 실어 "이 이름이 의도한 것인지" 사람이 보게 한다 — 오타(`EVIDENCE_MISSNG`)와
    새 어휘를 시스템이 구별할 방법은 없고, 아는 사람은 승인하는 사람뿐이다.
    """
    from .models import RuleFlag

    used = {
        split_flag(str(flag))[0]
        for node in snapshot.get("nodes", [])
        if (flag := (node.get("action") or {}).get("flag"))
    }
    if not used:
        return []
    known = set(RuleFlag.objects.filter(code__in=used).values_list("code", flat=True))
    return sorted(used - known)


def label_map() -> dict[str, dict]:
    """`code → 표시 정보` 사전. 화면이 라벨 사전을 따로 들지 않게 서버가 실어 보낸다.

    프론트에 같은 목록을 복사해 두면 곧 어긋난다 — 실제로 어긋나 있었다(백엔드 27개 vs
    프론트 9개). 호출부는 요청당 한 번만 부르고 결과를 재사용한다.

    **분류·심각도·해소주체의 한글 표기까지 함께 싣는다.** 코드(`HIGH`·`SPENDER`)만 보내면
    화면이 그 사전을 또 복사하게 되고, 그게 정확히 이 파일이 막으려던 상황이다.
    """
    from .models import RuleFlag

    cat, sev, own = dict(FlagCategory.choices), dict(FlagSeverity.choices), dict(FlagOwner.choices)
    return {
        r.code: {
            "code": r.code, "label": r.label, "description": r.description,
            "severity": r.severity, "severityLabel": sev.get(r.severity, r.severity),
            "owner": r.owner, "ownerLabel": own.get(r.owner, r.owner),
            "category": r.category, "categoryLabel": cat.get(r.category, r.category),
            "isSystem": r.is_system,
        }
        for r in RuleFlag.objects.filter(is_active=True)
    }


def describe(flag: str, labels: dict[str, dict] | None = None) -> dict:
    """플래그 문자열 하나를 표시 정보로 편다. 인자가 붙은 시스템 플래그도 처리한다.

    미등록 코드는 **감추지 않고** 코드 그대로 라벨에 넣는다 — 숨기면 판정 근거가 사라지고,
    오타를 아무도 못 본다.
    """
    labels = label_map() if labels is None else labels
    code, arg = split_flag(flag)
    row = labels.get(code)
    label = row["label"] if row else code
    if arg:
        label = f"{label}({arg})"
    return {
        "code": code, "arg": arg, "flag": flag, "label": label,
        "description": (row or {}).get("description", ""),
        "severity": (row or {}).get("severity", ""),
        "severityLabel": (row or {}).get("severityLabel", ""),
        "owner": (row or {}).get("owner", ""),
        "ownerLabel": (row or {}).get("ownerLabel", ""),
        "category": (row or {}).get("category", ""),
        "categoryLabel": (row or {}).get("categoryLabel", ""),
        "isSystem": (row or {}).get("isSystem", False),
        "known": row is not None,
    }

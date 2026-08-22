"""섹션 레지스트리 — 카탈로그 하나 = 섹션 하나.

각 빌더는 **live 모델·enum만 읽어** JSON 직렬화 가능한 dict를 돌려준다. 값을 여기
적어 두면 그 순간 사본이 되므로, 어떤 리터럴도 이 파일에서 새로 태어나지 않는다
(리터럴이 보이면 그건 옮겨온 게 아니라 원래 없던 어휘다 — 지금은 `notes`뿐이다).

섹션 dict 형태::

    {"id": "dsl.grammar", "title": "...", "data": {...}, "notes": ["...", ...]}

`notes`는 **도메인 불변식**이다(표현이 아니라 규칙). 예: "엔진은 최종반려를 만들지
않는다". 이걸 ai 쪽 렌더러에 두면 core가 규칙을 바꿔도 프롬프트는 옛말을 계속 한다.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

from django.utils import timezone


# ─────────────────────────────────────────────────────────────── dsl.grammar

def _dsl_grammar(_params: dict) -> dict[str, Any]:
    """연산자 화이트리스트 — `policies/dsl.py`가 실제로 검증에 쓰는 집합 그대로."""
    from domain.policies import dsl

    return {
        "data": {
            "logic_operators": sorted(dsl.LOGIC_OPERATORS),
            "compare_operators": sorted(dsl.COMPARE_OPERATORS),
            "value_operator": "var",
            "max_depth": dsl.MAX_DEPTH,
        },
        "notes": [
            "위 목록이 전부다. 산술 연산자(+ - * /)가 **없다** — 계산이 필요한 값은 조립기가 "
            "미리 넣어둔 필드(`tx.per_person_amount` 등)를 쓴다.",
            "`var`의 인자는 dot-path 문자열 하나다. 허용 경로 목록 밖의 경로는 활성화 검증에서 거부된다.",
            "`in`의 우변은 **리터럴 목록만** 온다(경로 불가). 좌변이 null이면 결과는 항상 거짓이다.",
            "타입이 다르면 비교는 참이 되지 않는다(문자열 `\"30000\"`과 숫자 `30000`은 다르다).",
            "null은 「거짓」이 아니라 「모름」이다. 대소 비교(`>` `>=` `<` `<=`)는 한쪽이 null이면 "
            "항상 거짓이고, `==`/`!=`만 null끼리의 동일성을 본다.",
            "⚠️ 그래서 `!=`는 값을 **모를 때 참이 된다**(`x != 5`는 x가 null이면 참). "
            "「~가 아니면 걸린다」는 룰은 `!=` 하나로 쓰지 말고 값의 존재를 함께 확인해라.",
        ],
    }


# ────────────────────────────────────────────────────── eval_context.paths

def _eval_context_paths(_params: dict) -> dict[str, Any]:
    """룰 조건이 참조할 수 있는 사실 목록 + 타입 + 한 줄 설명."""
    from domain.policies.context_builder import policy_field_specs
    from domain.policies.eval_context import schema_catalog

    # 적재된 별표가 만드는 `policy.*`까지 함께 싣는다 — 프롬프트가 아는 목록과
    # `validate_graph_vars`가 강제하는 목록이 갈리면 이 계층의 존재 이유가 없어진다.
    return {
        "data": schema_catalog(policy_field_specs()),
        "notes": [
            "여기 없는 경로를 쓴 그래프는 ACTIVE로 전환되지 않는다. 표현할 사실이 없으면 "
            "룰을 지어내지 말고 건너뛴 사유를 남겨라.",
            "값이 `null`이면 「거짓」이 아니라 **「모른다」**다. 룰이 실제로 참조한 경로가 null이면 "
            "엔진이 판정을 「검토 필요」로 낮춘다(미해소 가드) — 조용히 통과시키지 않는다.",
            "`policy.*`는 규정 별표에서 미리 뽑아 둔 숫자다. 한도·기준액은 숫자 리터럴로 적지 말고 "
            "이 경로를 좌·우변에 써라(규정이 개정되면 표만 바뀌고 룰은 그대로다).",
            "`tables`·`conflicts`는 감사용 동적 섹션이라 고정 필드가 없고 룰이 참조할 수 없다.",
            "`enum`이 붙은 필드는 값 어휘가 따로 있다. 그 목록에 없는 표기로 비교하면 에러가 아니라 "
            "**조용히 안 걸린다** — 반드시 해당 어휘 섹션의 표기를 그대로 써라.",
        ],
    }


# ─────────────────────────────────────────────────────────────── policy.vars

def _policy_vars(_params: dict) -> dict[str, Any]:
    """`policy.*`가 어느 별표에서, 어떤 축으로 해소되는지 + **지금 적재돼 있는지**.

    목록이 고정 8종이 아니라 `policy_fields()`인 이유: 고객이 올린 규정에서 새 별표가
    들어오면 그것도 룰이 쓸 수 있는 변수라, 프롬프트가 모르면 모델은 그 값을 숫자
    리터럴로 박는다(규정이 개정돼도 안 따라간다).
    """
    from domain.policies.context_builder import DERIVED_FROM_TABLE, load_tables, policy_fields

    tables = load_tables()

    def row(path: str, table_key: str) -> dict[str, Any]:
        t = tables.get(table_key)
        return {
            "path": path,
            "table_key": table_key,
            "title": t.title if t else None,
            "key_axes": list(t.key_axes or []) if t else None,
            "strict_keys": t.strict_keys if t else None,
            "effective_date": t.effective_date.isoformat() if t else None,
            "source_clause": t.source_clause if t else None,
            # 적재돼 있지 않은 임계값을 룰이 참조하면 판정이 통째로 REVIEW로 떨어진다.
            # 「쓸 수 있는가」를 모델에게 숨기면 쓸 수 없는 룰을 자신 있게 만든다.
            "loaded": t is not None,
        }

    return {
        "data": {
            "vars": [row(f"policy.{name}", key) for name, key in policy_fields(tables).items()],
            "derived": [row(path, key) for path, key in DERIVED_FROM_TABLE.items()],
        },
        "notes": [
            "`key_axes`는 그 별표가 어떤 사실로 값을 고르는지다. 축에 해당하는 사실이 null이면 "
            "임계값도 해소되지 않는다 — 축 필드를 조건에 함께 두면 왜 검토로 갔는지가 드러난다.",
            "`loaded=false`인 임계값을 참조하는 룰은 실제 판정에서 전건 「검토 필요」가 된다. "
            "그 별표가 적재되기 전이라면 룰을 만들지 말고 사유를 남겨라.",
            "금지업종처럼 `strict_keys=true`인 표는 축 값을 모르면 해소하지 않는다 — "
            "「모르니까 안전」이라고 단정하지 않기 위해서다.",
        ],
    }


# ────────────────────────────────────────────────────────────── action.schema

def _action_schema(_params: dict) -> dict[str, Any]:
    """판정(decision)·심각도(severity) 선택지 + 그 판정이 정산을 어디로 보내는지."""
    from domain.policies.engine import DECISIONS_CATALOG, PASS_THROUGH, SEVERITIES_CATALOG
    from domain.settlements.models import SettlementStatus
    from domain.settlements.services import JUDGE_MAP

    labels = dict(SettlementStatus.choices)
    return {
        "data": {
            "decisions": list(DECISIONS_CATALOG),
            "severities": list(SEVERITIES_CATALOG),
            "pass_through": PASS_THROUGH,
            "decision_effect": {
                d: {"status": s, "label": labels.get(s, s)} for d, s in JUDGE_MAP.items()
            },
        },
        "notes": [
            "`severity`는 순서가 있다 — 앞이 더 심각하다. 검토 큐 정렬에 쓰이지 상태를 바꾸진 않는다.",
            f"`{PASS_THROUGH}`는 판정을 내리지 않고 다음 노드로 넘기는 특수값이다(중간 분기 노드용).",
            "**엔진은 최종반려를 만들지 않는다.** 노드 `decision`이 REJECT여도 정산은 "
            "「보완요청(RETURNED)」으로 간다 — 재제출 불가 단말은 회계 담당자만 찍을 수 있다.",
            "판정을 결정하는 축은 `decision` **하나**다. `flag`는 사유 설명일 뿐 상태를 바꾸지 않는다.",
        ],
    }


# ───────────────────────────────────────────────────────────── flags.registry

def _flags_registry(_params: dict) -> dict[str, Any]:
    """`action.flag`에 쓸 수 있는 사유 코드 어휘.

    DB(`RuleFlag`)가 정본이지만 아직 동기화 전(빈 테이블)일 수 있다 — 그때는 같은 값의
    원천인 `flags.RULE_FLAGS` 상수로 떨어진다. 사본이 아니라 **DB를 채우는 그 목록**이다.
    """
    from domain.policies.flags import RULE_FLAGS, FlagCategory, FlagOwner, FlagSeverity, SystemFlag
    from domain.policies.models import RuleFlag

    rows = list(
        RuleFlag.objects.filter(is_active=True, is_system=False).order_by("category", "code")
        .values("code", "label", "category", "severity", "owner", "description")
    )
    source = "db"
    if not rows:
        source = "code"
        rows = [
            {"code": c, "label": l, "category": cat, "severity": sev, "owner": own, "description": desc}
            for c, l, cat, sev, own, desc in RULE_FLAGS
        ]

    return {
        "data": {
            "source": source,
            "rule_flags": rows,
            "system_flags": [{"code": f.value, "label": f.label} for f in SystemFlag],
            "categories": {c.value: c.label for c in FlagCategory},
            "severities": {s.value: s.label for s in FlagSeverity},
            "owners": {o.value: o.label for o in FlagOwner},
        },
        "notes": [
            "새 코드를 만들기 전에 **이 목록에서 같은 뜻을 먼저 찾아라.** 미등록 코드도 동작은 "
            "하지만(고객 규정에서 새 어휘가 생기는 게 제품 전제) ACTIVE 승인 화면에 경고로 뜬다.",
            "`code`는 불변 데이터 계약이다(과거 판정 통계·Risk Review 입력의 키). 표기를 바꾸고 "
            "싶으면 `label`을 고치지 코드를 새로 만들지 마라.",
            "시스템 플래그는 엔진이 스스로 붙인다 — 룰이 쓰면 안 된다.",
            "`owner`는 「누가 이걸 해소하는가」다. 지출자가 못 고치는 일을 지출자 소유 플래그로 "
            "달면 화면이 엉뚱한 버튼을 보여준다.",
        ],
    }


# ───────────────────────────────────────────────────────────────── 레지스트리

_TITLES = {
    "dsl.grammar": "조건식 DSL 문법 (연산자 화이트리스트)",
    "eval_context.paths": "판정에 쓸 수 있는 사실 목록 (EvalContext)",
    "policy.vars": "규정 임계값 변수와 그 출처 별표",
    "action.schema": "판정·심각도 선택지",
    "flags.registry": "사유 플래그 어휘",
}

BUILDERS: dict[str, Callable[[dict], dict[str, Any]]] = {
    "dsl.grammar": _dsl_grammar,
    "eval_context.paths": _eval_context_paths,
    "policy.vars": _policy_vars,
    "action.schema": _action_schema,
    "flags.registry": _flags_registry,
}


def build_section(section_id: str, params: dict | None = None) -> dict[str, Any]:
    builder = BUILDERS.get(section_id)
    if builder is None:
        raise KeyError(section_id)
    built = builder(params or {})
    return {
        "id": section_id,
        "title": _TITLES.get(section_id, section_id),
        "data": built["data"],
        "notes": built.get("notes", []),
    }


def etag_of(sections: list[dict[str, Any]]) -> str:
    """카탈로그 내용 해시.

    생성물(`RuleGraph.generation_meta`·trace)에 함께 남겨 "이 룰은 어떤 어휘로 만들어졌나"를
    나중에 되짚게 한다. 플래그가 27종이던 시절의 생성물을 지금 목록으로 설명하면 어긋난다.
    """
    blob = json.dumps(sections, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def build(section_ids: list[str], params: dict | None = None) -> dict[str, Any]:
    sections = [build_section(sid, params) for sid in section_ids]
    return {
        "sections": sections,
        "etag": etag_of(sections),
        "generatedAt": timezone.now().isoformat(),
    }

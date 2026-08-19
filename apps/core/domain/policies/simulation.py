"""룰 그래프 시뮬레이션 — 플레이스홀더 보고서 (FR-RV-02).

대량 재현·LLM 요약을 갖춘 실제 파이프라인 이전의 자리표시자다. 다만 판정은 흉내내지 않고
**실제 룰 엔진**으로 돌린다:

- EvalContext는 정산/거래에서 얕게 조립한 부분 컨텍스트다. 채우지 못한 필드는 ``None``으로
  남고, DSL은 ``None`` 비교를 안전하게 거짓 처리한다(dsl.py).
- Agent 의견은 그래프 구조와 결과 통계에서 **규칙 기반으로 생성한 마크다운**이다(LLM 호출 없음).
  실제 Agent 연동 시 이 함수만 교체하면 된다.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.db import transaction as db_tx
from django.utils import timezone

from domain.settlements.models import Settlement, SettlementStatus

from .context_builder import apply_facts, build_rule_context, load_tables, resolve_policy
from .engine import GraphValidationError, run_rule_engine, validate_graph
from . import scope as policies_scope
from .eval_context import empty_eval_context
from .models import (
    RuleGraph, RuleSimulationResult, RuleSimulationRun, RuleTestCase, SimulationSource,
)
from .snapshot import graph_snapshot as _graph_snapshot
from .snapshot import snapshot_hash as _snapshot_hash

HISTORY_LIMIT = 40
REVIEW_DECISIONS = {"REVIEW"}
RISK_DECISIONS = {"REVIEW", "RETURN", "REJECT"}
# 사람 손이 필요했던(=자동처리되지 못한) 상태. 자동처리율 계산에서 제외한다.
MANUAL_STATUSES = {
    SettlementStatus.IN_REVIEW, SettlementStatus.SUBMITTED, SettlementStatus.RPA_JUDGED,
    SettlementStatus.RETURNED, SettlementStatus.TEAM_RETURNED,
    SettlementStatus.REJECT, SettlementStatus.TEAM_REJECTED,
}
# 정산 상태 → 그래프 판정과 비교할 "기존 분류".
BASELINE_BY_STATUS = {
    SettlementStatus.IN_REVIEW: "REVIEW", SettlementStatus.SUBMITTED: "REVIEW",
    SettlementStatus.RPA_JUDGED: "REVIEW",
    SettlementStatus.RETURNED: "RETURN", SettlementStatus.TEAM_RETURNED: "RETURN",
    SettlementStatus.REJECT: "REJECT", SettlementStatus.TEAM_REJECTED: "REJECT",
    SettlementStatus.PENDING_CONFIRM: "PASS", SettlementStatus.CONFIRMED: "PASS",
    SettlementStatus.ERP_VOUCHER_DRAFTED: "PASS",
}
DECISION_KO = {"PASS": "통과", "REVIEW": "검토 필요", "RETURN": "보완요청", "REJECT": "반려", "": "미처리"}
# 엔진이 직접 붙이는 고정 플래그만 번역한다(engine.py·orchestrator.py 참조). 룰 노드가
# 스스로 붙이는 플래그(예: "M-001")는 회사 규정마다 다른 임의 코드라 사전 번역이 불가능하다
# — 그런 코드는 원문 그대로 두고 "자세히" 영역에서만 보여준다(§7 문구 다듬기 설계).
SYSTEM_FLAG_KO = {
    "NO_ACTIVE_RULE_GRAPH": "적용할 룰 그래프가 아예 없음",
    "NO_SCOPE_RULE_GRAPH": "이 비용 분류에 세부 룰이 없음(공통 게이트만 통과)",
    "UNRESOLVED_POLICY_VAR": "규정표에서 값을 찾지 못함(별표 미등록)",
}


def _flag_label(flag: str) -> str:
    """엔진 고정 플래그는 한글로, 룰 작성자가 붙인 임의 코드는 원문 그대로."""
    if flag in SYSTEM_FLAG_KO:
        return SYSTEM_FLAG_KO[flag]
    if flag.startswith("UNRESOLVED_FACT:"):
        return f"판단에 필요한 정보 없음({flag.split(':', 1)[1]})"
    return flag


# ── EvalContext 조립 ─────────────────────────────────────────────
def context_from_case(case: dict[str, Any], tables: dict[str, Any] | None = None) -> dict[str, Any]:
    """검증 케이스 → EvalContext.

    실 정산에서 온 케이스(`_settlement`)는 **운영과 같은 조립기**를 탄다 — 시뮬레이션 결과가
    실제 판정과 어긋나지 않게 하기 위해서다. 화면에서 만든 가상 케이스만 얕게 조립한다.

    별표는 `resolve_policy`가 `ctx.policy.*` 스칼라로 선해소하고, 화면 facts는 **그 이후** 얹혀
    상위로 이긴다 — "만약 한도가 X라면"을 시험할 수 있어야 한다.
    """
    tables = tables if tables is not None else load_tables()
    settlement = case.get("_settlement")
    if settlement is not None:
        context, _ = build_rule_context(settlement=settlement, tables=tables)
        return apply_facts(context, case.get("facts") or {})

    context = empty_eval_context()
    context["tx"]["amount"] = _number(case.get("amount"))
    context["tx"]["payment_method"] = case.get("paymentMethod") or "법인카드"
    context["category"]["value"] = case.get("category") or None
    context["category"]["item_type"] = case.get("itemType") or None
    context["merchant"]["merchant_type"] = case.get("merchantType") or None
    resolve_policy(context, tables)
    return apply_facts(context, case.get("facts") or {})


def case_from_settlement(settlement: Settlement) -> dict[str, Any]:
    """이전달 실제 정산 내역 → 테스트 케이스 형태."""
    tx = settlement.transaction
    ts = timezone.localtime(tx.ts) if tx and tx.ts else None
    has_receipt = bool(tx and tx.receipts.exclude(status="MISSING").exists())
    return {
        "id": f"S-{settlement.pk}",
        "settlementId": settlement.pk,
        # 조립기에 넘길 원본. 보고서 행에는 담기지 않는다(`_run_rows`가 새 dict를 만든다).
        "_settlement": settlement,
        "label": settlement.purpose or (tx.merchant if tx else f"정산 #{settlement.pk}"),
        "merchant": tx.merchant if tx else "",
        "amount": int(tx.amount) if tx else 0,
        "category": settlement.category or "",
        "merchantType": settlement.merchant_industry or "",
        "paymentMethod": "법인카드",
        "currentStatus": settlement.status,
        "date": ts.strftime("%m/%d") if ts else "",
        "aiSuggested": settlement.ai_suggested,
        "facts": {
            "evidence.has_valid_receipt": has_receipt,
            "evidence.expense_purpose_missing": not bool(settlement.purpose),
            "derived.is_late_night": bool(ts and (ts.hour >= 22 or ts.hour < 6)),
            "derived.is_weekend": bool(ts and ts.weekday() >= 5),
            "category.confidence": 0.5 if settlement.ai_suggested else 0.95,
        },
    }


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ── 시뮬레이션 실행 ───────────────────────────────────────────────
def _run_rows(snapshot: dict, cases: list[dict[str, Any]], source: str) -> list[dict[str, Any]]:
    node_titles = {
        str(item.get("node_key")): str((item.get("action") or {}).get("title", ""))
        for item in snapshot.get("nodes", [])
    }
    tables = load_tables()          # 실행당 1회 로드 후 메모리 룩업 (N+1 방지)
    rows: list[dict[str, Any]] = []
    for index, case in enumerate(cases):
        result = run_rule_engine(context_from_case(case, tables), snapshot)
        expected = (case.get("expected") or "").strip().upper()
        status = case.get("currentStatus") or ""
        baseline = BASELINE_BY_STATUS.get(status, "")
        changed = bool(baseline) and baseline != result.decision
        comment, comment_detail, verdict = (
            _change_comment(baseline, result.decision, case, node_titles, result)
            if changed else ("", "", "")
        )
        rows.append({
            "id": str(case.get("id") or f"{source}-{index + 1}"),
            "source": source,
            "label": case.get("label") or case.get("merchant") or f"케이스 {index + 1}",
            "merchant": case.get("merchant") or "",
            "amount": int(_number(case.get("amount")) or 0),
            "category": case.get("category") or "",
            "date": case.get("date") or "",
            "currentStatus": status,
            "baseline": baseline,
            "changed": changed,
            "aiComment": comment,
            "aiCommentDetail": comment_detail,
            "commentVerdict": verdict,  # 'intended' | 'risk' | 'reversal' | ''
            "decision": result.decision,
            "path": result.path,
            "flags": result.flags,
            "expected": expected,
            "matchedExpectation": (expected == result.decision) if expected else None,
            "risk": result.decision in RISK_DECISIONS or (bool(expected) and expected != result.decision)
            or verdict in ("risk", "reversal"),
            # 자동처리 = 그래프가 통과로 끝냈고, 사람 손이 필요한 상태도 아니었던 건
            "auto": result.decision == "PASS" and status not in MANUAL_STATUSES,
            "testCaseId": case.get("testCaseId"),
            "settlementId": case.get("settlementId"),
        })
    return rows


def _change_comment(baseline: str, decision: str, case: dict[str, Any],
                    node_titles: dict[str, str], result) -> tuple[str, str, str]:
    """분류가 달라진 건에만 붙는 AI 코멘트 — (한줄 요약, 자세히 보기용 기술 상세, 판단).

    "무엇이 바뀌었는가"를 먼저 쉬운 문장으로 말하고, 플래그 코드·평가 경로 같은 기술적
    디테일은 `detail`로 분리한다 — 화면에서 요약은 항상 보이고 상세는 펼쳐야 보이게 해
    "근거 플래그: PERSONAL_USE_SUSPECTED, 평가 경로 GLOBAL→R-003→..." 같은 문장을 매번
    먼저 읽지 않아도 되게 한다(2026-08-18 UX 개선, 사용자가 "너무 어렵다"고 지적).

    판단(verdict)은 세 단계: `intended`(의도한 개선) / `risk`(위험 변경) /
    `reversal`(사람이 이미 문제로 확정했던 건을 규칙이 뒤집어 통과시킴 — risk 중에서도
    가장 심각한 경우라 화면에서 더 강하게 강조한다).
    """
    before, after = DECISION_KO.get(baseline, baseline), DECISION_KO.get(decision, decision)
    last = result.path[-1] if result.path else ""
    where = f"`{last}`({node_titles.get(last, '종단 노드')})" if last else "그래프"
    flag_labels = [_flag_label(f) for f in result.flags]
    detail_parts = []
    if result.flags:
        detail_parts.append("근거: " + ", ".join(flag_labels))
    if len(result.path) > 1:
        detail_parts.append("평가 경로: " + " → ".join(result.path))
    detail = " · ".join(detail_parts)

    if baseline == "REVIEW" and decision == "PASS":
        return (f"사람이 검토하던 건을 {where}에서 자동 «{after}» 처리했습니다. "
                "의도한 자동화 효과입니다. 이 경로의 조건이 실제 승인 기준과 같은지 표본 확인을 권장합니다.",
                detail, "intended")
    if baseline == "REVIEW":
        return (f"검토 대기였던 건을 {where}에서 «{after}»로 확정했습니다. "
                "사람이 판단하던 것을 규칙이 대신한 셈이므로, 판정 근거 조항이 맞는지 확인하세요.",
                detail, "intended")
    if baseline == "PASS" and decision in RISK_DECISIONS:
        return (f"기존에 {before}된 건이 {where}에서 «{after}»로 바뀌었습니다. "
                "규정 근거가 명확하지 않다면 과탐(오탐)으로 검토량만 늘어납니다 — 임계값을 확인하세요.",
                detail, "risk")
    if baseline in {"RETURN", "REJECT"} and decision == "PASS":
        return (f"⚠ 이전에 사람이 «{before}» 처리했던 건을 이번 그래프가 «{after}»로 뒤집었습니다. "
                "놓친 위반이 없는지 반드시 확인하세요 — 사람의 결정이 완전히 뒤집힌 경우라 가장 먼저 봐야 합니다.",
                detail, "reversal")
    if case.get("aiSuggested"):
        return (f"«{before}» → «{after}»로 바뀌었고, 비용 분류 자체가 AI 저신뢰 추천 건입니다. "
                "분류부터 다시 확인하세요.", detail, "risk")
    return (f"«{before}» → «{after}»로 판정이 바뀌었습니다. {where} 기준입니다. "
            "의도한 규정 변화인지 확인하세요.", detail, "intended")


def _previous_month_cases(scope: str = policies_scope.GLOBAL) -> tuple[list[dict[str, Any]], str]:
    """직전 달 정산 내역. 없으면 최근 내역으로 대체한다(시연 데이터 보호).

    `scope`가 GLOBAL이 아니면(=과목별 그래프) 그 과목(`Settlement.category`)의 정산만
    본다 — 실제 운영에서 이 그래프는 해당 과목 정산에만 적용되기 때문이다(`orchestrator.py`
    의 scope 게이팅과 같은 전제). 필터 없이 돌리면 무관한 과목 정산까지 이 그래프에 억지로
    태워 REVIEW·위험변경이 과대계상된다(실사용 중 발견, 2026-08-18 — 회식 scope 그래프를
    비품·식대·출장 정산까지 섞어 돌려 자동처리율이 실제보다 훨씬 낮게 나왔다)."""
    now = timezone.localtime()
    first_of_this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    start = (first_of_this_month - timedelta(days=1)).replace(day=1)
    base = Settlement.objects.select_related("transaction")
    if scope != policies_scope.GLOBAL:
        base = base.filter(category=scope)
    queryset = base.filter(created_at__gte=start, created_at__lt=first_of_this_month).order_by("-created_at")
    label = start.strftime("%Y-%m")
    if not queryset.exists():
        queryset = base.order_by("-created_at")
        label = "최근"
    return [case_from_settlement(s) for s in queryset[:HISTORY_LIMIT]], label


def _previous_auto_rate(graph: RuleGraph) -> tuple[float | None, str]:
    """같은 계열 직전 버전의 자동처리율. 시뮬레이션 이력이 없으면 (None, '')."""
    previous = (
        RuleGraph.objects.filter(family_key=graph.family_key, version__lt=graph.version)
        .order_by("-version").first()
    )
    if previous is None:
        return None, ""
    rate = ((previous.sim_result or {}).get("stats") or {}).get("autoRate")
    if rate is None:
        return None, f"v{previous.version}"
    return float(rate), f"v{previous.version}"


def _graph_shape(graph: RuleGraph) -> dict[str, Any]:
    """도달 가능성·깊이 등 구조 지표 — Agent 의견의 근거."""
    node_keys = [node.node_key for node in graph.nodes.all()]
    routings = list(graph.routings.all())
    depth: dict[str, int] = {}
    entry = graph.entry_node_key if graph.entry_node_key in node_keys else (node_keys[0] if node_keys else "")
    queue = [entry] if entry else []
    if entry:
        depth[entry] = 1
    guard = len(node_keys) ** 2 + 16
    while queue and guard > 0:
        guard -= 1
        current = queue.pop(0)
        for route in routings:
            if route.from_node_key != current or not route.to_node_key:
                continue
            if depth.get(route.to_node_key, 0) < depth[current] + 1:
                depth[route.to_node_key] = depth[current] + 1
                queue.append(route.to_node_key)
    terminals = [key for key in node_keys if not any(r.from_node_key == key and r.to_node_key for r in routings)]
    return {
        "nodeCount": len(node_keys),
        "routingCount": len(routings),
        "maxDepth": max(depth.values(), default=0),
        "unreachable": sorted(set(node_keys) - set(depth)),
        "terminals": terminals,
        "entry": entry,
    }


# 스냅샷 변환은 `snapshot.py`가 소유한다 — 실판정(orchestrator)과 같은 모양이어야
# "시뮬은 통과인데 실판정은 다르다"가 생기지 않는다. 기존 호출부 호환을 위해 재노출한다.
graph_snapshot = _graph_snapshot
snapshot_hash = _snapshot_hash


def simulate(graph: RuleGraph, test_cases: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """그래프를 테스트셋 + 직전달 내역으로 시뮬레이션하고 보고서를 만든다(저장하지 않음)."""
    snapshot = graph_snapshot(graph)
    structure_error = ""
    try:
        validate_graph(snapshot)
    except (GraphValidationError, ValueError) as exc:
        structure_error = str(exc)

    test_rows = _run_rows(snapshot, list(test_cases or []), "test")
    history_cases, period_label = _previous_month_cases(graph.scope)
    history_rows = _run_rows(snapshot, history_cases, "history")

    shape = _graph_shape(graph)
    previous_auto_rate, previous_label = _previous_auto_rate(graph)
    stats = _stats(test_rows, history_rows, shape, previous_auto_rate, previous_label)
    grades = _grades(shape, stats, structure_error)
    return {
        "grades": grades,
        "graphId": str(graph.pk),
        "graphName": graph.name,
        "graphVersion": graph.version,
        "ranAt": timezone.localtime().strftime("%Y-%m-%d %H:%M"),
        "periodLabel": period_label,
        # 이 함수는 저장 전 계산 단계라 아직 LLM 서술을 시도하지 않았다 — 항상 True.
        # 실제 최종값은 `run_and_save()` 이후 뷰가 `apply_narrative()`를 호출하면 바뀐다.
        "placeholder": True,
        "structureError": structure_error,
        "stats": stats,
        "structure": shape,
        "snapshot": snapshot,
        "agentReport": _agent_report(graph, shape, stats, grades, test_rows, history_rows,
                                     structure_error, period_label),
        "testResults": test_rows,
        "historyResults": history_rows,
    }


# ── 저장 / 조회 ──────────────────────────────────────────────────
def test_cases_of(graph: RuleGraph) -> list[dict[str, Any]]:
    """저장된 검증셋 → 시뮬레이터 입력 형태."""
    return [{
        "id": case.key,
        "testCaseId": case.pk,
        "label": case.label,
        "merchant": case.merchant,
        "amount": int(case.amount),
        "category": case.category,
        "merchantType": case.merchant_type,
        "paymentMethod": case.payment_method,
        "expected": case.expected,
        "facts": case.facts or {},
    } for case in graph.test_cases.all()]


@db_tx.atomic
def replace_test_cases(graph: RuleGraph, payload: list[dict[str, Any]], actor=None) -> list[dict[str, Any]]:
    """화면에서 편집한 검증셋으로 그래프의 테스트케이스를 통째로 교체한다."""
    graph.test_cases.all().delete()
    RuleTestCase.objects.bulk_create([
        RuleTestCase(
            graph=graph,
            key=str(case.get("id") or f"TC-{index + 1}")[:32],
            label=str(case.get("label") or "")[:120],
            merchant=str(case.get("merchant") or "")[:200],
            amount=int(_number(case.get("amount")) or 0),
            category=str(case.get("category") or "")[:20],
            merchant_type=str(case.get("merchantType") or "")[:100],
            payment_method=str(case.get("paymentMethod") or "")[:30],
            expected=str(case.get("expected") or "")[:12],
            facts=case.get("facts") or {},
            order=index,
            created_by=actor,
        )
        for index, case in enumerate(payload)
    ])
    return test_cases_of(graph)


@db_tx.atomic
def run_and_save(graph: RuleGraph, test_cases: list[dict[str, Any]] | None, actor=None) -> RuleSimulationRun:
    """시뮬레이션을 실행하고 실행 스냅샷·통계·행 결과를 저장한다."""
    report = simulate(graph, test_cases)
    run = RuleSimulationRun.objects.create(
        graph=graph,
        graph_version=graph.version,
        snapshot=report["snapshot"],
        snapshot_hash=snapshot_hash(report["snapshot"]),
        period_label=report["periodLabel"],
        structure_error=report["structureError"][:300],
        stats=report["stats"],
        grades=report["grades"],
        agent_report=report["agentReport"],
        ran_by=actor,
    )
    RuleSimulationResult.objects.bulk_create([
        RuleSimulationResult(
            run=run,
            source=SimulationSource.TEST if row["source"] == "test" else SimulationSource.HISTORY,
            test_case_id=row.get("testCaseId"),
            settlement_id=row.get("settlementId"),
            row_key=row["id"][:64], label=row["label"][:200], merchant=row["merchant"][:200],
            amount=row["amount"], category=row["category"][:20], date_label=row["date"][:16],
            current_status=row["currentStatus"][:24], baseline=row["baseline"][:12],
            decision=row["decision"][:12], path=row["path"], flags=row["flags"],
            expected=row["expected"][:12], matched_expectation=row["matchedExpectation"],
            changed=row["changed"], risk=row["risk"], auto=row["auto"],
            ai_comment=row["aiComment"], ai_comment_detail=row.get("aiCommentDetail", ""),
            comment_verdict=row["commentVerdict"][:12],
            order=index,
        )
        for index, row in enumerate(report["testResults"] + report["historyResults"])
    ])
    graph.sim_result = {
        "runId": run.pk, "ranAt": timezone.localtime(run.ran_at).strftime("%Y-%m-%d %H:%M"),
        "stats": report["stats"], "grades": report["grades"], "placeholder": run.agent_report_placeholder,
    }
    graph.save(update_fields=["sim_result"])
    return run


def _result_row(result: RuleSimulationResult) -> dict[str, Any]:
    return {
        "id": result.row_key,
        "source": "test" if result.source == SimulationSource.TEST else "history",
        "testCaseId": result.test_case_id,
        "settlementId": result.settlement_id,
        "label": result.label, "merchant": result.merchant, "amount": int(result.amount),
        "category": result.category, "date": result.date_label, "currentStatus": result.current_status,
        "baseline": result.baseline, "decision": result.decision,
        "path": result.path or [], "flags": result.flags or [],
        "expected": result.expected, "matchedExpectation": result.matched_expectation,
        "changed": result.changed, "risk": result.risk, "auto": result.auto,
        "aiComment": result.ai_comment, "aiCommentDetail": result.ai_comment_detail,
        "commentVerdict": result.comment_verdict,
    }


def report_from_run(run: RuleSimulationRun) -> dict[str, Any]:
    """저장된 실행 → 화면 보고서. 그래프가 그 뒤 바뀌었으면 stale로 표시한다."""
    graph = run.graph
    current_hash = snapshot_hash(graph_snapshot(graph))
    rows = list(run.results.all())
    return {
        "runId": run.pk,
        "graphId": str(graph.pk),
        "graphName": graph.name,
        "graphVersion": run.graph_version,
        "ranAt": timezone.localtime(run.ran_at).strftime("%Y-%m-%d %H:%M"),
        "ranBy": getattr(run.ran_by, "first_name", "") or getattr(run.ran_by, "username", ""),
        "periodLabel": run.period_label,
        "placeholder": run.agent_report_placeholder,
        "structureError": run.structure_error,
        "stats": run.stats,
        "grades": run.grades,
        "structure": {  # 현재 그래프 기준 구조 지표(카운트 표시에만 사용)
            **_graph_shape(graph),
        },
        "snapshotHash": run.snapshot_hash,
        "stale": run.snapshot_hash != current_hash,
        "agentReport": run.agent_report,
        "testResults": [_result_row(row) for row in rows if row.source == SimulationSource.TEST],
        "historyResults": [_result_row(row) for row in rows if row.source == SimulationSource.HISTORY],
    }


def latest_run(graph: RuleGraph) -> RuleSimulationRun | None:
    return graph.simulation_runs.first()


def _stats(test_rows: list[dict], history_rows: list[dict], shape: dict,
           previous_auto_rate: float | None, previous_label: str) -> dict[str, Any]:
    history_total = len(history_rows)
    review_count = sum(1 for row in history_rows if row["decision"] in REVIEW_DECISIONS)
    # 자동처리율 = 사람 검토(IN_REVIEW 등)로 빠지지 않고 그래프가 통과로 끝낸 비율.
    auto_count = sum(1 for row in history_rows if row["auto"])
    auto_rate = round(auto_count / history_total, 4) if history_total else 0.0
    visited = {key for row in test_rows + history_rows for key in row["path"]}
    graded = [row for row in test_rows if row["matchedExpectation"] is not None]
    return {
        "autoRate": auto_rate,
        "autoCount": auto_count,
        "manualCount": history_total - auto_count,
        # 검토 감소량 = 같은 계열 이전 버전의 자동처리율 대비 증가폭(%p).
        "prevAutoRate": round(previous_auto_rate or 0.0, 4),
        "prevVersionLabel": previous_label,
        "hasPrevVersion": previous_auto_rate is not None,
        "reviewReduction": round(auto_rate - (previous_auto_rate or 0.0), 4),
        "historyTotal": history_total,
        "reviewCount": review_count,
        "riskCount": sum(1 for row in history_rows if row["risk"]),
        # 변경건을 두 갈래로 — 위험 변경(AI가 위험하다고 본 건) / 정상 변경(의도된 변경)
        "changedCount": sum(1 for row in history_rows if row["changed"]),
        "riskChangedCount": sum(
            1 for row in history_rows if row["changed"] and row["commentVerdict"] in ("risk", "reversal")
        ),
        # 완전 반전(반려/보완요청 → 통과) — 위험 변경 중에서도 최우선으로 봐야 할 건.
        "reversalChangedCount": sum(
            1 for row in history_rows if row["changed"] and row["commentVerdict"] == "reversal"
        ),
        "intendedChangedCount": sum(
            1 for row in history_rows if row["changed"] and row["commentVerdict"] == "intended"
        ),
        "testTotal": len(test_rows),
        "testGraded": len(graded),
        "testPassed": sum(1 for row in graded if row["matchedExpectation"]),
        "testFailed": sum(1 for row in graded if not row["matchedExpectation"]),
        "nodeCoverage": round(len(visited) / shape["nodeCount"], 4) if shape["nodeCount"] else 0.0,
        "visitedNodes": len(visited),
    }


GRADE_LABEL = {"poor": "미흡", "warn": "주의", "good": "우수"}
ACTION_LABEL = {"poor": "수정", "warn": "재검토", "good": "활성화"}


def _grades(shape: dict, stats: dict, structure_error: str) -> dict[str, Any]:
    """Agent 의견 상단 3단계 등급 — 구조 / 실행결과 / 권장처리."""
    if structure_error:
        structure = ("poor", "실행 계약 위반 — Active 전환 불가")
    elif shape["unreachable"]:
        structure = ("poor", f"도달 불가 노드 {len(shape['unreachable'])}개 — 켜도 평가되지 않습니다")
    elif stats["nodeCoverage"] < 0.8:
        structure = ("warn", f"노드 커버리지 {stats['nodeCoverage'] * 100:.0f}% — 검증되지 않은 노드가 있습니다")
    else:
        structure = ("good", f"노드 {shape['nodeCount']}개 · 깊이 {shape['maxDepth']}단계 · 전 노드 검증됨")

    graded = stats["testGraded"]
    fail_ratio = (stats["testFailed"] / graded) if graded else 0.0
    risk_ratio = (stats["riskChangedCount"] / stats["historyTotal"]) if stats["historyTotal"] else 0.0
    if fail_ratio > 0.3 or risk_ratio > 0.4:
        result = ("poor", f"기대 불일치 {stats['testFailed']}건 · 위험 변경 {stats['riskChangedCount']}건")
    elif stats["testFailed"] or risk_ratio > 0.15:
        result = ("warn", f"기대 불일치 {stats['testFailed']}건 · 위험 변경 {stats['riskChangedCount']}건")
    elif not graded:
        result = ("warn", "채점 가능한 테스트 케이스가 없음")
    else:
        result = ("good", f"테스트 {stats['testPassed']}/{graded} 통과 · 위험 변경 0건")

    worst = "poor" if "poor" in (structure[0], result[0]) else "warn" if "warn" in (structure[0], result[0]) else "good"
    # 권장 처리는 구조/실행결과 중 더 나쁜 등급을 그대로 물려받는다(둘 다 독립된 안전검사라
    # 하나만 나빠도 전체가 그 등급을 따른다 — "평균"이 아니라 "AND 게이트"). `cause`는 그중
    # 어느 축이 원인인지 화면에 밝혀 "권장 처리" 카드만 보고도 뭘 고쳐야 하는지 알게 한다.
    cause = [name for name, grade in (("structure", structure[0]), ("result", result[0])) if grade == worst]
    cause_label = " · ".join({"structure": "그래프 구조", "result": "실행 결과(테스트/실내역)"}[c] for c in cause)
    action_note = {
        "poor": f"원인: {cause_label}. 그래프를 수정한 뒤 다시 시뮬레이션하세요.",
        "warn": f"원인: {cause_label}. 확인 사항을 재검토한 뒤 승인 여부를 결정하세요.",
        "good": "승인대기로 전환해도 좋습니다.",
    }[worst]
    return {
        "structure": {"level": structure[0], "label": GRADE_LABEL[structure[0]], "note": structure[1]},
        "result": {"level": result[0], "label": GRADE_LABEL[result[0]], "note": result[1]},
        "action": {"level": worst, "label": ACTION_LABEL[worst], "note": action_note, "cause": cause},
    }


def _decision_mix(rows: list[dict]) -> str:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["decision"]] = counts.get(row["decision"], 0) + 1
    return ", ".join(f"{key} {value}건" for key, value in sorted(counts.items())) or "판정 없음"


def _narrative_facts(graph, shape, stats, grades, test_rows, history_rows,
                     structure_error, period_label) -> dict[str, Any]:
    """보고서 서술에 필요한 사실만 추출한 JSON 조각.

    `_render_template_report()`(결정론적 폴백)와 FastAPI `narrate-report`(LLM 실서술)가
    **같은 이 dict**를 입력으로 받는다 — 서술 주체가 바뀌어도(템플릿 ↔ LLM) 근거 사실은
    하나여야 "판정은 실제인데 설명은 다른 근거를 든다"가 생기지 않는다.
    """
    percent = lambda value: f"{value * 100:.1f}%"  # noqa: E731
    watch: list[str] = []   # 주의깊게 살펴봐야 할 부분
    reasons: list[str] = [] # 권장처리 판단의 근거

    # ── 판단 근거 수집 ──
    if structure_error:
        reasons.append(f"구조 오류로 실행 계약을 위반합니다 — {structure_error}")
    if shape["unreachable"]:
        reasons.append(
            f"진입 노드에서 도달할 수 없는 노드가 {len(shape['unreachable'])}개 있습니다"
            f"(`{'`, `'.join(shape['unreachable'])}`)"
        )
    if stats["testFailed"]:
        reasons.append(f"테스트 케이스 {stats['testGraded']}건 중 {stats['testFailed']}건이 기대 판정과 다르게 나왔습니다")
    if stats["riskChangedCount"]:
        reasons.append(f"기존 처리와 달라진 건 중 {stats['riskChangedCount']}건을 위험 변경으로 판단했습니다")
    if not reasons:
        reasons.append("구조·테스트·실제 내역 판정 모두에서 특이사항이 발견되지 않았습니다")

    verdict = {
        "poor": "🚫 **수정 필요** — 아래 사유를 해결한 뒤 다시 시뮬레이션하세요.",
        "warn": "⚠️ **재검토 후 판단** — 아래 확인 사항을 검토한 뒤 승인 여부를 결정하세요.",
        "good": "✅ **활성화 권장** — 확인된 문제가 없습니다.",
    }[grades["action"]["level"]]

    # ── 주의깊게 살펴볼 부분 ──
    if structure_error:
        watch.append(f"**구조 오류** — {structure_error} 이 상태로는 Active 전환이 거부됩니다.")
    if shape["unreachable"]:
        watch.append(
            f"**도달 불가 노드 {len(shape['unreachable'])}개** (`{'`, `'.join(shape['unreachable'])}`) — "
            "진입 노드에서 이어지는 라우팅이 없어 켜도 절대 평가되지 않습니다. 라우팅을 연결하거나 노드를 삭제하세요."
        )
    if stats["testFailed"]:
        watch.append(
            f"**기대 판정 불일치 {stats['testFailed']}건** — 아래 «테스트셋 결과»에서 불일치 건의 "
            "조건·임계값을 확인하세요. 기대값이 틀린 것인지, 규칙이 틀린 것인지부터 가려야 합니다."
        )
    if stats["riskChangedCount"]:
        watch.append(
            f"**위험 변경 {stats['riskChangedCount']}건** — 기존에 통과되던 건이 막히거나, 반대로 "
            "막히던 건이 통과된 경우입니다. 아래 «최근 내역 결과 → 위험건»에서 각 건의 근거를 확인하세요."
        )
    if stats["visitedNodes"] < shape["nodeCount"]:
        never = shape["nodeCount"] - stats["visitedNodes"]
        watch.append(
            f"**미검증 노드 {never}개** — 이번 실행에서 한 번도 평가되지 않았습니다. "
            "해당 조건을 만족하는 테스트 케이스를 추가해 검증 범위를 넓히는 것을 권장합니다."
        )
    if stats["autoRate"] < 0.5 and stats["historyTotal"]:
        watch.append(
            f"**낮은 자동처리율({percent(stats['autoRate'])})** — 검토(REVIEW)로 빠지는 노드의 "
            "임계값이 과도하게 촘촘하지 않은지 살펴보세요. 자동화 효과가 제한적입니다."
        )

    compare = (
        f"직전 버전({stats['prevVersionLabel']}) {percent(stats['prevAutoRate'])} → {percent(stats['autoRate'])}"
        if stats["hasPrevVersion"] else
        f"직전 버전 시뮬레이션 이력이 없어 0.0% → {percent(stats['autoRate'])}로 계산"
    )

    # 대표 사례 — "8건 중 8건 통과"라는 숫자만으론 왜 그런지 알 수 없다. 실제로 어느 노드를
    # 거쳐 어떤 판정에 도달했는지 구체적 사례 1~2개를 줘서 서술이 그걸 인용해 설명하게 한다
    # (§6, 2026-08-19 — "숫자만 있고 왜 그런지는 없다"는 사용자 피드백).
    def _example(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "label": row["label"], "path": row["path"], "decision": row["decision"],
            "expected": row.get("expected") or None, "aiComment": row.get("aiComment") or None,
        }
    test_pass = next((r for r in test_rows if r["matchedExpectation"]), None)
    test_fail = next((r for r in test_rows if r["matchedExpectation"] is False), None)
    risky_examples = [r for r in history_rows if r["changed"] and r["risk"]][:2]

    return {
        "graphName": graph.name,
        "graphVersion": graph.version,
        "periodLabel": period_label,
        "structureError": structure_error,
        "shape": shape,
        "stats": stats,
        "grades": grades,
        "reasons": reasons,
        "watch": watch,
        "verdictText": verdict,
        "compareLine": compare,
        "decisionMixTest": _decision_mix(test_rows),
        "decisionMixHistory": _decision_mix(history_rows),
        # 대표 사례 — 서술이 "왜 이 숫자가 나왔는지"를 구체적으로 인용할 근거.
        "testExamples": [_example(r) for r in (test_pass, test_fail) if r],
        "riskyExamples": [_example(r) for r in risky_examples],
    }


def _render_template_report(facts: dict[str, Any]) -> str:
    """`_narrative_facts()` 결과를 결정론적 마크다운으로 편성 — LLM 미가용 시 폴백.

    구성: **한눈에 보기**(가장 중요 — 화면에서 항상 펼쳐짐) → 개요(이유·권장처리) →
    그래프 구성 평가 → 실행결과 → 주의깊게 볼 부분(뒤 4개는 화면에서 접혀서 시작 —
    프론트가 첫 `## ` 섹션과 나머지를 분리해 렌더링한다, `SimulationReport.tsx` 참조).
    """
    percent = lambda value: f"{value * 100:.1f}%"  # noqa: E731
    shape, stats, grades = facts["shape"], facts["stats"], facts["grades"]
    watch = facts["watch"]
    graded = stats["testGraded"] or stats["testTotal"]

    top_watch = watch[0] if watch else None
    summary_lines = [
        "## 한눈에 보기",
        f"**권장 처리: {grades['action']['label']}** — {facts['reasons'][0] if facts['reasons'] else grades['action']['note']}",
    ]
    if top_watch:
        summary_lines.append(f"가장 먼저 확인할 것: {top_watch}")
    summary_lines.append("")

    lines = [
        *summary_lines,
        "## 개요",
        f"`{facts['graphName']}` v{facts['graphVersion']}을(를) 테스트셋 {stats['testTotal']}건과 "
        f"{facts['periodLabel']} 실제 내역 {stats['historyTotal']}건으로 시뮬레이션했습니다.",
        "",
        "**판단 근거**",
        *[f"- {text}" for text in facts["reasons"]],
        "",
        f"**권장 처리 — {grades['action']['label']}**",
        facts["verdictText"],
        "",
        "## 그래프 구성 평가",
        f"- 노드 {shape['nodeCount']}개 · 라우팅 {shape['routingCount']}개 · 최대 깊이 {shape['maxDepth']}단계",
        f"- 진입 노드 `{shape['entry'] or '미지정'}` · 종결 노드 {len(shape['terminals'])}개 "
        f"· 도달 불가 노드 {len(shape['unreachable'])}개",
        f"- 구조 평가: **{grades['structure']['label']}** ({grades['structure']['note']})",
        "",
        "## 실행결과",
        "",
        "**테스트케이스 구성 및 결과**",
        f"- 검증셋 {stats['testTotal']}건 중 기대 판정이 지정된 건 {stats['testGraded']}건 "
        f"→ **일치 {stats['testPassed']}건 / 불일치 {stats['testFailed']}건**",
        f"- 판정 분포: {facts['decisionMixTest']}",
        "",
        f"**{facts['periodLabel']} 실제 내역 결과 요약**",
        f"- 대상 {stats['historyTotal']}건 · 판정 분포: {facts['decisionMixHistory']}",
        f"- 자동처리 {stats['autoCount']}건 / 사람 확인 {stats['manualCount']}건 "
        f"→ 자동처리율 **{percent(stats['autoRate'])}**",
        f"- 검토 감소량 **{percent(stats['reviewReduction'])}p** ({facts['compareLine']})",
        f"- 기존 처리와 달라진 건 {stats['changedCount']}건 "
        f"→ **위험 변경 {stats['riskChangedCount']}건 / 정상 변경 {stats['intendedChangedCount']}건**",
        "",
        "**노드 커버리지**",
        f"- 이번 실행에서 평가된 노드 {stats['visitedNodes']}/{shape['nodeCount']}개 "
        f"(**{percent(stats['nodeCoverage'])}**)",
        f"- 실행결과 평가: **{grades['result']['label']}** ({grades['result']['note']})",
        "",
        "## 주의깊게 살펴봐야 할 부분",
    ]
    if watch:
        lines += [f"{index}. {text}" for index, text in enumerate(watch, start=1)]
    else:
        lines.append("- 별도로 확인이 필요한 항목은 발견되지 않았습니다. 테스트 {}건이 모두 기대대로 판정됐고, "
                     "기존 처리와 달라진 건 중 위험 판단도 없습니다.".format(graded))
    lines += [
        "",
        "> 이 보고서는 룰 기반 템플릿입니다(Rule Agent 서술 생성 실패 또는 미실행). 판정은 실제 룰 엔진 "
        "결과이지만, EvalContext는 정산·거래에서 조립한 일부 필드만 채워져 있습니다. "
        "사람 확인 없이 자동 승인하지 마세요.",
    ]
    return "\n".join(lines)


def _agent_report(graph, shape, stats, grades, test_rows, history_rows,
                  structure_error, period_label) -> str:
    """구조·통계 기반 자연어(마크다운) 보고 — 결정론적 템플릿 폴백."""
    facts = _narrative_facts(graph, shape, stats, grades, test_rows, history_rows,
                             structure_error, period_label)
    return _render_template_report(facts)


def narrative_facts_for_run(run: RuleSimulationRun) -> dict[str, Any]:
    """저장된 실행 결과로부터 서술용 사실 dict를 재구성 — FastAPI narrate 호출 입력."""
    graph = run.graph
    shape = _graph_shape(graph)
    rows = list(run.results.all())
    test_rows = [_result_row(row) for row in rows if row.source == SimulationSource.TEST]
    history_rows = [_result_row(row) for row in rows if row.source == SimulationSource.HISTORY]
    return _narrative_facts(
        graph, shape, run.stats, run.grades, test_rows, history_rows,
        run.structure_error, run.period_label,
    )


def apply_narrative(run: RuleSimulationRun, narrative: str) -> None:
    """LLM이 실제로 작성한 서술을 실행 결과에 반영 — placeholder 플래그도 함께 내린다.

    `run_and_save()`가 이미 `graph.sim_result["placeholder"]`를 True로 저장해 둔 뒤이므로,
    여기서도 같이 내려야 그래프 목록 화면이 최신 상태를 본다(§13.3 참조).
    """
    run.agent_report = narrative
    run.agent_report_placeholder = False
    run.save(update_fields=["agent_report", "agent_report_placeholder"])
    graph = run.graph
    if isinstance(graph.sim_result, dict) and graph.sim_result.get("runId") == run.pk:
        graph.sim_result["placeholder"] = False
        graph.save(update_fields=["sim_result"])


def apply_action_assessment(run: RuleSimulationRun, action: dict[str, Any] | None) -> None:
    """LLM이 재판단한 "권장 처리"(action) 등급을 반영 — 2026-08-19, 사용자 요청으로 도입.

    `_grades()`의 기계적 규칙(구조/실행결과 중 더 나쁜 쪽을 그대로 채택)이 지나치게
    보수적일 수 있어 LLM이 `facts` 전체를 보고 종합 판단하게 했다. **단, 안전 하한은
    서버에서 한 번 더 강제한다** — 구조 평가가 `poor`(구조 오류·도달 불가 노드)면 LLM이
    무슨 응답을 줬든 `poor`로 되돌린다. 프롬프트 지시만으로는 LLM이 틀릴 수 있으므로
    (환각·지시 무시), "그래프가 구조적으로 깨진 상태를 활성화해도 된다고 판단"하는 일이
    실제로 일어나지 않도록 코드로 검증한다.
    """
    if not isinstance(action, dict):
        return
    level = action.get("level")
    note = str(action.get("note") or "").strip()
    if level not in {"poor", "warn", "good"} or not note:
        return  # 스키마를 어긴 응답은 조용히 무시 — 결정론적 action 유지

    grades = dict(run.grades or {})
    structure = grades.get("structure") or {}
    if structure.get("level") == "poor":
        level = "poor"  # 안전 하한 — LLM 응답과 무관하게 강제

    current = grades.get("action") or {}
    grades["action"] = {**current, "level": level, "label": ACTION_LABEL[level], "note": note, "aiAdjusted": True}
    run.grades = grades
    run.save(update_fields=["grades"])
    graph = run.graph
    if isinstance(graph.sim_result, dict) and graph.sim_result.get("runId") == run.pk:
        graph.sim_result["grades"] = grades
        graph.save(update_fields=["sim_result"])

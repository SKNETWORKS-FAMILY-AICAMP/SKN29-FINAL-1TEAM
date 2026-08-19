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
from domain.transactions import industry as industry_vocab

from .context_builder import apply_facts, build_rule_context, load_tables, resolve_policy
from .engine import GraphValidationError, run_rule_engine, validate_graph
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
    # 손으로 만든 검증셋도 정본 어휘로 접는다 — 시뮬레이션이 실 판정과 다른 어휘로 돌면
    #  "룰 콘솔에선 걸렸는데 실제로는 안 걸린다"가 된다(§7-1).
    context["merchant"]["merchant_type"] = industry_vocab.canonical_label(case.get("merchantType")) or None
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
        "merchantType": settlement.merchant_industry_code or settlement.merchant_industry or "",
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
        comment, verdict = (_change_comment(baseline, result.decision, case, node_titles, result)
                            if changed else ("", ""))
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
            "commentVerdict": verdict,  # 'intended' | 'risk' | ''
            "decision": result.decision,
            "path": result.path,
            "flags": result.flags,
            "expected": expected,
            "matchedExpectation": (expected == result.decision) if expected else None,
            "risk": result.decision in RISK_DECISIONS or (bool(expected) and expected != result.decision)
            or verdict == "risk",
            # 자동처리 = 그래프가 통과로 끝냈고, 사람 손이 필요한 상태도 아니었던 건
            "auto": result.decision == "PASS" and status not in MANUAL_STATUSES,
            "testCaseId": case.get("testCaseId"),
            "settlementId": case.get("settlementId"),
        })
    return rows


def _change_comment(baseline: str, decision: str, case: dict[str, Any],
                    node_titles: dict[str, str], result) -> tuple[str, str]:
    """분류가 달라진 건에만 붙는 AI 코멘트 — (문구, 판단).

    "무엇이 바뀌었는가"에 더해 **어느 노드가 어떤 근거로 그렇게 판정했는지**를 함께 적어,
    회계 담당자가 그래프를 열어보지 않고도 변경 사유를 확인할 수 있게 한다.
    """
    before, after = DECISION_KO.get(baseline, baseline), DECISION_KO.get(decision, decision)
    last = result.path[-1] if result.path else ""
    where = f"`{last}`({node_titles.get(last, '종단 노드')})" if last else "그래프"
    because = f" 근거 플래그: {', '.join(result.flags)}." if result.flags else ""
    trail = f" 평가 경로 {' → '.join(result.path)}." if len(result.path) > 1 else ""

    if baseline == "REVIEW" and decision == "PASS":
        return (f"사람이 검토하던 건을 {where}에서 자동 «{after}» 처리했습니다.{trail} "
                "의도한 자동화 효과입니다. 이 경로의 조건이 실제 승인 기준과 같은지 표본 확인을 권장합니다.", "intended")
    if baseline == "REVIEW":
        return (f"검토 대기였던 건을 {where}에서 «{after}»로 확정했습니다.{because}{trail} "
                "사람이 판단하던 것을 규칙이 대신한 셈이므로, 판정 근거 조항이 맞는지 확인하세요.", "intended")
    if baseline == "PASS" and decision in RISK_DECISIONS:
        return (f"기존에 {before}된 건이 {where}에서 «{after}»로 바뀌었습니다.{because}{trail} "
                "규정 근거가 명확하지 않다면 과탐(오탐)으로 검토량만 늘어납니다 — 임계값을 확인하세요.", "risk")
    if baseline in {"RETURN", "REJECT"} and decision == "PASS":
        return (f"기존에 {before}된 건이 «{after}»로 바뀌었습니다.{trail} "
                "이전에 사람이 문제로 본 건을 규칙이 통과시켰습니다. 놓친 위반이 없는지 반드시 확인하세요.", "risk")
    if case.get("aiSuggested"):
        return (f"«{before}» → «{after}»로 바뀌었고, 비용 분류 자체가 AI 저신뢰 추천 건입니다.{because} "
                "분류부터 다시 확인하세요.", "risk")
    return (f"«{before}» → «{after}»로 판정이 바뀌었습니다. {where} 기준입니다.{because}{trail} "
            "의도한 규정 변화인지 확인하세요.", "intended")


def _previous_month_cases() -> tuple[list[dict[str, Any]], str]:
    """직전 달 정산 내역. 없으면 최근 내역으로 대체한다(시연 데이터 보호)."""
    now = timezone.localtime()
    first_of_this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    start = (first_of_this_month - timedelta(days=1)).replace(day=1)
    queryset = (
        Settlement.objects.select_related("transaction")
        .filter(created_at__gte=start, created_at__lt=first_of_this_month)
        .order_by("-created_at")
    )
    label = start.strftime("%Y-%m")
    if not queryset.exists():
        queryset = Settlement.objects.select_related("transaction").order_by("-created_at")
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
    history_cases, period_label = _previous_month_cases()
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
            ai_comment=row["aiComment"], comment_verdict=row["commentVerdict"][:12],
            order=index,
        )
        for index, row in enumerate(report["testResults"] + report["historyResults"])
    ])
    graph.sim_result = {
        "runId": run.pk, "ranAt": timezone.localtime(run.ran_at).strftime("%Y-%m-%d %H:%M"),
        "stats": report["stats"], "grades": report["grades"], "placeholder": True,
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
        "aiComment": result.ai_comment, "commentVerdict": result.comment_verdict,
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
        "placeholder": True,
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
        "riskChangedCount": sum(1 for row in history_rows if row["changed"] and row["commentVerdict"] == "risk"),
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
    action_note = {
        "poor": "그래프를 수정한 뒤 다시 시뮬레이션하세요.",
        "warn": "확인 사항을 재검토한 뒤 승인 여부를 결정하세요.",
        "good": "승인대기로 전환해도 좋습니다.",
    }[worst]
    return {
        "structure": {"level": structure[0], "label": GRADE_LABEL[structure[0]], "note": structure[1]},
        "result": {"level": result[0], "label": GRADE_LABEL[result[0]], "note": result[1]},
        "action": {"level": worst, "label": ACTION_LABEL[worst], "note": action_note},
    }


def _decision_mix(rows: list[dict]) -> str:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["decision"]] = counts.get(row["decision"], 0) + 1
    return ", ".join(f"{key} {value}건" for key, value in sorted(counts.items())) or "판정 없음"


def _agent_report(graph, shape, stats, grades, test_rows, history_rows,
                  structure_error, period_label) -> str:
    """구조·통계 기반 자연어(마크다운) 보고. LLM 연동 시 이 함수를 교체한다.

    구성: 개요(이유·권장처리) → 그래프 구성 평가 → 실행결과 → 주의깊게 볼 부분.
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
    graded = stats["testGraded"] or stats["testTotal"]

    lines = [
        "## 개요",
        f"`{graph.name}` v{graph.version}을(를) 테스트셋 {stats['testTotal']}건과 "
        f"{period_label} 실제 내역 {stats['historyTotal']}건으로 시뮬레이션했습니다.",
        "",
        "**판단 근거**",
        *[f"- {text}" for text in reasons],
        "",
        f"**권장 처리 — {grades['action']['label']}**",
        verdict,
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
        f"- 판정 분포: {_decision_mix(test_rows)}",
        "",
        f"**{period_label} 실제 내역 결과 요약**",
        f"- 대상 {stats['historyTotal']}건 · 판정 분포: {_decision_mix(history_rows)}",
        f"- 자동처리 {stats['autoCount']}건 / 사람 확인 {stats['manualCount']}건 "
        f"→ 자동처리율 **{percent(stats['autoRate'])}**",
        f"- 검토 감소량 **{percent(stats['reviewReduction'])}p** ({compare})",
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
        "> 이 보고서는 플레이스홀더입니다. 판정은 실제 룰 엔진 결과이지만, "
        "EvalContext는 정산·거래에서 조립한 일부 필드만 채워져 있습니다. "
        "사람 확인 없이 자동 승인하지 마세요.",
    ]
    return "\n".join(lines)

"""룰 그래프 **단계별 채점** — 자동처리율과 오탐율을 실제로 돌려 잰다.

    docker compose exec core python manage.py rule_eval
    docker compose exec core python manage.py rule_eval --md var/rule_eval.md --miss

## 무엇을 재나

**룰엔진은 분류기다** — 확실한 건만 분류하고 나머지는 사람에게 넘긴다
([[rule-engine-semantics]]). 그래서 지표도 「사람에게 보냈는가」가 아니라
**「확정을 맞게 했는가」**로 잰다.

  · `PASS`(승인대기)·`RETURN`(보완요청)·`REJECT` → 룰이 **확정**했다 = 자동처리
  · `REVIEW`(검토) → 룰이 **확정 못 했다** = 사람에게. **실패가 아니다.**

| 지표 | 뜻 |
|---|---|
| 자동처리율 | 1 − (검토 / 전체) — **룰이 결론 낸 비율.** 규칙이 촘촘해질수록 오른다 |
| 오탐율 | 확정한 것 중 **틀린** 비율 — 보완반려할 건을 `PASS`로, 승인할 건을 `RETURN`으로 |

**미탐은 재지 않는다.** 「확정할 수 있었는데 검토로 넘김」은 곧 검토 비율이고,
자동처리율의 역이라 같은 수를 두 번 적는 셈이다.

이상적인 곡선: **자동처리율은 0에서 올라가고, 오탐율은 내내 낮다가 끝에 0.**

## 검증셋

`domain/policies/golden.py` — 정답이 자명한 300건(승인 180 · 보완반려 120).
EvalContext를 직접 조립하므로 **DB도 시드도 필요 없다**(`run_rule_engine`은 순수 함수).

애매한 건은 넣지 않는다. 검토가 정답인 케이스를 섞으면 「확정을 맞게 했는가」를 못 잰다.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from django.core.management.base import BaseCommand

from domain.policies import golden, rule_timeline
from domain.policies.engine import run_rule_engine

SETTLED = ("PASS", "RETURN", "REJECT")


class Command(BaseCommand):
    help = "룰 그래프 단계별 자동처리율·오탐율 측정"

    def add_arguments(self, parser):
        parser.add_argument("--md", help="결과를 마크다운으로 쓸 경로")
        parser.add_argument("--miss", action="store_true", help="오탐 건을 자세히 출력")

    def handle(self, *args, **opts):
        cases = golden.build()
        counts = Counter(c["label"] for c in cases)
        self.stdout.write(
            f"golden {len(cases)} (approve {counts[golden.APPROVE]} / "
            f"block {counts[golden.BLOCK]})")

        rows = [self._score(stage, cases) for stage in rule_timeline.TIMELINE]
        self._print(rows)
        if opts.get("miss"):
            self._print_misses(rows[-1])
        if opts.get("md"):
            out = Path(opts["md"])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(self._markdown(rows, cases), encoding="utf-8")
            self.stdout.write(f"\nmarkdown -> {out}")

    # ── 채점 ────────────────────────────────────────────────────────
    def _decide(self, gate_snap, scope_snaps, category, ctx) -> str:
        """게이트 → (통과 시) 과목별. `orchestrator.judge`와 **같은 순서**다."""
        gate = run_rule_engine(ctx, gate_snap)
        if gate.decision != "PASS":
            return gate.decision
        scope_snap = scope_snaps.get(category)
        if scope_snap is None:
            return "PASS"
        return run_rule_engine(ctx, scope_snap).decision

    def _score(self, stage, cases) -> dict:
        label, note, _g, scoped, _days = stage
        gate_snap, scope_snaps = rule_timeline.snapshots(stage)
        settled = wrong = 0
        by_decision: Counter = Counter()
        misses: list[dict] = []
        for case in cases:
            decision = self._decide(gate_snap, scope_snaps, case["category"], case["ctx"])
            by_decision[decision] += 1
            if decision not in SETTLED:
                continue
            settled += 1
            #  **오탐 = 틀리게 확정한 것.** 방향은 둘 다 잘못이다 —
            #  ① 되돌렸어야 할 건을 승인대기로 ② 승인할 건을 되돌림.
            bad = ((case["label"] == golden.BLOCK and decision == "PASS")
                   or (case["label"] == golden.APPROVE and decision in ("RETURN", "REJECT")))
            if bad:
                wrong += 1
                misses.append({**case, "decision": decision})
        n = len(cases) or 1
        return {
            "label": label, "note": note, "n": n, "scopes": sorted(scoped),
            "settled": settled, "autoRate": settled / n * 100,
            "wrong": wrong, "wrongRate": wrong / (settled or 1) * 100,
            "decisions": dict(by_decision), "misses": misses,
        }

    # ── 출력 ────────────────────────────────────────────────────────
    def _print(self, rows):
        self.stdout.write("")
        self.stdout.write(f"{'stage':<8}{'auto':>16}{'wrong':>16}   scopes")
        self.stdout.write("-" * 62)
        for r in rows:
            self.stdout.write(
                f"{r['label']:<8}"
                f"{r['settled']:>5}/{r['n']:<4}{r['autoRate']:>6.1f}%"
                f"{r['wrong']:>5}/{r['settled']:<4}{r['wrongRate']:>6.1f}%"
                f"   {','.join(r['scopes']) or '-'}"
            )

    def _print_misses(self, row):
        self.stdout.write(f"\nwrong on {row['label']}: {len(row['misses'])}")
        seen: Counter = Counter()
        for m in row["misses"]:
            key = m["name"].rsplit(" ", 1)[0]
            seen[f"{key} -> {m['decision']}"] += 1
        for key, n in seen.most_common():
            self.stdout.write(f"  {n:>3}  {key}")

    def _markdown(self, rows, cases) -> str:
        counts = Counter(c["label"] for c in cases)
        lines = [
            "# 룰엔진 도입 타임라인 — 단계별 채점", "",
            f"_검증셋 {len(cases)}건 — 승인 {counts[golden.APPROVE]} · "
            f"보완반려 {counts[golden.BLOCK]}_", "",
            "**룰엔진은 분류기다** — 확실한 건만 분류하고 나머지는 검토로 넘긴다.",
            "`PASS`·`RETURN`·`REJECT`=확정(자동처리), `REVIEW`=미확정(사람에게).", "",
            "· **자동처리율** = 1 − 검토/전체 — 룰이 결론 낸 비율",
            "· **오탐율** = 확정한 것 중 틀린 비율(승인↔보완반려가 뒤집힌 건)", "",
            "미탐은 재지 않는다 — 검토 비율은 자동처리율의 역이라 같은 수를 두 번 적는 셈이다.",
            "",
            "| 단계 | 무엇이 늘었나 | 과목 규칙 | 자동처리율 | 오탐율 |",
            "|---|---|---|---|---|",
        ]
        for r in rows:
            lines.append(
                f"| **{r['label']}** | {r['note']} | {', '.join(r['scopes']) or '—'} | "
                f"**{r['autoRate']:.1f}%** ({r['settled']}/{r['n']}) | "
                f"{r['wrongRate']:.1f}% ({r['wrong']}/{r['settled']}) |"
            )
        lines += ["", "## 판정 분포", "",
                  "| 단계 | PASS | RETURN | REJECT | REVIEW |", "|---|---|---|---|---|"]
        for r in rows:
            d = r["decisions"]
            lines.append(f"| {r['label']} | " + " | ".join(
                str(d.get(k, 0)) for k in ("PASS", "RETURN", "REJECT", "REVIEW")) + " |")
        last = rows[-1]
        if last["misses"]:
            lines += ["", "## 최종 단계에 남은 오탐", ""]
            seen: Counter = Counter()
            for m in last["misses"]:
                seen[f"{m['name'].rsplit(' ', 1)[0]} → `{m['decision']}`"] += 1
            for key, n in seen.most_common():
                lines.append(f"- {key} — {n}건")
        return "\n".join(lines) + "\n"

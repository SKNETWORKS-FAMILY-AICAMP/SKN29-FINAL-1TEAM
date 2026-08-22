"""카탈로그 JSON → 프롬프트 마크다운.

렌더러가 여기 있는 이유는 프롬프트가 여기 있기 때문이다. 문구를 바꾸려고 Django를
재배포해야 하면 아무도 프롬프트를 안 고친다(core는 사실만, 여기가 문장).

서식 규칙 두 개:
  · **한 줄 = 한 항목.** 표(`|`)는 토큰을 두 배로 먹고 모델이 열을 흘린다.
  · `notes`는 섹션 끝에 `- ` 목록으로 붙인다 — core가 소유한 도메인 불변식이라
    여기서 요약하거나 고쳐 쓰지 않고 **그대로** 싣는다.
"""
from __future__ import annotations

import json
from typing import Any


def _dsl_grammar(d: dict[str, Any]) -> list[str]:
    ops = " ".join(f"`{o}`" for o in d["logic_operators"] + d["compare_operators"])
    return [
        f"허용 연산자: {ops} · 값 참조 `{d['value_operator']}` (최대 중첩 {d['max_depth']})",
    ]


def _eval_context_paths(d: dict[str, Any]) -> list[str]:
    lines = [f"스키마 v{d['schema_version']} (조립기 {d['builder_version']})"]
    for sec in d.get("sections", []):
        fields = sec.get("fields", [])
        if not fields:
            # tables·conflicts처럼 고정 필드가 없는 감사 섹션. 있다는 사실만 알린다.
            lines.append(f"\n[{sec['section']}] {sec['title']} — 고정 필드 없음(룰 참조 불가)")
            continue
        lines.append(f"\n[{sec['section']}] {sec['title']}")
        for f in fields:
            enum = f" ←어휘:{f['enum']}" if f.get("enum") else ""
            lines.append(f"  {f['path']} ({f['type']}){enum} — {f['desc']}")
    return lines


def _policy_vars(d: dict[str, Any]) -> list[str]:
    def row(v: dict[str, Any]) -> str:
        axes = ", ".join(v["key_axes"]) if v.get("key_axes") else "축 없음"
        state = "적재됨" if v.get("loaded") else "⚠️ 미적재 — 참조하면 판정이 검토로 강등된다"
        title = f" {v['title']}" if v.get("title") else ""
        return f"  {v['path']} ← {v['table_key']}{title} [축: {axes}] ({state})"

    lines = [row(v) for v in d.get("vars", [])]
    derived = d.get("derived") or []
    if derived:
        lines.append("\n별표에서 선해소되지만 `policy.*`가 아닌 자리에 들어가는 값:")
        lines += [row(v) for v in derived]
    return lines


def _action_schema(d: dict[str, Any]) -> list[str]:
    lines = [
        "decision: " + " ".join(f"`{x}`" for x in d["decisions"]),
        "severity(심각한 순): " + " ".join(f"`{x}`" for x in d["severities"]),
    ]
    effect = d.get("decision_effect") or {}
    if effect:
        lines.append("판정이 정산을 보내는 곳:")
        lines += [f"  {k} → {v['label']}({v['status']})" for k, v in effect.items()]
    return lines


def _flags_registry(d: dict[str, Any]) -> list[str]:
    cats = d.get("categories", {})
    by_cat: dict[str, list[dict[str, Any]]] = {}
    for f in d.get("rule_flags", []):
        by_cat.setdefault(f.get("category", ""), []).append(f)

    lines: list[str] = []
    for cat, rows in by_cat.items():
        lines.append(f"\n[{cats.get(cat, cat)}]")
        for f in rows:
            lines.append(
                f"  {f['code']} — {f['label']} "
                f"(심각도 {f.get('severity', '')} · 해소 {f.get('owner', '')}): {f.get('description', '')}"
            )
    system = d.get("system_flags") or []
    if system:
        lines.append("\n[엔진 전용 — 룰이 쓰지 말 것] " + ", ".join(f["code"] for f in system))
    return lines


_RENDERERS = {
    "dsl.grammar": _dsl_grammar,
    "eval_context.paths": _eval_context_paths,
    "policy.vars": _policy_vars,
    "action.schema": _action_schema,
    "flags.registry": _flags_registry,
}


def render_section(section: dict[str, Any]) -> str:
    renderer = _RENDERERS.get(section["id"])
    if renderer is None:
        # 모르는 섹션(core가 먼저 늘어난 경우)도 버리지 않는다 — 원본을 그대로 싣는다.
        body = [json.dumps(section.get("data", {}), ensure_ascii=False, indent=1)]
    else:
        body = renderer(section.get("data", {}))
    out = [f"## {section['title']}", *body]
    for note in section.get("notes", []):
        out.append(f"- {note}")
    return "\n".join(out)


def render(sections: list[dict[str, Any]], *, stale: bool = False, error: str = "") -> str:
    if stale or not sections:
        # 조용히 빈 블록을 내보내면 모델이 "제약이 없다"로 읽는다. 실패를 실패로 적는다.
        head = (
            "## ⚠️ 도메인 카탈로그 조회 실패\n"
            "허용 경로·플래그·임계값 목록을 가져오지 못했다. **확실한 것만 보수적으로** 쓰고, "
            "조금이라도 불확실하면 만들지 말고 건너뛴 사유를 남겨라."
        )
        if error:
            head += f"\n(사유: {error})"
        return head if not sections else head + "\n\n" + "\n\n".join(render_section(s) for s in sections)
    return "\n\n".join(render_section(s) for s in sections)

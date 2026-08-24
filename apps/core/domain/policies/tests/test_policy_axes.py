"""별표 축 정합 + `policy.*` 동적 노출 회귀.

여기서 고정하는 계약은 둘이다.

① **축은 실재하는 사실이어야 한다.** 축이 EvalContext 스키마에 없으면 `resolve_path`가 늘
   None을 돌려주고, `strict_keys=False`인 표는 `"*"`로 조용히 폴백한다 — 값도 나오고
   에러도 플래그도 없어서 그 표가 축을 잃은 걸 아무도 모른다. 실제로 `category.scope`가
   그 상태로 오래 있었다.

② **임계값은 열리고 사실은 닫힌다.** 고객이 규정을 올려 새 별표가 들어오면 그 값은 코드
   변경 없이 `ctx.policy.*`가 되고 룰이 참조할 수 있어야 한다. 반대로 사실 경로는 닫아
   둔다 — SoR·추출에 원천이 없는 경로를 열면 룰은 만들어지는데 값은 영원히 null이다.
"""
from __future__ import annotations

from datetime import date

from django.test import TestCase

from domain.policies.context_builder import (
    DERIVED_FROM_TABLE,
    NON_POLICY_TABLES,
    RESOLVERS,
    allowed_var_paths,
    check_table_axes,
    load_tables,
    policy_field_specs,
    policy_fields,
    resolve_policy,
)
from domain.policies.eval_context import (
    EVAL_CONTEXT_SCHEMA_PATHS,
    empty_eval_context,
    schema_catalog,
    validate_graph_vars,
)
from domain.policies.models import PolicyTable, RuleGraph, RuleGraphStatus, RuleNode
from domain.policies.services import activate
from domain.policies.tiger_tables import TABLES, upsert_all

EFFECTIVE = date(2026, 1, 1)


class TableAxisTests(TestCase):
    """① 축 정합"""

    def test_코드_별표의_모든_축이_스키마에_있다(self):
        """`tiger_tables.py`는 우리가 손으로 쓰는 파일이라 오타가 그대로 들어온다."""
        for spec in TABLES:
            for axis in spec.get("key_axes") or []:
                with self.subTest(table=spec["key"], axis=axis):
                    self.assertIn(axis, EVAL_CONTEXT_SCHEMA_PATHS)

    def test_적재된_별표의_축을_검사한다(self):
        upsert_all(EFFECTIVE)
        self.assertEqual(check_table_axes(), {})

    def test_스키마에_없는_축은_잡힌다(self):
        """DB 행만 낡은 경우 — 코드는 맞는데 시드가 옛 축을 들고 있는 상황이다."""
        PolicyTable.objects.create(
            key="stale_table", title="낡은 표", key_axes=["user.position"],
            payload={"*": 1}, effective_date=EFFECTIVE,
        )
        self.assertEqual(check_table_axes(), {"stale_table": ["user.position"]})


class DynamicPolicyFieldTests(TestCase):
    """② 임계값은 열린다"""

    def setUp(self):
        upsert_all(EFFECTIVE)
        self.tables = load_tables(EFFECTIVE)

    def test_기존_8종_이름이_유지된다(self):
        """이름이 바뀌면 이미 ACTIVE인 그래프의 조건이 통째로 깨진다."""
        fields = policy_fields(self.tables)
        for name, table_key in RESOLVERS.items():
            self.assertEqual(fields.get(name), table_key)

    def test_새_별표가_코드_변경_없이_변수가_된다(self):
        PolicyTable.objects.create(
            key="project_budget_limit_table", title="프로젝트별 예산 한도",
            key_axes=[], payload={"value": 700_000}, effective_date=EFFECTIVE,
        )
        tables = load_tables(EFFECTIVE)
        self.assertEqual(policy_fields(tables).get("project_budget_limit"), "project_budget_limit_table")

        ctx = empty_eval_context()
        resolve_policy(ctx, tables)
        self.assertEqual(ctx["policy"]["project_budget_limit"], 700_000)

    def test_조립기_전용_표와_다른_자리를_차지한_표는_빠진다(self):
        fields = policy_fields(self.tables)
        for table_key in set(DERIVED_FROM_TABLE.values()) | set(NON_POLICY_TABLES):
            with self.subTest(table=table_key):
                self.assertNotIn(table_key, fields.values())

    def test_스칼라가_아닌_표는_올리지_않는다(self):
        """DSL은 스칼라 비교만 한다 — 목록을 올리면 룰이 비교할 수 없는 값을 참조한다."""
        self.assertNotIn("required_evidence", policy_fields(self.tables))

    def test_사실_경로는_여전히_닫혀_있다(self):
        allowed = allowed_var_paths(self.tables)
        self.assertNotIn("project.code", allowed)
        self.assertNotIn("dining.org_unit", allowed)
        self.assertTrue({"tx.amount", "merchant.merchant_type"} <= allowed)

    def test_검증_기본값은_정적이고_숨은_조회가_없다(self):
        """판정 계열 함수에 숨은 I/O를 두지 않는다 — 동적 집합은 호출부가 명시로 넘긴다."""
        PolicyTable.objects.create(
            key="night_meal_limit_table", title="야간 식대 한도",
            key_axes=[], payload={"value": 20_000}, effective_date=EFFECTIVE,
        )
        graph = {"nodes": [{"condition": {
            ">": [{"var": "tx.amount"}, {"var": "policy.night_meal_limit"}]
        }}]}
        self.assertEqual(validate_graph_vars(graph), {"policy.night_meal_limit"})
        self.assertEqual(validate_graph_vars(graph, allowed_var_paths(load_tables(EFFECTIVE))), set())

    def test_없는_사실은_어느_쪽으로도_막힌다(self):
        graph = {"nodes": [{"condition": {"==": [{"var": "project.code"}, "X"]}}]}
        self.assertEqual(validate_graph_vars(graph), {"project.code"})
        self.assertEqual(
            validate_graph_vars(graph, allowed_var_paths(self.tables)), {"project.code"},
        )

    def test_프롬프트와_검증기가_같은_목록을_본다(self):
        """카탈로그가 모르는 변수를 검증기만 허용하면 모델은 그 값을 숫자로 박는다."""
        PolicyTable.objects.create(
            key="welfare_limit_table", title="복리후생비 한도",
            key_axes=[], payload={"value": 100_000}, effective_date=EFFECTIVE,
        )
        tables = load_tables(EFFECTIVE)
        catalog = schema_catalog(policy_field_specs(tables))
        advertised = {f["path"] for sec in catalog["sections"] for f in sec["fields"]}
        self.assertEqual(advertised, set(allowed_var_paths(tables)))
        self.assertIn("policy.welfare_limit", advertised)

    def test_새_변수_설명은_별표_제목에서_온다(self):
        PolicyTable.objects.create(
            key="welfare_limit_table", title="복리후생비 한도",
            key_axes=[], payload={"value": 100_000}, effective_date=EFFECTIVE,
        )
        specs = policy_field_specs(load_tables(EFFECTIVE))
        self.assertIn("복리후생비 한도", specs["welfare_limit"].desc)
        # 손으로 쓴 설명이 있는 정적 8종은 덮어쓰지 않는다.
        self.assertNotIn("dining_per_person_limit", specs)


class ActivationGateTests(TestCase):
    """게이트가 **실제로** 동적 목록을 넘기는지.

    `validate_graph_vars`의 기본값이 정적이라, 넘기는 걸 잊으면 새 별표를 참조하는 룰이
    승인 단계에서 막힌다 — 그것도 "EvalContext에 정의되지 않은 경로"라는, 원인을 짐작하기
    어려운 메시지로. 단위 함수가 아니라 이 경로를 고정한다.
    """

    def setUp(self):
        upsert_all(EFFECTIVE)
        PolicyTable.objects.create(
            key="welfare_limit_table", title="복리후생비 한도",
            key_axes=[], payload={"value": 100_000}, effective_date=EFFECTIVE,
        )
        self.draft = RuleGraph.objects.create(
            #  "비품"은 2026-08-24에 Category에서 폐기됐다 — scope CHECK 제약이 막는다.
            #  이 테스트가 보는 건 별표 축이지 과목이 아니라 아무 유효 scope나 쓰면 된다.
            name="복리후생 검증", scope="기타", status=RuleGraphStatus.DRAFT,
            version=1, entry_node_key="entry",
        )

    def _node(self, condition):
        RuleNode.objects.create(
            graph=self.draft, node_key="entry", condition=condition,
            action={"decision": "REVIEW", "severity": "MEDIUM"},
        )

    def test_새_별표를_참조하는_룰이_승인된다(self):
        self._node({">": [{"var": "tx.amount"}, {"var": "policy.welfare_limit"}]})
        activate(self.draft)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, RuleGraphStatus.ACTIVE)

    def test_원천_없는_사실은_승인에서_막힌다(self):
        self._node({"==": [{"var": "project.code"}, "X"]})
        with self.assertRaises(ValueError) as ctx:
            activate(self.draft)
        self.assertIn("project.code", str(ctx.exception))

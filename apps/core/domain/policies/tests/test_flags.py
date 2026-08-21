"""네임드 플래그 레지스트리 회귀.

고정하는 계약 (`policies/flags.py`):
  ① **플래그는 상태머신을 움직이지 않는다** — 상태는 `decision` 한 축이 정한다.
     같은 `decision`이면 플래그가 무엇이든 도착 상태가 같아야 한다.
  ② **열린 레지스트리** — 미등록 플래그도 판정은 그대로 돌고, ACTIVE 전환도 막지 않는다.
     고객 규정에서 생성된 룰이 새 어휘를 쓸 수 있기 때문이다. 대신 경고로 남긴다.
  ③ **시스템 플래그는 닫힌 집합** — 엔진이 만들고 룰 편집 선택지에서는 빠진다.
  ④ **라벨의 원천은 서버 하나** — 프론트가 사전을 복사하면 어긋난다(실제로 27 vs 9로 어긋났다).
  ⑤ 시드 룰이 쓰는 플래그는 전부 등록돼 있어야 한다 — 우리 어휘부터 흔들리면 통계가 갈린다.
"""
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from domain.accounts.models import Capability, Role, User
from domain.cards.models import Card
from domain.policies import services
from domain.policies.flags import (
    RULE_FLAGS,
    SystemFlag,
    describe,
    label_map,
    seed_rule_flags,
    split_flag,
    unknown_flags,
)
from domain.policies.models import (
    RuleFlag,
    RuleGraph,
    RuleGraphStatus,
    RuleNode,
    RuleRouting,
)
from domain.policies.scope import GLOBAL
from domain.settlements import services as settlement_services
from domain.settlements.models import Settlement
from domain.settlements.models import SettlementStatus as S
from domain.transactions.models import Transaction


def _graph(scope=GLOBAL, decision="PASS", flag="", status=RuleGraphStatus.ACTIVE):
    graph = RuleGraph.objects.create(
        name=f"{scope} 그래프", scope=scope, status=status, version=1, entry_node_key="n1",
    )
    action = {"decision": decision, "title": "t"}
    if flag:
        action["flag"] = flag
    RuleNode.objects.create(graph=graph, node_key="n1", condition=True, action=action)
    RuleRouting.objects.create(graph=graph, from_node_key="n1", on_result="MATCH", to_node_key="")
    return graph


class RegistrySeedTests(TestCase):
    def test_seeding_is_idempotent(self):
        first = seed_rule_flags()
        self.assertEqual(seed_rule_flags(), first)

    def test_system_flags_are_registered_and_marked(self):
        seed_rule_flags()
        for choice in SystemFlag:
            row = RuleFlag.objects.get(code=choice.value)
            self.assertTrue(row.is_system, f"{choice.value}는 시스템 플래그여야 한다")

    def test_rule_flags_are_not_system(self):
        """룰 편집 선택지에 `NO_ACTIVE_RULE_GRAPH`가 뜨면 의미가 뒤집힌다."""
        seed_rule_flags()
        codes = {code for code, *_ in RULE_FLAGS}
        self.assertFalse(RuleFlag.objects.filter(code__in=codes, is_system=True).exists())

    def test_seed_rule_vocabulary_is_registered(self):
        """시드 룰이 쓰는 플래그가 레지스트리에 다 있어야 한다.

        실측 배경: `seed_rules`는 `EVIDENCE_MISSING`, `seed_clean`은 `MISSING_RECEIPT`로
        같은 개념에 다른 이름을 쓰고 있었다 — 같은 저장소 안에서 이미 갈렸다.
        """
        from domain.common.management.commands import seed_clean, seed_rules

        seed_rule_flags()
        known = set(RuleFlag.objects.values_list("code", flat=True))
        used = set()
        for module in (seed_rules, seed_clean):
            source = open(module.__file__, encoding="utf-8").read()
            used |= {
                line.split('flag="')[1].split('"')[0]
                for line in source.splitlines() if 'flag="' in line
            }
        used.discard("")
        self.assertEqual(used - known, set(), "시드 룰이 미등록 플래그를 쓴다")


class LabelResolutionTests(TestCase):
    def setUp(self):
        seed_rule_flags()

    def test_known_flag_gets_its_label(self):
        info = describe("PRE_APPROVAL_MISSING", label_map())
        self.assertEqual(info["label"], "사전승인 누락")
        self.assertEqual(info["owner"], "APPROVER")
        self.assertTrue(info["known"])

    def test_unknown_flag_shows_the_raw_code(self):
        """감추면 판정 근거가 사라지고 오타를 아무도 못 본다."""
        info = describe("EVIDENCE_MISSNG", label_map())
        self.assertEqual(info["label"], "EVIDENCE_MISSNG")
        self.assertFalse(info["known"])

    def test_display_labels_come_from_the_server(self):
        """심각도·해소주체·분류의 **한글 표기까지** 서버가 싣는다.

        코드(`HIGH`·`APPROVER`)만 보내면 화면이 그 사전을 또 복사하게 되고, 그게 정확히
        이 모듈이 막으려던 상황이다(백엔드 27개 vs 프론트 9개로 실제 어긋났던 이력).
        """
        info = describe("PRE_APPROVAL_MISSING", label_map())
        self.assertEqual(info["severityLabel"], "높음")
        self.assertEqual(info["ownerLabel"], "결재권자")
        self.assertEqual(info["categoryLabel"], "결재·승인")
        self.assertTrue(info["description"])          # 화면이 "왜 걸렸는지"를 설명할 수 있어야 한다
        self.assertFalse(info["isSystem"])

    def test_system_flag_is_marked_as_such(self):
        """엔진이 붙인 플래그는 룰이 만든 게 아니다 — 화면이 구분해 표시할 수 있어야 한다."""
        info = describe("UNRESOLVED_FACT:approval.pre_approval_obtained", label_map())
        self.assertTrue(info["isSystem"])
        self.assertEqual(info["arg"], "approval.pre_approval_obtained")

    def test_unknown_flag_display_fields_are_blank_not_missing(self):
        """미등록 코드도 같은 키를 갖는다 — 화면이 키 존재 여부로 분기하지 않게."""
        info = describe("NOPE", label_map())
        for key in ("description", "severityLabel", "ownerLabel", "categoryLabel"):
            self.assertEqual(info[key], "")

    def test_parameterized_system_flag_keeps_its_argument(self):
        info = describe("UNRESOLVED_FACT:approval.pre_approval_obtained", label_map())
        self.assertEqual(info["code"], "UNRESOLVED_FACT")
        self.assertEqual(info["arg"], "approval.pre_approval_obtained")
        self.assertIn("approval.pre_approval_obtained", info["label"])

    def test_split_flag_without_argument(self):
        self.assertEqual(split_flag("HIGH_AMOUNT"), ("HIGH_AMOUNT", ""))


class FlagsDoNotDriveStateTests(TestCase):
    """**핵심 불변식**: 같은 `decision`이면 플래그가 무엇이든 도착 상태가 같다."""

    def setUp(self):
        seed_rule_flags()
        self.user = User.objects.create_user("kim", password="pw", role=Role.EMPLOYEE)

    def _settle(self):
        card = Card.objects.create(name="법인카드", card_type="SHARED")
        tx = Transaction.objects.create(
            card=card, merchant="강남한식당", amount=Decimal("452000"), ts=timezone.now(),
        )
        return Settlement.objects.create(
            transaction=tx, category="접대", status=S.DRAFT, purpose="접대",
        )

    def test_state_is_identical_regardless_of_flag(self):
        outcomes = []
        for flag in ("", "PRE_APPROVAL_MISSING", "PROHIBITED_MERCHANT"):
            RuleGraph.objects.all().delete()
            _graph(decision="PASS", flag=flag)
            settlement = self._settle()
            settlement_services.raise_to_team(settlement, self.user)
            settlement_services.submit(settlement, self.user)
            settlement_services.judge(settlement, self.user, reuse_recorded=True)
            settlement.refresh_from_db()
            outcomes.append(settlement.status)
        self.assertEqual(set(outcomes), {S.PENDING_CONFIRM}, "플래그가 상태를 바꿨다")

    def test_flag_is_recorded_as_a_reason(self):
        _graph(decision="RETURN", flag="EVIDENCE_MISSING")
        settlement = self._settle()
        settlement_services.raise_to_team(settlement, self.user)
        settlement.refresh_from_db()
        self.assertIn("EVIDENCE_MISSING", settlement.rule_flags)
        self.assertEqual(settlement.rule_decision, "RETURN")


class UnknownFlagWarningTests(TestCase):
    def setUp(self):
        seed_rule_flags()
        self.lead = User.objects.create_user(
            "acclead", password="pw", role=Role.ACCOUNTANT_LEAD,
            extra_capabilities=[Capability.RULE_ACTIVATE.value],
        )

    def test_unknown_flags_are_detected(self):
        graph = _graph(decision="RETURN", flag="TOTALLY_NEW_THING", status=RuleGraphStatus.DRAFT)
        snapshot = services._snapshot(graph)
        self.assertEqual(unknown_flags(snapshot), ["TOTALLY_NEW_THING"])

    def test_registered_flags_produce_no_warning(self):
        graph = _graph(decision="RETURN", flag="EVIDENCE_MISSING", status=RuleGraphStatus.DRAFT)
        self.assertEqual(unknown_flags(services._snapshot(graph)), [])

    def test_activation_is_not_blocked_by_unknown_flags(self):
        """고객 규정에서 생성된 룰이 새 어휘를 쓸 수 있다 — 막으면 룰 생성이 멈춘다."""
        graph = _graph(decision="RETURN", flag="CUSTOMER_SPECIFIC", status=RuleGraphStatus.DRAFT)
        services.activate(graph, self.lead)
        graph.refresh_from_db()
        self.assertEqual(graph.status, RuleGraphStatus.ACTIVE)
        self.assertEqual(graph.unknown_flags, ["CUSTOMER_SPECIFIC"])


class FlagRegistryApiTests(TestCase):
    def setUp(self):
        seed_rule_flags()
        self.user = User.objects.create_user("acc", password="pw", role=Role.ACCOUNTANT)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_registry_excludes_system_flags_by_default(self):
        rows = self.client.get("/api/rules/flags/").data
        codes = {r["code"] for r in rows}
        self.assertIn("EVIDENCE_MISSING", codes)
        self.assertNotIn(SystemFlag.NO_ACTIVE_RULE_GRAPH.value, codes)

    def test_system_flags_available_on_request(self):
        rows = self.client.get("/api/rules/flags/?system=1").data
        codes = {r["code"] for r in rows}
        self.assertIn(SystemFlag.NO_ACTIVE_RULE_GRAPH.value, codes)


class SettlementFlagInfoTests(TestCase):
    """화면이 라벨 사전을 따로 들지 않게 서버가 실어 보낸다."""

    def setUp(self):
        seed_rule_flags()
        self.user = User.objects.create_user("acc", password="pw", role=Role.ACCOUNTANT)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_flag_info_is_serialized_with_labels(self):
        _graph(decision="RETURN", flag="EVIDENCE_MISSING")
        card = Card.objects.create(name="법인카드", card_type="SHARED")
        tx = Transaction.objects.create(
            card=card, merchant="강남한식당", amount=Decimal("452000"), ts=timezone.now(),
        )
        settlement = Settlement.objects.create(
            transaction=tx, category="접대", status=S.DRAFT, purpose="접대",
        )
        settlement_services.raise_to_team(settlement, self.user)

        row = self.client.get(f"/api/settlements/{settlement.pk}/").data
        self.assertEqual(row["ruleFlags"], ["EVIDENCE_MISSING"])
        self.assertEqual(row["ruleFlagInfo"][0]["label"], "적격증빙 없음")
        self.assertEqual(row["ruleFlagInfo"][0]["owner"], "SPENDER")

"""직책·직급 코드 테이블 회귀 — 타이거 규정 원문 기준.

고정하는 계약 (「직급체계」 · 「법인카드 사용 규정」 별표1):
  ① **직책이 권위 축이다** — "결재 권한 및 법인카드 사용한도는 직책 기준으로 부여한다
     (직급 기준이 아니다)". 별표1 각주도 "직급(사원~전무)과는 무관하다"고 못박는다.
  ② **직급은 판정에 올라가지 않는다** — 처우(급여·승진) 축이다. EvalContext에 넣으면
     "직급으로 한도를 정할 수 있다"는 잘못된 신호를 룰 작성자에게 준다.
  ③ 조직 마스터는 **SoR에서** 온다 — 문서(RAG) 선해소가 아니다. 재현성·엔티티매칭·발령일.
  ④ **모르면 `None`** — 직책 미지정을 임의로 채우지 않는다. 별표는 와일드카드로 해소되고,
     그 기본값은 **가장 좁은 한도(비직책자)** 다. 모를 때 느슨해지면 규정보다 헐거워진다.
  ⑤ 이름(`name`)이 **별표 룩업 키**다 — 어긋나면 한도가 조용히 와일드카드로 떨어진다.
  ⑥ 서열(`rank`)로 상하를 비교한다 — 이름 비교로 만들면 체계가 바뀔 때 룰을 전부 고쳐야 한다.
"""
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from domain.accounts.models import JobTitle, Position, Role, User
from domain.accounts.org_codes import check_table_keys, seed_org_codes
from domain.cards.models import Card
from domain.policies.context_builder import build_rule_context
from domain.policies.eval_context import EVAL_CONTEXT_SCHEMA_PATHS
from domain.policies.tiger_tables import upsert_all
from domain.settlements.models import Settlement
from domain.settlements.models import SettlementStatus as S
from domain.transactions.models import Transaction


class OrgCodeSeedTests(TestCase):
    def test_seeding_is_idempotent(self):
        first = seed_org_codes()
        second = seed_org_codes()
        self.assertEqual(first, second)

    def test_job_title_ladder_matches_the_regulation(self):
        """별표1의 행이 곧 직책 목록이다 — 빠지면 그 직책의 한도가 와일드카드로 떨어진다."""
        seed_org_codes()
        names = list(JobTitle.objects.order_by("rank").values_list("name", flat=True))
        self.assertEqual(names, ["비직책자(공용카드)", "팀장", "부서장", "본부장", "대표이사"])

    def test_position_ladder_has_ten_grades(self):
        """「직급체계」§2: 총 10단계(사원~대표이사)."""
        seed_org_codes()
        names = list(Position.objects.order_by("rank").values_list("name", flat=True))
        self.assertEqual(len(names), 10)
        self.assertEqual(names[0], "사원")
        self.assertEqual(names[-1], "대표이사")

    def test_position_and_job_title_are_independent(self):
        """부장(직급)인데 직책이 없을 수 있고, 과장(직급)이 팀장(직책)일 수 있다."""
        seed_org_codes()
        senior_without_title = User.objects.create_user(
            "senior", password="pw",
            position=Position.objects.get(name="부장"),
            job_title=JobTitle.objects.get(name="비직책자(공용카드)"),
        )
        junior_with_title = User.objects.create_user(
            "lead", password="pw", role=Role.TEAM_LEAD,
            position=Position.objects.get(name="과장"),
            job_title=JobTitle.objects.get(name="팀장"),
        )
        # 직급은 부장 > 과장인데, 권한(직책)은 반대다 — 직급으로 한도를 정하면 뒤집힌다.
        self.assertGreater(senior_without_title.position.rank, junior_with_title.position.rank)
        self.assertLess(senior_without_title.job_title.rank, junior_with_title.job_title.rank)

    def test_table_keys_are_fully_covered(self):
        """별표 축 값이 코드 테이블에 다 있어야 한다.

        이전 구현은 `daily/monthly_limit_table`의 축이 `user.position`(직급)인데 payload에
        직책(`본부장`)과 직급(`과장`·`대리`)이 섞여 있었다. 규정 원문 대조로 축=직책,
        값=별표1로 확정하면서 해소됐다.
        """
        seed_org_codes()
        self.assertEqual(check_table_keys(), {})


class EvalContextAxisTests(TestCase):
    """판정에 올라가는 건 직책뿐이다."""

    def test_position_is_not_a_judgement_input(self):
        """직급을 스키마에 두면 "직급으로 한도를 정할 수 있다"는 잘못된 신호가 된다."""
        self.assertIn("user.job_title", EVAL_CONTEXT_SCHEMA_PATHS)
        self.assertIn("user.job_title_rank", EVAL_CONTEXT_SCHEMA_PATHS)
        self.assertNotIn("user.position", EVAL_CONTEXT_SCHEMA_PATHS)
        self.assertNotIn("user.position_rank", EVAL_CONTEXT_SCHEMA_PATHS)


class ContextJobTitleTests(TestCase):
    def setUp(self):
        seed_org_codes()
        upsert_all()
        card = Card.objects.create(name="법인카드", card_type="SHARED")
        tx = Transaction.objects.create(
            card=card, merchant="강남한식당", amount=Decimal("452000"), ts=timezone.now(),
        )
        self.settlement = Settlement.objects.create(
            transaction=tx, category="접대", status=S.DRAFT, purpose="접대",
        )

    def _ctx(self, **user_kwargs):
        if user_kwargs:
            self.settlement.submitted_by = User.objects.create_user("kim", password="pw", **user_kwargs)
            self.settlement.save(update_fields=["submitted_by"])
        ctx, _ = build_rule_context(settlement=self.settlement)
        return ctx

    def test_job_title_reaches_the_eval_context(self):
        ctx = self._ctx(
            position=Position.objects.get(name="과장"),
            job_title=JobTitle.objects.get(name="팀장"),
        )
        self.assertEqual(ctx["user"]["job_title"], "팀장")
        self.assertEqual(ctx["user"]["job_title_rank"], JobTitle.objects.get(name="팀장").rank)

    def test_limits_resolve_from_the_job_title(self):
        """별표1 원문값: 팀장 1일 100만 · 월 400만 · 사전승인 50만 초과."""
        ctx = self._ctx(job_title=JobTitle.objects.get(name="팀장"))
        self.assertEqual(ctx["policy"]["position_daily_limit"], 1_000_000)
        self.assertEqual(ctx["policy"]["position_monthly_limit"], 4_000_000)
        self.assertEqual(ctx["policy"]["preapproval_threshold"], 500_000)

    def test_grade_does_not_change_the_limit(self):
        """같은 직책이면 직급이 달라도 한도가 같아야 한다 — 규정이 그렇게 정한다."""
        limits = []
        for idx, grade in enumerate(["사원", "부장"]):
            settlement = Settlement.objects.create(
                transaction=self.settlement.transaction, category="접대", status=S.DRAFT,
                submitted_by=User.objects.create_user(
                    f"u{idx}", password="pw",
                    position=Position.objects.get(name=grade),
                    job_title=JobTitle.objects.get(name="팀장"),
                ),
            )
            ctx, _ = build_rule_context(settlement=settlement)
            limits.append(ctx["policy"]["position_daily_limit"])
        self.assertEqual(limits[0], limits[1])

    def test_unknown_job_title_falls_back_to_the_narrowest_limit(self):
        """모를 때 느슨해지면 규정보다 헐거워진다 — 와일드카드는 비직책자 값이다."""
        ctx = self._ctx()   # 직책 미지정
        self.assertIsNone(ctx["user"]["job_title"])
        self.assertEqual(ctx["policy"]["position_daily_limit"], 500_000)
        self.assertEqual(
            ctx["policy"]["position_daily_limit"],
            500_000,  # 별표1 비직책자(공용카드) 1일 한도와 동일
        )

"""`seed_adopted` 회귀 — 3개월째 굴러가고 있는 회사의 시연 상태.

시드 하나가 20초 넘게 걸리므로 **클래스당 한 번만 돌리고**(`setUpTestData`) 그 위에서
계약을 확인한다. 여기서 지키는 것:

  ① **판정이 진짜다** — 시드가 상태 문자열을 박지 않고 `services`의 전이를 태운다.
     그래서 `rule_hits`·`SettlementEvent`·ERP 전표가 정산 수에 걸맞게 존재한다.
  ② **시각이 되돌려져 있다** — `auto_now_add` 때문에 이력이 전부 "지금"으로 찍히면
     월별 통계와 검토 소요시간이 통째로 무너진다.
  ③ **지난달은 끝나 있다** — 미결이 지난달에 남아 있으면 "적용 완료"가 아니라 "밀린 회사"다.
  ④ **엔진이 시드의 기대와 같은 답을 냈다** — 룰이 바뀌면 여기서 먼저 깨져야 한다.
  ⑤ **예산 불변식** — 팀 총한도 = 과목 한도 합, 모든 과목에 행이 있다.
"""
from collections import Counter, defaultdict

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from domain.erp.models import ErpVoucher
from domain.notifications.models import Notification
from domain.policies.models import RuleGraph, RuleGraphStatus, RuleHit
from domain.settlements.models import Category, Settlement, SettlementEvent, TeamBudget
from domain.settlements.models import SettlementStatus as S
from domain.common.management.commands.seed_adopted import CASES, INTENTIONAL_UNRESOLVED
from domain.risk.models import DecisionCase

#: 「아직 진행 중」인 상태들 — 지난달에 이게 남아 있으면 안 된다.
OPEN_STATES = {
    S.DRAFT, S.TEAM_COLLECTING, S.TEAM_RETURNED, S.SUBMITTED,
    S.RPA_JUDGED, S.PENDING_CONFIRM, S.IN_REVIEW, S.RETURNED,
}


class SeedAdoptedTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_adopted", verbosity=0)
        cls.this_month = timezone.localdate().strftime("%Y-%m")
        cls.by_month = defaultdict(Counter)
        for s in Settlement.objects.select_related("transaction"):
            key = timezone.localtime(s.transaction.ts).strftime("%Y-%m")
            cls.by_month[key][s.status] += 1

    # ── ① 판정이 진짜다 ────────────────────────────────────────────────
    def test_판정로그가_정산마다_남아_있다(self):
        """`rule_hits`가 비면 검토 화면이 "왜 이 판정인지"를 못 보여준다."""
        judged = Settlement.objects.exclude(status=S.DRAFT).count()
        self.assertGreater(judged, 100)
        self.assertGreaterEqual(RuleHit.objects.count(), judged)

    def test_확정된_건에는_ERP_전표안이_있다(self):
        """확정(CONFIRMED)의 다음 단계가 전표(안) 생성이다 — 서비스가 만든다."""
        drafted = Settlement.objects.filter(status=S.ERP_VOUCHER_DRAFTED).count()
        self.assertGreater(drafted, 100)
        self.assertEqual(ErpVoucher.objects.count(), drafted)

    def test_상태_이력이_서비스를_거쳐_쌓였다(self):
        """상태를 직접 쓰면 이력이 없다 — 그러면 감사도 통계도 못 한다."""
        for settlement in Settlement.objects.filter(status=S.ERP_VOUCHER_DRAFTED)[:5]:
            states = list(settlement.events.order_by("id").values_list("to_state", flat=True))
            self.assertEqual(states[0], S.TEAM_COLLECTING)
            self.assertEqual(states[-1], S.ERP_VOUCHER_DRAFTED)
            self.assertIn(S.RPA_JUDGED, states)

    # ── ② 시각이 되돌려져 있다 ─────────────────────────────────────────
    def test_이력_시각이_거래월과_같은_달에_있다(self):
        """`auto_now_add`를 그대로 두면 지난달 건의 이력이 오늘로 찍힌다."""
        months = {timezone.localtime(e.created_at).strftime("%Y-%m")
                  for e in SettlementEvent.objects.all()}
        self.assertGreaterEqual(len(months), 3, months)

    def test_평균_검토시간을_계산할_수_있다(self):
        """IN_REVIEW 진입과 결정이 같은 시각이면 지표가 0분으로 죽는다."""
        durations = []
        for ev in SettlementEvent.objects.filter(from_state=S.IN_REVIEW):
            entered = (SettlementEvent.objects
                       .filter(settlement_id=ev.settlement_id, to_state=S.IN_REVIEW,
                               created_at__lte=ev.created_at)
                       .order_by("-created_at").first())
            if entered:
                durations.append((ev.created_at - entered.created_at).total_seconds())
        self.assertTrue(durations)
        self.assertTrue(all(d > 0 for d in durations), durations)

    # ── ③ 지난달은 끝나 있다 ───────────────────────────────────────────
    def test_지난달에는_미결이_없다(self):
        past = [m for m in self.by_month if m != self.this_month]
        self.assertTrue(past)
        for month in past:
            open_rows = {k: v for k, v in self.by_month[month].items() if k in OPEN_STATES}
            self.assertEqual(open_rows, {}, f"{month}에 미결이 남았다: {open_rows}")

    def test_이번달에는_처리할_일이_남아_있다(self):
        """전부 끝나 있으면 팀 취합·검토 화면이 빈 껍데기가 된다."""
        current = self.by_month[self.this_month]
        self.assertGreater(current[S.TEAM_COLLECTING], 0)
        self.assertGreater(current[S.IN_REVIEW], 0)
        self.assertGreater(current[S.PENDING_CONFIRM], 0)

    # ── ④ 룰 상태 ──────────────────────────────────────────────────────
    def test_회사_규정_반영_그래프가_활성이다(self):
        """제품 기본 게이트는 같은 GLOBAL scope라 물러나 있어야 한다(초기 상태는 seed_clean)."""
        active = {g.scope for g in RuleGraph.objects.filter(status=RuleGraphStatus.ACTIVE)}
        self.assertIn("GLOBAL", active)
        self.assertIn(Category.ENTERTAIN.value, active)
        self.assertFalse(
            RuleGraph.objects.filter(name__contains="기본 정산 게이트",
                                     status=RuleGraphStatus.ACTIVE).exists()
        )

    def test_검토로_간_건에는_사유가_붙어_있다(self):
        """사유 없이 검토 큐에 오면 담당자가 빈손으로 받는다.

        **판정 이력(`RuleHit`)을 본다.** 정산의 현재 `rule_judgement`가 아니다 — 보완 후
        재제출된 건은 그 뒤 판정이 `PASS`로 덮여, "검토로 왔을 때 사유가 있었는가"를
        현재값으로는 물을 수 없다(실측: 사례 건 6개가 그래서 사유 없음으로 잡혔다).
        """
        reviewed = Settlement.objects.filter(events__to_state=S.IN_REVIEW).distinct()
        self.assertTrue(reviewed.exists())
        for settlement in reviewed:
            hits = RuleHit.objects.filter(settlement=settlement, decision="REVIEW")
            self.assertTrue(hits.exists(), f"{settlement.pk} 검토 판정 이력이 없다")
            for flags in hits.values_list("flags", flat=True):
                real = [f for f in (flags or []) if not f.startswith("NO_SCOPE")]
                self.assertTrue(real, f"{settlement.pk} 사유 없음: {flags}")

    def test_미해소_강등으로_검토에_온_건이_없다(self):
        """`UNRESOLVED_*`는 "사실이 없어서 판정을 못 했다"는 뜻이다 — 적용 완료 회사엔
        그런 건이 없어야 한다(있으면 시드가 채워야 할 사실을 빠뜨린 것이다).

        **예외는 시드가 일부러 만든 것뿐이다**(`INTENTIONAL_UNRESOLVED`). 업종을 못 접은
        가맹점은 금지업종 여부도 알 수 없고, 그때 사람에게 넘기는 것이 설계다 — 결정 사례
        조리법 하나가 정확히 그 상황을 만든다. 목록에 없는 경로가 뜨면 그건 진짜 누락이다.
        """
        offenders = []
        for settlement in Settlement.objects.exclude(status=S.DRAFT):
            flags = (settlement.rule_judgement or {}).get("flags", [])
            bad = [f for f in flags
                   if f.startswith("UNRESOLVED") and f not in INTENTIONAL_UNRESOLVED]
            if bad:
                offenders.append((settlement.pk, settlement.category, bad))
        self.assertEqual(offenders, [], offenders[:5])

    def test_결정_사례가_세_패턴으로_쌓여_있다(self):
        """사례는 시드가 쓰는 게 아니라 `services.review()`가 「사람이 기계와 다르게
        판단했다」고 보고 남기는 것이다. 그래서 중간 고리가 하나만 끊겨도(엔진이 REVIEW를
        안 내거나·검토를 안 거치거나·사유가 비거나) **조용히 0건이 된다** — 실제로 오랫동안
        0건이었다. 여기서 그 연결을 통째로 고정한다.
        """
        cases = DecisionCase.objects.all()
        self.assertEqual(cases.count(), len(CASES))
        #  세 패턴이 각각 남아야 한다. 한 방향만 쌓이면 검색이 그쪽으로 쏠린다.
        moves = Counter(f"{c.expected}->{c.outcome}" for c in cases)
        self.assertGreater(moves["REJECT->APPROVE"], 0, moves)    # A 오탐 교정
        self.assertGreater(moves["APPROVE->RETURN"] + moves["APPROVE->REJECT"], 0, moves)  # B 미탐
        self.assertGreater(moves["REJECT->RETURN"], 0, moves)     # C 수위 조정
        for case in cases:
            #  사유가 사례의 본체다 — 짧으면 검색돼도 쓸모가 없다.
            self.assertGreaterEqual(len(case.reason), 40, case.case_id)
            self.assertIn(case.reason.strip()[:20], case.text)

    # ── ⑤ 예산·알림 ────────────────────────────────────────────────────
    def test_월별_예산이_세_달치_있다(self):
        months = set(TeamBudget.objects.values_list("year_month", flat=True))
        self.assertGreaterEqual(len(months), 3, months)

    def test_예산_불변식(self):
        """총한도 != 과목 합이면 대시보드가 원인 없이 어긋난다(과거 실제 결함)."""
        for month in set(TeamBudget.objects.values_list("year_month", flat=True)):
            for team_id in set(TeamBudget.objects.filter(year_month=month)
                               .values_list("team_id", flat=True)):
                rows = TeamBudget.objects.filter(year_month=month, team_id=team_id)
                self.assertEqual(
                    rows.get(category="").limit_amount,
                    sum(r.limit_amount for r in rows.exclude(category="")),
                )
                self.assertEqual(
                    set(rows.exclude(category="").values_list("category", flat=True)),
                    set(Category.values),
                )

    def test_종결된_건의_알림은_남기지_않는다(self):
        """3개월치 전이를 다 태우면 알림 수백 개가 종이 되어 첫 화면을 덮는다."""
        alive = set(Settlement.objects.exclude(
            status__in=[S.CONFIRMED, S.ERP_VOUCHER_DRAFTED, S.REJECT, S.TEAM_REJECTED]
        ).values_list("pk", flat=True))
        targets = {n.target for n in Notification.objects.all()}
        for target in targets:
            _, _, pk = target.partition(":")
            if pk.isdigit():
                self.assertIn(int(pk), alive, target)

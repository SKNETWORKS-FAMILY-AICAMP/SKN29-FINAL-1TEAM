"""ERP 결제기록 수집·본인 등록 회귀.

고정하는 계약:
  ① **귀속은 카드 구분이 정한다** — 개인카드는 배정자에게 바로, 팀·공용카드는 주인 없이.
  ② **모르는 건 모르는 채로** — 팀카드 건의 실사용자를 임의로 채우지 않는다.
     `actual_user_recorded`는 판정이 쓰는 사실이라 지어내면 그대로 오판이 된다.
  ③ **멱등** — 같은 결제가 두 번 들어오지 않는다. 버튼을 여러 번 눌러도 다음 회차만.
  ④ **본인 등록** — 같은 팀 사람만, DRAFT일 때만, 주인 없을 때만.
"""
from django.test import TestCase
from rest_framework.test import APIClient

from domain.accounts.models import Role, Team, User
from domain.cards.models import CardType
from domain.settlements import erp_import
from domain.settlements.models import Settlement, SettlementStatus
from domain.transactions.models import Transaction


class ErpImportTests(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name="재무회계팀", bu="경영지원본부")
        self.acc = User.objects.create_user("acc", password="pw", role=Role.ACCOUNTANT,
                                            team=self.team, first_name="박회계")
        self.mate = User.objects.create_user("mate", password="pw", role=Role.EMPLOYEE,
                                             team=self.team, first_name="동료")

    def test_personal_card_is_attributed_immediately(self):
        erp_import.import_next_batch(self.acc)
        personal = Settlement.objects.filter(transaction__card__card_type=CardType.PERSONAL)
        self.assertTrue(personal.exists())
        for s in personal:
            self.assertEqual(s.submitted_by_id, self.acc.pk)
            # 개인카드는 소유자가 곧 사용자라 실사용자 기록이 성립한다.
            self.assertIs(s.actual_user_recorded, True)
            self.assertEqual(s.actual_user_id, self.acc.pk)

    def test_team_card_has_no_owner_and_no_invented_facts(self):
        """주인을 임의로 채우면 `actual_user_recorded`가 거짓 사실이 된다."""
        erp_import.import_next_batch(self.acc)
        team_rows = Settlement.objects.filter(transaction__card__card_type=CardType.TEAM)
        self.assertTrue(team_rows.exists())
        for s in team_rows:
            self.assertIsNone(s.submitted_by_id)
            self.assertIsNone(s.actual_user_id)
            self.assertIsNone(s.actual_user_recorded)   # False가 아니라 None = 모름
            self.assertEqual(s.team_id, self.team.pk)   # 팀은 알고 있다 → 팀원에게 보인다

    def test_everything_lands_as_draft(self):
        erp_import.import_next_batch(self.acc)
        self.assertEqual(
            set(Settlement.objects.values_list("status", flat=True)), {SettlementStatus.DRAFT},
        )

    def test_batches_advance_and_then_exhaust(self):
        seen = []
        for _ in range(erp_import.TOTAL_BATCHES):
            result = erp_import.import_next_batch(self.acc)
            seen.append(result.batch)
            self.assertGreater(result.created, 0)
        self.assertEqual(seen, [1, 2, 3])

        done = erp_import.import_next_batch(self.acc)
        self.assertTrue(done.exhausted)
        self.assertEqual(done.created, 0)

    def test_reimport_does_not_duplicate(self):
        """버튼을 여러 번 눌러도 같은 결제가 두 건이 되면 안 된다."""
        erp_import.import_next_batch(self.acc)
        first = Transaction.objects.count()
        erp_import.import_next_batch(self.acc)      # 다음 회차
        second = Transaction.objects.count()
        self.assertGreater(second, first)
        # 이미 받은 회차의 external_id는 유일 제약이 지킨다.
        ids = list(Transaction.objects.values_list("external_id", flat=True))
        self.assertEqual(len(ids), len(set(ids)))

    def test_each_user_gets_their_own_records(self):
        erp_import.import_next_batch(self.acc)
        erp_import.import_next_batch(self.mate)
        self.assertTrue(Settlement.objects.filter(submitted_by=self.acc).exists())
        self.assertTrue(Settlement.objects.filter(submitted_by=self.mate).exists())


class ClaimTests(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name="재무회계팀")
        self.other_team = Team.objects.create(name="영업팀")
        self.acc = User.objects.create_user("acc", password="pw", role=Role.ACCOUNTANT, team=self.team)
        self.mate = User.objects.create_user("mate", password="pw", role=Role.EMPLOYEE, team=self.team)
        self.outsider = User.objects.create_user("out", password="pw", role=Role.EMPLOYEE,
                                                 team=self.other_team)
        erp_import.import_next_batch(self.acc)
        self.pending = Settlement.objects.filter(submitted_by__isnull=True).first()

    def test_claim_attributes_and_records_actual_user(self):
        """등록이 곧 `actual_user_recorded` 사실의 해소다 — 판정이 그 값을 쓴다."""
        erp_import.claim(self.pending, self.mate)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.submitted_by_id, self.mate.pk)
        self.assertEqual(self.pending.actual_user_id, self.mate.pk)
        self.assertIs(self.pending.actual_user_recorded, True)

    def test_other_team_cannot_claim(self):
        with self.assertRaises(erp_import.ClaimError):
            erp_import.claim(self.pending, self.outsider)

    def test_already_claimed_is_refused(self):
        erp_import.claim(self.pending, self.mate)
        self.pending.refresh_from_db()
        with self.assertRaises(erp_import.ClaimError):
            erp_import.claim(self.pending, self.acc)


class ErpImportApiTests(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name="재무회계팀")
        self.acc = User.objects.create_user("acc", password="pw", role=Role.ACCOUNTANT, team=self.team)
        self.client = APIClient()

    def test_import_requires_login(self):
        """익명으로 열어두면 주인 없는 초안만 쌓인다."""
        self.assertEqual(self.client.post("/api/settlements/import/").status_code, 401)

    def test_import_reports_batch_progress(self):
        self.client.login(username="acc", password="pw")
        resp = self.client.post("/api/settlements/import/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["batch"], 1)
        self.assertEqual(resp.data["totalBatches"], erp_import.TOTAL_BATCHES)
        self.assertGreater(resp.data["created"], 0)
        self.assertGreater(resp.data["claimPending"], 0)

    def test_unclaimed_rows_are_flagged_for_the_whole_team(self):
        """`claimPending`이 없으면 주인 없는 건이 아무에게도 안 보인다."""
        self.client.login(username="acc", password="pw")
        self.client.post("/api/settlements/import/")
        rows = self.client.get("/api/settlements/").data
        pending = [r for r in rows if r["claimPending"]]
        self.assertTrue(pending)
        for row in pending:
            self.assertIsNone(row["user"])
            self.assertEqual(row["teamId"], self.team.pk)

    def test_claim_endpoint_attributes_the_row(self):
        self.client.login(username="acc", password="pw")
        self.client.post("/api/settlements/import/")
        target = Settlement.objects.filter(submitted_by__isnull=True).first()
        resp = self.client.post(f"/api/settlements/{target.pk}/claim/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["user"], "acc")
        self.assertFalse(resp.data["claimPending"])

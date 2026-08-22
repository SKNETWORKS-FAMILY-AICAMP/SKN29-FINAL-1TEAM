"""알림 회귀 — 「무엇을 알리고 무엇을 안 알리는가」.

## 고정하는 계약

  ① **본인이 한 일은 본인에게 안 알린다** — 내가 누른 버튼의 결과는 소음이다.
  ② **한 사건 = 한 알림** — 한 번의 제출로 전이가 2~3회 일어나도 사람에게는 하나다.
  ③ **개수형 알림은 묶는다** — 팀원이 10건을 올려도 알림은 하나이고 `count`만 는다.
     단 **읽은 뒤에 온 건은 새 행**이다(다시 알려야 한다).
  ④ **수신자는 역할이 아니라 Capability로 정한다** — 개인 추가부여(`extra_capabilities`)로만
     능력을 가진 사람이 실재하므로, 역할로 거르면 그 사람이 빠진다.
  ⑤ **알림 실패가 업무를 막지 않는다** — 상태 전이가 알림 때문에 롤백되면 안 된다.
  ⑥ **남의 알림은 읽을 수 없다** — 목록만 좁히고 읽음 처리를 안 막으면 id를 찍어 읽는다.
"""
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from domain.accounts.models import Capability, Role, Team, User
from domain.accounts.queries import users_with_capability
from domain.cards.models import Card, CardType
from domain.notifications import events, services
from domain.notifications.models import LINK_OF, Notification, NotificationKind as K
from domain.settlements import services as settlement_services
from domain.settlements.models import Category, Settlement, SettlementStatus as S
from domain.transactions.models import Receipt, Transaction


class _Base(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name="영업팀", bu="영업본부")
        self.other_team = Team.objects.create(name="개발팀", bu="기술본부")
        self.spender = User.objects.create_user("kim", password="pw", role=Role.EMPLOYEE,
                                                team=self.team, first_name="김영업")
        self.lead = User.objects.create_user("lead", password="pw", role=Role.TEAM_LEAD,
                                             team=self.team, first_name="이팀장")
        self.other_lead = User.objects.create_user("lead2", password="pw", role=Role.TEAM_LEAD,
                                                   team=self.other_team, first_name="박팀장")
        self.acc = User.objects.create_user("acc", password="pw", role=Role.ACCOUNTANT,
                                            first_name="최회계")
        self.card = Card.objects.create(card_type=CardType.PERSONAL, owner=self.spender)

    def _settlement(self, **kwargs):
        tx = Transaction.objects.create(card=self.card, merchant="강남한식당",
                                        amount=Decimal("45000"), ts=timezone.now())
        Receipt.objects.create(matched_tx=tx, status="MATCHED", file_ref="r.jpg")
        defaults = dict(transaction=tx, submitted_by=self.spender, team=self.team,
                        status=S.DRAFT, category=Category.MEAL, purpose="팀 점심")
        defaults.update(kwargs)
        return Settlement.objects.create(**defaults)

    def _inbox(self, user, kind=None):
        qs = Notification.objects.filter(recipient=user)
        return qs.filter(kind=kind) if kind else qs


class SelfNotifyTests(_Base):
    """① 본인이 한 일은 본인에게 안 알린다."""

    def test_내가_한_일은_나에게_안_온다(self):
        made = services.notify(self.lead, K.TEAM_COLLECT_PENDING, title="x", actor=self.lead)
        self.assertIsNone(made)
        self.assertEqual(Notification.objects.count(), 0)

    def test_다른_사람이_한_일은_온다(self):
        made = services.notify(self.lead, K.TEAM_COLLECT_PENDING, title="x", actor=self.spender)
        self.assertIsNotNone(made)


class SettlementNotificationTests(_Base):
    """정산 흐름 — 되돌아온 건 / 처리할 건."""

    def test_보완요청은_지출자에게_사유와_함께(self):
        s = self._settlement(status=S.IN_REVIEW)
        settlement_services.review(s, "RETURN", self.acc, "참석자 명단이 없습니다.")
        row = self._inbox(self.spender, K.SETTLEMENT_RETURNED).get()
        self.assertIn("강남한식당", row.title)
        #  **사유를 그대로 싣는다** — 요약하면 무엇을 고쳐야 하는지가 사라진다.
        self.assertIn("참석자 명단이 없습니다.", row.body)
        self.assertEqual(row.link, LINK_OF[K.SETTLEMENT_RETURNED])

    def test_반려는_재제출_불가를_알린다(self):
        s = self._settlement(status=S.IN_REVIEW)
        settlement_services.review(s, "REJECT", self.acc, "업무 관련성 없음")
        row = self._inbox(self.spender, K.SETTLEMENT_REJECTED).get()
        self.assertIn("재제출할 수 없습니다", row.body)

    def test_팀_반려는_최종반려로_말하지_않는다(self):
        s = self._settlement(status=S.TEAM_COLLECTING)
        settlement_services.team_decide(s, "REJECT", self.lead, "사유 불명확")
        row = self._inbox(self.spender, K.SETTLEMENT_REJECTED).get()
        self.assertIn("팀장", row.body)
        self.assertNotIn("재제출할 수 없습니다", row.body)

    # ② 한 사건 = 한 알림
    def test_제출_한_번에_지출자_알림은_하나(self):
        """제출 → 판정 → RETURNED는 전이가 3회지만 사람에게는 「보완요청」 하나다."""
        s = self._settlement(status=S.TEAM_COLLECTING)
        settlement_services.submit(s, self.lead)
        with patch("domain.settlements.risk_review.schedule"):
            settlement_services.judge(s, None)
        self.assertLessEqual(self._inbox(self.spender).count(), 1)

    def test_팀에_올리면_팀장이_받는다(self):
        s = self._settlement()
        settlement_services.raise_to_team(s, self.spender)
        self.assertEqual(self._inbox(self.lead, K.TEAM_COLLECT_PENDING).count(), 1)

    def test_다른_팀_팀장은_안_받는다(self):
        s = self._settlement()
        settlement_services.raise_to_team(s, self.spender)
        self.assertEqual(self._inbox(self.other_lead).count(), 0)

    def test_회계_검토_대기는_회계에게(self):
        s = self._settlement(status=S.SUBMITTED)
        settlement_services.transition(s, S.RPA_JUDGED, None)
        settlement_services.transition(s, S.IN_REVIEW, None)
        self.assertEqual(self._inbox(self.acc, K.REVIEW_PENDING).count(), 1)


class CoalescingTests(_Base):
    """③ 개수형 알림은 묶는다."""

    def test_여러_건이_올라와도_알림은_하나(self):
        for _ in range(3):
            settlement_services.raise_to_team(self._settlement(), self.spender)
        rows = self._inbox(self.lead, K.TEAM_COLLECT_PENDING)
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.get().count, 3)

    def test_읽은_뒤에_온_건은_새_행(self):
        """읽고 나면 다시 알려야 한다 — 안 그러면 새 일이 생겨도 벨이 안 울린다."""
        settlement_services.raise_to_team(self._settlement(), self.spender)
        row = self._inbox(self.lead, K.TEAM_COLLECT_PENDING).get()
        row.read_at = timezone.now()
        row.save(update_fields=["read_at"])

        settlement_services.raise_to_team(self._settlement(), self.spender)
        self.assertEqual(self._inbox(self.lead, K.TEAM_COLLECT_PENDING).count(), 2)

    def test_검토_대기와_확정_대기는_따로_묶인다(self):
        """성격이 다른 일이라 한 줄로 합치면 「무엇을 해야 하는지」가 사라진다."""
        for target in (S.IN_REVIEW, S.PENDING_CONFIRM):
            s = self._settlement(status=S.SUBMITTED)
            settlement_services.transition(s, S.RPA_JUDGED, None)
            settlement_services.transition(s, target, None)
        self.assertEqual(self._inbox(self.acc, K.REVIEW_PENDING).count(), 2)

    def test_보완요청은_묶이지_않는다(self):
        """건마다 사유가 다르다 — 묶으면 어느 건의 사유인지 알 수 없다."""
        for reason in ("증빙 없음", "목적 불명확"):
            s = self._settlement(status=S.IN_REVIEW)
            settlement_services.review(s, "RETURN", self.acc, reason)
        self.assertEqual(self._inbox(self.spender, K.SETTLEMENT_RETURNED).count(), 2)


class RecipientTests(_Base):
    """④ 수신자는 역할이 아니라 Capability로."""

    def test_개인_추가부여만으로도_수신자가_된다(self):
        helper = User.objects.create_user("helper", password="pw", role=Role.EMPLOYEE,
                                          team=self.team,
                                          extra_capabilities=[Capability.TEAM_AGGREGATE.value])
        recipients = users_with_capability(Capability.TEAM_AGGREGATE, team=self.team)
        self.assertIn(helper, recipients)

    def test_비활성_사용자는_제외된다(self):
        self.lead.is_active = False
        self.lead.save(update_fields=["is_active"])
        self.assertNotIn(self.lead, users_with_capability(Capability.TEAM_AGGREGATE, team=self.team))

    def test_본인은_제외할_수_있다(self):
        self.assertNotIn(
            self.lead,
            users_with_capability(Capability.TEAM_AGGREGATE, team=self.team, exclude=self.lead),
        )


class ResilienceTests(_Base):
    """⑤ 알림 실패가 업무를 막지 않는다."""

    def test_알림이_터져도_상태_전이는_성공한다(self):
        s = self._settlement()
        with patch.object(events, "_dispatch", side_effect=RuntimeError("boom")):
            settlement_services.raise_to_team(s, self.spender)
        s.refresh_from_db()
        self.assertEqual(s.status, S.TEAM_COLLECTING)
        self.assertEqual(Notification.objects.count(), 0)

    def test_수신자가_없으면_조용히_넘어간다(self):
        """주인 없는 팀카드 건(`submitted_by=None`)은 보낼 곳이 없다."""
        self.assertIsNone(services.notify(None, K.SETTLEMENT_RETURNED, title="x"))


class DocAndRuleTests(_Base):
    """문서 적재 · 룰 자동 생성."""

    class _Doc:
        pk, title, chunk_count, error = 1, "법인카드 사용규정", 25, ""

        def __init__(self, uploader):
            self.uploaded_by = uploader

    def test_적재_완료는_올린_사람에게(self):
        events.on_doc_ingested(self._Doc(self.acc), ok=True)
        self.assertEqual(self._inbox(self.acc, K.DOC_INGEST_DONE).count(), 1)

    def test_적재_실패도_알린다(self):
        doc = self._Doc(self.acc)
        doc.error = "PDF를 열 수 없습니다."
        events.on_doc_ingested(doc, ok=False)
        self.assertIn("PDF를 열 수 없습니다.", self._inbox(self.acc, K.DOC_INGEST_FAILED).get().body)

    def test_룰이_생겼을_때만_회계팀에_알린다(self):
        doc = self._Doc(self.spender)
        events.on_rule_auto_created(doc, {"status": "NO_SOURCE"})
        self.assertEqual(Notification.objects.filter(kind=K.RULE_AUTO_CREATED).count(), 0)

        events.on_rule_auto_created(doc, {"status": "DRAFT_SAVED", "scope": "식대"})
        self.assertEqual(self._inbox(self.acc, K.RULE_AUTO_CREATED).count(), 1)


class NotificationApiTests(_Base):
    """⑥ 남의 알림은 읽을 수 없다."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(self.spender)
        self.mine = services.notify(self.spender, K.SETTLEMENT_RETURNED, title="내 알림")
        self.theirs = services.notify(self.acc, K.REVIEW_PENDING, title="남의 알림")

    def test_내_알림만_보인다(self):
        r = self.client.get("/api/notifications/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual([n["id"] for n in r.data["results"]], [self.mine.id])

    def test_남의_알림은_읽을_수_없다(self):
        r = self.client.post(f"/api/notifications/{self.theirs.id}/read/")
        self.assertEqual(r.status_code, 404)
        self.theirs.refresh_from_db()
        self.assertIsNone(self.theirs.read_at)

    def test_미읽음_개수(self):
        self.assertEqual(self.client.get("/api/notifications/unread-count/").data["count"], 1)
        self.client.post(f"/api/notifications/{self.mine.id}/read/")
        self.assertEqual(self.client.get("/api/notifications/unread-count/").data["count"], 0)

    def test_모두_읽음은_내_것만_바꾼다(self):
        self.client.post("/api/notifications/read-all/")
        self.theirs.refresh_from_db()
        self.assertIsNone(self.theirs.read_at)

    def test_열려_있는_대상은_접힌다(self):
        """룰 콘솔이 그래프를 열면 그 알림은 이미 확인한 것이다."""
        row = services.notify(self.spender, K.RULE_UPDATED, title="룰 수정", target="rulegraph:7")
        r = self.client.post("/api/notifications/read-target/", {"target": "rulegraph:7"}, format="json")
        self.assertEqual(r.data["updated"], 1)
        row.refresh_from_db()
        self.assertIsNotNone(row.read_at)

    def test_로그인하지_않으면_못_본다(self):
        self.assertIn(APIClient().get("/api/notifications/").status_code, (401, 403))

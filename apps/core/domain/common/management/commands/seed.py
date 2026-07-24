"""데모 데이터 시드 — 프론트 연동/통합 테스트용 (프론트 mock 셰이프와 정렬).

    docker compose exec core python manage.py seed [--fresh]
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from domain.accounts.models import Role, Team
from domain.cards.models import Card, CardType
from domain.policies.models import OnResult, RuleGraph, RuleGraphStatus, RuleNode, RuleRouting
from domain.risk.models import RiskReview
from domain.settlements.models import Category, Settlement, SettlementStatus
from domain.transactions.models import MerchantCategory, MerchantSource, Receipt, Transaction

User = get_user_model()


class Command(BaseCommand):
    help = "데모 데이터 시드"

    def add_arguments(self, parser):
        parser.add_argument("--fresh", action="store_true", help="기존 데모 데이터 삭제 후 재생성")

    def handle(self, *args, **opts):
        if opts["fresh"]:
            Settlement.objects.all().delete()
            Transaction.objects.all().delete()
            Card.objects.all().delete()
            RuleGraph.objects.all().delete()
            User.objects.filter(is_superuser=False).delete()
            Team.objects.all().delete()
            self.stdout.write("기존 데모 데이터 삭제 완료")

        now = timezone.now()
        team = Team.objects.create(name="AI사업본부 1팀", bu="AI사업본부")
        emp = User.objects.create_user("kim", password="pass1234", role=Role.EMPLOYEE, team=team)
        User.objects.create_user("lead", password="pass1234", role=Role.TEAM_LEAD, team=team)
        User.objects.create_user("acc", password="pass1234", role=Role.ACCOUNTANT)
        User.objects.create_user("exec", password="pass1234", role=Role.EXECUTIVE)

        card = Card.objects.create(card_type=CardType.PERSONAL, name="개인법인카드", number_masked="**** 1234", owner=emp)
        shared = Card.objects.create(card_type=CardType.SHARED, name="부서공용", number_masked="**** 9999", team=team)

        MerchantCategory.objects.get_or_create(
            normalized_name="스타벅스", defaults=dict(
                industry_code="CE7", industry_label="카페", source=MerchantSource.KAKAO, confidence=0.95)
        )

        # 프론트 mock(myExpenses/reviewItems)과 유사한 셰이프의 정산 건들
        rows = [
            ("스타벅스 강남점", 28000, card, Category.MEETING, True, SettlementStatus.DRAFT, "MATCHED"),
            ("카카오T", 14300, card, Category.TRIP, False, SettlementStatus.DRAFT, "MISSING"),
            ("더본코리아", 132000, card, Category.MEAL, True, SettlementStatus.SUBMITTED, "MATCHED"),
            ("교보문고", 46500, card, Category.SUPPLIES, False, SettlementStatus.RETURNED, "MATCHED"),
            ("골든테이블", 880000, shared, Category.ENTERTAIN, True, SettlementStatus.IN_REVIEW, "MISSING"),
            ("쿠팡", 89000, card, Category.SUPPLIES, False, SettlementStatus.CONFIRMED, "MATCHED"),
        ]
        for i, (merchant, amount, c, cat, ai, status, ev) in enumerate(rows):
            tx = Transaction.objects.create(card=c, merchant=merchant, amount=amount, ts=now - timedelta(days=i))
            if ev == "MATCHED":
                Receipt.objects.create(matched_tx=tx, status=Receipt.Status.MATCHED, file_ref=f"receipts/{tx.id}.jpg")
            s = Settlement.objects.create(
                transaction=tx, category=cat, ai_category=cat, ai_suggested=ai,
                merchant_industry="카페" if "스타벅스" in merchant else "",
                status=status, submitted_by=emp, team=team,
            )
            if status == SettlementStatus.IN_REVIEW:
                RiskReview.objects.create(
                    settlement=s, anomaly_score=0.92,
                    reasons=[{"feature": "심야 사용(23:40)", "weight": 0.34},
                             {"feature": "건당 금액 상위 1%", "weight": 0.29},
                             {"feature": "접대 한도 초과", "weight": 0.21}],
                    rag_refs=[{"title": "접대비 50만원 초과 사전결재 필요", "source": "TIGER-REG-2026-003 §12조 2항"},
                              {"title": "유흥업소 사용분 손금 불산입", "source": "법인세법 시행령 §41"}],
                    ai_recommendation="REJECT", ai_confidence=0.86,
                )

        # 룰 그래프(트리) — ACTIVE 1개
        g = RuleGraph.objects.create(
            name="접대비 한도 검토", scope="접대", status=RuleGraphStatus.ACTIVE, version=1,
            entry_node_key="n_limit", source_clause="TIGER-REG-2026-003 §12조 2항",
            sim_result={"matched": 142, "false_positive_rate": 0.037, "review_reduction": 0.28},
            activated_at=now,
        )
        RuleNode.objects.create(graph=g, node_key="n_limit", condition={"expr": "amount > limit"}, action={"decision": "REVIEW"})
        RuleNode.objects.create(graph=g, node_key="n_entertain", condition={"expr": "category == '접대'"}, action={"decision": "REJECT"}, priority=1)
        RuleRouting.objects.create(graph=g, from_node_key="n_limit", on_result=OnResult.MATCH, to_node_key="n_entertain")
        RuleRouting.objects.create(graph=g, from_node_key="n_limit", on_result=OnResult.NO_MATCH, to_node_key="")

        self.stdout.write(self.style.SUCCESS(
            "시드 완료 - 사용자 kim/lead/acc/exec (pass1234), 정산 6건, 룰 그래프 1개"
        ))

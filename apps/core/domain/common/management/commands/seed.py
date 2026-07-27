"""운영 시연용 샘플 데이터 시드.

    docker compose exec core python manage.py seed [--fresh]

팀은 3개(영업팀 / AI·개발팀 / 재무회계팀)로 단순화.
로그인 계정(pw pass1234): kim(영업사원)·lead(영업팀장)·acc(회계담당)·acclead(회계팀장)·exec(운영진)
- kim(영업팀 1인) '내 지출' 처리 흐름 샘플
- 검토 워크스페이스(IN_REVIEW) 다양한 내역 샘플
- 샘플 Rule 그래프(초안/시뮬/활성) — 화면 실제 연동용
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from domain.accounts.models import Role, Team
from domain.cards.models import Card, CardType
from domain.policies.models import (
    OnResult, RuleGraph, RuleGraphStatus, RuleGraphVersion, RuleNode, RuleRouting,
)
from domain.risk.models import RiskReview
from domain.settlements.models import Category as C, Settlement, SettlementStatus as S
from domain.transactions.models import MerchantCategory, MerchantSource, Receipt, Transaction

User = get_user_model()


class Command(BaseCommand):
    help = "운영 시연용 샘플 데이터 시드"

    def add_arguments(self, parser):
        parser.add_argument("--fresh", action="store_true", help="기존 데이터 삭제 후 재생성")

    def handle(self, *args, **opts):
        if opts["fresh"]:
            for m in (Settlement, Transaction, Card, RuleGraph, MerchantCategory):
                m.objects.all().delete()
            User.objects.filter(is_superuser=False).delete()
            Team.objects.all().delete()
            self.stdout.write("기존 데이터 삭제 완료")

        now = timezone.now()

        def at(days, hour=12, minute=0):
            return (now - timedelta(days=days)).replace(hour=hour, minute=minute, second=0, microsecond=0)

        # ── 팀 3개 ────────────────────────────────
        sales = Team.objects.create(name="영업팀", bu="영업본부")
        devai = Team.objects.create(name="AI·개발팀", bu="AI·개발본부")
        fin = Team.objects.create(name="재무회계팀", bu="경영지원본부")

        # ── 로그인 계정 ───────────────────────────
        kim = User.objects.create_user("kim", password="pass1234", role=Role.EMPLOYEE, team=sales, first_name="김영업")
        User.objects.create_user("lead", password="pass1234", role=Role.TEAM_LEAD, team=sales, first_name="이팀장")
        User.objects.create_user("acc", password="pass1234", role=Role.ACCOUNTANT, team=fin, first_name="박회계")
        User.objects.create_user("acclead", password="pass1234", role=Role.ACCOUNTANT_LEAD, team=fin, first_name="정회계팀장")
        User.objects.create_user("exec", password="pass1234", role=Role.EXECUTIVE, team=fin, first_name="최운영")

        def emp(name, team):
            return User.objects.create_user(name, password="pass1234", role=Role.EMPLOYEE, team=team)

        # 검토/팀 취합용 추가 사용자
        u = {n: emp(n, t) for n, t in [
            ("이영희", devai), ("최지우", devai), ("김철수", devai),
            ("박민수", sales), ("정하늘", sales), ("이도윤", sales),
        ]}

        # ── 카드 ─────────────────────────────────
        kim_card = Card.objects.create(card_type=CardType.PERSONAL, name="김영업 개인카드", number_masked="**** 1001", owner=kim)
        sales_team_card = Card.objects.create(card_type=CardType.TEAM, name="영업팀 팀카드", number_masked="**** 7001", team=sales)
        shared_card = Card.objects.create(card_type=CardType.SHARED, name="AI·개발팀 공용", number_masked="**** 9999", team=devai)
        postpaid = Card.objects.create(card_type=CardType.POST_PAID, name="후정산 청구", number_masked="후정산")
        Card.objects.create(card_type=CardType.PREPAID, name="영업팀 선불", number_masked="**** 3300", team=sales)

        for nm, code, label in [("스타벅스", "CE7", "카페"), ("강남한식당", "FD6", "한식"),
                                ("신라스테이", "AD5", "숙박"), ("메가커피", "CE7", "카페")]:
            MerchantCategory.objects.get_or_create(
                normalized_name=nm, defaults=dict(industry_code=code, industry_label=label,
                                                  source=MerchantSource.KAKAO, confidence=0.95))

        def mk(owner, merchant, amount, card, cat, ai, status, ev, days, hour, purpose="", industry="", risk=None):
            tx = Transaction.objects.create(card=card, merchant=merchant, amount=amount, ts=at(days, hour))
            if ev == "OK":
                Receipt.objects.create(matched_tx=tx, status=Receipt.Status.MATCHED, file_ref=f"receipts/{tx.id}.jpg")
            s = Settlement.objects.create(
                transaction=tx, category=cat, ai_category=cat, ai_suggested=ai,
                merchant_industry=industry, purpose=purpose, status=status,
                submitted_by=owner, team=owner.team)
            if risk:
                RiskReview.objects.create(settlement=s, **risk)
            return s

        # ── 김영업(영업팀 1인) '내 지출' 처리 흐름 (전 상태) ──
        mk(kim, "스타벅스 강남점", 18000, kim_card, C.MEETING, True, S.DRAFT, "OK", 1, 10, "거래처 미팅 음료", "카페")
        mk(kim, "카카오T", 23400, kim_card, C.TRIP, False, S.DRAFT, "MISSING", 1, 9, "고객사 방문 이동")
        mk(kim, "GS칼텍스 주유", 70000, kim_card, C.TRIP, False, S.SUBMITTED, "OK", 2, 8, "지방 출장 주유")
        mk(kim, "본죽 역삼점", 12000, kim_card, C.MEAL, True, S.PENDING_CONFIRM, "OK", 3, 12, "야근 식대")
        mk(kim, "교보문고", 38000, kim_card, C.SUPPLIES, False, S.RETURNED, "OK", 5, 14, "영업 자료 서적")
        mk(kim, "롯데호텔 커피숍", 46000, kim_card, C.MEETING, True, S.CONFIRMED, "OK", 8, 15, "거래처 상담")
        mk(kim, "대한항공", 210000, postpaid, C.TRIP, True, S.ERP_VOUCHER_DRAFTED, "OK", 12, 7, "부산 출장 항공", "항공")

        # ── 영업팀 취합용(팀장 뷰) 다른 팀원 건 ──
        mk(u["박민수"], "배달의민족", 84000, sales_team_card, C.MEAL, True, S.SUBMITTED, "OK", 2, 20, "팀 야근 식대")
        mk(u["정하늘"], "이마트", 51000, sales_team_card, C.SUPPLIES, False, S.SUBMITTED, "OK", 3, 17, "팀 비품")

        # ── 검토 워크스페이스(IN_REVIEW) 다양한 샘플 ──
        reviews = [
            (u["이영희"], "강남한식당", 452000, shared_card, C.ENTERTAIN, "MISSING", 1, 19, "거래처 A사 계약 논의 접대", "한식",
             0.92, [{"feature": "전월대비 결제금액 급증", "weight": 0.45}, {"feature": "심야 시간대 결제", "weight": 0.32}, {"feature": "증빙 서류 누락", "weight": 0.23}],
             [{"title": "3만원 초과 접대비는 적격증빙 필수, 미수취 시 손금불산입", "source": "법인카드 사용규정 제11조", "kind": "policy"},
              {"title": "유사사례 #1123 — 적격증빙 미비 반려(91% 패턴 일치)", "source": "과거 반려사례 DB", "kind": "case"}],
             ["접대비·심야결제·증빙없음"], "REJECT", 0.86),
            (u["박민수"], "신라스테이", 310000, postpaid, C.ENTERTAIN, "OK", 2, 21, "거래처 접대 후 숙박", "숙박",
             0.78, [{"feature": "건당 한도 근접", "weight": 0.36}, {"feature": "유사 반려사례 존재", "weight": 0.28}],
             [{"title": "접대비 건당 한도 50만원 초과 시 사전결재", "source": "TIGER-REG-2026-003 §12조", "kind": "policy"}],
             ["건당한도 근접·유사사례 있음"], "RETURN", 0.64),
            (u["최지우"], "메가커피 x 12건", 128000, shared_card, C.MEETING, "OK", 3, 14, "팀 회의 다과", "카페",
             0.65, [{"feature": "동일 가맹점 빈도 급증", "weight": 0.41}, {"feature": "한도 임계값 바로 아래", "weight": 0.22}],
             [{"title": "분할결제 의심 시 원거래 통합 검토", "source": "TIGER-REG-2026-003 §8조", "kind": "policy"}],
             ["가맹점 반복·소액 다건"], "RETURN", 0.55),
            (u["김철수"], "쿠팡", 95000, shared_card, C.SUPPLIES, "OK", 4, 11, "개발 장비 소모품", "",
             0.51, [{"feature": "분류 신뢰도 낮음", "weight": 0.28}], [], ["분류 신뢰도 낮음"], "APPROVE", 0.72),
            (u["정하늘"], "김밥천국", 60000, sales_team_card, C.MEAL, "OK", 6, 13, "주말 근무 식대", "",
             0.43, [{"feature": "주말 결제", "weight": 0.19}], [], ["주말 결제·소액"], "APPROVE", 0.81),
            (u["이도윤"], "백반집", 42000, sales_team_card, C.MEAL, "OK", 7, 12, "업무 오찬", "",
             0.30, [{"feature": "경미한 금액 편차", "weight": 0.12}], [], ["경미한 금액 편차"], "APPROVE", 0.88),
        ]
        for (o, m, amt, card, cat, ev, d, h, pp, ind, sc, contrib, refs, ar, reco, conf) in reviews:
            mk(o, m, amt, card, cat, True, S.IN_REVIEW, ev, d, h, pp, ind,
               risk=dict(anomaly_score=sc, reasons=contrib, rag_refs=refs, anomaly_reasons=ar,
                         ai_recommendation=reco, ai_confidence=conf))

        # ── 샘플 Rule 그래프 (초안/시뮬/활성) ─────
        def graph(name, scope, status, clause, sim, nodes, routings, ver=1, activated=False):
            g = RuleGraph.objects.create(name=name, scope=scope, status=status, version=ver,
                                         entry_node_key=nodes[0][0], source_clause=clause,
                                         sim_result=sim or {}, activated_at=(now if activated else None))
            for key, cond, act, pr in nodes:
                RuleNode.objects.create(graph=g, node_key=key, condition=cond, action=act, priority=pr)
            for f, res, to, pr in routings:
                RuleRouting.objects.create(graph=g, from_node_key=f, on_result=res, to_node_key=to, priority=pr)
            return g

        g_active = graph("접대비 한도 검토", "접대", RuleGraphStatus.ACTIVE, "TIGER-REG-2026-003 §12조 2항",
                         {"matched": 142, "false_positive_rate": 0.031, "review_reduction": 0.28},
                         [("n_limit", {"expr": "amount > limit"}, {"decision": "REVIEW"}, 0),
                          ("n_entertain", {"expr": "category == '접대'"}, {"decision": "REJECT"}, 1)],
                         [("n_limit", OnResult.MATCH, "n_entertain", 0), ("n_limit", OnResult.NO_MATCH, "", 1)],
                         ver=3, activated=True)
        RuleGraphVersion.objects.create(graph=g_active, version=3, is_active=True, approved_at=now,
                                        snapshot={"note": "현재 활성"})
        graph("식대 30만원 초과 사전승인", "식대", RuleGraphStatus.DRAFT, "법인카드 사용규정 제10조②", {},
              [("n_meal", {"expr": "category=='식대' and amount>300000"}, {"decision": "REVIEW"}, 0)],
              [("n_meal", OnResult.MATCH, "", 0)])
        graph("후정산 증빙 필수 검증", "후정산", RuleGraphStatus.SIMULATED, "법인카드 사용규정 제9조",
              {"matched": 88, "false_positive_rate": 0.052, "review_reduction": 0.15},
              [("n_pp", {"expr": "cardType=='POST_PAID' and evidence=='MISSING'"}, {"decision": "RETURN"}, 0)],
              [("n_pp", OnResult.MATCH, "", 0)])

        self.stdout.write(self.style.SUCCESS(
            f"시드 완료 - 팀 {Team.objects.count()} / 사용자 {User.objects.count()} / 카드 {Card.objects.count()} / "
            f"정산 {Settlement.objects.count()}(검토 {RiskReview.objects.count()}) / 룰그래프 {RuleGraph.objects.count()}"
        ))

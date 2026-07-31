"""운영 시연용 샘플 데이터 시드.

    docker compose exec core python manage.py seed [--fresh]

팀은 3개(영업팀 / AI·개발팀 / 재무회계팀)로 단순화.
로그인 계정(pw pass1234): kim(영업사원)·lead(영업팀장)·acc(회계담당)·acclead(회계팀장)·exec(운영진)
- kim(영업팀 1인) '내 지출' 처리 흐름 샘플
- 영업팀 취합(TEAM_COLLECTING) 정상·증빙누락·고액·공용카드 샘플
- 검토 워크스페이스(IN_REVIEW) 다양한 내역 샘플
- RULE 명세서의 GLOBAL 게이트(R-002·R-003)
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

from domain.accounts.models import Capability, Role, Team
from domain.cards.models import Card, CardType
from domain.policies.models import RuleGraph
from domain.risk.models import RiskReview
from domain.settlements.models import Category as C, Settlement, SettlementStatus as S, TeamBudget
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
        # 인가는 기능 단위(Capability) — 역할 기본값 ∪ extra_capabilities. (accounts.ROLE_DEFAULT_CAPABILITIES)
        #  kim=일반 사원(능력 없음)
        #  acc=회계작업·룰콘솔열람(역할기본) + 팀취합(추가부여)
        #  acclead=회계작업·룰콘솔열람·룰활성(역할기본)
        kim = User.objects.create_user("kim", password="pass1234", role=Role.EMPLOYEE, team=sales, first_name="김영업")
        User.objects.create_user("lead", password="pass1234", role=Role.TEAM_LEAD, team=sales, first_name="이팀장")
        acc = User.objects.create_user("acc", password="pass1234", role=Role.ACCOUNTANT, team=fin, first_name="박회계",
                                       extra_capabilities=[Capability.TEAM_AGGREGATE.value])
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
        acc_card = Card.objects.create(card_type=CardType.PERSONAL, name="박회계 개인카드", number_masked="**** 2002", owner=acc)
        sales_team_card = Card.objects.create(card_type=CardType.TEAM, name="영업팀 팀카드", number_masked="**** 7001", team=sales)
        sales_shared_card = Card.objects.create(card_type=CardType.SHARED, name="영업본부 공용", number_masked="**** 7700", team=sales)
        shared_card = Card.objects.create(card_type=CardType.SHARED, name="AI·개발팀 공용", number_masked="**** 9999", team=devai)
        postpaid = Card.objects.create(card_type=CardType.POST_PAID, name="후정산 청구", number_masked="후정산")
        sales_prepaid = Card.objects.create(card_type=CardType.PREPAID, name="영업팀 선불", number_masked="**** 3300", team=sales)

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
        mk(kim, "카카오T", 23400, kim_card, C.TRIP, False, S.DRAFT, "OK", 1, 9, "고객사 방문 이동")
        mk(kim, "GS칼텍스 주유", 70000, kim_card, C.TRIP, False, S.SUBMITTED, "OK", 2, 8, "지방 출장 주유")
        mk(kim, "본죽 역삼점", 12000, kim_card, C.MEAL, True, S.PENDING_CONFIRM, "OK", 3, 12, "야근 식대")
        mk(kim, "교보문고", 38000, kim_card, C.SUPPLIES, False, S.RETURNED, "OK", 5, 14, "영업 자료 서적")
        mk(kim, "롯데호텔 커피숍", 46000, kim_card, C.MEETING, True, S.CONFIRMED, "OK", 8, 15, "거래처 상담")
        mk(kim, "대한항공", 210000, postpaid, C.TRIP, True, S.ERP_VOUCHER_DRAFTED, "OK", 12, 7, "부산 출장 항공", "항공")

        # ── 박회계(재무회계팀) '내 지출' — 회계 담당자 개인 법인카드 지출 다양화(전 상태) ──
        mk(acc, "투썸플레이스 을지로", 15400, acc_card, C.MEETING, True, S.DRAFT, "OK", 1, 10, "결산 리뷰 미팅 음료", "카페")
        mk(acc, "오피스디포", 42000, acc_card, C.SUPPLIES, False, S.DRAFT, "MISSING", 1, 13, "회계 증빙 보관용 파일박스")
        mk(acc, "김밥천국 여의도", 9000, acc_card, C.MEAL, True, S.SUBMITTED, "OK", 2, 20, "월말 결산 야근 식대")
        mk(acc, "코레일 KTX", 47600, acc_card, C.TRIP, False, S.SUBMITTED, "OK", 3, 8, "세무조사 대응 본사 출장", "철도")
        mk(acc, "교보문고", 33000, acc_card, C.SUPPLIES, False, S.PENDING_CONFIRM, "OK", 4, 15, "개정세법 실무 서적")
        mk(acc, "스타벅스 여의도", 21000, acc_card, C.ENTERTAIN, True, S.RETURNED, "OK", 5, 16, "외부 회계법인 미팅 - 목적 보완 필요", "카페")
        mk(acc, "본죽 여의도", 12800, acc_card, C.MEAL, False, S.CONFIRMED, "OK", 9, 12, "주말 결산 근무 식대")
        mk(acc, "우체국 등기", 8000, acc_card, C.OPERATION, False, S.ERP_VOUCHER_DRAFTED, "OK", 13, 11, "회계 원본 증빙 발송")

        # ── 영업팀 취합 단계(팀장 뷰) — TEAM_* 상태 다양화 ──
        mk(u["박민수"], "배달의민족", 84000, sales_team_card, C.MEAL, True, S.TEAM_COLLECTING, "OK", 2, 20, "팀 야근 식대")
        mk(u["박민수"], "신라스테이", 450000, postpaid, C.TRIP, True, S.TEAM_COLLECTING, "OK", 3, 21, "지방 출장 숙박")
        mk(u["정하늘"], "이마트", 51000, sales_team_card, C.SUPPLIES, False, S.TEAM_RETURNED, "OK", 3, 17, "팀 비품 - 사용목적 보완 필요")
        mk(u["정하늘"], "스타벅스 코엑스", 26000, sales_team_card, C.MEETING, False, S.TEAM_COLLECTING, "OK", 4, 14, "주간 회의 다과")
        mk(u["이도윤"], "한우명가", 298000, shared_card, C.ENTERTAIN, True, S.TEAM_COLLECTING, "OK", 5, 19, "거래처 접대(실사용자 지정 필요)")
        mk(u["이도윤"], "롯데시네마 건대", 132000, shared_card, C.ENTERTAIN, True, S.TEAM_REJECTED, "OK", 6, 18, "접대 성격 불명확 - 팀 반려")
        mk(u["이도윤"], "카카오T", 12600, sales_team_card, C.TRIP, False, S.DRAFT, "OK", 2, 9, "고객사 방문 이동")
        # 이미 회계로 제출된 건(SUBMITTED)도 일부 유지
        mk(u["정하늘"], "교보문고", 54000, kim_card, C.SUPPLIES, False, S.SUBMITTED, "OK", 8, 12, "기술서적 구입")

        # ── 영업팀 취합 대기(TEAM_COLLECTING) 다양한 처리 샘플 ──
        # 프론트 S-02의 사람별 필터·분류별 예산·이상건 강조/자동 보완요청 시연용.
        collecting = [
            # owner, merchant, amount, card, category, ai, evidence, days, hour, purpose, industry
            (u["박민수"], "성수동 커피랩", 27000, sales_team_card, C.MEETING, True, "OK", 1, 10, "거래처 킥오프 미팅", "카페"),
            (u["박민수"], "KTX 서울-부산", 119600, postpaid, C.TRIP, False, "OK", 2, 7, "부산 고객사 방문", "철도"),
            (u["박민수"], "그랜드호텔 레스토랑", 420000, sales_team_card, C.ENTERTAIN, True, "OK", 3, 20, "신규 거래처 접대", "한식"),
            (u["정하늘"], "오피스디포", 73500, sales_team_card, C.SUPPLIES, False, "OK", 1, 15, "영업 제안서 바인더 및 용지", "사무용품"),
            (u["정하늘"], "카카오T 블랙", 38600, postpaid, C.TRIP, True, "MISSING", 2, 22, "야간 고객사 미팅 복귀", "운수"),
            (u["정하늘"], "한강파크 푸드코트", 66500, sales_prepaid, C.MEAL, False, "OK", 4, 12, "현장 영업팀 오찬", "음식점"),
            (u["이도윤"], "렌탈프로 행사장비", 680000, sales_team_card, C.OPERATION, True, "MISSING", 1, 16, "제품 시연회 장비 대여", "렌탈"),
            (u["이도윤"], "공용카드 온라인몰", 158000, sales_shared_card, C.SUPPLIES, True, "OK", 2, 14, "고객 증정용 샘플", "전자상거래"),
            (u["이도윤"], "마티나라운지", 91000, postpaid, C.MEAL, True, "MISSING", 5, 6, "조찬 출장 식사", "음식점"),
            (kim, "테크노마트", 245000, kim_card, C.SUPPLIES, False, "OK", 3, 13, "시연용 휴대 기기", "전자기기"),
            (kim, "스타벅스 역삼점", 31500, kim_card, C.MEETING, True, "MISSING", 4, 11, "잠재고객 상담", "카페"),
            (kim, "비즈니스 디너", 298000, sales_team_card, C.ENTERTAIN, False, "OK", 6, 19, "재계약 협의 저녁", "양식"),
        ]
        for owner, merchant, amount, card, cat, ai, ev, days, hour, purpose, industry in collecting:
            mk(owner, merchant, amount, card, cat, ai, S.TEAM_COLLECTING, ev, days, hour, purpose, industry)

        # ── 검토 워크스페이스(IN_REVIEW) 다양한 샘플 ──
        reviews = [
            (u["이영희"], "강남한식당", 452000, shared_card, C.ENTERTAIN, "OK", 1, 19, "거래처 A사 계약 논의 접대", "한식",
             0.92, [{"feature": "전월대비 결제금액 급증", "weight": 0.45}, {"feature": "심야 시간대 결제", "weight": 0.32}, {"feature": "적격증빙 확인 필요(AI 검토)", "weight": 0.23}],
             [{"title": "3만원 초과 접대비는 적격증빙 필수, 미수취 시 손금불산입", "source": "법인카드 사용규정 제11조", "kind": "policy"},
              {"title": "유사사례 #1123 — 적격증빙 미비 반려(91% 패턴 일치)", "source": "과거 반려사례 DB", "kind": "case"}],
             ["접대비·심야결제·적격증빙 확인"], "REJECT", 0.86),
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

        # ── Rule 그래프: RULE 명세서의 GLOBAL 게이트만 별도 멱등 커맨드로 구성 ──
        call_command("seed_rules")

        # ── 팀 예산(TeamBudget) — 한도만 DB 정의, 사용액은 Settlement 집계로 산출 ──
        # category='' 행은 팀 월 총한도. 프론트 teamBudget 셰이프와 정합.
        this_month = now.strftime("%Y-%m")
        budget_plan = {
            sales: {"": 5000000, C.MEAL: 1000000, C.TRIP: 1200000, C.ENTERTAIN: 1000000, C.SUPPLIES: 800000, C.MEETING: 500000},
            devai: {"": 4000000, C.MEAL: 800000, C.TRIP: 1000000, C.ENTERTAIN: 900000, C.SUPPLIES: 900000, C.MEETING: 400000},
        }
        for team, plan in budget_plan.items():
            for cat, lim in plan.items():
                TeamBudget.objects.create(team=team, year_month=this_month, category=cat, limit_amount=lim)

        self.stdout.write(self.style.SUCCESS(
            f"시드 완료 - 팀 {Team.objects.count()} / 사용자 {User.objects.count()} / 카드 {Card.objects.count()} / "
            f"정산 {Settlement.objects.count()}(검토 {RiskReview.objects.count()}) / 룰그래프 {RuleGraph.objects.count()} / "
            f"예산 {TeamBudget.objects.count()}"
        ))

"""운영 시연용 샘플 데이터 시드.

    docker compose exec core python manage.py seed [--fresh]

팀은 3개(영업팀 / AI·개발팀 / 재무회계팀).
로그인 계정(pw pass1234): kim(영업사원)·lead(영업팀장)·acc(회계담당)·acclead(회계팀장)·exec(운영진)

시연 구성:
- kim(영업팀) · acc(재무회계팀) '내 지출' 전 상태 흐름
- 재무회계팀 자체 지출(결산·세무·감사 대응) — 회계팀도 지출 주체라는 점을 보여줌
- 영업팀 취합(TEAM_*) 샘플
- 검토 워크스페이스(IN_REVIEW) 30건 — 위험도·패턴·권장처리를 폭넓게 분포
- 검토 '이전 처리' 10건 — 이번 달에 승인·보완요청·반려로 끝난 건(이상탐지 결과 포함)
- 그중 시연 하이라이트 3건: RAG 내규 검증 보고서(마크다운) + 실제 EvalContext 스냅샷(rule_hits)

모든 거래일자는 **이번 달 1일~30일** 사이에 배치된다(팀 통계·검토 이력의 '이번 달' 필터와 정합).
- 룰 그래프는 `seed_rules` 커맨드가 담당(GLOBAL v3·기업업무추진비 v2·회식비 v1+초안·출장비 승인대기)
"""
import calendar
from collections import defaultdict

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

from domain.accounts.models import Capability, Role, Team
from domain.cards.models import Card, CardType
from domain.policies.engine import run_rule_engine
from domain.policies.eval_context import BUILDER_VERSION, EVAL_CONTEXT_SCHEMA_VERSION, empty_eval_context
from domain.policies.models import Policy, RuleGraph, RuleGraphStatus, RuleHit
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
            # RuleHit은 정산·거래에 SET_NULL이라 함께 지우지 않으면 고아 로그가 남는다.
            for m in (RuleHit, Settlement, Transaction, Card, RuleGraph, MerchantCategory, Policy):
                m.objects.all().delete()
            User.objects.filter(is_superuser=False).delete()
            Team.objects.all().delete()
            self.stdout.write("기존 데이터 삭제 완료")

        now = timezone.now()

        # 시연 데이터는 전부 **이번 달 1일~30일** 안에 놓는다.
        #  팀 통계 대시보드(팀·이번 달)와 검토 '이전 처리'(이번 달)가 같은 달을 보기 때문에,
        #  '며칠 전' 방식으로 두면 지난달로 넘어간 건이 화면에서 통째로 빠진다.
        #  각 호출부의 ``days``는 "얼마나 오래된 건인가"의 상대 순서만 뜻한다 — 클수록 월초 쪽.
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_day = min(30, calendar.monthrange(now.year, now.month)[1])

        def at(days, hour=12, minute=0):
            day = last_day - (days % last_day)  # days=1 → 29일, days=25 → 5일 (항상 1~30일)
            return month_start.replace(day=day, hour=hour, minute=minute)

        # ── 팀 3개 ────────────────────────────────
        sales = Team.objects.create(name="영업팀", bu="영업본부")
        devai = Team.objects.create(name="AI·개발팀", bu="AI·개발본부")
        fin = Team.objects.create(name="재무회계팀", bu="경영지원본부")

        # ── 로그인 계정 ───────────────────────────
        # 인가는 기능 단위(Capability) — 역할 기본값 ∪ extra_capabilities. (accounts.ROLE_DEFAULT_CAPABILITIES)
        #  kim=일반 사원(능력 없음)
        #  acc=회계작업·룰콘솔열람(역할기본) + 팀취합(추가부여)
        #  acclead=회계작업·룰콘솔열람·룰활성(역할기본) + 거버넌스열람(추가부여)
        #        — 회계팀장은 룰 활성화 판단에 지표가 필요해 거버넌스 대시보드도 본다.
        kim = User.objects.create_user("kim", password="pass1234", role=Role.EMPLOYEE, team=sales, first_name="김영업")
        User.objects.create_user("lead", password="pass1234", role=Role.TEAM_LEAD, team=sales, first_name="이팀장")
        acc = User.objects.create_user("acc", password="pass1234", role=Role.ACCOUNTANT, team=fin, first_name="박회계",
                                       extra_capabilities=[Capability.TEAM_AGGREGATE.value])
        acclead = User.objects.create_user("acclead", password="pass1234", role=Role.ACCOUNTANT_LEAD, team=fin,
                                           first_name="정회계팀장",
                                           extra_capabilities=[Capability.GOVERNANCE_VIEW.value])
        User.objects.create_user("exec", password="pass1234", role=Role.EXECUTIVE, team=fin, first_name="최운영")

        def emp(name, team):
            return User.objects.create_user(name, password="pass1234", role=Role.EMPLOYEE, team=team)

        # 검토/팀 취합용 추가 사용자
        u = {n: emp(n, t) for n, t in [
            ("이영희", devai), ("최지우", devai), ("김철수", devai), ("한도현", devai),
            ("박민수", sales), ("정하늘", sales), ("이도윤", sales), ("서지훈", sales),
            ("오세진", fin), ("한지민", fin),
        ]}

        # ── 카드 ─────────────────────────────────
        kim_card = Card.objects.create(card_type=CardType.PERSONAL, name="김영업 개인카드", number_masked="**** 1001", owner=kim)
        acc_card = Card.objects.create(card_type=CardType.PERSONAL, name="박회계 개인카드", number_masked="**** 2002", owner=acc)
        acclead_card = Card.objects.create(card_type=CardType.PERSONAL, name="정회계팀장 개인카드", number_masked="**** 2003", owner=acclead)
        fin_team_card = Card.objects.create(card_type=CardType.TEAM, name="재무회계팀 팀카드", number_masked="**** 5001", team=fin)
        fin_shared_card = Card.objects.create(card_type=CardType.SHARED, name="경영지원본부 공용", number_masked="**** 5500", team=fin)
        sales_team_card = Card.objects.create(card_type=CardType.TEAM, name="영업팀 팀카드", number_masked="**** 7001", team=sales)
        sales_shared_card = Card.objects.create(card_type=CardType.SHARED, name="영업본부 공용", number_masked="**** 7700", team=sales)
        shared_card = Card.objects.create(card_type=CardType.SHARED, name="AI·개발팀 공용", number_masked="**** 9999", team=devai)
        devai_team_card = Card.objects.create(card_type=CardType.TEAM, name="AI·개발팀 팀카드", number_masked="**** 9001", team=devai)
        postpaid = Card.objects.create(card_type=CardType.POST_PAID, name="후정산 청구", number_masked="후정산")
        sales_prepaid = Card.objects.create(card_type=CardType.PREPAID, name="영업팀 선불", number_masked="**** 3300", team=sales)

        for nm, code, label in [("스타벅스", "CE7", "카페"), ("강남한식당", "FD6", "한식"),
                                ("신라스테이", "AD5", "숙박"), ("메가커피", "CE7", "카페"),
                                ("르쁘띠바", "FD6", "주점"), ("한우명가", "FD6", "한식"),
                                ("제주그랜드리조트", "AD5", "숙박"), ("골든벨CC", "AT4", "골프장")]:
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

        # ── 박회계(acc) '내 지출' — 회계 담당자 개인 법인카드 지출 전 상태 ──
        mk(acc, "투썸플레이스 을지로", 15400, acc_card, C.MEETING, True, S.DRAFT, "OK", 1, 10, "결산 리뷰 미팅 음료", "카페")
        mk(acc, "오피스디포", 42000, acc_card, C.SUPPLIES, False, S.DRAFT, "MISSING", 1, 13, "회계 증빙 보관용 파일박스", "사무용품")
        mk(acc, "김밥천국 여의도", 9000, acc_card, C.MEAL, True, S.SUBMITTED, "OK", 2, 20, "월말 결산 야근 식대", "음식점")
        mk(acc, "코레일 KTX", 47600, acc_card, C.TRIP, False, S.SUBMITTED, "OK", 3, 8, "세무조사 대응 본사 출장", "철도")
        mk(acc, "교보문고", 33000, acc_card, C.SUPPLIES, False, S.PENDING_CONFIRM, "OK", 4, 15, "개정세법 실무 서적", "서점")
        mk(acc, "스타벅스 여의도", 21000, acc_card, C.ENTERTAIN, True, S.RETURNED, "OK", 5, 16, "외부 회계법인 미팅 - 목적 보완 필요", "카페")
        mk(acc, "본죽 여의도", 12800, acc_card, C.MEAL, False, S.CONFIRMED, "OK", 9, 12, "주말 결산 근무 식대", "음식점")
        mk(acc, "우체국 등기", 8000, acc_card, C.OPERATION, False, S.ERP_VOUCHER_DRAFTED, "OK", 13, 11, "회계 원본 증빙 발송", "우편")
        mk(acc, "이마트 여의도", 64000, fin_team_card, C.SUPPLIES, False, S.TEAM_COLLECTING, "OK", 2, 18, "결산 기간 팀 간식·비품", "마트")

        # ── 재무회계팀 지출 내역 — 결산·세무·감사 대응 업무 지출 ──
        fin_expenses = [
            (acclead, "삼정회계법인", 550000, fin_team_card, C.OPERATION, False, S.SUBMITTED, "OK", 6, 14,
             "반기 결산 외부 자문료", "회계법인"),
            (u["오세진"], "김가네 여의도", 78000, fin_team_card, C.MEAL, False, S.TEAM_COLLECTING, "OK", 1, 20,
             "월말 결산 야근 팀 식대", "음식점"),
            (u["오세진"], "쿠팡", 128000, fin_team_card, C.SUPPLIES, True, S.TEAM_COLLECTING, "MISSING", 2, 11,
             "전표 보관용 파일·라벨 프린터", "전자상거래"),
            (u["한지민"], "코레일 KTX", 118600, postpaid, C.TRIP, False, S.TEAM_COLLECTING, "OK", 3, 7,
             "지방사업장 재고실사 출장", "철도"),
            (u["한지민"], "신라스테이 대전", 132000, postpaid, C.TRIP, True, S.SUBMITTED, "OK", 3, 22,
             "재고실사 출장 숙박", "숙박"),
            (u["오세진"], "스타벅스 IFC", 34500, fin_shared_card, C.MEETING, True, S.TEAM_RETURNED, "OK", 5, 15,
             "세무 자문 미팅 - 실사용자 미기재로 보완요청", "카페"),
            (acclead, "회계관리 SaaS", 330000, fin_team_card, C.OPERATION, False, S.CONFIRMED, "OK", 20, 10,
             "결산 자동화 툴 연간 구독", "소프트웨어"),
            (u["한지민"], "설렁탕집 여의도", 156000, fin_team_card, C.MEAL, False, S.CONFIRMED, "OK", 25, 12,
             "결산 마감 팀 오찬", "음식점"),
        ]
        for owner, merchant, amount, card, cat, ai, status, ev, days, hour, purpose, industry in fin_expenses:
            mk(owner, merchant, amount, card, cat, ai, status, ev, days, hour, purpose, industry)

        # ── 영업팀 취합 단계(팀장 뷰) — TEAM_* 상태 다양화 ──
        mk(u["박민수"], "배달의민족", 84000, sales_team_card, C.MEAL, True, S.TEAM_COLLECTING, "OK", 2, 20, "팀 야근 식대")
        mk(u["박민수"], "신라스테이", 450000, postpaid, C.TRIP, True, S.TEAM_COLLECTING, "OK", 3, 21, "지방 출장 숙박")
        mk(u["정하늘"], "이마트", 51000, sales_team_card, C.SUPPLIES, False, S.TEAM_RETURNED, "OK", 3, 17, "팀 비품 - 사용목적 보완 필요")
        mk(u["정하늘"], "스타벅스 코엑스", 26000, sales_team_card, C.MEETING, False, S.TEAM_COLLECTING, "OK", 4, 14, "주간 회의 다과")
        mk(u["이도윤"], "한우명가", 298000, shared_card, C.ENTERTAIN, True, S.TEAM_COLLECTING, "OK", 5, 19, "거래처 접대(실사용자 지정 필요)")
        mk(u["이도윤"], "롯데시네마 건대", 132000, shared_card, C.ENTERTAIN, True, S.TEAM_REJECTED, "OK", 6, 18, "접대 성격 불명확 - 팀 반려")
        mk(u["이도윤"], "카카오T", 12600, sales_team_card, C.TRIP, False, S.DRAFT, "OK", 2, 9, "고객사 방문 이동")
        mk(u["정하늘"], "교보문고", 54000, kim_card, C.SUPPLIES, False, S.SUBMITTED, "OK", 8, 12, "기술서적 구입")

        # ── 영업팀 취합 대기(TEAM_COLLECTING) 다양한 처리 샘플 ──
        # 프론트 S-02의 사람별 필터·분류별 예산·이상건 강조/자동 보완요청 시연용.
        collecting = [
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

        # ── 검토 워크스페이스(IN_REVIEW) 30건 ──
        # 위험도(0.12~0.96)·비용분류·패턴·권장처리를 폭넓게 분포시켜 정렬/필터/일괄처리 시연이 가능하도록 구성.
        # (owner, merchant, amount, card, category, evidence, days, hour, purpose, industry,
        #  anomaly_score, feature_contribs, rag_refs, anomaly_reasons, recommendation, confidence)
        F = lambda *pairs: [{"feature": f, "weight": w} for f, w in pairs]  # noqa: E731
        R = lambda *rows: [{"title": t, "source": s, "kind": k} for t, s, k in rows]  # noqa: E731

        reviews = [
            # ── 고위험(0.8~) : 반려·보완 권장 ──
            (u["이영희"], "강남한식당", 452000, shared_card, C.ENTERTAIN, "MISSING", 1, 22, "거래처 A사 계약 논의 접대", "한식",
             0.94, F(("전월 대비 결제금액 급증", 0.45), ("심야 시간대 결제", 0.32), ("적격증빙 미첨부", 0.23)),
             R(("3만원 초과 접대비는 적격증빙 필수, 미수취 시 손금불산입", "TIGER-REG-2026-003 제11조②", "policy"),
               ("유사사례 #1123 — 적격증빙 미비 반려(91% 패턴 일치)", "과거 반려사례 DB", "case")),
             ["고액 접대·심야 결제·적격증빙 누락"], "REJECT", 0.86),
            (u["한지민"], "제주그랜드리조트", 386000, postpaid, C.TRIP, "OK", 2, 23, "지방사업장 실사 출장 숙박", "숙박",
             0.88, F(("1박 숙박 한도 초과", 0.42), ("승인 일정과 지역 불일치", 0.31), ("주말 연박", 0.17)),
             R(("지역 등급별 1박 숙박비 한도 초과 시 사전 승인 필요", "TIGER-REG-2026-003 제17조②", "policy"),
               ("출장 일정·지역 불일치 시 변경 승인 첨부", "TIGER-REG-2026-003 제16조④", "policy")),
             ["숙박 한도 초과·출장 일정 불일치"], "RETURN", 0.83),
            (u["최지우"], "메가커피 x 12건", 128000, shared_card, C.MEETING, "OK", 3, 14, "팀 회의 다과(분할 결제)", "카페",
             0.85, F(("동일 가맹점 반복 결제", 0.41), ("한도 임계값 바로 아래", 0.29), ("동일 행사 다중 결제", 0.15)),
             R(("분할결제 의심 시 원거래 통합 검토", "TIGER-REG-2026-003 제8조", "policy"),
               ("유사사례 #0987 — 한도 회피 분할결제 보완요청", "과거 반려사례 DB", "case")),
             ["가맹점 반복·소액 다건·분할결제 의심"], "RETURN", 0.79),
            (u["이도윤"], "르쁘띠바", 268000, sales_shared_card, C.ENTERTAIN, "OK", 2, 23, "거래처 2차 접대", "주점",
             0.91, F(("금지업종 결제", 0.48), ("심야 시간대 결제", 0.27), ("공용카드 실사용자 미기재", 0.16)),
             R(("유흥업소·사행성업종 결제 금지", "TIGER-REG-2026-003 제9조②", "policy"),
               ("공용카드는 실사용자·목적 기재 필수", "요구사항 §4.1", "policy")),
             ["금지업종·심야 결제·실사용자 미기재"], "REJECT", 0.92),
            (u["박민수"], "골든벨CC", 420000, sales_team_card, C.ENTERTAIN, "OK", 6, 9, "거래처 임원 골프 접대", "골프장",
             0.87, F(("청탁금지법 대상자 참석", 0.44), ("1인당 법정 한도 초과", 0.33)),
             R(("공직자 등 참석 시 1인당 법정 한도 적용", "청탁금지법 제8조", "policy"),
               ("기업업무추진비 건당 50만원 초과 사전결재", "TIGER-REG-2026-003 제12조①", "policy")),
             ["청탁금지법 대상 참석·1인당 한도 초과"], "REJECT", 0.88),
            (u["서지훈"], "롯데백화점 상품권", 300000, sales_team_card, C.OPERATION, "OK", 7, 15, "명절 거래처 선물", "백화점",
             0.83, F(("유가증권 구매", 0.46), ("사전승인 없음", 0.24)),
             R(("상품권 등 유가증권 구매는 사전 승인 필수", "TIGER-REG-2026-003 제9조③", "policy")),
             ["상품권 구매·사전승인 누락"], "RETURN", 0.8),

            # 회계팀 자신의 지출도 예외 없이 검토 대상 — 승인자·지출자 동일 신호
            (acclead, "한우명가 여의도", 264000, fin_team_card, C.ENTERTAIN, "OK", 4, 19,
             "세무대리인 감사 대응 협의 만찬", "한식",
             0.81, F(("승인자와 지출자 동일", 0.38), ("회계부서 자체 지출", 0.26), ("건당 금액 상위", 0.17)),
             R(("승인자와 지출자가 동일한 경우 상위 결재선 확인", "TIGER-REG-2026-003 제5조③", "policy"),
               ("회계부서 자체 지출은 교차 검토 대상", "TIGER-REG-2026-003 제5조④", "policy")),
             ["승인자·지출자 동일·회계부서 자체 지출"], "RETURN", 0.74),

            # ── 중위험(0.5~0.8) : 보완요청·검토 ──
            (u["박민수"], "신라스테이", 310000, postpaid, C.ENTERTAIN, "OK", 2, 21, "거래처 접대 후 숙박", "숙박",
             0.78, F(("건당 한도 근접", 0.36), ("유사 반려사례 존재", 0.28)),
             R(("접대비 건당 한도 50만원 초과 시 사전결재", "TIGER-REG-2026-003 제12조①", "policy")),
             ["건당 한도 근접·유사사례 있음"], "RETURN", 0.64),
            (u["이영희"], "위워크 회의실", 176000, devai_team_card, C.MEETING, "MISSING", 4, 16, "외부 협업 워크숍 대관", "임대",
             0.74, F(("증빙 미첨부", 0.38), ("고액 단건", 0.22)),
             R(("3만원 초과 지출 적격증빙 필수", "TIGER-REG-2026-003 제11조②", "policy")),
             ["증빙 누락·고액 단건"], "RETURN", 0.71),
            (u["정하늘"], "이자카야 정", 198000, sales_team_card, C.MEAL, "OK", 5, 22, "팀 회식 2차", "주점",
             0.72, F(("2차 연속 결제", 0.35), ("1인당 한도 초과", 0.24), ("주류 포함", 0.13)),
             R(("회식 2차 비용은 원칙적 불인정", "TIGER-REG-2026-003 제14조③", "policy"),
               ("회식비 1인당 5만원 한도", "TIGER-REG-2026-003 제14조①", "policy")),
             ["2차 회식·1인당 한도 초과"], "RETURN", 0.69),
            (u["김철수"], "AWS 클라우드", 892000, devai_team_card, C.OPERATION, "OK", 8, 3, "개발 인프라 월 사용료", "클라우드",
             0.68, F(("월 최고 금액", 0.33), ("심야 자동결제", 0.21), ("전월 대비 증가", 0.14)),
             R(("정기 구독료는 예산 항목 사전 배정 필요", "TIGER-REG-2026-003 제6조", "policy")),
             ["고액 정기결제·전월 대비 증가"], "RETURN", 0.62),
            (u["이도윤"], "대한항공 비즈니스", 620000, postpaid, C.TRIP, "OK", 9, 11, "일본 출장 항공(비즈니스석)", "항공",
             0.66, F(("단거리 상위 좌석", 0.34), ("직급 기준 초과", 0.2)),
             R(("6시간 미만 노선 비즈니스석은 직급 예외 확인", "TIGER-REG-2026-003 제17조④", "policy")),
             ["단거리 비즈니스석 이용"], "RETURN", 0.6),
            (u["서지훈"], "이마트 트레이더스", 236000, sales_shared_card, C.SUPPLIES, "OK", 6, 19, "행사 경품 일괄 구매", "마트",
             0.63, F(("공용카드 고액 결제", 0.3), ("실사용자 미기재", 0.22)),
             R(("공용카드는 실사용자·목적 기재 필수", "요구사항 §4.1", "policy")),
             ["공용카드 고액·실사용자 미기재"], "RETURN", 0.58),
            (u["오세진"], "택시 심야 3건", 64500, fin_team_card, C.TRIP, "MISSING", 3, 2, "결산 야근 후 귀가", "운수",
             0.61, F(("심야 반복 결제", 0.29), ("증빙 미첨부", 0.21)),
             R(("야근 교통비는 승인된 야근 기록과 대조", "TIGER-REG-2026-003 제18조②", "policy")),
             ["심야 반복 결제·증빙 누락"], "RETURN", 0.57),
            (u["최지우"], "배달의민족", 143000, devai_team_card, C.MEAL, "OK", 4, 21, "야근 팀 식대", "음식점",
             0.58, F(("1인당 한도 근접", 0.27), ("야간 결제", 0.16)),
             R(("야근 식대는 1인 2만원 한도", "TIGER-REG-2026-003 제15조①", "policy")),
             ["야근 식대 한도 근접"], "RETURN", 0.55),
            (u["한도현"], "무신사", 98000, shared_card, C.SUPPLIES, "OK", 7, 13, "팀 단체 후드티", "의류",
             0.56, F(("업무 관련성 불명확", 0.31), ("공용카드 사용", 0.14)),
             R(("복리후생성 지출은 별도 예산·승인 필요", "TIGER-REG-2026-003 제19조", "policy")),
             ["업무 관련성 불명확"], "RETURN", 0.53),
            (u["박민수"], "GS25 x 8건", 47600, sales_team_card, C.MEAL, "OK", 5, 15, "현장 간식 소액 다건", "편의점",
             0.54, F(("소액 다건 반복", 0.28), ("동일 가맹점 반복", 0.15)),
             R(("분할결제 의심 시 원거래 통합 검토", "TIGER-REG-2026-003 제8조", "policy")),
             ["소액 다건·동일 가맹점 반복"], "RETURN", 0.51),
            (u["정하늘"], "쿠팡", 187000, sales_shared_card, C.SUPPLIES, "OK", 10, 10, "사무 비품 대량 구매", "전자상거래",
             0.52, F(("분류 신뢰도 낮음", 0.26), ("공용카드 사용", 0.14)),
             R(), ["분류 신뢰도 낮음"], "RETURN", 0.5),

            # ── 저위험(~0.5) : 승인 권장 ──
            (u["김철수"], "쿠팡", 95000, shared_card, C.SUPPLIES, "OK", 4, 11, "개발 장비 소모품", "전자상거래",
             0.48, F(("분류 신뢰도 낮음", 0.28)), R(), ["분류 신뢰도 낮음"], "APPROVE", 0.72),
            (u["한지민"], "코레일 KTX", 59800, postpaid, C.TRIP, "OK", 6, 8, "지방사업장 실사 이동", "철도",
             0.44, F(("출장 신청 임박 제출", 0.21)), R(), ["출장 신청 지연"], "APPROVE", 0.76),
            (u["정하늘"], "김밥천국", 60000, sales_team_card, C.MEAL, "OK", 6, 13, "주말 근무 식대", "음식점",
             0.43, F(("주말 결제", 0.19)), R(), ["주말 결제·소액"], "APPROVE", 0.81),
            (u["이영희"], "스타벅스 삼성점", 42000, devai_team_card, C.MEETING, "OK", 3, 14, "스프린트 회고 다과", "카페",
             0.39, F(("반복 가맹점", 0.17)), R(), ["동일 가맹점 반복(경미)"], "APPROVE", 0.83),
            (u["오세진"], "설렁탕집 여의도", 38000, fin_team_card, C.MEAL, "OK", 8, 12, "결산 마감 팀 오찬", "음식점",
             0.36, F(("금액 편차 경미", 0.15)), R(), ["경미한 금액 편차"], "APPROVE", 0.85),
            (u["이도윤"], "백반집", 42000, sales_team_card, C.MEAL, "OK", 7, 12, "업무 오찬", "음식점",
             0.3, F(("경미한 금액 편차", 0.12)), R(), ["경미한 금액 편차"], "APPROVE", 0.88),
            (u["서지훈"], "다이소", 18500, sales_team_card, C.SUPPLIES, "OK", 9, 16, "행사 소모품", "생활용품",
             0.28, F(("소액 결제", 0.11)), R(), ["특이사항 없음"], "APPROVE", 0.9),
            (u["한도현"], "카카오T", 14300, devai_team_card, C.TRIP, "OK", 5, 18, "협력사 미팅 이동", "운수",
             0.24, F(("소액 결제", 0.1)), R(), ["특이사항 없음"], "APPROVE", 0.91),
            (kim, "투썸플레이스", 21500, kim_card, C.MEETING, "OK", 11, 15, "거래처 상담 음료", "카페",
             0.21, F(("정상 패턴", 0.08)), R(), ["특이사항 없음"], "APPROVE", 0.93),
            (u["최지우"], "교보문고", 46000, devai_team_card, C.SUPPLIES, "OK", 12, 17, "기술 서적 구입", "서점",
             0.18, F(("정상 패턴", 0.07)), R(), ["특이사항 없음"], "APPROVE", 0.94),
            (u["박민수"], "본죽", 11000, sales_team_card, C.MEAL, "OK", 13, 12, "출장 중 점심", "음식점",
             0.15, F(("정상 패턴", 0.06)), R(), ["특이사항 없음"], "APPROVE", 0.95),
            (u["오세진"], "우체국 등기", 7600, fin_team_card, C.OPERATION, "OK", 14, 11, "증빙 원본 발송", "우편",
             0.12, F(("정상 패턴", 0.05)), R(), ["특이사항 없음"], "APPROVE", 0.96),
        ]
        review_rows = {}
        for (o, m, amt, card, cat, ev, d, h, pp, ind, sc, contrib, refs, ar, reco, conf) in reviews:
            settlement = mk(o, m, amt, card, cat, True, S.IN_REVIEW, ev, d, h, pp, ind,
                            risk=dict(anomaly_score=sc, reasons=contrib, rag_refs=refs, anomaly_reasons=ar,
                                      ai_recommendation=reco, ai_confidence=conf))
            review_rows[m] = settlement

        # ── 검토 '이전 처리' 이력 — 이번 달에 회계 담당자가 이미 결정한 건 ──
        # S-03의 "이전 처리" 탭은 이번 달 승인·보완요청·반려 건을 보여준다. 이상탐지 결과를 함께
        # 남겨야 위험도·사유가 그대로 조회되므로, 처리 완료 상태 + RiskReview를 짝지어 시드한다.
        #  status: PENDING_CONFIRM/CONFIRMED/ERP_VOUCHER_DRAFTED=승인 · RETURNED=보완요청 · REJECT=반려
        processed_reviews = [
            (u["이영희"], "더현대 서울", 512000, shared_card, C.ENTERTAIN, S.REJECT, "MISSING", 18, 21,
             "거래처 선물 구매", "백화점", 0.9,
             F(("고액 단건", 0.42), ("적격증빙 미첨부", 0.31), ("업무 관련성 불명확", 0.17)),
             ["고액·증빙 누락·업무 관련성 불명확"], "REJECT", 0.87),
            (u["이도윤"], "노래타운 강남", 176000, sales_shared_card, C.ENTERTAIN, S.REJECT, "OK", 16, 23,
             "거래처 접대 2차", "노래연습장", 0.93,
             F(("금지업종 결제", 0.5), ("심야 시간대 결제", 0.28)),
             ["금지업종·심야 결제"], "REJECT", 0.94),
            (u["최지우"], "쿠팡 이츠", 132000, devai_team_card, C.MEAL, S.RETURNED, "MISSING", 15, 21,
             "야근 식대 - 증빙 보완 필요", "음식점", 0.66,
             F(("증빙 미첨부", 0.36), ("1인당 한도 근접", 0.2)),
             ["증빙 누락·한도 근접"], "RETURN", 0.68),
            (u["박민수"], "인터컨티넨탈 서울", 264000, postpaid, C.TRIP, S.RETURNED, "OK", 14, 22,
             "출장 숙박 - 한도 초과분 소명 필요", "숙박", 0.71,
             F(("1박 숙박 한도 초과", 0.4), ("주말 연박", 0.16)),
             ["숙박 한도 초과"], "RETURN", 0.73),
            (u["오세진"], "다나와 사무기기", 96000, fin_team_card, C.SUPPLIES, S.RETURNED, "OK", 12, 14,
             "결산용 라벨 프린터 - 사용 목적 보완", "전자상거래", 0.55,
             F(("사용 목적 형식적", 0.29), ("분류 신뢰도 낮음", 0.14)),
             ["사용 목적 불명확"], "RETURN", 0.56),
            (u["한지민"], "SRT 수서-동대구", 84600, postpaid, C.TRIP, S.PENDING_CONFIRM, "OK", 11, 8,
             "지방사업장 재고실사 이동", "철도", 0.34,
             F(("출장 신청 임박 제출", 0.18)), ["출장 신청 지연(경미)"], "APPROVE", 0.82),
            (u["김철수"], "GitHub Copilot", 42000, devai_team_card, C.OPERATION, S.PENDING_CONFIRM, "OK", 10, 9,
             "개발 도구 월 구독", "소프트웨어", 0.27,
             F(("정기 결제", 0.11)), ["특이사항 없음"], "APPROVE", 0.9),
            (u["정하늘"], "미스터피자 코엑스", 78000, sales_team_card, C.MEAL, S.CONFIRMED, "OK", 9, 12,
             "제안 마감 주말 근무 식대", "음식점", 0.41,
             F(("주말 결제", 0.19)), ["주말 결제"], "APPROVE", 0.84),
            (u["서지훈"], "알파문구", 23400, sales_team_card, C.SUPPLIES, S.CONFIRMED, "OK", 8, 16,
             "전시 부스 소모품", "생활용품", 0.19,
             F(("소액 결제", 0.08)), ["특이사항 없음"], "APPROVE", 0.93),
            (u["한도현"], "카카오T 벤티", 28900, devai_team_card, C.TRIP, S.ERP_VOUCHER_DRAFTED, "OK", 7, 18,
             "협력사 데모 장비 이동", "운수", 0.23,
             F(("정상 패턴", 0.09)), ["특이사항 없음"], "APPROVE", 0.92),
        ]
        for (o, m, amt, card, cat, st, ev, d, h, pp, ind, sc, contrib, ar, reco, conf) in processed_reviews:
            mk(o, m, amt, card, cat, True, st, ev, d, h, pp, ind,
               risk=dict(anomaly_score=sc, reasons=contrib, rag_refs=[], anomaly_reasons=ar,
                         ai_recommendation=reco, ai_confidence=conf))

        # ── 룰 그래프 시드(GLOBAL v3 · 기업업무추진비 v2 · 회식비 v1+초안 · 출장비 승인대기) ──
        call_command("seed_rules")

        # ── 시연 하이라이트 3건: RAG 내규 검증 보고서 + 실제 EvalContext 스냅샷 ──
        self._enrich_demo_cases(review_rows, now)

        # ── 팀 예산(TeamBudget) — 한도만 DB 정의, 사용액은 Settlement 집계로 산출 ──
        # 한도를 손으로 박아두면 시드 내역이 바뀔 때마다 대시보드가 어긋난다. 실제로 이번 달에
        # 시드된 사용액에서 역산해 한도를 만든다 — 내역이 바뀌어도 비율이 유지된다.
        #  ① **6개 계정과목 전부** 예산 행을 만든다. (기존엔 '업무활성'이 빠져 있어 그 지출이
        #     총 사용액에는 잡히는데 항목별 카드에는 안 보였다 → 항목 합 ≠ 총액)
        #  ② 팀 총한도(category='' 행) = **과목 한도의 합**. "전체 예산"과 "항목별 예산"을 일치시킨다.
        #  ③ 팀별로 한 과목만 한도를 넘기게 만들어(OVER_BUDGET_DEMO) 초과 경고 톤을 시연한다.
        this_month = now.strftime("%Y-%m")
        BASE_USAGE_RATE = 0.65      # 일반 과목 목표 소진율 — 팀 전체는 70~75%대로 떨어진다
        OVER_BUDGET_RATE = 1.15     # 초과 시연 과목: 한도 < 사용액
        MIN_CATEGORY_LIMIT = 300_000  # 사용액이 적거나 0인 과목의 하한(0 나누기·빈 막대 방지)
        OVER_BUDGET_DEMO = {sales.id: C.ENTERTAIN, devai.id: C.MEETING, fin.id: C.TRIP}

        def round_up(value, unit=10_000):
            return int(-(-int(value) // unit) * unit)

        used_by_team_cat = defaultdict(int)
        for s in Settlement.objects.exclude(status=S.REJECT).select_related("transaction"):
            if s.team_id and s.transaction.ts.strftime("%Y-%m") == this_month:
                used_by_team_cat[(s.team_id, s.category)] += int(s.transaction.amount)

        for team in (sales, devai, fin):
            limits = {}
            for cat in C.values:
                used = used_by_team_cat.get((team.id, cat), 0)
                rate = OVER_BUDGET_RATE if OVER_BUDGET_DEMO.get(team.id) == cat else BASE_USAGE_RATE
                limits[cat] = max(MIN_CATEGORY_LIMIT, round_up(used / rate)) if used else MIN_CATEGORY_LIMIT
            for cat, lim in limits.items():
                TeamBudget.objects.create(team=team, year_month=this_month, category=cat, limit_amount=lim)
            TeamBudget.objects.create(team=team, year_month=this_month, category="",
                                      limit_amount=sum(limits.values()))

        # ── 분류별 정책 한도(Policy) — Draft Agent get_policy 실연동(B-3)용 최소 시드 ──
        #  값은 Django 플레이스홀더(draft_agent.py THRESHOLDS)와 동일한 임시 기준(영수증 3만원)이며,
        #  TIGER-REG-2026-003 원문 대조는 별도 오픈이슈(_context/draft-agent-plan.md §7).
        if not Policy.objects.exists():
            for cat in C.values:
                Policy.objects.create(
                    category=cat, limit_amount=30_000, required_evidence=["영수증"],
                    tax_note="임시 기준값 — 규정 원문 대조 전", refs=[],
                )

        self.stdout.write(self.style.SUCCESS(
            f"시드 완료 - 팀 {Team.objects.count()} / 사용자 {User.objects.count()} / 카드 {Card.objects.count()} / "
            f"정산 {Settlement.objects.count()}(검토 {RiskReview.objects.count()}) / 룰그래프 {RuleGraph.objects.count()} / "
            f"판정로그 {RuleHit.objects.count()} / 예산 {TeamBudget.objects.count()} / 정책 {Policy.objects.count()}"
        ))

    # ════════════════════════════════════════════════════════════
    #  시연 하이라이트 — RAG 보고서 + EvalContext 스냅샷
    # ════════════════════════════════════════════════════════════
    def _enrich_demo_cases(self, rows, now):
        """3건에 고품질 RAG 검증 보고서와 실제 EvalContext·판정 스냅샷을 붙인다.

        EvalContext는 계약 스키마(empty_eval_context) 전체 구조를 채우고, 판정은 실제 ACTIVE
        그래프를 엔진으로 돌려 얻은 경로·결정을 그대로 저장한다(rule_hits).
        """
        specs = [
            ("강남한식당", "접대", self._ctx_entertain(now), ENTERTAIN_REPORT, ENTERTAIN_REFS),
            ("제주그랜드리조트", "출장", self._ctx_trip(now), TRIP_REPORT, TRIP_REFS),
            ("메가커피 x 12건", "식대", self._ctx_dining(now), DINING_REPORT, DINING_REFS),
        ]
        for merchant, scope, context, report, refs in specs:
            settlement = rows.get(merchant)
            if settlement is None:
                continue
            review = settlement.risk_reviews.first()
            if review:
                review.rag_report = report
                review.rag_refs = refs
                review.save(update_fields=["rag_report", "rag_refs"])

            graph = (RuleGraph.objects.filter(scope=scope, status=RuleGraphStatus.ACTIVE).first()
                     or RuleGraph.objects.filter(scope=scope).order_by("-version").first())
            if graph is None:
                continue
            snapshot = {
                "nodes": list(graph.nodes.values("node_key", "condition", "action", "priority")),
                "routings": list(graph.routings.values("from_node_key", "on_result", "to_node_key", "priority")),
                "entry_node_key": graph.entry_node_key,
            }
            result = run_rule_engine(context, snapshot)
            RuleHit.objects.create(
                transaction=settlement.transaction, settlement=settlement, graph=graph,
                graph_version=graph.version, path=result.path, eval_context=context,
                flags=result.flags, decision=result.decision, confidence=result.confidence,
                eval_context_schema_version=EVAL_CONTEXT_SCHEMA_VERSION, builder_version=BUILDER_VERSION,
            )

    # ── EvalContext 3종 (계약 스키마 전체 구조를 채운다) ──
    def _ctx_entertain(self, now):
        ctx = empty_eval_context()
        ctx["tx"].update({"amount": 452000, "per_person_amount": 113000,
                          "payment_time": "22:41", "day_of_week": "FRI", "is_holiday": False,
                          "payment_method": "법인카드", "service_charge_ratio": 0.12})
        ctx["card"].update({"card_type": "SHARED", "actual_user_recorded": True})
        ctx["user"].update({"position": "차장", "dept": "AI·개발팀",
                            "finance_dept_is_spender": False, "is_working_hours": False})
        ctx["merchant"].update({"merchant_type": "한식", "merchant_grade": "A",
                                "merchant_info_resolved": True, "forbidden": False})
        ctx["category"].update({"value": "접대", "confidence": 0.91, "item_type": "식사",
                                "entertainment_type": "거래처 접대", "meal_type": "만찬",
                                "event_type": "계약 협의", "scope": "접대"})
        ctx["evidence"].update({"has_valid_receipt": False, "has_supporting_evidence": True,
                                "event_plan_attached": False, "confirmation_doc_submitted": False,
                                "purpose_missing": False, "purpose_is_generic": False,
                                "participant_list_missing": False, "vendor_info_missing": False,
                                "venue_datetime_missing": False, "project_name_missing": True,
                                "participant_record_missing": False})
        ctx["approval"].update({"pre_approval_obtained": False, "pre_approval_level": None,
                                "post_approval_within_1biz_day": False, "approver_is_spender_self": False,
                                "escalated_approval_confirmed": False, "spender_attended": True})
        ctx["participants"].update({"participant_count": 4, "external_participant_count": 2,
                                    "contractor_participant_count": 0,
                                    "contractor_regular_communication_purpose": False,
                                    "has_kickback_law_target": False, "kickback_law_category": None,
                                    "kickback_law_target_status_missing": False,
                                    "participant_includes_former_employee": False,
                                    "family_or_personal_gathering_suspected": False})
        ctx["dining"].update({"includes_alcohol": True, "is_secondary_venue": False,
                              "same_event_multiple_merchants": False, "event_scale_payment_method": "일시불"})
        ctx["history"].update({"same_vendor_count_3m": 2, "user_post_approval_count_3m": 1,
                               "late_settlement_count_no_reason_3m": 0,
                               "daily_cumulative_amount": 452000, "monthly_cumulative_amount": 1284000})
        ctx["policy"].update({"preapproval_threshold": 500000, "position_daily_limit": 600000,
                              "position_monthly_limit": 3000000, "kickback_limit": 30000,
                              "position_required_level": "본부장", "gift_type": None,
                              "approver_daily_limit": 1000000})
        ctx["derived"].update({"personal_use_suspected": False, "business_days_since_expense": 1,
                               "biz_days_over_7": False, "is_late_night": True, "is_weekend": False,
                               "category_specific_deadline_applies": True,
                               "category_specific_preapproval_rule_exists": True})
        ctx["tables"].update({"pre_approval_threshold_table": "REG-2026-003-T3",
                              "kickback_limit_table": "ACRC-2026-T1"})
        ctx["meta"].update({"tx_id": "TX-DEMO-ENT-001", "settlement_id": "ST-DEMO-ENT-001",
                            "schema_version": EVAL_CONTEXT_SCHEMA_VERSION, "builder_version": BUILDER_VERSION,
                            "built_at": now.isoformat(timespec="seconds")})
        return ctx

    def _ctx_trip(self, now):
        ctx = empty_eval_context()
        ctx["tx"].update({"amount": 386000, "payment_time": "23:12", "day_of_week": "SAT",
                          "is_holiday": True, "payment_method": "법인카드"})
        ctx["card"].update({"card_type": "POST_PAID", "actual_user_recorded": True})
        ctx["user"].update({"position": "대리", "dept": "재무회계팀",
                            "finance_dept_is_spender": True, "is_working_hours": False})
        ctx["merchant"].update({"merchant_type": "숙박", "merchant_grade": "A",
                                "merchant_info_resolved": True, "forbidden": False})
        ctx["category"].update({"value": "출장", "confidence": 0.96, "item_type": "숙박", "scope": "출장"})
        ctx["evidence"].update({"has_valid_receipt": True, "has_supporting_evidence": True,
                                "purpose_missing": False, "purpose_is_generic": False,
                                "venue_datetime_missing": False, "project_name_missing": False})
        ctx["approval"].update({"pre_approval_obtained": True, "pre_approval_level": "팀장",
                                "post_approval_within_1biz_day": True, "approver_is_spender_self": False})
        ctx["trip"].update({"trip_type": "국내", "region_grade": "B", "lodging_amount_per_night": 193000,
                            "flight_class": None, "flight_duration_hours": None,
                            "booking_to_trip_gap_months": 0.2, "during_business_trip": True,
                            "itinerary_mismatch": True, "work_end_time": "18:30",
                            "expense_type": "숙박", "trip_request_submitted_days_before": 4,
                            "emergency_trip": False})
        ctx["history"].update({"same_vendor_count_3m": 1, "daily_cumulative_amount": 386000,
                               "monthly_cumulative_amount": 947600})
        ctx["policy"].update({"lodging_limit": 120000, "position_daily_limit": 400000,
                              "position_monthly_limit": 2000000, "preapproval_threshold": 500000})
        ctx["derived"].update({"personal_use_suspected": True, "business_days_since_expense": 2,
                               "biz_days_over_7": False, "is_late_night": True, "is_weekend": True})
        ctx["tables"].update({"lodging_limit_table": "REG-2026-003-T7"})
        ctx["meta"].update({"tx_id": "TX-DEMO-TRIP-002", "settlement_id": "ST-DEMO-TRIP-002",
                            "schema_version": EVAL_CONTEXT_SCHEMA_VERSION, "builder_version": BUILDER_VERSION,
                            "built_at": now.isoformat(timespec="seconds")})
        return ctx

    def _ctx_dining(self, now):
        ctx = empty_eval_context()
        ctx["tx"].update({"amount": 128000, "per_person_amount": 10667, "payment_time": "14:22",
                          "day_of_week": "WED", "is_holiday": False, "payment_method": "법인카드"})
        ctx["card"].update({"card_type": "SHARED", "actual_user_recorded": True})
        ctx["user"].update({"position": "과장", "dept": "AI·개발팀", "is_working_hours": True})
        ctx["merchant"].update({"merchant_type": "카페", "merchant_grade": "B",
                                "merchant_info_resolved": True, "forbidden": False})
        ctx["category"].update({"value": "식대", "confidence": 0.88, "item_type": "음료",
                                "meal_type": "다과", "event_type": "팀 회의", "scope": "식대"})
        ctx["evidence"].update({"has_valid_receipt": True, "purpose_missing": False,
                                "purpose_is_generic": True, "participant_list_missing": False})
        ctx["approval"].update({"pre_approval_obtained": False, "approver_is_spender_self": True})
        ctx["participants"].update({"participant_count": 12, "external_participant_count": 0})
        ctx["dining"].update({"includes_alcohol": False, "is_secondary_venue": False,
                              "same_event_multiple_merchants": True, "event_scale_payment_method": "분할"})
        ctx["history"].update({"same_vendor_count_3m": 12, "user_post_approval_count_3m": 3,
                               "daily_cumulative_amount": 128000, "monthly_cumulative_amount": 612000})
        ctx["policy"].update({"position_daily_limit": 300000, "preapproval_threshold": 500000})
        ctx["derived"].update({"personal_use_suspected": False, "business_days_since_expense": 3,
                               "biz_days_over_7": False, "is_late_night": False, "is_weekend": False})
        ctx["meta"].update({"tx_id": "TX-DEMO-DINE-003", "settlement_id": "ST-DEMO-DINE-003",
                            "schema_version": EVAL_CONTEXT_SCHEMA_VERSION, "builder_version": BUILDER_VERSION,
                            "built_at": now.isoformat(timespec="seconds")})
        return ctx


# ════════════════════════════════════════════════════════════════
#  RAG 내규 검증 보고서 3종 (마크다운) + 근거 목록
# ════════════════════════════════════════════════════════════════
ENTERTAIN_REPORT = """## 판정 요약

**반려(REJECT) 권장 · 신뢰도 86%** — 기업업무추진비 452,000원 건으로, 적격증빙 미첨부와
사전승인 누락이 동시에 확인됩니다. 두 사유 모두 규정상 손금불산입 또는 보완 대상입니다.

## 규정 대조 결과

| 검증 항목 | 규정 기준 | 이 건의 값 | 판정 |
|---|---|---|---|
| 적격증빙 | 3만원 초과 시 필수 (제11조②) | 미첨부 | ❌ 위반 |
| 사전승인 | 건당 50만원 초과 시 필요 (제12조①) | 452,000원 — 기준 미만 | ✅ 해당 없음 |
| 참석자 명단 | 접대 시 필수 기재 (제11조④) | 4명(외부 2명) 기재됨 | ✅ 충족 |
| 봉사료 비중 | 10% 이상 시 엄격 심사 (제12조②) | 12% | ⚠️ 확인 필요 |
| 결제 시간대 | 심야 결제는 사적사용 소명 필요 (제7조①) | 22:41 | ⚠️ 확인 필요 |

## 근거 조항 발췌

> **제11조② (적격증빙)** — 건당 3만원을 초과하는 기업업무추진비는 세금계산서·계산서·신용카드
> 매출전표 등 적격증빙을 수취하여야 하며, 미수취분은 **손금에 산입하지 아니한다.**

> **제12조② (봉사료)** — 결제금액 대비 봉사료가 100분의 10 이상인 경우 업무관련성을 엄격히
> 심사하고, 필요 시 참석자 확인서를 징구한다.

## 유사 사례 대조

과거 반려사례 DB에서 **패턴 일치도 91%**인 사례(#1123)를 찾았습니다 — 동일하게 3만원 초과
접대비이면서 적격증빙이 없어 보완요청 후 미제출로 최종 반려된 건입니다. 당시 처리 소요는
14일이었고, 증빙을 재발급받아 제출한 유사 건(#1156)은 승인 처리됐습니다.

## 회계 담당자 확인 사항

1. **적격증빙 재발급이 가능한지** 지출자에게 먼저 확인해주세요. 재발급이 가능하면 반려 대신
   보완요청이 적절합니다.
2. 봉사료 12%는 해당 업종의 통상 범위를 넘습니다. 실제 접대 목적이 맞는지 참석자 구성을
   확인해주세요(외부 2명 / 내부 2명).
3. 심야 결제 자체는 위반이 아니지만, 이상탐지 점수(0.94)가 높게 나온 주요 요인입니다.

> ⚠️ 이 보고서는 근거 제시용이며, **최종 결정은 회계 담당자**가 수행합니다.
"""

ENTERTAIN_REFS = [
    {"title": "3만원 초과 접대비는 적격증빙 필수, 미수취 시 손금불산입",
     "source": "TIGER-REG-2026-003 제11조②", "kind": "policy",
     "excerpt": "건당 3만원을 초과하는 기업업무추진비는 적격증빙을 수취하여야 하며, 미수취분은 손금에 산입하지 아니한다.",
     "relevance": 0.94},
    {"title": "봉사료 10% 이상 포함 시 업무관련성 엄격 심사",
     "source": "TIGER-REG-2026-003 제12조②", "kind": "policy",
     "excerpt": "결제금액 대비 봉사료가 100분의 10 이상인 경우 업무관련성을 엄격히 심사한다.",
     "relevance": 0.81},
    {"title": "유사사례 #1123 — 적격증빙 미비로 보완요청 후 최종 반려",
     "source": "과거 반려사례 DB", "kind": "case",
     "excerpt": "3만원 초과 접대비, 적격증빙 미수취. 보완요청 후 14일간 미제출로 반려 처리.",
     "relevance": 0.91},
]

TRIP_REPORT = """## 판정 요약

**보완요청(RETURN) 권장 · 신뢰도 83%** — 출장 숙박비 386,000원 건입니다. 1박 숙박비가
지역 등급 기준 한도를 초과했고, 승인된 출장 일정·지역과 결제 내역이 일치하지 않습니다.

## 규정 대조 결과

| 검증 항목 | 규정 기준 | 이 건의 값 | 판정 |
|---|---|---|---|
| 1박 숙박비 | 지역 등급 B 기준 120,000원 (제17조②) | 193,000원 | ❌ 한도 초과 |
| 출장 신청 | 3영업일 전 제출 (제16조①) | 4일 전 제출 | ✅ 충족 |
| 일정 일치 | 승인 일정·지역과 결제지 일치 (제16조④) | 불일치 | ❌ 위반 |
| 적격증빙 | 3만원 초과 시 필수 (제11조②) | 첨부됨 | ✅ 충족 |
| 결제 시점 | 휴일·심야 결제는 사적사용 소명 (제7조①) | 토요일 23:12 | ⚠️ 확인 필요 |

## 근거 조항 발췌

> **제17조② (숙박비 한도)** — 국내 출장 숙박비는 지역 등급별 1박 한도를 초과할 수 없으며,
> 초과분은 **개인 부담**으로 한다. 다만 성수기·행사 등 불가피한 사유로 사전 승인을 받은 경우는
> 예외로 한다.

> **제16조④ (일정 변경)** — 승인된 출장 일정 또는 지역이 변경된 경우 **변경 승인**을 받아야 하며,
> 변경 승인 없이 발생한 지출은 업무관련성을 인정하지 아니할 수 있다.

## 이상탐지 신호와의 대조

이상탐지가 지목한 3개 신호(1박 한도 초과 0.42 / 일정 불일치 0.31 / 주말 연박 0.17) 중
**2개가 규정 위반과 직접 연결**됩니다. 주말 연박은 그 자체로 위반은 아니지만, 일정 불일치와
결합되면 사적 사용 결합 여부를 확인해야 하는 조합입니다.

## 회계 담당자 확인 사항

1. **성수기 사전 승인 여부** — 승인이 있었다면 한도 초과는 예외 적용이 가능합니다.
2. **변경 승인 문서** 첨부를 요청해주세요. 지역이 승인 일정과 다릅니다.
3. 초과분(73,000원)에 대한 개인 부담 처리 여부를 함께 안내하면 재제출이 한 번에 끝납니다.

> ⚠️ 규정 위반 2건이 확인되지만 모두 **소명 가능한 유형**이라 반려보다 보완요청이 적절합니다.
"""

TRIP_REFS = [
    {"title": "지역 등급별 1박 숙박비 한도 초과 시 개인 부담 또는 사전 승인 필요",
     "source": "TIGER-REG-2026-003 제17조②", "kind": "policy",
     "excerpt": "국내 출장 숙박비는 지역 등급별 1박 한도를 초과할 수 없으며, 초과분은 개인 부담으로 한다.",
     "relevance": 0.93},
    {"title": "출장 일정·지역 변경 시 변경 승인 필요",
     "source": "TIGER-REG-2026-003 제16조④", "kind": "policy",
     "excerpt": "승인된 출장 일정 또는 지역이 변경된 경우 변경 승인을 받아야 한다.",
     "relevance": 0.87},
    {"title": "유사사례 #0842 — 성수기 사전승인 첨부 후 승인 처리",
     "source": "과거 반려사례 DB", "kind": "case",
     "excerpt": "숙박 한도 초과 건이나 성수기 사전 승인 문서를 첨부해 예외 인정, 승인 처리.",
     "relevance": 0.78},
]

DINING_REPORT = """## 판정 요약

**보완요청(RETURN) 권장 · 신뢰도 79%** — 동일 가맹점에서 3개월간 12회, 이번 건도 여러 건으로
나뉘어 결제된 정황입니다. 개별 금액은 모두 한도 이내지만 **분할 결제로 한도를 회피한 것인지**
확인이 필요합니다.

## 규정 대조 결과

| 검증 항목 | 규정 기준 | 이 건의 값 | 판정 |
|---|---|---|---|
| 분할 결제 | 동일 행사 다중 결제 시 원거래 통합 검토 (제8조) | 동일 행사 다중 가맹점 결제 | ❌ 확인 필요 |
| 1인당 한도 | 회식비 1인당 50,000원 (제14조①) | 10,667원(12명) | ✅ 충족 |
| 적격증빙 | 3만원 초과 시 필수 (제11조②) | 첨부됨 | ✅ 충족 |
| 사용 목적 | 구체적 목적 기재 (제11조④) | "팀 회의 다과" — 형식적 문구 | ⚠️ 보완 권장 |
| 결제 승인자 | 승인자와 지출자 동일 여부 (제5조③) | 동일인 | ⚠️ 확인 필요 |

## 근거 조항 발췌

> **제8조 (분할 결제 금지)** — 한도 회피를 목적으로 하나의 거래를 둘 이상으로 나누어 결제하여서는
> 아니 된다. 동일 일자·동일 가맹점에서 반복 결제가 확인된 경우 **원거래를 통합하여 한도를 적용**한다.

## 패턴 분석

- 3개월간 **동일 가맹점 12회** 결제 — 같은 기간 팀 평균(3.2회)의 약 3.8배입니다.
- 이번 건은 12건으로 나뉘어 총 128,000원이 결제됐고, 개별 건은 모두 소액입니다.
- 통합 적용해도 1인당 금액(10,667원)은 한도 이내라 **실질적 한도 위반은 아닙니다.**

## 회계 담당자 확인 사항

1. **의도적 분할인지, 참석자별 개별 주문인지** 확인해주세요. 후자라면 정상 처리 대상입니다.
2. 사용 목적이 "팀 회의 다과"로 형식적입니다. 회의명·안건을 포함하도록 안내해주세요.
3. 승인자와 지출자가 동일합니다. 반복될 경우 승인 라인 조정을 권고합니다.

> ℹ️ 규정 위반이 확정된 건은 아닙니다. **패턴이 반복되고 있다는 점**이 검토 대상으로 올라온 이유입니다.
"""

DINING_REFS = [
    {"title": "한도 회피 목적 분할 결제 금지 — 원거래 통합 적용",
     "source": "TIGER-REG-2026-003 제8조", "kind": "policy",
     "excerpt": "한도 회피를 목적으로 하나의 거래를 둘 이상으로 나누어 결제하여서는 아니 된다.",
     "relevance": 0.9},
    {"title": "회식비 1인당 5만원 한도",
     "source": "TIGER-REG-2026-003 제14조①", "kind": "policy",
     "excerpt": "회식비는 참석자 1인당 5만원을 초과할 수 없다.",
     "relevance": 0.72},
    {"title": "유사사례 #0987 — 반복 소액 결제, 개별 주문으로 확인되어 승인",
     "source": "과거 반려사례 DB", "kind": "case",
     "excerpt": "동일 가맹점 반복 결제 건. 참석자별 개별 주문으로 확인되어 정상 승인 처리.",
     "relevance": 0.84},
]

"""Risk Review Agent 실동작 검증용 시드 — 팀취합→룰판정→(IN_REVIEW/승인대기) 전 구간을
**실제 코드 경로**로 태워서 만든다.

    python manage.py seed_risk_review_check              # 생성 + 실판정
    python manage.py seed_risk_review_check --dry-run     # 무엇을 만들지만 미리 본다(생성 없음)

**선행 조건**: `python manage.py seed`가 먼저 실행돼 있어야 한다 — ACTIVE 룰 그래프·정책
별표뿐 아니라, 아래에서 쓰는 **실제 팀·사용자·카드**(영업팀 `kim`/AI·개발팀 `이영희`/재무회계팀
`acc`와 그들의 카드)가 이미 있어야 한다. 없으면 시작 전에 에러로 안내하고 멈춘다.

## 검증용 팀을 새로 만들지 않는 이유(2026-08-21, 방향 정정)

최초 구현은 전용 팀("리스크리뷰검증팀")을 새로 만들었는데, 이러면 증빙검토 화면의 팀
필터에 **가짜 팀이 실제 조직팀(영업팀·AI·개발팀·재무회계팀)과 나란히 섞여 보인다** — 회계
담당자가 실사용하는 화면에 존재하지 않는 팀이 뜨는 건 좋지 않다. 그래서 이 버전은 **기존
`seed.py`가 만든 실제 팀·사용자·카드에 검증용 정산만 얹는다.** 어차피 실제 데이터로 취급해도
무방하다는 게 이전 대화의 결론이었다 — 그렇다면 새 팀을 지어낼 이유가 없다.

카드별로 이미 실거래 이력이 있어서(kim 카드 10건·AI개발팀 팀카드 11건·acc 카드 8건, 실측)
이상탐지 모델의 zscore 피처가 처음부터 의미 있는 비교 대상을 가진다 — 별도 "평소 사용 이력"
필러 거래를 안 만들어도 된다(이전 버전엔 있었다).

## 왜 실판정인가

`seed.py`의 검토 대기 30여 건은 anomaly_score·recommendation을 전부 사람이 손으로 써넣은
값이다 — Risk Review Agent(v1: MCP 툴콜링·risk_tier 3단계 분류·분류/액션 단계 분리)가 실제로
잘 동작하는지 검증하는 데는 못 쓴다(숫자에 실제 근거가 없다는 게 대화 중 확인된 문제).
이 명령은 실제 `services.raise_to_team → submit → judge`를 태워 **진짜 룰 판정 + 진짜 Risk
Review Agent(LLM) 호출**을 발생시킨다.

## 무엇을 만드나

**결과가 뭘로 떨어질지 룰 노드 조건을 실측해서 결정론적으로 설계한** 시나리오 10건
(`seed_rules.py`의 실제 조건 — 회식 1인당 한도/2차 결제, 접대 청탁금지법, GLOBAL 심야·휴일
게이트)을 3개 실제 팀에 나눠 배정한다. 다만 **anomaly_score/risk_tier 자체는 사전학습된
모델이 실제로 계산하는 값이라 정확한 숫자를 보장하지 않는다** — 실행 결과를 명령 출력으로
그대로 보여준다(실측).

## 재실행(멱등)

새 팀을 안 만드니 팀 소속 관계로는 이전 실행분을 못 찾는다 — 대신 이 시나리오들만 쓰는
**고유 가맹점명 목록**으로 식별한다(실제 seed.py 가맹점명과 겹치지 않게 고른 이름들).
재실행하면 그 가맹점명의 정산·거래만 지우고 다시 만든다. **실제 팀·사용자·카드는 절대
건드리지 않는다**(생성도 삭제도).

## 주의

- IN_REVIEW로 떨어진 건마다 **실제 OpenAI API를 호출**한다(이 명령은 최대 10건 규모 —
  `seed.py` 30~40건 규모가 아니다). AI 서비스(FastAPI `ai`)가 안 떠 있으면 조용히 스킵되고
  판정 상태는 그대로 남는다(`risk_review.run` 실패해도 판정 자체는 유지되는 기존 계약).
- 실행 시간은 IN_REVIEW 건수 × (LLM 응답시간, 실측 수 초~10여 초) 만큼 걸린다.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from domain.cards.models import Card
from domain.policies.models import RuleGraph, RuleGraphStatus
from domain.settlements import services
from domain.settlements.models import Category as C
from domain.settlements.models import Settlement
from domain.settlements.models import SettlementStatus as S
from domain.transactions import industry as industry_vocab
from domain.transactions.models import Receipt, Transaction

# 이 시나리오들만 쓰는 가맹점명 — 재실행 시 이걸로 이전 실행분을 찾아 지운다.
_MERCHANT_NAMES = [
    "포차 참", "호프 만선", "이자카야 노을", "한정식 다온", "한우명가 프라임",
    "김밥천국 역삼점", "포장마차 24시", "무명 잡화점", "스타벅스 판교점",
    "KTX 서울-부산(검증용)",
]

ITEM_TYPE = {C.MEAL: "식사", C.MEETING: "식사", C.ENTERTAIN: "식사", C.GATHERING: "행사성",
             C.TRIP: "교통", C.SUPPLIES: "소모품"}

# 실제 seed.py 데이터에 이미 있는 팀·사용자·카드 — 새로 안 만들고 그대로 빌려 쓴다.
# username/card 이름은 seed.py의 실제 값과 정확히 일치해야 한다(선행조건 참조).
_FIXTURES = {
    # AI·개발팀 — 회식·접대(그룹 지출은 팀카드가 자연스럽다)
    "team_b": {"username": "이영희", "card_name": "AI·개발팀 팀카드"},
    # 영업팀 — 식대(GLOBAL 게이트만 적용되는 카테고리)
    "personal_a": {"username": "kim", "card_name": "김영업 개인카드"},
    # 재무회계팀 — 비품·회의·출장(GLOBAL 게이트만 적용되는 카테고리)
    "personal_c": {"username": "acc", "card_name": "박회계 개인카드"},
}


class Command(BaseCommand):
    help = "Risk Review Agent 실동작 검증용 — 팀취합→룰판정 전 구간을 실제로 태운 IN_REVIEW/승인대기 시드"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="무엇을 만들지만 미리 보고 멈춘다")

    def handle(self, *args, **options):
        if not RuleGraph.objects.filter(scope="GLOBAL", status=RuleGraphStatus.ACTIVE).exists():
            self.stderr.write(self.style.ERROR(
                "GLOBAL ACTIVE 룰 그래프가 없습니다 — 먼저 `python manage.py seed`를 실행하세요."
            ))
            return

        try:
            fixtures = self._resolve_fixtures()
        except (Card.DoesNotExist, get_user_model().DoesNotExist) as exc:
            self.stderr.write(self.style.ERROR(
                f"필요한 실제 사용자·카드를 못 찾았습니다({exc}) — "
                "먼저 `python manage.py seed`를 실행하세요."
            ))
            return

        scenarios = self._build_scenarios()

        if options["dry_run"]:
            self.stdout.write("생성 예정 시나리오(실제 생성 없음):")
            for sc in scenarios:
                f = fixtures[sc["card_key"]]
                self.stdout.write(
                    f"  - [{f['owner'].team.name}/{f['card'].name}] {sc['category']} {sc['merchant']} "
                    f"{sc['amount']:,}원 — 예상: {sc['expect']}"
                )
            self.stdout.write(self.style.WARNING("\n실제 실행: --dry-run 없이 다시 실행"))
            return

        self._cleanup_previous_run()

        results = []
        for sc in scenarios:
            f = fixtures[sc["card_key"]]
            settlement = self._create_settlement(f["card"], f["owner"], f["owner"].team, sc)
            services.raise_to_team(settlement, f["owner"])
            services.submit(settlement, f["owner"])
            services.judge(settlement, f["owner"], reuse_recorded=True)
            settlement.refresh_from_db()
            review = settlement.risk_reviews.first()
            results.append((sc, settlement, review))

        self._report(results)

    def _resolve_fixtures(self):
        User = get_user_model()
        resolved = {}
        for key, spec in _FIXTURES.items():
            owner = User.objects.get(username=spec["username"])
            card = Card.objects.get(name=spec["card_name"])
            resolved[key] = {"owner": owner, "card": card}
        return resolved

    # ── 시나리오 정의 ────────────────────────────────────────────
    def _build_scenarios(self):
        """category/merchant/amount 외 필드는 실제 룰 노드 조건(seed_rules.py)에 맞춰
        의도한 결과가 나오도록 값을 정했다 — 주석의 '예상'은 그 노드 조건의 실측 근거다."""
        return [
            # ── 회식(GATHERING) — DINING_V1: 참석자→1인당한도(5만원)→2차→PASS ──
            dict(card_key="team_b", category=C.GATHERING, merchant="포차 참",
                 amount=210_000, headcount=6, is_secondary_venue=False, hour=19, days_ago=0,
                 purpose="분기 마감 팀 회식(1차)", industry="포차",
                 expect="1인당 35,000원(한도 이내)·2차 아님 → PASS → PENDING_CONFIRM"),
            dict(card_key="team_b", category=C.GATHERING, merchant="호프 만선",
                 amount=240_000, headcount=3, is_secondary_venue=False, hour=20, days_ago=1,
                 purpose="스프린트 마감 회식", industry="호프",
                 expect="1인당 80,000원(한도 5만원 초과, M-001) → REVIEW → IN_REVIEW"),
            dict(card_key="team_b", category=C.GATHERING, merchant="이자카야 노을",
                 amount=520_000, headcount=5, is_secondary_venue=True, hour=22, days_ago=2,
                 purpose="런칭 기념 회식(2차)", industry="이자카야",
                 expect="2차 결제(M-002) → REVIEW → IN_REVIEW, 금액도 이력 대비 크게 튐"),

            # ── 접대(ENTERTAIN) — ENTERTAIN_V2: 증빙→사전승인→청탁금지법→참석자→PASS ──
            dict(card_key="team_b", category=C.ENTERTAIN, merchant="한정식 다온",
                 amount=120_000, headcount=2, kickback_target=False, evidence_ok=True, hour=19, days_ago=3,
                 purpose="거래처 미팅 식사", industry="한식",
                 expect="증빙 있음·사전승인 불필요(30만원 미만)·청탁금지법 대상 아님 → PASS"),
            dict(card_key="team_b", category=C.ENTERTAIN, merchant="한우명가 프라임",
                 amount=100_000, headcount=2, kickback_target=True, evidence_ok=True, hour=20, days_ago=4,
                 purpose="공직 유관기관 협의 만찬", industry="한식",
                 expect="청탁금지법 대상자 참석 + 1인당 5만원(한도 3만원 초과, E-003 CRITICAL) → REVIEW"),

            # ── GLOBAL 게이트만 적용되는 카테고리(전용 scope 그래프 없음) — R-006 심야·휴일/업종미확인 ──
            dict(card_key="personal_a", category=C.MEAL, merchant="김밥천국 역삼점",
                 amount=12_000, hour=12, days_ago=1, weekday_override=1,
                 purpose="평일 점심 식대", industry="음식점", evidence_ok=True,
                 expect="평일 낮·업종 확인됨 → GLOBAL PASS(전용 그래프 없음) → PENDING_CONFIRM"),
            dict(card_key="personal_a", category=C.MEAL, merchant="포장마차 24시",
                 amount=45_000, hour=23, days_ago=5, weekday_override=5,
                 purpose="주말 야근 식대", industry="음식점", evidence_ok=True,
                 expect="심야(23시)+휴일(토) → R-006 REVIEW → IN_REVIEW"),
            dict(card_key="personal_c", category=C.SUPPLIES, merchant="무명 잡화점",
                 amount=68_000, hour=23, days_ago=6, weekday_override=2,
                 purpose="사무용품 구매", industry="", evidence_ok=True,
                 expect="심야(23시)+업종 미확인(industry='') → R-006 REVIEW → IN_REVIEW"),
            dict(card_key="personal_c", category=C.MEETING, merchant="스타벅스 판교점",
                 amount=28_000, hour=14, days_ago=2, weekday_override=1,
                 purpose="주간 회의 다과", industry="카페", evidence_ok=True,
                 expect="평일 낮 → GLOBAL PASS(전용 그래프 없음) → PENDING_CONFIRM"),
            dict(card_key="personal_c", category=C.TRIP, merchant="KTX 서울-부산(검증용)",
                 amount=119_600, hour=8, days_ago=7, weekday_override=3,
                 purpose="지방사업장 방문 이동", industry="철도", evidence_ok=True,
                 expect="평일 낮, 출장비 그래프는 승인대기(비활성) → GLOBAL PASS → PENDING_CONFIRM"),
        ]

    def _create_settlement(self, card, owner, team, sc):
        # `timezone.now()`는 UTC라 `.replace(hour=23)`을 그대로 쓰면 KST로는 08시가 된다
        # (실측 버그: R-006 심야 게이트가 안 걸림). 로컬 시각 기준으로 계산해야 한다.
        now = timezone.localtime(timezone.now())
        days_ago = sc.get("days_ago", 0)
        hour = sc.get("hour", 12)
        ts = (now - timezone.timedelta(days=days_ago)).replace(
            hour=hour, minute=0, second=0, microsecond=0
        )
        # 요일을 특정 값으로 맞춰야 하는 시나리오(휴일 게이트 등) — days_ago로 대략 맞추고
        # weekday_override가 있으면 그 요일이 나올 때까지 날짜를 밀어 정확히 맞춘다.
        target_weekday = sc.get("weekday_override")
        if target_weekday is not None:
            while ts.weekday() != target_weekday:
                ts -= timezone.timedelta(days=1)

        tx = Transaction.objects.create(
            card=card, merchant=sc["merchant"], amount=sc["amount"], ts=ts,
            raw_payload={"일시불할부구분코드": "A"},
        )
        if sc.get("evidence_ok"):
            Receipt.objects.create(matched_tx=tx, status=Receipt.Status.MATCHED, file_ref=f"receipts/{tx.id}.jpg")

        industry_code, industry_label = industry_vocab.resolve(sc.get("industry", ""))
        cat = sc["category"]
        headcount = sc.get("headcount")
        return Settlement.objects.create(
            transaction=tx, category=cat, ai_category=cat, ai_suggested=True,
            merchant_industry=industry_label, merchant_industry_code=industry_code,
            purpose=sc["purpose"], status=S.DRAFT, submitted_by=owner, team=team,
            item_type=ITEM_TYPE.get(cat, "기타"),
            actual_user_recorded=bool(sc["purpose"]) if card.card_type in ("SHARED", "TEAM") else None,
            actual_user=owner if card.card_type in ("SHARED", "TEAM") else None,
            headcount=headcount,
            external_headcount=0 if headcount else None,
            kickback_target=sc.get("kickback_target"),
            pre_approved=sc["amount"] <= 300_000,
            is_secondary_venue=sc.get("is_secondary_venue"),
            includes_alcohol=sc.get("is_secondary_venue"),
        )

    def _cleanup_previous_run(self):
        """이전 실행분만 지운다 — **실제 팀·사용자·카드는 절대 안 건드린다.**

        이 시나리오 전용 가맹점명(`_MERCHANT_NAMES`)으로 찾은 Settlement만 대상이다.
        `Settlement.transaction`은 PROTECT라 Settlement를 먼저 지워야 Transaction을 지울 수
        있다. 카드·팀·사용자는 seed.py가 소유한 실제 데이터라 여기서 만들지도 지우지도 않는다.
        """
        settlements = Settlement.objects.filter(transaction__merchant__in=_MERCHANT_NAMES)
        tx_ids = list(settlements.values_list("transaction_id", flat=True))
        settlements.delete()  # RiskReview·SettlementEvent는 CASCADE라 함께 정리된다
        Receipt.objects.filter(matched_tx_id__in=tx_ids).delete()
        Transaction.objects.filter(id__in=tx_ids).delete()

    def _report(self, results):
        self.stdout.write(self.style.SUCCESS(f"\n생성·판정 완료 — {len(results)}건\n"))
        header = f"{'가맹점':<20} {'팀':<10} {'분류':<6} {'룰판정':<8} {'상태':<16} {'anomaly':>9} {'등급':<6} {'권고':<10}"
        self.stdout.write(header)
        self.stdout.write("-" * len(header))
        for sc, settlement, review in results:
            anomaly = f"{review.anomaly_score:.4f}" if review else "-"
            tier = (review.risk_tier or "(없음)") if review else "(미실행)"
            reco = review.ai_recommendation or "-" if review else "-"
            self.stdout.write(
                f"{sc['merchant']:<20} {settlement.team.name:<10} {sc['category']:<6} "
                f"{settlement.rule_decision or '-':<8} {settlement.status:<16} {anomaly:>9} {tier:<6} {reco:<10}"
            )
            self.stdout.write(f"  기대: {sc['expect']}")
        in_review = sum(1 for _, s, _ in results if s.status == S.IN_REVIEW)
        pending = sum(1 for _, s, _ in results if s.status == S.PENDING_CONFIRM)
        no_review = sum(1 for _, _, r in results if r is None)
        self.stdout.write(
            f"\nIN_REVIEW {in_review}건 · PENDING_CONFIRM {pending}건 · "
            f"Risk Review 미실행(AI 서비스 다운 등) {no_review}건"
        )

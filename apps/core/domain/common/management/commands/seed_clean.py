"""시연용 **깨끗한 초기 상태** 시드 — 사용자 + DEFAULT GATE 하나만.

    docker compose exec core python manage.py seed_clean
    docker compose exec core python manage.py seed_clean --dry-run   # 지울 것만 보고 멈춤

`seed`(시연 데이터 한가득)와 정반대 목적이다. **"제품을 막 설치한 회사"** 상태를 만든다:
정산 내역·규정 문서·과목별 룰이 하나도 없고, 로그인할 사람과 범용 기본 게이트만 있다.
여기서부터 규정 문서를 올리고 Rule Agent가 룰을 만드는 흐름을 그대로 시연할 수 있다.

## 왜 룰이 게이트 하나뿐인가

제품이 미리 제공하는 룰은 `DEFAULT GATE` 하나라는 게 확정 사항이다(CLAUDE.md §2).
과목별 세부 룰은 **고객이 자기 규정 문서를 올리면 Rule Agent가 생성**한다. 그래서 여기에
접대·회식·출장 룰을 심어 두면 제품이 하지 않기로 한 일을 하는 셈이 된다.

## 기본 게이트가 하는 일 = "막지 않고, 사람에게 넘긴다"

회사 규정이 아직 없는 상태에서도 참인 것만 넣었다. 한도·기한 같은 **정책 판단은 넣을 수
없다** - 그건 회사 별표(`policy_tables`)에서 오는데 신규 설치엔 그게 없다. 없는 `policy.*`를
참조하면 미해소 가드가 **전건을 REVIEW로 강등**시켜 게이트가 무용지물이 된다.

**초기 도입은 유연해야 한다.** 걸 이유가 분명한 것만 걸고, 걸린 건은 전부
`REVIEW`(검토 필요)로 보낸다 - `RETURN`(지출자에게 되돌려보냄)은 회사가 무엇을 요구하는지
정해지기도 전에 내릴 결정이 아니다. 회계 담당자가 큐에서 보고 필요하면 그때 보완요청한다.

거는 것은 넷뿐이고 나머지는 전부 `PASS`다:

  · 법령·세법 위험 업종   - 사행성·유흥·노래연습장. 어느 회사에나 해당하는 축
  · 고액 증빙 누락        - 100만원 이상인데 증빙이 없을 때(소액 누락은 통과)
  · 비용분류 미기재        - 어느 과목 룰을 적용할지 정할 수 없다
  · 지출 목적 미기재       - 업무관련성 소명이 불가능하다

심야·주말·반복결제 같은 **이상 신호는 일부러 넣지 않았다.** 그건 Risk Review Agent(이상탐지)의
일이고, 회사마다 정상 범위가 달라 "범용 기본 룰"이 될 수 없다.
**PG사 결제 여부**도 넣지 않았다 - 판정에 쓸 사실이 없다(조립기의 `tx.payment_method`는
`"법인카드"` 고정이고 원장에도 PG 식별자가 없다). 지어내면 그대로 오판이 된다.

## 참조 필드를 고른 기준 (중요)

엔진은 **참조한 경로가 `None`이면 판정 전체를 REVIEW로 강등**한다(`engine._finalize`).
그래서 조립기가 **항상 값을 채우는 필드**만 썼다. 예를 들어 `card.actual_user_recorded`는
공용카드일 때 `Settlement.actual_user_recorded`(null 허용, None=모름)를 그대로 받아 대개
None이라, 그걸 참조하면 공용카드 건이 전부 REVIEW로 떨어진다 - 그래서 뺐다.
"""
from django.core.management.base import BaseCommand
from django.db import transaction as db_tx
from django.utils import timezone

from domain.accounts.models import Capability, JobTitle, Position, Role, Team, User
from domain.cards.models import Card, CardType
from domain.erp.models import ErpVoucher
from domain.policies.models import (
    OnResult, PolicyClause, PolicyDoc, PolicyFolder, PolicyTable, RuleGraph, RuleGraphStatus,
    RuleHit, RuleNode, RuleRouting,
)
from domain.risk.models import RiskReview
from domain.settlements.models import Category, Settlement, TeamBudget
from domain.transactions.industry import IndustryCode
from domain.transactions.models import MerchantCategory, Receipt, Transaction

from .ensure_service_account import SERVICE_USERNAME, ensure_service_account
from .seed_rules import branch, node

DEFAULT_GATE_NAME = "기본 정산 게이트"

# ── 기본 게이트 임계값 ────────────────────────────────────────────────────
#  회사 별표(`policy_tables`)가 없는 신규 설치에서 쓰는 **제품 기본값**이다. 정상이라면
#  이런 숫자는 `policy.*`(별표 선해소)에서 와야 하지만, 갓 설치한 회사엔 그 표가 없다 —
#  없는 `policy.*`를 참조하면 미해소 가드가 **전건을 REVIEW로 강등**해 게이트가 무용지물이 된다.
#  고객이 규정 문서를 올리면 Rule Agent가 만드는 과목별 룰이 이 자리를 대체한다.

#: 증빙 없이 넘어가지 않는 금액선. 소액 누락까지 잡으면 초기 도입에서 전건이 검토로 몰린다.
HIGH_AMOUNT_EVIDENCE_MIN = 1_000_000

#: 법령·세법상 위험이 큰 업종 — 회사 규정이 아니라 **어느 회사에나 해당**하는 축이라 기본값에 둔다.
#  (유흥주점=과세유흥장소, 사행성=도박, 노래연습장=유흥 유사) 손금 부인·사적사용 소명 대상이다.
#  라벨을 문자열로 박지 않고 정본 어휘(`transactions.industry`)에서 가져온다 — 표기가 바뀌면
#  룰의 `in [...]`이 **에러 없이 조용히 안 걸린다**(어휘 통일 때 실제로 겪은 실패 양상).
LEGAL_RISK_MERCHANT_TYPES = [
    IndustryCode.GAMBLING.label,
    IndustryCode.BAR_ENTERTAINMENT.label,
    IndustryCode.KARAOKE.label,
]


def default_gate_spec() -> dict:
    """DEFAULT GATE 그래프 — **막지 않고, 사람에게 넘긴다.**

    ## 설계 원칙: 초기 도입은 유연하게

    갓 설치한 회사에는 판정에 쓸 사실도, 회사 규정도 거의 없다. 이 상태에서 게이트를
    빡빡하게 걸면 두 가지가 동시에 일어난다 — 전건이 걸려서 게이트가 신호를 잃고,
    지출자에게 **보완요청(RETURN)이 쏟아져** 되돌아온 건이 쌓인다.

    그래서 기본 게이트는 이렇게 동작한다:

      · 걸린 건은 **전부 `REVIEW`(검토 필요)** 로 보낸다. `RETURN`을 쓰지 않는다 —
        RETURN은 지출자에게 일을 되돌려보내는 결정이고, 회사가 무엇을 요구하는지
        아직 정해지지 않은 상태에서 내릴 결정이 아니다. 회계 담당자가 큐에서 보고
        필요하면 그때 보완요청하면 된다.
      · **나머지는 전부 `PASS`.** 확인 안 된 것을 일단 걸어두는 대신, 걸 이유가 분명한
        것만 건다.

    ## 무엇을 거는가 (4가지)

    ①  **법령·세법 위험 업종** — 사행성·유흥·노래연습장. 회사 규정이 아니라 어느
        회사에나 해당하는 축이다.
    ②  **고액 증빙 누락** — 1,000,000원 이상인데 증빙이 없는 건. 소액 누락은 통과시킨다.
    ③  **비용분류 미기재** — 어느 과목 룰을 적용할지 정할 수 없다.
    ④  **지출 목적 미기재** — 업무관련성 소명이 불가능하다.

    ## 업종을 모르는 건은 왜 그냥 통과시키나

    엔진의 미해소 가드는 **노드가 참조한 경로가 `None`이면 판정을 REVIEW로 강등**한다.
    금지업종 노드가 `merchant.merchant_type`을 참조하는데 업종 미확정 건이 그 노드에
    도달하면, 실제로 금지업종이 아니어도 전부 검토로 떨어진다(신규 설치엔 가맹점 캐시가
    비어 있어 그게 대다수다).

    그래서 **분기로 우회한다** — `n_industry_known`이 업종 확인 여부만 보고(이 필드는
    조립기가 항상 채운다) 확인된 건만 금지업종 노드로 보낸다. 모르는 건은 그 노드를
    아예 지나지 않으므로 강등되지 않는다. 「모르는 걸 안전하다고 단정」하는 것과는 다르다
    — 업종 미확정은 Risk Review와 과목별 룰이 다시 볼 축이고, 기본 게이트가 전건을
    붙잡을 이유가 아니다.

    ## 넣지 않은 것

    · **PG사 결제 여부** — 판정에 쓸 사실이 없다. `tx.payment_method`는 조립기가
      `"법인카드"` 하나로 고정해 넣고 있고, 원장(`Transaction`)에도 PG 식별자가 없다.
      지어내면 그대로 오판이 되므로 룰을 만들지 않았다.
    · **한도·기한** — 회사 별표에서 와야 하는 값이라 신규 설치엔 근거가 없다.
    · **심야·주말·반복 결제** — Risk Review(이상탐지)의 일이고, 회사마다 정상 범위가
      달라 범용 기본값이 될 수 없다.
    """
    nodes = [
        node(
            "n_industry_known", "업종 확인 여부",
            {"==": [{"var": "merchant.merchant_info_resolved"}, True]},
            # 판정을 내리지 않는 분기 노드 — 업종을 아는 건만 금지업종 검사로 보낸다.
            "PASS_THROUGH", "업종을 확인한 건만 금지업종 검사로 보내는 분기", 0,
            severity="INFO", flag="",
            when="가맹점 업종을 확인했는지 보는 갈림길입니다",
            then="확인했으면 금지업종인지 보고, 확인하지 못했으면 이 검사를 건너뜁니다",
        ),
        node(
            "n_forbidden", "법령·세법 위험 업종",
            {"in": [{"var": "merchant.merchant_type"}, LEGAL_RISK_MERCHANT_TYPES]},
            "REVIEW", "사행성·유흥·노래연습장 등 법령·세법상 위험이 큰 업종 결제", 1,
            severity="CRITICAL", flag="PROHIBITED_MERCHANT",
            when="결제한 가게의 업종이 사행성업종·주점/유흥·노래연습장일 때",
            then="법인카드로 쓰기 어려운 업종이라 회계 담당자가 직접 확인하도록 검토로 넘깁니다",
        ),
        node(
            "n_evidence_high", "고액 증빙 누락",
            {"and": [
                {">=": [{"var": "tx.amount"}, HIGH_AMOUNT_EVIDENCE_MIN]},
                {"==": [{"var": "evidence.has_valid_receipt"}, False]},
            ]},
            "REVIEW", f"{HIGH_AMOUNT_EVIDENCE_MIN:,}원 이상인데 증빙이 확인되지 않은 건", 2,
            severity="HIGH", flag="EVIDENCE_MISSING",
            when=f"결제 금액이 {HIGH_AMOUNT_EVIDENCE_MIN:,}원 이상인데 영수증 등 증빙이 없을 때",
            then="금액이 큰 건이라 증빙 없이 넘기지 않고 회계 담당자 검토로 넘깁니다",
        ),
        node(
            "n_category", "비용분류 미기재",
            {"==": [{"var": "category.value"}, None]},
            "REVIEW", "비용분류가 선택되지 않아 적용할 과목 룰을 정할 수 없는 건", 3,
            severity="MEDIUM", flag="CATEGORY_MISSING",
            when="비용분류(식대·출장·접대 등)를 고르지 않았을 때",
            then="어느 과목 규칙을 적용할지 정할 수 없어 담당자가 확인하도록 검토로 넘깁니다",
        ),
        node(
            "n_purpose", "지출 목적 미기재",
            {"==": [{"var": "evidence.expense_purpose_missing"}, True]},
            "REVIEW", "지출 목적·사유가 비어 있어 업무관련성을 소명할 수 없는 건", 4,
            severity="MEDIUM", flag="PURPOSE_UNCLEAR",
            when="지출 목적·사유를 적지 않았을 때",
            then="업무와 어떤 관련이 있는지 확인할 수 없어 담당자가 보도록 검토로 넘깁니다",
        ),
        node(
            "_GATE_PASS", "기본 게이트 통과",
            True, "PASS", "기본 확인 항목에 걸리지 않은 건", 5,
            severity="INFO", flag="",
            when="위 확인 항목에 하나도 해당하지 않을 때",
            then="기본 검사를 통과한 것으로 보고 비용분류별 룰로 넘어갑니다",
        ),
    ]
    # 선형 체인이되 첫 노드만 분기다 — 업종을 모르면 금지업종 노드를 **지나지 않는다**
    # (지나면 미해소 가드가 강등한다, 위 docstring 참조).
    routings = [
        *branch("n_industry_known", match_to="n_forbidden", no_match_to="n_evidence_high"),
        *branch("n_forbidden", match_to="", no_match_to="n_evidence_high"),
        *branch("n_evidence_high", match_to="", no_match_to="n_category"),
        *branch("n_category", match_to="", no_match_to="n_purpose"),
        *branch("n_purpose", match_to="", no_match_to="_GATE_PASS"),
        *branch("_GATE_PASS", match_to="", no_match_to=""),
    ]
    return {"nodes": nodes, "routings": routings, "entry_node_key": "n_industry_known"}


# 지우는 대상. 순서가 있다 — RuleHit이 정산·거래를 SET_NULL로 참조해서 먼저 비워야
# 고아 로그가 남지 않는다(`seed --fresh`와 같은 이유).
WIPE_MODELS = (
    RuleHit, ErpVoucher, RiskReview, Settlement, Receipt, Transaction, Card,
    PolicyClause, PolicyDoc, PolicyFolder, PolicyTable,
    RuleRouting, RuleNode, RuleGraph, MerchantCategory,
)


class Command(BaseCommand):
    help = "시연용 초기 상태: 사용자 + DEFAULT GATE 하나만 남기고 전부 비운다"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="지울 건수만 출력하고 멈춘다")

    def handle(self, *args, **options):
        counts = {m.__name__: m.objects.count() for m in WIPE_MODELS}
        counts["User(비슈퍼유저)"] = User.objects.filter(is_superuser=False).count()
        counts["Team"] = Team.objects.count()

        if options["dry_run"]:
            self.stdout.write("삭제 대상 (dry-run - 아무것도 지우지 않았다):")
            for name, n in counts.items():
                if n:
                    self.stdout.write(f"  {name:<24}{n:>6}")
            self.stdout.write(self.style.WARNING("\n실제 실행: --dry-run 없이 다시 실행"))
            return

        with db_tx.atomic():
            for model in WIPE_MODELS:
                model.objects.all().delete()
            User.objects.filter(is_superuser=False).delete()
            Team.objects.all().delete()

            teams = self._teams()
            self._users(teams)
            self._budgets(teams)
            graph = self._default_gate()

        deleted = sum(counts.values())
        self.stdout.write(self.style.SUCCESS(
            f"초기화 완료 - 기존 {deleted}건 삭제\n"
            f"  사용자 {User.objects.filter(is_superuser=False).count()}명 / 팀 {Team.objects.count()}개 / "
            f"카드 {Card.objects.count()}장 / 예산 {TeamBudget.objects.count()}행\n"
            f"  ACTIVE 룰 그래프 1개: {graph.name} (GLOBAL, 노드 {graph.nodes.count()}개)"
        ))
        self.stdout.write(
            "\n다음 단계: 규정 문서 관리에서 사내 규정 PDF를 올리면 적재 후 Rule Agent가\n"
            "해당 비용분류의 룰 초안을 만듭니다. 과목별 룰은 사전 탑재하지 않습니다."
        )

    # ── 조직 ─────────────────────────────────────────────────
    def _teams(self) -> dict[str, Team]:
        return {
            "sales": Team.objects.create(name="영업팀", bu="영업본부"),
            "devai": Team.objects.create(name="AI·개발팀", bu="AI·개발본부"),
            "fin": Team.objects.create(name="재무회계팀", bu="경영지원본부"),
        }

    def _budgets(self, teams: dict[str, Team]) -> None:
        """이번 달 팀 예산 — **한도만** 넣는다(사용액은 저장하지 않는다).

        사용액은 그 팀·월 `Settlement` 집계로 산출되므로(`TeamBudgetView`), 정산이 0건인
        갓 설치 상태에서는 자연히 0이 된다. 여기서 사용액을 흉내내면 화면이 실제 내역과
        어긋난 숫자를 보여주게 된다.

        **불변식 2개를 지킨다**(예산 화면 둘이 기대하는 형태):
          ① 팀 총한도(`category=""` 행) = 과목 한도의 **합**
          ② **6개 과목 전부** 행을 만든다 — 하나라도 빠지면 그 과목 지출이 총액에는
             잡히는데 항목 카드엔 안 보여서 "항목 합 != 총액"이 된다(과거 실제 결함).

        금액은 **제품 기본값**이다. 회사가 정한 예산이 아니므로 사람이 조정해야 하지만
        아직 예산 쓰기 API가 없다 — 그때까지는 여기가 유일한 출처다.
        """
        this_month = timezone.localdate().strftime("%Y-%m")
        #  과목별 기본 한도. 팀마다 쓰는 과목이 다르지만 갓 설치한 회사에 대해 우리가 아는
        #  건 없다 — 전 팀에 같은 값을 주고 사람이 조정하게 둔다.
        default_limits = {
            Category.MEAL: 1_500_000,
            Category.GATHERING: 2_000_000,
            Category.MEETING: 1_000_000,
            Category.TRIP: 3_000_000,
            Category.ENTERTAIN: 3_000_000,
            Category.SUPPLIES: 1_000_000,
        }
        missing = set(Category.values) - {c.value for c in default_limits}
        assert not missing, f"예산 행이 없는 과목: {missing} (불변식 2)"

        for team in teams.values():
            for category, limit in default_limits.items():
                TeamBudget.objects.create(team=team, year_month=this_month,
                                          category=category, limit_amount=limit)
            TeamBudget.objects.create(team=team, year_month=this_month, category="",
                                      limit_amount=sum(default_limits.values()))

    def _users(self, teams: dict[str, Team]) -> None:
        """로그인 계정 — `seed`와 **같은 아이디·비밀번호**를 쓴다.

        시드를 갈아끼울 때마다 로그인 정보가 바뀌면 시연 중에 헤맨다. 역할별 능력은
        `ROLE_DEFAULT_CAPABILITIES`가 주고, 개인 추가부여만 여기서 얹는다.
        """
        # 직책·직급 기준 코드 — 사람보다 먼저. 규정 별표와 달리 **회사 마스터 데이터**라
        #  갓 설치한 상태에도 있어야 사람을 등록할 수 있다(정책 판단이 아니라 조직 사실이다).
        from domain.accounts.org_codes import seed_org_codes
        from domain.policies.flags import seed_rule_flags

        seed_org_codes()
        # 판정 사유 코드의 기준 어휘. 갓 설치한 회사에도 있어야 한다 — 규정이 아니라
        # 제품이 제공하는 **표시·분류 어휘**다(고객 문서에서 새 코드가 추가될 수 있다).
        seed_rule_flags()
        pos = {p.name: p for p in Position.objects.all()}
        title = {j.name: j for j in JobTitle.objects.all()}
        NONE = title["비직책자(공용카드)"]

        User.objects.create_user("kim", password="pass1234", role=Role.EMPLOYEE,
                                 team=teams["sales"], first_name="김영업",
                                 position=pos["대리"], job_title=NONE)
        User.objects.create_user("lead", password="pass1234", role=Role.TEAM_LEAD,
                                 team=teams["sales"], first_name="이팀장",
                                 position=pos["과장"], job_title=title["팀장"])
        User.objects.create_user("acc", password="pass1234", role=Role.ACCOUNTANT,
                                 team=teams["fin"], first_name="박회계",
                                 position=pos["대리"], job_title=NONE,
                                 extra_capabilities=[Capability.TEAM_AGGREGATE.value])
        User.objects.create_user("acclead", password="pass1234", role=Role.ACCOUNTANT_LEAD,
                                 team=teams["fin"], first_name="정회계팀장",
                                 position=pos["부장"], job_title=title["팀장"],
                                 extra_capabilities=[Capability.GOVERNANCE_VIEW.value])
        # 경영지원본부는 본부장 직위 미설치 → 부서장이 실무 최종 승인권자(「조직도」§3).
        User.objects.create_user("exec", password="pass1234", role=Role.EXECUTIVE,
                                 team=teams["fin"], first_name="최운영",
                                 position=pos["이사"], job_title=title["부서장"])

        # ai(FastAPI)가 core에 쓰기를 할 때 쓰는 서비스 계정. 비밀번호가 비어 있으면
        # 룰 생성·규정 적재가 401로 실패하므로 조용히 넘기지 않고 경고한다.
        _, _, password_set = ensure_service_account()
        if not password_set:
            self.stdout.write(self.style.WARNING(
                f"[경고] 서비스 계정 `{SERVICE_USERNAME}` 비밀번호 미설정(AI_SERVICE_PASSWORD) - "
                "AI 룰 생성·규정 적재가 401로 실패한다."
            ))

        # 카드가 없으면 신규 지출 등록에서 카드를 고를 수 없어 시연이 막힌다.
        # **거래·정산은 만들지 않는다** — 지출은 시연하는 사람이 직접 등록하는 게 이 시드의 목적이다.
        Card.objects.create(name="법인카드(개인)", card_type=CardType.PERSONAL, limit_amount=1_500_000)
        Card.objects.create(name="법인카드(팀)", card_type=CardType.TEAM, limit_amount=5_000_000)
        Card.objects.create(name="법인카드(공용)", card_type=CardType.SHARED, limit_amount=4_000_000)

    # ── 기본 게이트 ───────────────────────────────────────────
    def _default_gate(self) -> RuleGraph:
        spec = default_gate_spec()
        graph = RuleGraph.objects.create(
            name=DEFAULT_GATE_NAME,
            scope="GLOBAL",
            status=RuleGraphStatus.ACTIVE,
            version=1,
            entry_node_key=spec["entry_node_key"],
            source_clause="제품 기본 제공(회사 규정 무관)",
        )
        RuleNode.objects.bulk_create([RuleNode(graph=graph, **n) for n in spec["nodes"]])
        RuleRouting.objects.bulk_create([RuleRouting(graph=graph, **r) for r in spec["routings"]])
        return graph

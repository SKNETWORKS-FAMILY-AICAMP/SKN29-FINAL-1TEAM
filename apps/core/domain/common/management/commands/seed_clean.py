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

## 기본 게이트가 검사하는 것 = "판정 가능한 기록인가"

회사 규정이 아직 없는 상태에서도 참인 것만 넣었다. 한도·기한 같은 **정책 판단은 넣을 수
없다** - 그건 회사 별표(`policy_tables`)에서 오는데 신규 설치엔 그게 없다. 없는 `policy.*`를
참조하면 미해소 가드가 **전건을 REVIEW로 강등**시켜 게이트가 무용지물이 된다.

그래서 이 게이트는 정책을 판단하지 않고 **기록의 완결성**만 본다:

  · 증빙이 있는가        - 없으면 어느 회사에서도 정산이 안 된다
  · 지출 목적이 있는가    - 없으면 소명 자체가 불가능하다
  · 가맹점 업종이 확인됐나 - 모르면 비용분류의 근거가 없다
  · 분류를 믿을 수 있나   - AI 저신뢰 추천이면 사람이 본다

심야·주말·고액 같은 **이상 신호는 일부러 넣지 않았다.** 그건 Risk Review Agent(이상탐지)의
일이고, 회사마다 정상 범위가 달라 "범용 기본 룰"이 될 수 없다.

## 참조 필드를 고른 기준 (중요)

엔진은 **참조한 경로가 `None`이면 판정 전체를 REVIEW로 강등**한다(`engine._finalize`).
그래서 조립기가 **항상 값을 채우는 필드**만 썼다. 예를 들어 `card.actual_user_recorded`는
공용카드일 때 `Settlement.actual_user_recorded`(null 허용, None=모름)를 그대로 받아 대개
None이라, 그걸 참조하면 공용카드 건이 전부 REVIEW로 떨어진다 - 그래서 뺐다.
"""
from django.core.management.base import BaseCommand
from django.db import transaction as db_tx

from domain.accounts.models import Capability, Role, Team, User
from domain.cards.models import Card, CardType
from domain.erp.models import ErpVoucher
from domain.policies.models import (
    OnResult, PolicyClause, PolicyDoc, PolicyFolder, PolicyTable, RuleGraph, RuleGraphStatus,
    RuleHit, RuleNode, RuleRouting,
)
from domain.risk.models import RiskReview
from domain.settlements.models import Settlement
from domain.transactions.models import MerchantCategory, Receipt, Transaction

from .ensure_service_account import SERVICE_USERNAME, ensure_service_account
from .seed_rules import branch, node

DEFAULT_GATE_NAME = "기본 정산 게이트"
# 분류 신뢰도 하한. 회사 규정이 아니라 **우리 AI 추천의 신뢰도** 임계값이라 기본값으로 둔다
# (조립기가 ai_suggested=True면 0.5, 아니면 0.95를 넣는다 — 그 사이 어디든 같은 결과다).
CATEGORY_CONFIDENCE_MIN = 0.7


def default_gate_spec() -> dict:
    """DEFAULT GATE 그래프 — 선형 체인(하나라도 걸리면 그 노드가 종결).

    순서는 "보완하면 끝나는 것 → 사람이 봐야 하는 것"이다. 증빙·목적은 담당자가 채우면
    해결되므로 먼저 걸러 RETURN하고, 업종·분류는 사람의 확인이 필요해 REVIEW로 남긴다.
    """
    nodes = [
        node(
            "n_receipt", "증빙 누락",
            {"==": [{"var": "evidence.has_valid_receipt"}, False]},
            "RETURN", "영수증 등 증빙이 확인되지 않은 건", 0,
            severity="HIGH", flag="MISSING_RECEIPT",
            when="영수증 등 증빙이 등록되지 않았을 때",
            then="증빙을 첨부해 다시 제출하도록 보완요청합니다",
        ),
        node(
            "n_purpose", "지출 목적 미기재",
            {"==": [{"var": "evidence.expense_purpose_missing"}, True]},
            "RETURN", "지출 목적·사유가 비어 있는 건", 1,
            severity="HIGH", flag="MISSING_PURPOSE",
            when="지출 목적·사유를 적지 않았을 때",
            then="목적을 기재해 다시 제출하도록 보완요청합니다",
        ),
        node(
            "n_merchant", "가맹점 업종 미확인",
            {"==": [{"var": "merchant.merchant_info_resolved"}, False]},
            "REVIEW", "업종을 판별하지 못해 비용분류 근거가 없는 건", 2,
            severity="MEDIUM", flag="MERCHANT_UNRESOLVED",
            when="가맹점 업종을 확인하지 못했을 때",
            then="비용분류가 맞는지 담당자가 확인하도록 검토로 넘깁니다",
        ),
        node(
            "n_category", "비용분류 저신뢰",
            {"<": [{"var": "category.confidence"}, CATEGORY_CONFIDENCE_MIN]},
            "REVIEW", "AI 분류 신뢰도가 낮아 사람 확인이 필요한 건", 3,
            severity="MEDIUM", flag="LOW_CATEGORY_CONFIDENCE",
            when="AI가 추천한 비용분류의 신뢰도가 낮을 때",
            then="분류가 맞는지 담당자가 확인하도록 검토로 넘깁니다",
        ),
        node(
            "_GATE_PASS", "기본 게이트 통과",
            True, "PASS", "기본 확인 항목에 걸리지 않은 건", 4,
            severity="INFO", flag="",
            when="위 확인 항목에 하나도 해당하지 않을 때",
            then="기본 검사를 통과한 것으로 보고 비용분류별 룰로 넘어갑니다",
        ),
    ]
    chain = ["n_receipt", "n_purpose", "n_merchant", "n_category", "_GATE_PASS"]
    routings = []
    for index, key in enumerate(chain):
        # MATCH → 단말(그 노드의 decision으로 종결) / NO_MATCH → 다음 확인 항목
        routings += branch(key, match_to="", no_match_to=chain[index + 1] if index + 1 < len(chain) else "")
    return {"nodes": nodes, "routings": routings, "entry_node_key": chain[0]}


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
            graph = self._default_gate()

        deleted = sum(counts.values())
        self.stdout.write(self.style.SUCCESS(
            f"초기화 완료 - 기존 {deleted}건 삭제\n"
            f"  사용자 {User.objects.filter(is_superuser=False).count()}명 / 팀 {Team.objects.count()}개 / "
            f"카드 {Card.objects.count()}장\n"
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

    def _users(self, teams: dict[str, Team]) -> None:
        """로그인 계정 — `seed`와 **같은 아이디·비밀번호**를 쓴다.

        시드를 갈아끼울 때마다 로그인 정보가 바뀌면 시연 중에 헤맨다. 역할별 능력은
        `ROLE_DEFAULT_CAPABILITIES`가 주고, 개인 추가부여만 여기서 얹는다.
        """
        User.objects.create_user("kim", password="pass1234", role=Role.EMPLOYEE,
                                 team=teams["sales"], first_name="김영업")
        User.objects.create_user("lead", password="pass1234", role=Role.TEAM_LEAD,
                                 team=teams["sales"], first_name="이팀장")
        User.objects.create_user("acc", password="pass1234", role=Role.ACCOUNTANT,
                                 team=teams["fin"], first_name="박회계",
                                 extra_capabilities=[Capability.TEAM_AGGREGATE.value])
        User.objects.create_user("acclead", password="pass1234", role=Role.ACCOUNTANT_LEAD,
                                 team=teams["fin"], first_name="정회계팀장",
                                 extra_capabilities=[Capability.GOVERNANCE_VIEW.value])
        User.objects.create_user("exec", password="pass1234", role=Role.EXECUTIVE,
                                 team=teams["fin"], first_name="최운영")

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
        Card.objects.create(name="법인카드(개인)", card_type=CardType.PERSONAL)
        Card.objects.create(name="법인카드(팀)", card_type=CardType.TEAM)
        Card.objects.create(name="법인카드(공용)", card_type=CardType.SHARED)

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

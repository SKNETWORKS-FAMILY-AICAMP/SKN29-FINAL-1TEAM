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

## 기본 게이트가 하는 일 = "기본은 검토, 자동 통과는 예외"

회사 규정이 아직 없는 상태에서도 참인 것만 넣었다. 한도·기한 같은 **정책 판단은 넣을 수
없다** - 그건 회사 별표(`policy_tables`)에서 오는데 신규 설치엔 그게 없다. 없는 `policy.*`를
참조하면 미해소 가드가 **전건을 REVIEW로 강등**시켜 신호가 사라진다.

**통과를 기본값으로 두지 않는다.** 갓 설치한 회사에서 우리가 아는 건 거의 없는데, 모르는
것을 통과로 접으면 게이트가 못 보는 축(심야 결제·이상 패턴·회사 규정)이 전부 조용히
승인 대기로 흐른다. 그래서:

  · **기본은 `REVIEW`** - 사람이 본다. 다만 **왜 봐야 하는지 사유(플래그)를 달아서** 넘긴다.
  · **`PASS`는 화이트리스트** - 증빙·목적·분류가 모두 채워져 있고, 업종을 확인했고
    법령·세법 위험 업종이 아니며, 금액이 상한 미만일 때만. 자동 통과는 되돌리기 어려운
    방향이라(틀리면 그냥 새는 돈) 확신이 있을 때만 낸다.
  · **`RETURN`·`REJECT`는 내지 않는다** - 지출자에게 되돌려보내거나 반려하는 건 회사가
    무엇을 요구하는지 정해진 뒤의 결정이다. 회계가 큐에서 보고 판단한다.

사유 플래그는 **해당하는 것이 전부** 붙는다(금지업종·업종미확정·증빙누락·목적누락·
분류미기재·실사용자미등록·고액). 사유마다 단말로 끊으면 첫 번째 하나만 남는다.

심야·주말·반복결제 같은 **이상 신호는 일부러 넣지 않았다.** 그건 Risk Review Agent(이상탐지)의
일이고, 회사마다 정상 범위가 달라 "범용 기본 룰"이 될 수 없다 - 이제 기본이 REVIEW라
그런 건도 어차피 사람을 거친다.
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
#  없는 `policy.*`를 참조하면 미해소 가드가 **전건을 REVIEW로 강등**해 신호가 사라진다.
#  고객이 규정 문서를 올리면 Rule Agent가 만드는 과목별 룰이 이 자리를 대체한다.

#: 사람 확인 없이 승인 대기로 보낼 수 있는 금액 상한. 이 위는 무조건 사람이 본다.
#  자동 통과는 **되돌리기 어려운 방향**이라 보수적으로 잡는다(틀리면 그냥 새는 돈이 된다).
AUTO_PASS_MAX_AMOUNT = 300_000

#: 법령·세법상 위험이 큰 업종 — 회사 규정이 아니라 **어느 회사에나 해당**하는 축이라 기본값에 둔다.
#  (유흥주점=과세유흥장소, 사행성=도박, 노래연습장=유흥 유사) 손금 부인·사적사용 소명 대상이다.
#  라벨을 문자열로 박지 않고 정본 어휘(`transactions.industry`)에서 가져온다 — 표기가 바뀌면
#  룰의 `in [...]`이 **에러 없이 조용히 안 걸린다**(어휘 통일 때 실제로 겪은 실패 양상).
LEGAL_RISK_MERCHANT_TYPES = [
    IndustryCode.GAMBLING.label,
    IndustryCode.BAR_ENTERTAINMENT.label,
    IndustryCode.KARAOKE.label,
]


def _flag_node(key, title, condition, flag, priority, *, severity, when, then, description):
    """사유만 붙이고 **판정하지 않는** 노드.

    `PASS_THROUGH`라 순회가 멈추지 않는다 — 그래서 해당하는 사유가 **전부** 쌓인 채로
    마지막 판정 노드까지 간다. 사유마다 단말로 끊으면 첫 번째 하나만 남아서, 검토자가
    "이 건에 뭐가 걸렸나"를 한 번에 볼 수 없다.
    """
    return node(
        key, title, condition, "PASS_THROUGH", description, priority,
        severity=severity, flag=flag, when=when, then=then,
    )


def default_gate_spec() -> dict:
    """DEFAULT GATE 그래프 — **기본값은 검토다. 자동 통과는 예외다.**

    ## 왜 방향을 뒤집었나

    이전 버전은 "걸리는 것만 걸고 나머지는 통과"였다. 그건 **통과를 기본값으로 두는 설계**라,
    게이트가 못 보는 축(심야 결제·이상 패턴·회사 규정)이 전부 조용히 승인 대기로 흘렀다.
    갓 설치한 회사에서 우리가 아는 건 거의 없는데, 모르는 것을 통과로 접은 셈이다.

    지금은 반대다:

      · **기본은 `REVIEW`** — 사람이 본다. 다만 **왜 봐야 하는지 사유(플래그)를 달아서** 넘긴다.
        검토자가 빈손으로 받지 않는다.
      · **`PASS`는 화이트리스트** — 아래 조건을 **전부** 만족하는 건만. 자동 통과는
        되돌리기 어려운 방향이라(틀리면 그냥 새는 돈) 확신이 있을 때만 낸다.
      · **`RETURN`·`REJECT`는 내지 않는다** — 지출자에게 일을 되돌려보내거나 반려하는 건
        회사가 무엇을 요구하는지 정해진 뒤의 결정이다. 회계가 큐에서 보고 판단한다.

    ## 자동 통과(PASS) 조건 — 전부 만족해야 한다

      ① 적격증빙이 있다
      ② 지출 목적이 적혀 있다
      ③ 비용분류가 **사람이 확정한 값**으로 채워져 있다
      ④ 가맹점 업종을 확인했고, 법령·세법 위험 업종이 아니다
      ⑤ 금액이 상한(`AUTO_PASS_MAX_AMOUNT`) 미만이다
      ⑥ (엔진 가드) 참조한 사실 중 **모르는 값이 하나도 없다** — 공용카드 실사용자
         미등록처럼 `None`인 사실이 있으면 자동 통과되지 않는다

    ⑥은 룰로 적지 않았다. 엔진의 미해소 가드가 이미 그 일을 한다(`engine._finalize`):
    순회 중 참조한 경로에 `None`이 있으면 판정을 REVIEW로 낮춘다. 같은 규칙을 두 곳에
    적으면 한쪽이 곧 뒤처진다.

    ## 사유 플래그 (판정하지 않고 표시만)

    `PASS_THROUGH` 노드들이 해당하는 사유를 **전부 쌓아서** 마지막 판정 노드까지 보낸다 —
    금지업종·업종미확정·증빙누락·목적누락·분류미기재·실사용자미등록·고액. 사유마다 단말로
    끊으면 첫 번째 하나만 남는다.

    ## 업종을 모르는 건은 왜 분기로 우회하나

    미해소 가드는 **노드가 참조한** 경로의 `None`을 본다(조건이 매치되는지와 무관하다).
    금지업종 노드가 `merchant.merchant_type`을 참조하는데 업종 미확정 건이 그 노드에
    도달하면 `UNRESOLVED_FACT`가 붙는다 — 사유로는 `MERCHANT_UNRESOLVED`가 더 정확하다.
    그래서 `n_industry_known`이 갈라서, 모르는 건은 전용 사유 노드로 보낸다.

    ## 넣지 않은 것

    · **PG사 결제 여부** — 판정에 쓸 사실이 없다. `tx.payment_method`는 조립기가
      `"법인카드"` 하나로 고정해 넣고 있고 원장(`Transaction`)에도 PG 식별자가 없다.
    · **한도·기한** — 회사 별표에서 와야 하는 값이라 신규 설치엔 근거가 없다.
    · **심야·주말·반복 결제** — Risk Review(이상탐지)의 일이고, 회사마다 정상 범위가
      달라 범용 기본값이 될 수 없다. 다만 이제 기본이 REVIEW라 그런 건도 사람을 거친다.
    """
    nodes = [
        node(
            "n_industry_known", "업종 확인 여부",
            {"==": [{"var": "merchant.merchant_info_resolved"}, True]},
            "PASS_THROUGH", "업종을 확인한 건과 못 한 건을 가르는 분기", 0,
            severity="INFO", flag="",
            when="가맹점 업종을 확인했는지 보는 갈림길입니다",
            then="확인했으면 금지업종인지 보고, 못 했으면 '업종 미확정' 사유를 답니다",
        ),
        _flag_node(
            "n_forbidden", "법령·세법 위험 업종",
            {"in": [{"var": "merchant.merchant_type"}, LEGAL_RISK_MERCHANT_TYPES]},
            "PROHIBITED_MERCHANT", 1, severity="CRITICAL",
            description="사행성·유흥·노래연습장 등 법령·세법상 위험이 큰 업종 결제",
            when="결제한 가게의 업종이 사행성업종·주점/유흥·노래연습장일 때",
            then="법인카드로 쓰기 어려운 업종이라는 사유를 달아 검토로 넘깁니다",
        ),
        _flag_node(
            "n_industry_unresolved", "가맹점 업종 미확정",
            True,   # 이 노드에 도달했다는 것 자체가 "업종을 모른다"는 뜻이다(위 분기의 NO_MATCH).
            "MERCHANT_UNRESOLVED", 2, severity="LOW",
            description="업종을 판별하지 못해 비용분류·금지업종 판단 근거가 없는 건",
            when="가맹점 업종을 확인하지 못했을 때",
            then="업종을 모른다는 사유를 달아 검토로 넘깁니다",
        ),
        _flag_node(
            "n_evidence", "증빙 누락",
            {"==": [{"var": "evidence.has_valid_receipt"}, False]},
            "EVIDENCE_MISSING", 3, severity="HIGH",
            description="영수증 등 적격증빙이 확인되지 않은 건",
            when="영수증 등 증빙이 등록되지 않았을 때",
            then="증빙이 없다는 사유를 달아 검토로 넘깁니다",
        ),
        _flag_node(
            "n_purpose", "지출 목적 미기재",
            {"==": [{"var": "evidence.expense_purpose_missing"}, True]},
            "PURPOSE_UNCLEAR", 4, severity="MEDIUM",
            description="지출 목적·사유가 비어 있어 업무관련성을 소명할 수 없는 건",
            when="지출 목적·사유를 적지 않았을 때",
            then="목적이 없다는 사유를 달아 검토로 넘깁니다",
        ),
        _flag_node(
            "n_category", "비용분류 미기재",
            {"==": [{"var": "category.value"}, None]},
            "CATEGORY_MISSING", 5, severity="MEDIUM",
            description="비용분류가 확정되지 않아 적용할 과목 룰을 정할 수 없는 건",
            when="비용분류(식대·출장·접대 등)가 확정되지 않았을 때",
            then="분류가 비었다는 사유를 달아 검토로 넘깁니다",
        ),
        _flag_node(
            "n_actual_user", "실사용자 미등록",
            {"==": [{"var": "card.actual_user_recorded"}, False]},
            "ACTUAL_USER_REQUIRED", 6, severity="MEDIUM",
            description="팀·공용 카드 결제인데 실제로 쓴 사람이 기록되지 않은 건",
            when="팀·공용 카드 결제의 실사용자가 등록되지 않았을 때",
            then="누가 썼는지 모른다는 사유를 달아 검토로 넘깁니다",
        ),
        _flag_node(
            "n_high_amount", "고액 지출",
            {">=": [{"var": "tx.amount"}, AUTO_PASS_MAX_AMOUNT]},
            "HIGH_AMOUNT", 7, severity="LOW",
            description="자동 통과 상한을 넘어 사람이 확인해야 하는 금액대",
            when="결제 금액이 자동 통과 상한 이상일 때",
            then="금액이 커서 사람이 봐야 한다는 사유를 달아 검토로 넘깁니다",
        ),
        node(
            "n_autopass_gate", "자동 통과 검사 가능 여부",
            # 업종을 모르는 건은 자동 통과 자체가 불가능하다(요건 ④). 그런데 `n_auto_pass`가
            # `merchant.merchant_type`을 참조하므로, 업종 미확정 건이 그 노드에 **도달만 해도**
            # 미해소 가드가 `UNRESOLVED_FACT`를 붙인다 — 이미 `MERCHANT_UNRESOLVED`로 더
            # 정확히 표시한 사유라 중복이다. 그래서 도달하기 전에 갈라 보낸다.
            {"==": [{"var": "merchant.merchant_info_resolved"}, True]},
            "PASS_THROUGH", "업종을 확인한 건만 자동 통과 요건 검사로 보내는 분기", 8,
            severity="INFO", flag="",
            when="자동 통과 요건을 따져볼 수 있는 건인지 보는 갈림길입니다",
            then="업종을 확인한 건만 요건 검사로 보내고, 나머지는 바로 검토로 넘깁니다",
        ),
        node(
            "n_auto_pass", "자동 통과 요건",
            # **화이트리스트다.** 하나라도 어긋나면 검토로 간다. 위 사유 노드들과 조건이
            # 겹치지만 합칠 수 없다 — 플래그는 상태머신을 움직이지 않는다는 불변식 때문에
            # 엔진이 "지금까지 붙은 플래그"를 조건으로 읽을 수 없다(그게 설계 의도다).
            {"and": [
                {"==": [{"var": "evidence.has_valid_receipt"}, True]},
                {"==": [{"var": "evidence.expense_purpose_missing"}, False]},
                {"!=": [{"var": "category.value"}, None]},
                {"==": [{"var": "merchant.merchant_info_resolved"}, True]},
                {"not": {"in": [{"var": "merchant.merchant_type"}, LEGAL_RISK_MERCHANT_TYPES]}},
                {"<": [{"var": "tx.amount"}, AUTO_PASS_MAX_AMOUNT]},
            ]},
            "PASS", "기록이 완결됐고 위험 신호가 없어 승인 대기로 바로 보내는 건", 9,
            severity="INFO", flag="",
            when="증빙·목적·분류가 모두 채워져 있고, 업종을 확인했으며 위험 업종이 아니고, "
                 "금액이 자동 통과 상한 미만일 때",
            then="사람이 따로 볼 것이 없다고 보고 승인 대기로 바로 넘깁니다",
        ),
        node(
            "_GATE_REVIEW", "회계 검토 필요",
            True, "REVIEW", "자동 통과 요건을 다 채우지 못해 사람이 확인해야 하는 건", 10,
            severity="INFO", flag="",
            when="자동 통과 요건을 하나라도 채우지 못했을 때",
            then="위에 붙은 사유와 함께 회계 담당자 검토로 넘깁니다",
        ),
    ]
    #  사유 노드는 **매치되든 아니든 다음으로 흐른다**(PASS_THROUGH) — 사유가 전부 쌓인다.
    #  판정은 마지막 두 노드가 한다: 요건 충족이면 PASS, 아니면 REVIEW.
    routings = [
        *branch("n_industry_known", match_to="n_forbidden", no_match_to="n_industry_unresolved"),
        *branch("n_forbidden", match_to="n_evidence", no_match_to="n_evidence"),
        *branch("n_industry_unresolved", match_to="n_evidence", no_match_to="n_evidence"),
        *branch("n_evidence", match_to="n_purpose", no_match_to="n_purpose"),
        *branch("n_purpose", match_to="n_category", no_match_to="n_category"),
        *branch("n_category", match_to="n_actual_user", no_match_to="n_actual_user"),
        *branch("n_actual_user", match_to="n_high_amount", no_match_to="n_high_amount"),
        *branch("n_high_amount", match_to="n_autopass_gate", no_match_to="n_autopass_gate"),
        *branch("n_autopass_gate", match_to="n_auto_pass", no_match_to="_GATE_REVIEW"),
        *branch("n_auto_pass", match_to="", no_match_to="_GATE_REVIEW"),
        *branch("_GATE_REVIEW", match_to="", no_match_to=""),
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
        #  개인카드로 결제하고 회사가 나중에 정산해 주는 수단. 법인카드가 없거나 못 쓰는
        #  자리(해외·소액·긴급)에서 실제로 쓰이므로 **선택지에 있어야 한다** — 없으면
        #  사용자가 엉뚱한 카드를 골라 카드 귀속이 사실과 어긋난다.
        #  주인·팀이 없어 `/api/cards/mine/`에서 전 직원에게 보인다(회사 공용 수단).
        Card.objects.create(name="개인카드 후정산", card_type=CardType.POST_PAID, limit_amount=2_000_000)

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

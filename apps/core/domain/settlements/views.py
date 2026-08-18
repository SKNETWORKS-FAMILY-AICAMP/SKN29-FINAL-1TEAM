import logging
import re
from datetime import datetime, time

import httpx
from django.conf import settings
from django.db.models import Sum
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)

from domain.cards.models import Card
from domain.common.permissions import CanAccountingReview, CanTeamAggregate
from domain.transactions.models import Receipt, Transaction

from . import draft_agent, erp_import, services
from .models import Settlement, TeamBudget
from .serializers import SettlementDetailSerializer, SettlementSerializer

# 본인이 직접 지울 수 있는 상태 — 아직 팀·회계로 넘어가기 전 단계만.
DELETABLE_STATUSES = {"DRAFT", "TEAM_RETURNED", "TEAM_REJECTED"}


def _actor(request):
    """인증된 사용자만 actor로. (개발단계 AllowAny → 익명은 None)"""
    user = getattr(request, "user", None)
    return user if (user and user.is_authenticated) else None


class SettlementViewSet(viewsets.ModelViewSet):
    """정산 조회/보정 + 상태 액션(submit/review/confirm/judge).

    상태 전이는 services.py를 통해서만 이뤄진다(직접 PATCH로 status 변경 불가).
    프론트 client.ts의 settlements/submit/confirm/review에 대응.
    """
    queryset = Settlement.objects.select_related(
        "transaction", "transaction__card", "submitted_by"
    ).prefetch_related("events", "risk_reviews", "rule_hits__graph", "transaction__receipts")
    serializer_class = SettlementSerializer
    http_method_names = ["get", "patch", "post", "delete", "head", "options"]

    def get_serializer_class(self):
        return SettlementDetailSerializer if self.action == "retrieve" else SettlementSerializer

    def get_permissions(self):
        # 기능 단위 인가(Capability RBAC)
        if self.action in ("review", "confirm"):
            return [CanAccountingReview()]
        if self.action == "team_decision":  # 팀 취합(보완요청/반려/제출) — 기존 미보호 구멍 방어
            return [CanTeamAggregate()]
        return super().get_permissions()

    # POST /api/settlements/  (신규 지출 등록 — 거래+정산 생성)
    def create(self, request, *args, **kwargs):
        d = request.data
        raw_date = (d.get("date") or "")[:10]
        pd = parse_date(raw_date) if raw_date else None
        ts = timezone.make_aware(datetime.combine(pd, time(12, 0))) if pd else timezone.now()
        amount = int(re.sub(r"[^0-9]", "", str(d.get("amount") or "0")) or 0)
        card = Card.objects.filter(card_type=d.get("cardType")).first() if d.get("cardType") else None
        category = d.get("category") or d.get("aiCategory") or ""

        tx = Transaction.objects.create(
            card=card, merchant=d.get("merchant") or "미상 가맹점", amount=amount, ts=ts,
        )
        if d.get("evidence") == "OK":
            Receipt.objects.create(matched_tx=tx, status=Receipt.Status.MATCHED, file_ref=f"receipts/{tx.id}.jpg")
        actor = _actor(request)
        s = Settlement.objects.create(
            transaction=tx, category=category, ai_category=d.get("aiCategory") or category,
            ai_suggested=bool(d.get("aiSuggested")), merchant_industry=d.get("merchantIndustry", ""),
            purpose=d.get("purpose", ""), submitted_by=actor,
            team=getattr(actor, "team", None), status="DRAFT",
        )
        return Response(self.get_serializer(s).data, status=201)

    # DELETE /api/settlements/{id}/  — '내 지출'에서 아직 올리지 않은 건만 본인이 삭제
    def destroy(self, request, *args, **kwargs):
        settlement = self.get_object()
        if settlement.status not in DELETABLE_STATUSES:
            return Response(
                {"detail": "이미 팀·회계로 넘어간 건은 삭제할 수 없습니다. 보완요청·반려 절차를 따라주세요."},
                status=400,
            )
        actor = _actor(request)
        if actor and settlement.submitted_by_id and settlement.submitted_by_id != actor.id:
            return Response({"detail": "본인이 등록한 건만 삭제할 수 있습니다."}, status=403)
        transaction = settlement.transaction
        settlement.delete()
        # 정산이 사라진 거래는 남겨둘 이유가 없다(다른 정산이 참조 중이면 유지).
        if transaction and not transaction.settlements.exists():
            transaction.receipts.all().delete()
            transaction.delete()
        return Response(status=204)

    # POST /api/settlements/draft-suggest/  — 초안 작성 Agent
    @action(detail=False, methods=["post"], url_path="draft-suggest")
    def draft_suggest(self, request):
        """영수증·거래로 초안 생성, 또는 자연어 지시로 초안 수정.

        `instruction`이 있으면 수정 모드, 없으면 생성 모드. FastAPI Draft Agent(`/agent/draft`)를
        우선 호출하고, 미기동·타임아웃 등으로 실패하면 로컬 플레이스홀더로 폴백한다(응답 셰이프는
        두 경로가 동일하므로 화면은 어느 쪽이 응답했는지 알 필요가 없다).
        """
        data = request.data if isinstance(request.data, dict) else {}

        ai_result = self._call_draft_agent(data)
        if ai_result is not None:
            return Response(ai_result)

        if str(data.get("instruction", "")).strip():
            return Response(draft_agent.revise_draft(data))
        return Response(draft_agent.suggest_draft(data))

    @staticmethod
    def _call_draft_agent(data):
        """FastAPI `/agent/draft` 호출. 실패(미기동·타임아웃·5xx 등)하면 None을 돌려줘 폴백을 유도한다."""
        try:
            resp = httpx.post(f"{settings.AI_BASE_URL}/agent/draft", json=data, timeout=20)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("FastAPI Draft Agent 호출 실패, 로컬 폴백 사용: %s", exc)
            return None

    def get_queryset(self):
        qs = super().get_queryset()
        p = self.request.query_params
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        if p.get("category"):
            qs = qs.filter(category=p["category"])
        if p.get("card_type"):
            qs = qs.filter(transaction__card__card_type=p["card_type"])
        if p.get("submitted_by"):
            qs = qs.filter(submitted_by_id=p["submitted_by"])
        if p.get("team"):
            qs = qs.filter(team_id=p["team"])
        return qs

    # POST /api/settlements/import/  — ERP/카드사 결제기록 수집("내역 불러오기")
    @action(detail=False, methods=["post"], url_path="import")
    def import_transactions(self, request):
        """다음 회차 결제기록을 가져와 초안(DRAFT)으로 만든다.

        인증이 필요하다 — 누구 카드의 결제를 가져올지는 **요청자**로 정해지고, 개인카드 건은
        그 사람에게 바로 귀속되기 때문이다. 익명으로 열어두면 주인 없는 초안만 쌓인다.
        """
        actor = _actor(request)
        if actor is None:
            return Response({"detail": "로그인이 필요합니다."}, status=401)
        result = erp_import.import_next_batch(actor)
        return Response(result.to_dict())

    # POST /api/settlements/{id}/claim/  — 팀·공용 카드 결제의 실사용자 본인 등록
    @action(detail=True, methods=["post"])
    def claim(self, request, pk=None):
        """"내가 사용했어요" — 주인 없는 팀카드 결제를 본인에게 귀속시킨다."""
        actor = _actor(request)
        if actor is None:
            return Response({"detail": "로그인이 필요합니다."}, status=401)
        try:
            settlement = erp_import.claim(self.get_object(), actor)
        except erp_import.ClaimError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(self.get_serializer(settlement).data)

    # POST /api/settlements/raise/  {ids:[...]}  개인 '올림'(DRAFT → TEAM_COLLECTING)
    @action(detail=False, methods=["post"], url_path="raise")
    def raise_to_team(self, request):
        ids = request.data.get("ids", [])
        raised, skipped = [], []
        for s in Settlement.objects.filter(id__in=ids):
            try:
                services.raise_to_team(s, _actor(request))
                raised.append(s.id)
            except services.TransitionError:
                skipped.append(s.id)
        return Response({"raised": raised, "skipped": skipped})

    # POST /api/settlements/submit/  {ids:[...]}  팀 제출(TEAM_COLLECTING → SUBMITTED)·재제출(RETURNED → SUBMITTED)
    @action(detail=False, methods=["post"])
    def submit(self, request):
        """제출 후 곧바로 판정 결과를 상태에 반영한다 (SUBMITTED → RPA_JUDGED → …).

        상태 반영을 따로 떼어 두면 아무도 부르지 않아 정산이 SUBMITTED에 고인다 —
        상태머신상 제출의 다음 단계는 룰 판정이고, 그건 사람이 누르는 단계가 아니다.

        **엔진을 여기서 다시 돌리지는 않는다.** 판정은 팀 취합에 올라온 시점에 이미 돌았고
        (`services.raise_to_team`), 같은 사실·같은 그래프면 결과가 같다. 다시 돌리면
        `rule_hits`가 회차별로 쌓여 검토 화면이 어느 게 최신 근거인지 잃는다. 다만 회계
        보완요청 재제출(`RETURNED → SUBMITTED`)은 팀 단계를 거치지 않고 사실이 바뀐 뒤라
        옛 판정을 쓸 수 없다 — 그 경로만 재판정한다.

        판정 실패는 제출을 되돌리지 않는다. 제출은 이미 성공했고 판정은 다시 돌릴 수 있다
        (`POST /settlements/{id}/judge/`). 실패를 감추면 SUBMITTED에 고인 건이 왜 안 넘어가는지
        알 수 없으므로 `judgeFailed`로 함께 돌려준다.
        """
        ids = request.data.get("ids", [])
        actor = _actor(request)
        submitted, skipped, judged, judge_failed = [], [], {}, {}
        for s in Settlement.objects.filter(id__in=ids):
            # 전이 전에 봐야 한다 — `submit()` 뒤엔 전부 SUBMITTED라 출처를 알 수 없다.
            came_from_team = s.status == "TEAM_COLLECTING"
            try:
                services.submit(s, actor)
            except services.TransitionError:
                skipped.append(s.id)
                continue
            submitted.append(s.id)
            try:
                result = services.judge(s, actor, reuse_recorded=came_from_team)
            except Exception as exc:  # noqa: BLE001  # 조립기·엔진·DB 어느 쪽이든
                logger.warning("정산 %s 판정 실패: %s", s.id, exc, exc_info=True)
                judge_failed[str(s.id)] = f"{type(exc).__name__}: {exc}"
                continue
            judged[str(s.id)] = {"decision": result.decision, "status": s.status, "flags": result.flags}
        return Response({
            "submitted": submitted, "skipped": skipped,
            "judged": judged, "judgeFailed": judge_failed,
        })

    # POST /api/settlements/{id}/confirm/  (사람 최종 확정, FR-ST-03)
    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        s = self.get_object()
        try:
            services.confirm(s, _actor(request))
        except services.TransitionError as e:
            return Response({"detail": str(e)}, status=400)
        return Response(self.get_serializer(s).data)

    # POST /api/settlements/{id}/review/  {decision, reason}
    @action(detail=True, methods=["post"])
    def review(self, request, pk=None):
        s = self.get_object()
        try:
            services.review(s, request.data.get("decision"), _actor(request), request.data.get("reason", ""))
        except services.TransitionError as e:
            return Response({"detail": str(e)}, status=400)
        return Response(self.get_serializer(s).data)

    # POST /api/settlements/{id}/team-decision/  {decision, reason}
    @action(detail=True, methods=["post"], url_path="team-decision")
    def team_decision(self, request, pk=None):
        s = self.get_object()
        try:
            services.team_decide(
                s, request.data.get("decision"), _actor(request), request.data.get("reason", "")
            )
        except services.TransitionError as e:
            return Response({"detail": str(e)}, status=400)
        return Response(self.get_serializer(s).data)

    # POST /api/settlements/{id}/judge/  (RPA 1차판정 — 재판정·수동 실행용)
    @action(detail=True, methods=["post"])
    def judge(self, request, pk=None):
        """단건 RPA 1차판정. 제출 시 자동으로 돌지만, 판정이 실패했거나 룰 그래프를
        바꾼 뒤 다시 돌려야 할 때 쓴다. 판정 근거(`ruleResult`)를 응답에 함께 싣는다."""
        s = self.get_object()
        try:
            result = services.judge(s, _actor(request))
        except services.TransitionError as e:
            return Response({"detail": str(e)}, status=400)
        # Risk Review 호출은 `services.judge`가 소유한다(커밋 후 실행) — 여기서 따로 부르면
        # 제출 경로와 수동 판정 경로 중 한쪽만 도는 상황이 다시 생긴다.
        return Response({**self.get_serializer(s).data, "ruleResult": result.to_dict()})


class SettlementSummaryView(APIView):
    """GET /api/internal/settlement-summary/<settlement_id>/ — Risk Review 2차 검증 진입점(Django 내부 read API).

    FastAPI(ai) Risk Review Agent가 settlement_id만 갖고 tx_id·분류·가맹점·목적을 얻는 최소
    조회. 관계형 데이터는 Django 경유 원칙(CLAUDE.md §1)에 따라 Postgres를 직접 조회하지 않는다.
    """
    permission_classes = [AllowAny]

    def get(self, request, settlement_id):
        s = Settlement.objects.select_related("transaction").filter(pk=settlement_id).first()
        if s is None:
            return Response({"detail": "정산을 찾을 수 없습니다."}, status=404)
        tx = s.transaction
        return Response({
            "settlement_id": s.pk,
            "tx_id": tx.pk,
            "category": s.category or s.ai_category,
            "merchant": tx.merchant,
            "amount": int(tx.amount),
            "purpose": s.purpose,
        })


# 팀 사용액은 진행 상태와 무관하게 "이미 쓴 돈"으로 잡는다.
#  카드는 이미 결제됐으므로 제출·검토 단계가 어디든 사용액이다. 최종 반려(REJECT)만 제외한다.
_BUDGET_EXCLUDE = ["REJECT"]


class TeamBudgetView(APIView):
    """GET /api/team-budget/?team=<id>&month=YYYY-MM — 팀 예산 현황(S-02).

    한도(limit)는 TeamBudget(DB)에서, 사용액(used)은 해당 팀·월 Settlement 집계로 산출한다(실 내역 기반).
    프론트 data/mock.ts의 teamBudget 셰이프({total, used, categories:[{label,limit,used}]})와 정합.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        team_id = request.query_params.get("team")
        month = request.query_params.get("month") or ""

        budgets = TeamBudget.objects.all()
        if team_id:
            budgets = budgets.filter(team_id=team_id)
        if month:
            budgets = budgets.filter(year_month=month)

        used_qs = Settlement.objects.exclude(status__in=_BUDGET_EXCLUDE)
        if team_id:
            used_qs = used_qs.filter(team_id=team_id)
        if month and "-" in month:
            y, m = month.split("-")[:2]
            used_qs = used_qs.filter(transaction__ts__year=int(y), transaction__ts__month=int(m))
        used_by_cat = {
            r["category"]: int(r["s"] or 0)
            for r in used_qs.values("category").annotate(s=Sum("transaction__amount"))
        }

        total_limit, categories = 0, []
        for b in budgets:
            if b.category == "":
                total_limit = b.limit_amount
            else:
                categories.append({"label": b.category, "limit": b.limit_amount, "used": used_by_cat.get(b.category, 0)})

        # 예산 행이 없는 과목(또는 분류 미지정)의 지출 — 총 사용액에는 들어가지만 항목별 카드엔 없다.
        # 그대로 두면 "항목 합 ≠ 총 사용액"이 되어 대시보드가 어긋나 보이므로 따로 내려준다.
        budgeted_labels = {c["label"] for c in categories}
        unbudgeted = {k: v for k, v in used_by_cat.items() if k not in budgeted_labels and v}
        return Response({
            "team": int(team_id) if team_id else None, "month": month,
            "total": total_limit, "used": sum(used_by_cat.values()), "categories": categories,
            # {계정과목(또는 ''): 금액} — 비어 있으면 항목 합 == 총 사용액이라는 뜻.
            "unbudgeted": unbudgeted, "unbudgetedUsed": sum(unbudgeted.values()),
        })

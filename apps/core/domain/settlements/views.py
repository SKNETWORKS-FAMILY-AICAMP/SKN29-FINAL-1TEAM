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
from domain.risk.models import RiskReview
from domain.transactions.models import Receipt, Transaction

from . import draft_agent, services
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
        ids = request.data.get("ids", [])
        submitted, skipped = [], []
        for s in Settlement.objects.filter(id__in=ids):
            try:
                services.submit(s, _actor(request))
                submitted.append(s.id)
            except services.TransitionError:
                skipped.append(s.id)
        return Response({"submitted": submitted, "skipped": skipped})

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

    # POST /api/settlements/{id}/judge/  (RPA 1차판정 placeholder → IN_REVIEW)
    @action(detail=True, methods=["post"])
    def judge(self, request, pk=None):
        s = self.get_object()
        try:
            services.judge(s, _actor(request))
        except services.TransitionError as e:
            return Response({"detail": str(e)}, status=400)
        if s.status == "IN_REVIEW":
            self._run_risk_review(s)
        return Response(self.get_serializer(s).data)

    @staticmethod
    def _run_risk_review(settlement):
        """IN_REVIEW 전이 직후 Risk Review Agent(1차 이상탐지 + 2차 RAG 검증) 호출·저장.

        FastAPI는 확정 데이터를 소유하지 않는다(CLAUDE.md §1) — 응답만 반환하고, 저장은
        여기(Django)에서 한다. AI 미기동·타임아웃 등으로 실패해도 judge 자체(상태 전이)는
        이미 커밋됐으므로 조용히 넘어간다 — 검토자가 육안 검토는 계속할 수 있어야 한다.
        """
        try:
            resp = httpx.post(
                f"{settings.AI_BASE_URL}/agent/risk-review",
                json={"settlement_id": settlement.id}, timeout=60,
            )
            resp.raise_for_status()
            result = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("risk-review 호출 실패(settlement=%s): %s", settlement.id, exc)
            return

        stage1 = result.get("stage1_anomaly", {})
        stage2 = result.get("stage2_rag_review", {})
        RiskReview.objects.create(
            settlement=settlement,
            anomaly_score=stage1.get("anomaly_score", 0.0),
            reasons=stage1.get("contribs", []),
            anomaly_reasons=stage2.get("review_reasons", []),
            rag_refs=[
                {"title": c.get("quote_summary", ""), "source": f"{c.get('doc','')} {c.get('article','')}".strip(), "kind": "policy"}
                for c in stage2.get("citations", [])
            ] + [
                {"title": sc.get("relevance", ""), "source": f"사례 {sc.get('case_id','')} ({sc.get('outcome','')})", "kind": "case"}
                for sc in stage2.get("similar_cases", [])
            ],
            ai_recommendation={"APPROVE": "APPROVE", "SUPPLEMENT": "RETURN", "REJECT": "REJECT"}.get(
                stage2.get("recommendation", ""), ""
            ),
            stage2_verdict=stage2,
        )


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

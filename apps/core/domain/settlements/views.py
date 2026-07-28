import re
from datetime import datetime, time

from django.db.models import Sum
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from domain.cards.models import Card
from domain.common.permissions import IsAccountant
from domain.transactions.models import Receipt, Transaction

from . import services
from .models import Settlement, TeamBudget
from .serializers import SettlementDetailSerializer, SettlementSerializer


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
    ).prefetch_related("events", "risk_reviews")
    serializer_class = SettlementSerializer
    http_method_names = ["get", "patch", "post", "head", "options"]

    def get_serializer_class(self):
        return SettlementDetailSerializer if self.action == "retrieve" else SettlementSerializer

    def get_permissions(self):
        # 검토(승인/보완/반려)·확정은 회계 담당자만 (RBAC)
        if self.action in ("review", "confirm"):
            return [IsAccountant()]
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

    # POST /api/settlements/submit/  {ids:[...]}
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

    # POST /api/settlements/{id}/judge/  (RPA 1차판정 placeholder → IN_REVIEW)
    @action(detail=True, methods=["post"])
    def judge(self, request, pk=None):
        s = self.get_object()
        try:
            services.judge(s, _actor(request))
        except services.TransitionError as e:
            return Response({"detail": str(e)}, status=400)
        return Response(self.get_serializer(s).data)


# 반려 상태는 예산 사용액에서 제외
_BUDGET_EXCLUDE = ["REJECT", "TEAM_REJECTED"]


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
        return Response({
            "team": int(team_id) if team_id else None, "month": month,
            "total": total_limit, "used": sum(used_by_cat.values()), "categories": categories,
        })

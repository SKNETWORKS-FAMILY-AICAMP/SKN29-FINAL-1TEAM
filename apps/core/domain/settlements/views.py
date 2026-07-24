from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from . import services
from .models import Settlement
from .serializers import SettlementDetailSerializer, SettlementSerializer


def _actor(request):
    """인증된 사용자만 actor로. (개발단계 AllowAny → 익명은 None)"""
    user = getattr(request, "user", None)
    return user if (user and user.is_authenticated) else None


class SettlementViewSet(viewsets.ModelViewSet):
    """정산 조회/보정 + 상태 액션(submit/review/confirm/judge).

    상태 전이는 services.py를 통해서만 이뤄진다(직접 PATCH로 status 변경 불가).
    """
    queryset = Settlement.objects.select_related(
        "transaction", "transaction__card", "submitted_by"
    ).prefetch_related("events")
    serializer_class = SettlementSerializer
    http_method_names = ["get", "patch", "post", "head", "options"]

    def get_serializer_class(self):
        return SettlementDetailSerializer if self.action == "retrieve" else SettlementSerializer

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

    # POST /api/settlements/submit/  {ids:[...]}  (팀 취합·일괄 제출)
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

    # POST /api/settlements/{id}/review/  {decision, reason}  (승인/보완/반려)
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

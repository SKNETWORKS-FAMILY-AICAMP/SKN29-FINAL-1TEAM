from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from . import services
from .models import RuleGraph
from .serializers import RuleGraphListSerializer, RuleGraphSerializer


def _actor(request):
    user = getattr(request, "user", None)
    return user if (user and user.is_authenticated) else None


class RuleGraphViewSet(viewsets.ReadOnlyModelViewSet):
    """GET /api/rules/  (룰 그래프 목록/상세) + activate/rollback 액션.

    프론트 client.ts의 rules()/activateRule()/rollbackRule()에 대응.
    """
    queryset = RuleGraph.objects.prefetch_related("nodes", "routings", "versions")

    def get_serializer_class(self):
        return RuleGraphListSerializer if self.action == "list" else RuleGraphSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.query_params.get("status"):
            qs = qs.filter(status=self.request.query_params["status"])
        return qs

    # POST /api/rules/{id}/activate/  (승인 → ACTIVE, 자동 승인 금지)
    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        graph = self.get_object()
        services.activate(graph, _actor(request))
        return Response(RuleGraphSerializer(graph).data)

    # POST /api/rules/{id}/rollback/  (이전 승인 버전으로 복원)
    @action(detail=True, methods=["post"])
    def rollback(self, request, pk=None):
        graph = self.get_object()
        try:
            services.rollback(graph, _actor(request))
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)
        return Response(RuleGraphSerializer(graph).data)

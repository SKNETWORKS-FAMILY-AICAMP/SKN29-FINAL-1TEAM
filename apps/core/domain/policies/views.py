from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from domain.common.permissions import CanActivateRule

from . import services
from .models import RuleGraph
from .serializers import RuleGraphListSerializer, RuleGraphSerializer


def _actor(request):
    user = getattr(request, "user", None)
    return user if (user and user.is_authenticated) else None


class RuleGraphViewSet(viewsets.ReadOnlyModelViewSet):
    """GET /api/rules/ (룰 그래프 목록/상세) + activate/rollback 액션."""
    queryset = RuleGraph.objects.prefetch_related("nodes", "routings", "versions")

    def get_serializer_class(self):
        return RuleGraphListSerializer if self.action == "list" else RuleGraphSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.query_params.get("status"):
            qs = qs.filter(status=self.request.query_params["status"])
        return qs

    def get_permissions(self):
        # Rule ACTIVE 승인/롤백은 룰 활성 권한 보유자만 (Capability RBAC)
        if self.action in ("activate", "rollback", "create_version", "create_graph"):
            return [CanActivateRule()]
        return super().get_permissions()

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        graph = self.get_object()
        try:
            services.activate(graph, _actor(request))
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)
        return Response(RuleGraphSerializer(graph).data)

    @action(detail=True, methods=["post"], url_path="versions")
    def create_version(self, request, pk=None):
        draft = services.create_draft_version(self.get_object(), _actor(request))
        return Response(RuleGraphSerializer(draft).data, status=201)

    @action(detail=False, methods=["post"], url_path="drafts")
    def create_graph(self, request):
        name = str(request.data.get("name", "")).strip()
        scope = str(request.data.get("scope", "")).strip()
        if not name:
            return Response({"detail": "그래프 이름이 필요합니다."}, status=400)
        try:
            graph = services.create_graph_draft(name, scope, _actor(request))
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)
        return Response(RuleGraphSerializer(graph).data, status=201)

    @action(detail=True, methods=["post"])
    def rollback(self, request, pk=None):
        graph = self.get_object()
        try:
            graph = services.rollback(graph, _actor(request))
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)
        return Response(RuleGraphSerializer(graph).data)

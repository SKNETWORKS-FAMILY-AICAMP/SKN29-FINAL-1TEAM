from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from domain.common.permissions import CanActivateRule, CanViewRule

from . import services
from .models import RuleGraph, RuleGraphStatus, RuleNode, RuleRouting
from .serializers import RuleGraphListSerializer, RuleGraphSerializer


def _actor(request):
    user = getattr(request, "user", None)
    return user if (user and user.is_authenticated) else None


def _graph_content(graph):
    """버전/상태/UI 메타를 제외한 실행 콘텐츠 비교용 정규화."""
    ignored_action_keys = {"origin", "ai_reason", "source_clause"}

    def clean_action(action):
        return {
            key: value for key, value in (action or {}).items()
            if key not in ignored_action_keys and value not in (None, "")
            and not (key == "workflow_status" and value == "DRAFT")
        }

    return {
        "entry": graph.entry_node_key,
        "nodes": [
            (node.node_key, node.condition, clean_action(node.action), node.priority)
            for node in graph.nodes.order_by("priority", "node_key")
        ],
        "routings": [
            (route.from_node_key, route.on_result, route.to_node_key, route.priority)
            for route in graph.routings.order_by("priority", "from_node_key", "on_result")
        ],
    }


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
        if self.action in ("activate", "rollback"):
            return [CanActivateRule()]
        if self.action in ("create_version", "create_graph", "create_node", "update_node", "discard_draft", "delete_graph"):
            return [CanViewRule()]
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

    @action(detail=True, methods=["delete"], url_path="draft")
    def discard_draft(self, request, pk=None):
        graph = self.get_object()
        if graph.status != RuleGraphStatus.DRAFT:
            return Response({"detail": "DRAFT 버전만 폐기할 수 있습니다."}, status=400)
        graph.delete()
        return Response(status=204)

    @action(detail=True, methods=["delete"], url_path="delete")
    def delete_graph(self, request, pk=None):
        graph = self.get_object()
        if graph.status == RuleGraphStatus.ACTIVE:
            return Response({"detail": "ACTIVE 그래프는 삭제할 수 없습니다."}, status=400)
        graph.delete()
        return Response(status=204)

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

    @action(detail=True, methods=["post"], url_path="nodes")
    def create_node(self, request, pk=None):
        graph = self.get_object()
        if graph.status != RuleGraphStatus.DRAFT:
            return Response({"detail": "DRAFT 그래프에만 노드를 추가할 수 있습니다."}, status=400)
        node_key = str(request.data.get("nodeKey", "")).strip()
        if not node_key:
            return Response({"detail": "nodeKey가 필요합니다."}, status=400)
        node, created = RuleNode.objects.get_or_create(
            graph=graph,
            node_key=node_key,
            defaults={
                "condition": {},
                "action": {"title": "(제목 미설정)", "origin": "new", "workflow_status": "DRAFT"},
                "priority": graph.nodes.count(),
            },
        )
        if not graph.entry_node_key:
            graph.entry_node_key = node_key
            graph.save(update_fields=["entry_node_key"])
        return Response({"nodeKey": node.node_key, "created": created}, status=201 if created else 200)

    @action(detail=True, methods=["patch", "delete"], url_path=r"nodes/(?P<node_key>[^/.]+)")
    def update_node(self, request, pk=None, node_key=None):
        graph = self.get_object()
        if graph.status != RuleGraphStatus.DRAFT:
            return Response({"detail": "DRAFT 그래프만 수정할 수 있습니다."}, status=400)
        try:
            node = graph.nodes.get(node_key=node_key)
        except RuleNode.DoesNotExist:
            return Response({"detail": "노드를 찾을 수 없습니다."}, status=404)
        if request.method == "DELETE":
            graph.routings.filter(from_node_key=node_key).delete()
            graph.routings.filter(to_node_key=node_key).update(to_node_key="")
            node.delete()
            if graph.entry_node_key == node_key:
                graph.entry_node_key = graph.nodes.order_by("priority", "id").values_list("node_key", flat=True).first() or ""
                graph.save(update_fields=["entry_node_key"])
            return Response(status=204)
        if "condition" in request.data:
            node.condition = request.data["condition"]
        if "action" in request.data:
            node.action = request.data["action"]
        node.save(update_fields=["condition", "action"])
        if "routings" in request.data:
            graph.routings.filter(from_node_key=node.node_key).delete()
            RuleRouting.objects.bulk_create([
                RuleRouting(
                    graph=graph,
                    from_node_key=node.node_key,
                    on_result=route.get("onResult", "MATCH"),
                    to_node_key=route.get("toNodeKey", ""),
                    priority=index,
                )
                for index, route in enumerate(request.data["routings"])
            ])
        active = RuleGraph.objects.filter(
            family_key=graph.family_key, status=RuleGraphStatus.ACTIVE
        ).exclude(pk=graph.pk).first()
        if active and _graph_content(graph) == _graph_content(active):
            active_id = active.id
            graph.delete()
            return Response({"nodeKey": node_key, "saved": True, "revertedToGraphId": active_id})
        return Response({"nodeKey": node.node_key, "saved": True})


    @action(detail=True, methods=["post"])
    def rollback(self, request, pk=None):
        graph = self.get_object()
        try:
            graph = services.rollback(graph, _actor(request))
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)
        return Response(RuleGraphSerializer(graph).data)

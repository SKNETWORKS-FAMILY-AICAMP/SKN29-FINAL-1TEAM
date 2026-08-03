from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from domain.common.permissions import CanActivateRule, CanViewRule

from . import services, simulation
from .models import RuleAuthoringMessage, RuleGraph, RuleGraphStatus, RuleNode, RuleRouting
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
        if self.action in ("activate", "rollback", "rollback_to", "reject_activation"):
            return [CanActivateRule()]
        if self.action in ("create_version", "create_graph", "create_node", "update_node",
                           "discard_draft", "delete_graph", "simulate", "test_cases",
                           "simulation_report", "request_activation", "messages"):
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

    @action(detail=True, methods=["get", "post"], url_path="messages")
    def messages(self, request, pk=None):
        """룰 초안 작성 대화 로그 — 조회 / 추가(사용자 지시 + Agent 반영 결과)."""
        graph = self.get_object()
        if request.method == "GET":
            node_key = request.query_params.get("nodeKey")
            rows = graph.messages.all()
            if node_key:
                rows = rows.filter(node_key=node_key)
            return Response([{
                "id": row.id, "nodeKey": row.node_key, "role": row.role, "text": row.text,
                "appliedNote": row.applied_note,
                "author": getattr(row.author, "first_name", "") or getattr(row.author, "username", ""),
                "createdAt": row.created_at,
            } for row in rows])

        entries = request.data.get("messages")
        if not isinstance(entries, list) or not entries:
            return Response({"detail": "messages는 비어 있지 않은 배열이어야 합니다."}, status=400)
        node_key = str(request.data.get("nodeKey", ""))[:64]
        start = graph.messages.count()
        created = RuleAuthoringMessage.objects.bulk_create([
            RuleAuthoringMessage(
                graph=graph, node_key=node_key,
                role=RuleAuthoringMessage.Role.AI if entry.get("role") == "ai" else RuleAuthoringMessage.Role.USER,
                text=str(entry.get("text", "")), applied_note=str(entry.get("appliedNote", ""))[:200],
                author=_actor(request) if entry.get("role") != "ai" else None,
                order=start + index,
            )
            for index, entry in enumerate(entries)
        ])
        return Response({"saved": len(created)}, status=201)

    @action(detail=True, methods=["get", "put"], url_path="test-cases")
    def test_cases(self, request, pk=None):
        """그래프(버전)에 귀속된 검증셋 조회/전체 교체."""
        graph = self.get_object()
        if request.method == "GET":
            return Response(simulation.test_cases_of(graph))
        cases = request.data.get("testCases")
        if not isinstance(cases, list):
            return Response({"detail": "testCases는 배열이어야 합니다."}, status=400)
        return Response(simulation.replace_test_cases(graph, cases, _actor(request)))

    @action(detail=True, methods=["post"], url_path="simulate")
    def simulate(self, request, pk=None):
        """검증 시뮬레이션 — 검증셋 + 직전달 내역으로 판정하고 결과를 저장한 뒤 보고서를 돌려준다."""
        graph = self.get_object()
        cases = request.data.get("testCases")
        if cases is not None and not isinstance(cases, list):
            return Response({"detail": "testCases는 배열이어야 합니다."}, status=400)
        if cases is not None:
            simulation.replace_test_cases(graph, cases, _actor(request))
        run = simulation.run_and_save(graph, simulation.test_cases_of(graph), _actor(request))
        return Response(simulation.report_from_run(run))

    @action(detail=True, methods=["get"], url_path="simulation")
    def simulation_report(self, request, pk=None):
        """최신 시뮬레이션 보고서. 실행 이력이 없으면 204."""
        run = simulation.latest_run(self.get_object())
        if run is None:
            return Response(status=204)
        return Response(simulation.report_from_run(run))

    @action(detail=True, methods=["post"], url_path="request-activation")
    def request_activation(self, request, pk=None):
        """Active 요청 — 검토자 코멘트를 남기고 승인대기(SIMULATED)로 전환한다."""
        graph = self.get_object()
        comment = str(request.data.get("comment", "")).strip()
        if not comment:
            return Response({"detail": "검토자 코멘트를 입력해주세요."}, status=400)
        if simulation.latest_run(graph) is None:
            return Response({"detail": "시뮬레이션을 먼저 실행해야 Active 요청을 할 수 있습니다."}, status=400)
        try:
            services.request_activation(graph, comment, _actor(request))
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


    @action(detail=True, methods=["post"], url_path="reject-activation")
    def reject_activation(self, request, pk=None):
        """Active 요청 반려 — 사유를 남기고 초안(수정중)으로 되돌린다."""
        comment = str(request.data.get("comment", "")).strip()
        if not comment:
            return Response({"detail": "반려 사유를 입력해주세요."}, status=400)
        try:
            graph = services.reject_activation(self.get_object(), comment, _actor(request))
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)
        return Response(RuleGraphSerializer(graph).data)

    @action(detail=True, methods=["get"], url_path="family")
    def family(self, request, pk=None):
        """같은 계열(family_key)의 전체 버전 이력 — 버전 이력 모달·롤백 대상 목록."""
        graph = self.get_object()
        rows = (
            RuleGraph.objects.filter(family_key=graph.family_key)
            .prefetch_related("versions", "nodes")
            .order_by("-version")
        )
        return Response([{
            "id": str(item.pk),
            "version": item.version,
            "name": item.name,
            "scope": item.scope,
            "status": item.status,
            "statusLabel": item.get_status_display(),
            "nodeCount": item.nodes.count(),
            "activatedAt": item.activated_at,
            "activatedBy": getattr(item.approved_by, "first_name", "") or getattr(item.approved_by, "username", ""),
            "reviewedBy": getattr(item.reviewed_by, "first_name", "") or getattr(item.reviewed_by, "username", ""),
            "reviewedAt": item.reviewed_at,
            "reviewComment": item.review_comment,
            "simResult": item.sim_result or {},
            "isCurrent": item.status == RuleGraphStatus.ACTIVE,
            "canRollback": item.status != RuleGraphStatus.ACTIVE
            and item.versions.filter(approved_at__isnull=False).exists(),
        } for item in rows])

    @action(detail=True, methods=["post"], url_path="rollback-to")
    def rollback_to(self, request, pk=None):
        """이 버전으로 롤백 — 과거 승인 버전을 다시 ACTIVE로 되돌린다."""
        try:
            graph = services.rollback_to(self.get_object(), _actor(request))
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)
        return Response(RuleGraphSerializer(graph).data)

    @action(detail=True, methods=["post"])
    def rollback(self, request, pk=None):
        graph = self.get_object()
        try:
            graph = services.rollback(graph, _actor(request))
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)
        return Response(RuleGraphSerializer(graph).data)

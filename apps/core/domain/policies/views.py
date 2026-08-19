import httpx
from django.conf import settings as django_settings
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from domain.common.permissions import CanActivateRule, CanViewRule

from . import services, simulation
from .context_builder import load_tables, lookup
from .eval_context import empty_eval_context
from .models import RuleAuthoringMessage, RuleFlag, RuleGraph, RuleGraphStatus, RuleNode, RuleRouting
from .rule_agent_v0_views import action_schema_payload
from .scope import normalize_scope
from .serializers import RuleGraphListSerializer, RuleGraphSerializer


class PolicyLookupView(APIView):
    """GET /api/internal/policies/<category>/ — Draft/Rule/Risk Agent 공용 정책 조회(Django 내부 read API).

    관계형 데이터는 Django를 경유해야 한다는 원칙(CLAUDE.md §1)에 따라, FastAPI(ai)의
    get_policy 도구가 Postgres를 직접 조회하지 않고 이 API를 거친다.

    출처는 `PolicyTable`(별표)이다 — 구 `Policy` 모델(분류당 한도 1개)은 2키 별표를 담을 수
    없어 폐기했다(`_context/policy-domain.md`). **응답 계약은 그대로 유지**한다.
    """
    permission_classes = [AllowAny]

    def get(self, request, category):
        tables = load_tables()
        ctx = empty_eval_context()
        ctx["category"]["value"] = category

        limit_table = tables.get("evidence_threshold_table")
        evidence_table = tables.get("required_evidence_table")
        limit = lookup(limit_table, ctx) if limit_table else None
        evidence = lookup(evidence_table, ctx) if evidence_table else None
        refs = [t.source_clause for t in (limit_table, evidence_table) if t and t.source_clause]

        return Response({
            "category": category,
            "limit_amount": limit,
            "required_evidence": evidence if isinstance(evidence, list) else [],
            # 세무 판단은 RAG(tax_refs)에 위임한다 — 별표는 숫자만 갖는다(FR-DA-03c).
            "tax_note": "",
            "refs": refs,
        })


class RuleContextView(APIView):
    """GET /api/internal/rule-context/<settlement_id>/ — 판정용 EvalContext 조립(FR-RA-08).

    별표 룩업·ORM 조회는 전부 여기서 끝난다. FastAPI(ai)는 조립된 facts 스냅샷만 받아
    순수 엔진에 넘긴다(`run_rule_engine`). 미해소 정책값은 숨기지 않고 함께 반환한다 —
    조용한 결측이 이 도메인의 원인 결함이었다(`_context/policy-domain.md` §6).
    """
    permission_classes = [AllowAny]

    def get(self, request, settlement_id):
        from domain.settlements.models import Settlement

        from .context_builder import build_rule_context

        settlement = (
            Settlement.objects.select_related("transaction")
            .filter(pk=settlement_id).first()
        )
        if settlement is None:
            return Response({"detail": "정산을 찾을 수 없습니다."}, status=404)

        ctx, unresolved = build_rule_context(settlement=settlement)
        return Response({
            "settlement_id": settlement.pk,
            "eval_context": ctx,
            "unresolved_policy_fields": unresolved,
        })


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
            (node.node_key, node.condition, node.condition_text, clean_action(node.action), node.priority)
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
        if self.action in ("create_version", "create_graph", "generate_graph", "create_node",
                           "update_node", "discard_draft", "delete_graph", "simulate",
                           "test_cases", "simulation_report", "request_activation", "messages",
                           "converse", "generate_test_cases", "action_schema"):
            return [CanViewRule()]
        return super().get_permissions()

    @action(detail=False, methods=["get"], url_path="action-schema")
    def action_schema(self, request):
        """GET /api/rules/action-schema/ — decision/severity 선택지 카탈로그(룰 콘솔 화면용).

        `engine.py`가 유일한 소스 — AI 서비스가 쓰는 내부 API(`ActionSchemaView`)와 같은
        페이로드를 재사용한다(§8 후속, 2026-08-19). 프론트가 각자 하드코딩하던
        `<option>PASS</option>...` 목록을 여기서 받아 대체한다.
        """
        return Response(action_schema_payload())

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        graph = self.get_object()
        try:
            services.activate(graph, _actor(request))
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)
        data = RuleGraphSerializer(graph).data
        # 레지스트리에 없는 플래그 — 활성화를 막지는 않되(고객 어휘일 수 있다) 승인자에게
        # 알린다. 조용히 넘기면 오타가 그대로 화면·집계에 남는다.
        data["unknownFlags"] = getattr(graph, "unknown_flags", [])
        return Response(data)

    # GET /api/rules/flags/  — 네임드 플래그 레지스트리(룰 편집 선택지·화면 라벨)
    @action(detail=False, methods=["get"], url_path="flags")
    def flag_registry(self, request):
        """플래그 표기·분류의 단일 원천. 프론트가 라벨 사전을 따로 들고 있으면 곧 어긋난다.

        `system=1`이면 엔진 전용 플래그도 포함한다(기본 제외) — 룰 편집 드롭다운에
        `NO_ACTIVE_RULE_GRAPH`가 뜨면 룰이 그걸 스스로 붙일 수 있게 되어 의미가 뒤집힌다.
        """
        rows = RuleFlag.objects.filter(is_active=True)
        if request.query_params.get("system") not in ("1", "true"):
            rows = rows.filter(is_system=False)
        return Response([
            {
                "code": r.code, "label": r.label, "description": r.description,
                "category": r.category, "severity": r.severity, "owner": r.owner,
                "isSystem": r.is_system,
            }
            for r in rows
        ])

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
        """검증 시뮬레이션 — 검증셋 + 직전달 내역으로 판정하고 결과를 저장한 뒤 보고서를 돌려준다.

        판정·통계는 여기서 이미 실데이터로 저장된다. 그 위에 얹는 **서술문 + 권장 처리 재판단**만
        Rule Agent에게 맡긴다 — `generate_graph`/`converse`와 같은 얇은 프록시 원칙(인가·전달만).
        LLM 호출이 실패해도 시뮬레이션 자체는 실패로 보지 않는다 — `run_and_save()`가 이미 만든
        룰 기반 템플릿 서술(`placeholder=True`)과 결정론적 action 등급을 그대로 반환한다.

        `narrate=false`를 보내면 서술 생성 자체를 건너뛴다 — 검증셋 자동생성(`testcases.py`)의
        **자체검증 루프**가 노드마다 이 액션을 최대 2회 내부 호출하는데, 그 결과는 아무도 읽지
        않는데도 심층 모델(`narrate-report`, 추론 모델이라 느림) 호출을 매번 태워 전체가
        타임아웃 나던 문제(2026-08-18 실사용 발견)를 해결한다. 사용자가 직접 누르는 "실행"·
        검증셋 생성의 **최종** 보고서는 여전히 서술을 만든다.
        """
        graph = self.get_object()
        cases = request.data.get("testCases")
        if cases is not None and not isinstance(cases, list):
            return Response({"detail": "testCases는 배열이어야 합니다."}, status=400)
        if cases is not None:
            simulation.replace_test_cases(graph, cases, _actor(request))
        run = simulation.run_and_save(graph, simulation.test_cases_of(graph), _actor(request))
        if request.data.get("narrate", True):
            narrate_url = f"{django_settings.AI_BASE_URL}/agent/rule-v0/narrate-report"
            try:
                resp = httpx.post(
                    narrate_url, json={"facts": simulation.narrative_facts_for_run(run)},
                    timeout=httpx.Timeout(60.0, connect=5.0),
                )
                if resp.status_code == 200:
                    data = resp.json()
                    narrative = str(data.get("report") or "").strip()
                    if narrative:
                        simulation.apply_narrative(run, narrative)
                    simulation.apply_action_assessment(run, data.get("action"))
            except Exception:  # noqa: BLE001  # 서술 생성 실패는 시뮬레이션 실패가 아니다 — 템플릿 폴백 유지
                pass
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

    @action(detail=False, methods=["post"], url_path="generate")
    def generate_graph(self, request):
        """POST /api/rules/generate/ — 규정 문서(RAG)에서 룰 그래프 DRAFT를 생성한다.

        FastAPI는 내부 전용이라(CLAUDE.md §1) 브라우저가 직접 부르지 않는다. 여기서 하는
        일은 **인가(`rule_view`)와 전달뿐**이고, 실제 저장은 FastAPI가 서비스 계정 JWT로
        이 ViewSet의 `drafts`/`nodes` 액션을 다시 부르면서 일어난다 — 즉 사람이 만들든
        Agent가 만들든 **같은 서비스 레이어·같은 감사로그**를 탄다.

        실패는 감추지 않는다(AI-LAB 프록시와 같은 원칙): 연결 실패는 503, 나머지는
        FastAPI 상태코드·본문 그대로. 룰 생성이 왜 안 됐는지가 화면에 그대로 보여야 한다.
        """
        url = f"{django_settings.AI_BASE_URL}/agent/rule-v0/generate"
        try:
            # LLM + 임베딩 + Django 재호출이 직렬로 얹힌다 — 일반 API보다 넉넉히.
            # v1: 검증→재생성 루프(agent-v1-upgrade-plan.md §1.2-4)가 최대 3회 시도를
            # 직렬로 돌 수 있어(각 시도 = LLM 호출 + 저장 API 왕복 + /simulate) 1회 기준
            # 120초로는 부족할 수 있다.
            resp = httpx.post(url, json=request.data, timeout=httpx.Timeout(300.0, connect=5.0))
        except Exception as exc:  # noqa: BLE001
            return Response(
                {"detail": f"AI 서비스({django_settings.AI_BASE_URL})에 연결하지 못했습니다 — "
                           f"{type(exc).__name__}: {exc}"},
                status=503,
            )
        try:
            payload = resp.json()
        except ValueError:
            payload = {"detail": resp.text[:2000]}
        return Response(payload, status=resp.status_code)

    @action(detail=True, methods=["post"], url_path="converse")
    def converse(self, request, pk=None):
        """POST /api/rules/{id}/converse/ — 대화형 자연어 수정(§1.2-5).

        `generate_graph`와 같은 얇은 프록시 원칙: 인가·전달만 하고, 실제 그래프 수정은
        FastAPI가 서비스 계정 JWT로 이 ViewSet의 `nodes` 액션들을 다시 부르며 일어난다.

        **대화 로그는 Agent가 직접 남긴다**(`django_client.post_messages`) — 화면은 응답으로
        로그를 다시 저장하지 말고 `messages`를 다시 읽어야 한다. 양쪽에서 저장하면 같은
        대화가 두 번 쌓인다.
        """
        message = str(request.data.get("message", "")).strip()
        if not message:
            return Response({"detail": "message가 필요합니다."}, status=400)
        # 화면에서 지금 선택 중인 노드 — 모호한 지시("금액 30만원으로 바꿔줘")가 엉뚱한
        # 노드에 적용되는 걸 막는 힌트(2026-08-18). 안 보내도 동작은 한다.
        node_key = str(request.data.get("nodeKey", "")).strip() or None
        graph = self.get_object()
        if graph.status != RuleGraphStatus.DRAFT:
            # ACTIVE를 대화로 직접 고치면 시뮬레이션·승인 절차를 통째로 우회하게 된다.
            # 노드 CRUD 액션도 DRAFT만 허용하므로, 여기서 막지 않으면 Agent가 툴을 부르다
            # 400을 받고 "왜 안 됐는지 모르는" 응답이 화면에 뜬다.
            return Response({"detail": "DRAFT 그래프만 대화로 수정할 수 있습니다."}, status=400)
        url = f"{django_settings.AI_BASE_URL}/agent/rule-v0/converse"
        try:
            # LLM 툴콜링 여러 턴 + Django 재호출 왕복 — generate와 비슷하게 넉넉히.
            resp = httpx.post(
                url, json={"graph_id": str(graph.pk), "message": message, "node_key": node_key},
                timeout=httpx.Timeout(180.0, connect=5.0),
            )
        except Exception as exc:  # noqa: BLE001
            return Response(
                {"detail": f"AI 서비스({django_settings.AI_BASE_URL})에 연결하지 못했습니다 — "
                           f"{type(exc).__name__}: {exc}"},
                status=503,
            )
        try:
            payload = resp.json()
        except ValueError:
            payload = {"detail": resp.text[:2000]}
        return Response(payload, status=resp.status_code)

    @action(detail=True, methods=["post"], url_path="test-cases/generate")
    def generate_test_cases(self, request, pk=None):
        """POST /api/rules/{id}/test-cases/generate/ — 검증셋 자동생성(agent-v1-upgrade-plan.md §4).

        대화형이 아니다 — 한 번 호출로 완제품 검증셋을 만들어 기존 것에 추가(append)한다.
        `converse`와 같은 얇은 프록시 원칙: 인가·전달만, 실제 역산·자체검증·저장은
        FastAPI(`testcases.generate_test_cases`)가 이 ViewSet의 `test-cases`/`simulate`
        액션을 서비스 계정으로 다시 부르며 수행한다.
        """
        graph = self.get_object()
        if graph.status != RuleGraphStatus.DRAFT:
            return Response({"detail": "DRAFT 그래프만 검증셋을 자동생성할 수 있습니다."}, status=400)
        url = f"{django_settings.AI_BASE_URL}/agent/rule-v0/test-cases/generate"
        try:
            # 노드마다 조건 역산 + 자체검증(최대 2회 simulate 왕복)이 순차로 도니 여유 있게.
            resp = httpx.post(
                url, json={"graph_id": str(graph.pk)},
                timeout=httpx.Timeout(180.0, connect=5.0),
            )
        except Exception as exc:  # noqa: BLE001
            return Response(
                {"detail": f"AI 서비스({django_settings.AI_BASE_URL})에 연결하지 못했습니다 — "
                           f"{type(exc).__name__}: {exc}"},
                status=503,
            )
        try:
            payload = resp.json()
        except ValueError:
            payload = {"detail": resp.text[:2000]}
        return Response(payload, status=resp.status_code)

    @action(detail=False, methods=["post"], url_path="drafts")
    def create_graph(self, request):
        name = str(request.data.get("name", "")).strip()
        # 규정 문서 표기(기업업무추진비·회식 등)를 Category 값으로 접는다 — Rule Agent가
        # 조문에서 뽑은 과목명을 그대로 보내도 400으로 튕기지 않게 한다(scope.py가 SoT).
        scope = normalize_scope(str(request.data.get("scope", "")).strip())
        if not name:
            return Response({"detail": "그래프 이름이 필요합니다."}, status=400)
        try:
            graph = services.create_graph_draft(
                name, scope, _actor(request),
                generation_meta=request.data.get("generationMeta") or {},
            )
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
                "condition_text": "",
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
        # conditionText는 Rule Agent가 조건과 함께 갱신하는 설명 문장이다(사람이 직접 쓰지 않는다).
        if "conditionText" in request.data:
            node.condition_text = str(request.data["conditionText"] or "")
        if "action" in request.data:
            node.action = request.data["action"]
        node.save(update_fields=["condition", "condition_text", "action"])
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

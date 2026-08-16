"""규정 문서(RAG 소스) 업로드·적재 API.

    업로드 ─► PolicyDoc(PENDING) 생성 ─► FastAPI /embeddings/ingest 호출(즉시 반환)
                                          └─ 백그라운드: 파싱→교정→청킹→임베딩→Chroma upsert
                                             └─ 완료/실패 시 아래 IngestCallbackView로 결과 회신
    화면은 `GET /api/policy-docs/`를 폴링해 status가 DONE/FAILED가 될 때까지 지켜본다.

**왜 동기가 아닌가**: docling 파싱은 모델을 올리고 문서당 수십 초~분이 걸린다. HTTP 요청
안에서 끝내려 하면 브라우저가 먼저 끊긴다. **왜 큐가 아닌가**: 브로커·워커 컨테이너를
새로 들이는 비용이, 관리자가 가끔 규정 몇 종을 올리는 실제 부하에 비해 크다
(기술명세서 §6.2 "동기 REST, 별도 Job 큐 없음"). 대신 진행 상태를 DB에 두어 화면이
언제든 실제 상태를 알 수 있게 했다.

**한계(알고 쓰는 것)**: 적재 도중 ai 컨테이너가 재시작되면 그 작업은 사라진다. 그 건은
`PARSING`/`INDEXING`에 멈춰 있게 되고, 사람이 "재색인"을 누르면 복구된다 — 관리자 온디맨드
배치라는 전제와 일관된 회복 경로다.
"""
from __future__ import annotations

import logging

import httpx
from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import status as http
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from domain.common.permissions import CanViewRule

from .models import (
    ClauseDecision, IngestStatus, PolicyClause, PolicyDoc, PolicyFolder, RuleNode,
)
from .scope import normalize_scope
from .serializers import PolicyDocSerializer

logger = logging.getLogger(__name__)

# 적재 요청은 "접수"만 확인하면 된다 — 실제 작업은 ai가 백그라운드로 돌린다.
_DISPATCH_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
ALLOWED_SUFFIXES = (".pdf",)


def _folder_doc(doc: PolicyDoc) -> dict:
    """폴더 트리에 실리는 문서 요약 — 목록에 필요한 최소치만."""
    return {
        "id": doc.pk,
        "title": doc.title,
        "status": doc.status,
        # 확인이 필요한 조항 수 — 트리의 "확인 3" 배지.
        "reviewCount": getattr(doc, "review_count", 0),
        # 구판이면 "이전 버전" 배지. 지우지 않는 이유는 과거 판정이 인용한 조항 보존.
        "superseded": doc.superseded_by_id is not None,
    }


def _clause_row(clause: PolicyClause, links: list[dict]) -> dict:
    return {
        "id": clause.pk,
        "articleLabel": clause.article_label,
        "articleTitle": clause.article_title,
        "citation": clause.citation,
        "body": clause.body,
        "pageStart": clause.page_start,
        "pageEnd": clause.page_end,
        # LINKED / SKIPPED / NEEDS_REVIEW — 저장하지 않고 계산한 값이다.
        "ruleStatus": clause.rule_status(len(links)),
        "linkedRules": links,
        "decision": clause.decision,
        "decisionReason": clause.decision_reason,
        "decidedBy": getattr(clause.decided_by, "first_name", "") or getattr(clause.decided_by, "username", ""),
        "decidedAt": clause.decided_at,
    }


def _dispatch(doc: PolicyDoc) -> str:
    """ai에 적재를 요청한다. 실패 사유를 문자열로 돌려준다(성공이면 빈 문자열).

    여기서 예외를 올리지 않는 이유: 업로드 자체는 이미 성공했다. ai가 안 떠 있다고 파일을
    되돌리면 사용자는 올린 걸 또 올려야 한다. 대신 문서를 FAILED로 두어 재색인을 유도한다.
    """
    try:
        resp = httpx.post(
            f"{settings.AI_BASE_URL}/embeddings/ingest",
            json={
                "policyDocId": doc.pk,
                "filePath": doc.file.name,      # media 볼륨 기준 상대경로 (ai가 :ro로 마운트)
                "name": doc.title,
                "ruleScope": doc.rule_scope,
            },
            timeout=_DISPATCH_TIMEOUT,
        )
        resp.raise_for_status()
        return ""
    except Exception as exc:  # noqa: BLE001
        logger.warning("적재 요청 실패 doc=%s: %s", doc.pk, exc)
        return f"AI 서비스({settings.AI_BASE_URL}) 호출 실패 — {type(exc).__name__}: {exc}"


def _start(doc: PolicyDoc) -> PolicyDoc:
    """적재를 시작 상태로 돌리고 요청을 보낸다. 재색인도 같은 경로를 탄다."""
    doc.status = IngestStatus.PENDING
    doc.error = ""
    doc.rule_trigger = {}
    doc.save(update_fields=["status", "error", "rule_trigger", "updated_at"])

    failure = _dispatch(doc)
    if failure:
        doc.status = IngestStatus.FAILED
        doc.error = failure
        doc.save(update_fields=["status", "error", "updated_at"])
    return doc


class PolicyDocViewSet(viewsets.ModelViewSet):
    """GET/POST /api/policy-docs/ · POST /api/policy-docs/{id}/reembed/ · DELETE

    인가는 `rule_view`다 — 규정 문서는 룰의 원천이고, 적재는 임베딩 비용을 쓰면서
    모든 판정이 인용하는 코퍼스를 바꾼다. 조회까지 같은 권한으로 묶는다.
    """
    queryset = PolicyDoc.objects.select_related("uploaded_by")
    serializer_class = PolicyDocSerializer
    permission_classes = [CanViewRule]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    http_method_names = ["get", "post", "delete", "head", "options"]

    def create(self, request, *args, **kwargs):
        upload = request.FILES.get("file")
        if upload is None:
            return Response({"detail": "파일이 필요합니다."}, status=http.HTTP_400_BAD_REQUEST)
        if not upload.name.lower().endswith(ALLOWED_SUFFIXES):
            # 파싱 파이프라인이 PDF 전용이다. 다른 확장자를 받아 두면 적재가 조용히 실패한다.
            return Response(
                {"detail": f"지원하지 않는 형식입니다: {upload.name} (PDF만 가능)"},
                status=http.HTTP_400_BAD_REQUEST,
            )

        doc = PolicyDoc.objects.create(
            title=(request.data.get("title") or upload.name).strip()[:200],
            category=str(request.data.get("category") or "")[:20],
            version=str(request.data.get("version") or "")[:20],
            # 규정 표기(기업업무추진비·회식)를 보내도 Category 값으로 접힌다.
            rule_scope=normalize_scope(str(request.data.get("ruleScope") or "").strip())
            if request.data.get("ruleScope") else "",
            file=upload,
            file_size=upload.size or 0,
            folder=PolicyFolder.objects.filter(pk=request.data.get("folderId")).first()
            if request.data.get("folderId") else None,
            uploaded_by=request.user if request.user.is_authenticated else None,
        )
        _start(doc)
        return Response(self.get_serializer(doc).data, status=http.HTTP_201_CREATED)

    @action(detail=False, methods=["get", "post"])
    def folders(self, request):
        """GET: 폴더 트리 + 각 폴더의 문서 / POST: 폴더 생성 `{name, parentId}`.

        폴더는 검색에 아무 영향이 없다 — 사람이 문서를 찾기 위한 분류다. 미분류 문서는
        트리 밖에 따로 담아 돌려준다(폴더에 안 넣었다고 안 보이면 문서를 잃어버린다).
        """
        if request.method == "POST":
            name = str(request.data.get("name", "")).strip()
            if not name:
                return Response({"detail": "폴더 이름이 필요합니다."}, status=http.HTTP_400_BAD_REQUEST)
            parent = PolicyFolder.objects.filter(pk=request.data.get("parentId")).first()
            folder, created = PolicyFolder.objects.get_or_create(name=name[:80], parent=parent)
            return Response({"id": folder.pk, "name": folder.name, "created": created},
                            status=http.HTTP_201_CREATED if created else http.HTTP_200_OK)

        docs = list(
            PolicyDoc.objects.select_related("folder")
            .annotate(review_count=Count("clauses", filter=Q(clauses__decision="")))
        )
        by_folder: dict[int | None, list] = {}
        for doc in docs:
            by_folder.setdefault(doc.folder_id, []).append(doc)

        def node(folder: PolicyFolder) -> dict:
            children = [node(child) for child in folder.children.all()]
            own = [_folder_doc(d) for d in by_folder.get(folder.pk, [])]
            return {
                "id": folder.pk, "name": folder.name,
                "children": children, "documents": own,
                # 하위 전체 문서 수 — 화면의 "(12개)" 배지.
                "docCount": len(own) + sum(c["docCount"] for c in children),
            }

        roots = PolicyFolder.objects.filter(parent__isnull=True).prefetch_related("children")
        return Response({
            "folders": [node(f) for f in roots],
            "unfiled": [_folder_doc(d) for d in by_folder.get(None, [])],
            "totalDocs": len(docs),
            "totalFolders": PolicyFolder.objects.count(),
        })

    @action(detail=True, methods=["get"])
    def clauses(self, request, pk=None):
        """문서의 조 단위 조항 + 룰 연결 상태.

        연결 상태는 **저장하지 않고 계산한다** — 룰은 나중에 생기고 지워지므로 컬럼에
        굳히면 곧 실제와 어긋난다. 링크는 `RuleNode.action.source_clause` 일치로 찾는다.
        """
        doc = self.get_object()
        rows = list(doc.clauses.all())
        # N+1 방지: 이 문서의 인용 전체를 한 번에 조회해 조항별로 나눈다.
        citations = [c.citation for c in rows if c.citation]
        links: dict[str, list[dict]] = {}
        if citations:
            for node_row in (
                RuleNode.objects.filter(action__source_clause__in=citations)
                .select_related("graph")
            ):
                links.setdefault(node_row.action.get("source_clause", ""), []).append({
                    "graphId": str(node_row.graph_id),
                    "graphName": node_row.graph.name,
                    "graphStatus": node_row.graph.status,
                    "nodeKey": node_row.node_key,
                    "title": (node_row.action or {}).get("title", ""),
                    "conditionText": node_row.condition_text,
                    "decision": (node_row.action or {}).get("decision", ""),
                })
        return Response([_clause_row(c, links.get(c.citation, [])) for c in rows])

    @action(detail=True, methods=["post"], url_path=r"clauses/(?P<clause_id>\d+)/decision")
    def clause_decision(self, request, pk=None, clause_id=None):
        """조항 결정 — `{decision: "SKIP"|"RESET", reason}`.

        `SKIP`(규칙 생성 안 함)은 **사유가 필수**다. 나중에 "왜 이 조항엔 규칙이 없지"를
        묻는 사람이 반드시 나오고, 그때 답이 없으면 같은 검토를 처음부터 다시 한다.
        `RESET`은 결정을 되돌려 다시 '확인 필요'로 만든다.
        """
        clause = PolicyClause.objects.filter(doc_id=pk, pk=clause_id).first()
        if clause is None:
            return Response({"detail": "조항을 찾을 수 없습니다."}, status=http.HTTP_404_NOT_FOUND)

        decision = str(request.data.get("decision", "")).upper()
        if decision == "RESET":
            clause.decision, clause.decision_reason = "", ""
            clause.decided_by, clause.decided_at = None, None
        elif decision == "SKIP":
            reason = str(request.data.get("reason", "")).strip()
            if not reason:
                return Response({"detail": "규칙을 만들지 않는 이유를 입력해주세요."},
                                status=http.HTTP_400_BAD_REQUEST)
            clause.decision = ClauseDecision.SKIP
            clause.decision_reason = reason
            clause.decided_by = request.user if request.user.is_authenticated else None
            clause.decided_at = timezone.now()
        else:
            return Response({"detail": f"알 수 없는 결정: {decision}"}, status=http.HTTP_400_BAD_REQUEST)

        clause.save()
        return Response(_clause_row(clause, [
            {"graphId": str(n.graph_id), "graphName": n.graph.name, "graphStatus": n.graph.status,
             "nodeKey": n.node_key, "title": (n.action or {}).get("title", ""),
             "conditionText": n.condition_text, "decision": (n.action or {}).get("decision", "")}
            for n in clause.linked_nodes()
        ]))

    @action(detail=True, methods=["post"], url_path="move")
    def move(self, request, pk=None):
        """문서를 폴더로 옮긴다. `folderId`가 null이면 미분류로."""
        doc = self.get_object()
        folder_id = request.data.get("folderId")
        doc.folder = PolicyFolder.objects.filter(pk=folder_id).first() if folder_id else None
        doc.save(update_fields=["folder", "updated_at"])
        return Response(self.get_serializer(doc).data)

    @action(detail=True, methods=["post"])
    def reembed(self, request, pk=None):
        """재색인 — 실패했거나, 청킹·임베딩 전략이 바뀌어 다시 넣어야 할 때.

        `doc_id`가 파일 내용 해시라 같은 파일이면 Chroma에서 같은 ID로 덮어쓴다(멱등).
        """
        doc = self.get_object()
        if not doc.file:
            return Response({"detail": "원본 파일이 없어 재색인할 수 없습니다."},
                            status=http.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(_start(doc)).data)


class IngestCallbackView(APIView):
    """POST /api/internal/policy-docs/{id}/ingest-result/ — ai가 적재 결과를 회신한다.

    **인증한다.** 다른 내부 read API(`PolicyLookupView` 등)는 AllowAny지만 이건 **쓰기**다.
    누구나 부를 수 있는 쓰기 경로를 열면 적재 상태를 외부에서 조작할 수 있다. ai는 룰
    에이전트와 같은 서비스 계정 JWT(capability `rule_view`)로 호출한다.
    """
    permission_classes = [CanViewRule]

    def post(self, request, pk):
        doc = PolicyDoc.objects.filter(pk=pk).first()
        if doc is None:
            return Response({"detail": "문서를 찾을 수 없습니다."}, status=http.HTTP_404_NOT_FOUND)

        state = str(request.data.get("status") or "")
        if state not in IngestStatus.values:
            return Response({"detail": f"알 수 없는 상태: {state}"},
                            status=http.HTTP_400_BAD_REQUEST)

        doc.status = state
        doc.error = str(request.data.get("error") or "")[:2000]
        for field, key in (
            ("doc_id", "docId"), ("profile", "profile"), ("collection", "collection"),
        ):
            setattr(doc, field, str(request.data.get(key) or "")[:32])
        doc.chunk_count = int(request.data.get("chunkCount") or 0)
        doc.leaf_count = int(request.data.get("leafCount") or 0)
        doc.rule_trigger = request.data.get("ruleTrigger") or {}
        if state == IngestStatus.DONE:
            doc.indexed_at = timezone.now()
        doc.save()

        if state == IngestStatus.DONE:
            _replace_clauses(doc, request.data.get("clauses") or [])
        return Response({"ok": True, "status": doc.status, "clauses": doc.clauses.count()})


@transaction.atomic
def _replace_clauses(doc: PolicyDoc, rows: list[dict]) -> None:
    """조항을 새 적재 결과로 교체하되 **사람의 결정은 지키고 이어붙인다**.

    재색인은 흔한 일이다(청킹 전략 변경·파싱 개선). 그때마다 "이 조항은 규칙으로 만들지
    않겠다"는 판단이 날아가면 담당자가 같은 결정을 반복해야 한다. 조 라벨이 같으면
    같은 조항으로 보고 결정을 옮긴다 — 본문이 바뀌었어도 조 번호는 개정 전후로 유지되는
    것이 규정 문서의 관례다.
    """
    kept = {
        c.article_label: (c.decision, c.decision_reason, c.decided_by_id, c.decided_at)
        for c in doc.clauses.exclude(decision="")
    }
    doc.clauses.all().delete()
    PolicyClause.objects.bulk_create([
        PolicyClause(
            doc=doc,
            order=int(row.get("order") or index),
            article_no=row.get("articleNo"),
            article_label=str(row.get("articleLabel") or "")[:32],
            article_title=str(row.get("articleTitle") or "")[:200],
            citation=str(row.get("citation") or "")[:300],
            body=str(row.get("body") or ""),
            page_start=int(row.get("pageStart") or 0),
            page_end=int(row.get("pageEnd") or 0),
            chunk_ids=row.get("chunkIds") or [],
            decision=kept.get(str(row.get("articleLabel") or ""), ("", "", None, None))[0],
            decision_reason=kept.get(str(row.get("articleLabel") or ""), ("", "", None, None))[1],
            decided_by_id=kept.get(str(row.get("articleLabel") or ""), ("", "", None, None))[2],
            decided_at=kept.get(str(row.get("articleLabel") or ""), ("", "", None, None))[3],
        )
        for index, row in enumerate(rows)
        if row.get("articleLabel")
    ])

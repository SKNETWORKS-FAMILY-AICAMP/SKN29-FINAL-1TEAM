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
from django.http import FileResponse
from django.utils import timezone
from rest_framework import status as http
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from domain.common.permissions import CanViewRule

from domain.risk.models import DecisionCase

from . import table_proposals
from .models import (
    DOC_PROFILE_CHOICES, ClauseDecision, ClauseKind, ClausePriority, IngestStatus,
    PolicyClause, PolicyDoc, PolicyFolder, PolicyTableProposal, RuleNode,
    TableProposalStatus,
)
from domain.notifications import events as notification_events

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


def _proposal_row(p: PolicyTableProposal) -> dict:
    """별표 후보 1행. **표 원문(`rawMarkdown`)을 함께 내린다** — 승인하는 사람이 대조할
    근거가 없으면 AI가 적어준 값을 그대로 누르게 되고, 그러면 승인 단계가 형식이 된다."""
    return {
        "id": p.pk,
        "sourceLabel": p.source_label,
        "citation": p.citation,
        "pageStart": p.page_start,
        "pageEnd": p.page_end,
        "rawMarkdown": p.raw_markdown,
        "key": p.key,
        "title": p.title,
        "keyAxes": p.key_axes,
        "payload": p.payload,
        "strictKeys": p.strict_keys,
        "effectiveDate": p.effective_date,
        "confidence": round(p.confidence, 2),
        "notes": p.notes,
        "comment": p.comment,
        "usageNote": p.usage_note,
        "checks": p.checks or [],
        "skipReason": p.skip_reason,
        "status": p.status,
        "reviewNote": p.review_note,
        "reviewedBy": getattr(p.reviewed_by, "first_name", "") or getattr(p.reviewed_by, "username", ""),
        "reviewedAt": p.reviewed_at,
        "approvedTableId": p.approved_table_id,
        # 지금 승인하면 걸릴 문제들 — 누르기 **전에** 보여준다.
        "problems": table_proposals.validate(p) if p.status == TableProposalStatus.PENDING else [],
        # 승인 시 생길 판정 변수(`ctx.policy.<이름>`). 무엇이 늘어나는지 알고 누르게 한다.
        "policyVar": f"policy.{p.key.strip().removesuffix('_table')}" if p.key.strip() else "",
    }


def _apply_proposal_patch(proposal: PolicyTableProposal, data) -> None:
    """사람이 고친 값을 제안에 반영한다 — 수정 저장과 승인이 **같은 함수**를 쓴다.

    둘이 갈라져 있으면 "고친 값으로 승인"과 "저장된 값으로 승인"이 생기고, 화면은 전자를
    보여주는데 서버는 후자를 검사한다. 온 키만 건드린다(빠진 키는 지우는 게 아니다).
    """
    fields = []
    for field, key in (("key", "key"), ("title", "title")):
        if key in data:
            setattr(proposal, field, str(data.get(key) or "").strip())
            fields.append(field)
    if "keyAxes" in data:
        axes = data.get("keyAxes") or []
        proposal.key_axes = [str(a).strip() for a in axes if str(a).strip()]
        fields.append("key_axes")
    if "payload" in data:
        proposal.payload = data.get("payload") or {}
        fields.append("payload")
    if "strictKeys" in data:
        proposal.strict_keys = bool(data.get("strictKeys"))
        fields.append("strict_keys")
    if "effectiveDate" in data:
        proposal.effective_date = data.get("effectiveDate") or None
        fields.append("effective_date")
    if fields:
        proposal.save(update_fields=[*fields, "updated_at"])


def _axis_options() -> list[dict]:
    """축으로 쓸 수 있는 **사실 경로**. `policy.*`와 감사 섹션은 뺀다.

    `policy.*`는 그 자체가 별표에서 나온 값이라 다른 별표의 축이 될 수 없고, `tables`·
    `conflicts`·`meta`는 감사용이라 룰도 별표도 참조하지 않는다.
    """
    from .eval_context import schema_catalog

    skip = {"policy", "tables", "conflicts", "meta"}
    return [
        {"path": f["path"], "type": f["type"], "desc": f["desc"], "section": sec["title"]}
        for sec in schema_catalog()["sections"] if sec["section"] not in skip
        for f in sec["fields"]
    ]


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
        # AI 분류(제안). 사람의 결정(`decision`)과 **다른 축**이라 따로 내보낸다 —
        # 한 필드로 합치면 화면이 "AI가 제외로 봤다"와 "사람이 제외로 정했다"를 못 가른다.
        "triageKind": clause.triage_kind,
        "triagePriority": clause.triage_priority,
        "triageReason": clause.triage_reason,
        "triageSummary": clause.triage_summary,
        "linkedRules": links,
        "decision": clause.decision,
        "decisionReason": clause.decision_reason,
        "decidedBy": getattr(clause.decided_by, "first_name", "") or getattr(clause.decided_by, "username", ""),
        "decidedAt": clause.decided_at,
    }


def _dispatch(doc: PolicyDoc, *, is_reindex: bool) -> str:
    """ai에 적재를 요청한다. 실패 사유를 문자열로 돌려준다(성공이면 빈 문자열).

    여기서 예외를 올리지 않는 이유: 업로드 자체는 이미 성공했다. ai가 안 떠 있다고 파일을
    되돌리면 사용자는 올린 걸 또 올려야 한다. 대신 문서를 FAILED로 두어 재색인을 유도한다.

    `is_reindex`: 룰 자동생성 트리거(§1.2-2) 켤 때 필요해진 구분 — 최초 적재에서만 자동
    생성하고 재색인에서는 안 한다(재색인마다 새 계열이 쌓이는 걸 막기 위함, 기존 계열에
    버전을 얹는 경로가 아직 없어서). ai 쪽 `rule_trigger.trigger()`가 이 값으로 분기한다.
    """
    try:
        resp = httpx.post(
            f"{settings.AI_BASE_URL}/embeddings/ingest",
            json={
                "policyDocId": doc.pk,
                "filePath": doc.file.name,      # media 볼륨 기준 상대경로 (ai가 :ro로 마운트)
                "name": doc.title,
                "ruleScope": doc.rule_scope,
                "isReindex": is_reindex,
                # 비면 파서 자동 감지. 지정하면 컬렉션 라우팅이 그 값으로 결정된다.
                "profileHint": doc.profile_hint,
            },
            timeout=_DISPATCH_TIMEOUT,
        )
        resp.raise_for_status()
        return ""
    except Exception as exc:  # noqa: BLE001
        logger.warning("적재 요청 실패 doc=%s: %s", doc.pk, exc)
        return f"AI 서비스({settings.AI_BASE_URL}) 호출 실패 — {type(exc).__name__}: {exc}"


def _start(doc: PolicyDoc, *, is_reindex: bool) -> PolicyDoc:
    """적재를 시작 상태로 돌리고 요청을 보낸다."""
    doc.status = IngestStatus.PENDING
    doc.error = ""
    doc.rule_trigger = {}
    doc.save(update_fields=["status", "error", "rule_trigger", "updated_at"])

    failure = _dispatch(doc, is_reindex=is_reindex)
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
        # 확장자는 이름일 뿐이라 얼마든지 속일 수 있다. 내용이 실제로 PDF인지 본다 —
        # `.pdf`로 위장한 HTML을 받아 두면 그걸 `inline`으로 되돌려줄 때 문제가 된다.
        head = upload.read(5)
        upload.seek(0)
        if head != b"%PDF-":
            return Response(
                {"detail": f"PDF 파일이 아닙니다: {upload.name} (내용이 PDF 형식과 다릅니다)"},
                status=http.HTTP_400_BAD_REQUEST,
            )

        # 업로더가 문서 유형을 지정하면 파서 자동 감지 대신 그 값을 쓴다(빈 값이면 자동 감지).
        # 유형이 컬렉션 라우팅을 정하므로, 틀리면 그 문서는 정산 판정에 아예 인용되지 않는다.
        hint = str(request.data.get("profileHint") or "").strip().upper()
        if hint and hint not in dict(DOC_PROFILE_CHOICES):
            return Response({"detail": f"알 수 없는 문서 유형: {hint}"}, status=http.HTTP_400_BAD_REQUEST)

        doc = PolicyDoc.objects.create(
            title=(request.data.get("title") or upload.name).strip()[:200],
            profile_hint=hint,
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
        _start(doc, is_reindex=False)
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

    @action(detail=False, methods=["post", "delete"], url_path=r"folders/(?P<folder_id>[0-9]+)")
    def folder_detail(self, request, folder_id=None):
        """POST: 이름 변경 `{name}` / DELETE: 폴더 삭제.

        이름 변경에 PATCH를 쓰지 않는 이유: 이 ViewSet에 `patch`를 열면 `partial_update`
        (`PATCH /policy-docs/{id}/`)까지 함께 열려 문서 필드가 검토 없이 수정 가능해진다.
        액션은 POST로 두는 이 앱의 기존 관례(`reembed`·`move`)를 따른다.

        **비어 있지 않으면 삭제를 거부한다.** 문서는 `SET_NULL`이라 미분류로 살아남고 하위
        폴더는 `CASCADE`로 함께 지워지는데, 그게 한 번의 클릭으로 조용히 일어나면 정리해 둔
        분류가 통째로 날아간다. 옮기고 나서 지우게 한다.
        """
        folder = PolicyFolder.objects.filter(pk=folder_id).first()
        if folder is None:
            return Response({"detail": "폴더를 찾을 수 없습니다."}, status=http.HTTP_404_NOT_FOUND)

        if request.method == "DELETE":
            docs = folder.documents.count()
            children = folder.children.count()
            if docs or children:
                return Response(
                    {"detail": f"비어 있지 않습니다 — 문서 {docs}건, 하위 폴더 {children}개. "
                               "먼저 옮긴 뒤 삭제해주세요."},
                    status=http.HTTP_400_BAD_REQUEST,
                )
            folder.delete()
            return Response(status=http.HTTP_204_NO_CONTENT)

        name = str(request.data.get("name", "")).strip()
        if not name:
            return Response({"detail": "폴더 이름이 필요합니다."}, status=http.HTTP_400_BAD_REQUEST)
        if PolicyFolder.objects.filter(parent=folder.parent, name=name[:80]).exclude(pk=folder.pk).exists():
            return Response({"detail": f"같은 위치에 '{name}' 폴더가 이미 있습니다."},
                            status=http.HTTP_400_BAD_REQUEST)
        folder.name = name[:80]
        folder.save(update_fields=["name"])
        return Response({"id": folder.pk, "name": folder.name})

    @action(detail=True, methods=["get"])
    def file(self, request, pk=None):
        """GET /api/policy-docs/{id}/file/[?download=1] — 원본 PDF 스트리밍.

        **`MEDIA_URL`로 직접 노출하지 않는 이유**가 둘이다:
          ① 인가 — 목록·조항이 `rule_view`를 요구하는데 원본만 무인증으로 열리면 그 통제가
             무의미해진다. 규정 원문은 회사 내부 문서다.
          ② 도달 경로 — nginx는 `/`를 web(SPA)으로 보내고 core로 가는 건 `/api/`뿐이다.
             `MEDIA_URL`을 열어도 브라우저에서 core에 닿지 않는다.

        기본은 `inline`(브라우저 PDF 뷰어로 바로 렌더), `?download=1`이면 첨부로 내려받는다.
        한글 파일명은 `FileResponse`가 RFC 5987로 인코딩해 준다.
        """
        doc = self.get_object()
        if not doc.file:
            return Response({"detail": "원본 파일이 없습니다."}, status=http.HTTP_404_NOT_FOUND)
        try:
            handle = doc.file.open("rb")
        except FileNotFoundError:
            # DB에는 있는데 볼륨에서 사라진 경우 — 조용히 빈 화면을 주지 않고 사유를 밝힌다.
            logger.warning("원본 파일 없음 doc=%s path=%s", doc.pk, doc.file.name)
            return Response(
                {"detail": "원본 파일을 찾을 수 없습니다(볼륨에서 삭제된 것으로 보입니다)."},
                status=http.HTTP_404_NOT_FOUND,
            )
        name = (doc.file.name.rsplit("/", 1)[-1]) or f"{doc.title}.pdf"
        resp = FileResponse(
            handle,
            content_type="application/pdf",
            as_attachment=bool(request.query_params.get("download")),
            filename=name,
        )
        # **inline + 사용자 업로드 파일**은 저장형 XSS의 고전적 조합이다. 우리가 보낸
        # Content-Type을 브라우저가 무시하고 내용을 스니핑해 HTML로 렌더하면, 그 스크립트가
        # **이 앱의 오리진**에서 돈다. nosniff가 그 경로를 막는다(업로드 시 매직바이트 검사와
        # 이중 방어 — 어느 한쪽만으로는 부족하다고 보지 않지만 둘 다 싸다).
        resp["X-Content-Type-Options"] = "nosniff"
        return resp

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

    @action(detail=True, methods=["post"], url_path=r"clauses/(?P<clause_id>\d+)/generate-rule")
    def clause_generate_rule(self, request, pk=None, clause_id=None):
        """POST — 이 조항 하나를 근거로 룰 그래프 DRAFT를 만든다.

        **AI가 `SKIP`으로 분류한 조항에서도 부를 수 있다.** 분류는 제안이지 차단이 아니다 —
        모델이 못 알아본 규칙을 사람이 보고 만들 수 있어야 하고, 그 통로가 없으면 분류가
        틀린 순간 그 조항은 영영 룰이 되지 못한다.

        질의를 여기서 만든다(화면이 아니라): 조 라벨·제목·본문 앞부분을 이어 붙이면 그
        조항 자체가 검색 상위로 올라온다. 화면이 만들면 같은 조항이 화면마다 다른 질의로
        검색된다.
        """
        doc = self.get_object()
        clause = doc.clauses.filter(pk=clause_id).first()
        if clause is None:
            return Response({"detail": "조항을 찾을 수 없습니다."}, status=http.HTTP_404_NOT_FOUND)

        # ⚠️ `normalize_scope("")`는 **`GLOBAL`을 돌려준다**. 정규화한 뒤에 비었는지
        #    보면 분류를 안 고른 요청이 조용히 전역 게이트 룰을 만든다 — 게이트는 모든
        #    정산을 먼저 통과하는 자리라 가장 위험한 기본값이다. 원문으로 먼저 판단한다.
        raw_scope = str(request.data.get("scope") or doc.rule_scope or "").strip()
        if not raw_scope:
            return Response(
                {"detail": "대상 비용분류를 지정해주세요 — 이 문서에는 지정된 분류가 없습니다."},
                status=http.HTTP_400_BAD_REQUEST,
            )
        scope = normalize_scope(raw_scope)

        query = " ".join(filter(None, [
            clause.article_label, clause.article_title, clause.body[:300],
        ])).strip()
        payload = {
            "scope": scope,
            "query": query,
            "name": f"{doc.title} {clause.article_label} 초안",
        }
        url = f"{settings.AI_BASE_URL}/agent/rule-v0/generate"
        try:
            resp = httpx.post(url, json=payload, timeout=httpx.Timeout(300.0, connect=5.0))
        except Exception as exc:  # noqa: BLE001
            return Response(
                {"detail": f"AI 서비스에 연결하지 못했습니다 — {type(exc).__name__}: {exc}"},
                status=503,
            )
        try:
            body = resp.json()
        except ValueError:
            body = {"detail": resp.text[:2000]}
        return Response(body, status=resp.status_code)

    @action(detail=True, methods=["get"], url_path="table-proposals")
    def table_proposals(self, request, pk=None):
        """문서에서 뽑은 별표 후보 + **축으로 쓸 수 있는 사실 목록**.

        축 목록을 함께 내리는 이유: 화면이 자유 입력을 받으면 오타가 그대로 저장되고,
        그 표는 에러 없이 항상 기본값으로 떨어진다(승인 검사가 막긴 하지만, 고를 수 있는
        것을 보여주는 편이 고치라고 되돌려보내는 것보다 낫다).
        """
        doc = self.get_object()
        rows = [_proposal_row(p) for p in doc.table_proposals.all()]
        return Response({"proposals": rows, "axisOptions": _axis_options()})

    # POST인 이유: 이 뷰셋은 `http_method_names`에서 PATCH/PUT을 **의도적으로** 뺐다
    #  (문서는 제자리 수정 대상이 아니다). 새 엔드포인트 하나를 위해 그 제약을 넓히면
    #  문서 자체에도 PATCH가 열린다 — 좁은 쪽에 맞춘다.
    @action(detail=True, methods=["post"],
            url_path=r"table-proposals/(?P<proposal_id>\d+)")
    def table_proposal_detail(self, request, pk=None, proposal_id=None):
        """제안 수정 — 승인 전에 사람이 고친다(키·제목·축·표 내용·시행일).

        이미 처리된(승인·반려) 제안은 고칠 수 없다. 승인된 값은 `PolicyTable`에 복제돼
        판정에 쓰이고 있으므로, 여기서 고쳐도 그쪽엔 반영되지 않는다 — 고쳐진 것처럼
        보이는 편이 안 고쳐지는 것보다 나쁘다. 값을 바꾸려면 개정(새 시행일)으로 간다.
        """
        doc = self.get_object()
        proposal = doc.table_proposals.filter(pk=proposal_id).first()
        if proposal is None:
            return Response({"detail": "제안을 찾을 수 없습니다."}, status=http.HTTP_404_NOT_FOUND)
        if proposal.status != TableProposalStatus.PENDING:
            return Response(
                {"detail": f"이미 처리된 제안입니다({proposal.get_status_display()}) — "
                           "값을 바꾸려면 개정(새 시행일)으로 등록하세요."},
                status=http.HTTP_400_BAD_REQUEST,
            )

        _apply_proposal_patch(proposal, request.data)
        return Response(_proposal_row(proposal))

    @action(detail=True, methods=["post"],
            url_path=r"table-proposals/(?P<proposal_id>\d+)/decision")
    def table_proposal_decision(self, request, pk=None, proposal_id=None):
        """`{action: "APPROVE"|"REJECT", note, …수정값}` — 승인하면 `PolicyTable` 행이 생긴다.

        승인 요청은 화면이 고친 값(키·축·표 내용·시행일)을 함께 실어 보낼 수 있고, 있으면
        **검사 전에 반영**한다. 승인 검사(축·키·구조·시행일)를 통과하지 못하면 **400과 사유
        전부**를 돌려준다 — 하나씩 알려주면 고치고 누르고를 반복하게 된다.
        """
        doc = self.get_object()
        proposal = doc.table_proposals.filter(pk=proposal_id).first()
        if proposal is None:
            return Response({"detail": "제안을 찾을 수 없습니다."}, status=http.HTTP_404_NOT_FOUND)

        verb = str(request.data.get("action") or "").upper()
        note = str(request.data.get("note") or "")
        # 화면이 고친 값을 **결정과 함께** 받는다. 따로 저장하게 두면 축·시행일을 고치고
        # 승인을 눌렀는데 서버는 옛 값으로 검사해 400이 난다 — 화면에는 고친 값이 그대로
        # 보이므로 왜 막혔는지 알 수 없는, 되돌아 나올 길 없는 자리가 된다.
        if verb == "APPROVE" and proposal.status == TableProposalStatus.PENDING:
            _apply_proposal_patch(proposal, request.data)
        try:
            if verb == "APPROVE":
                table_proposals.approve(proposal, actor=request.user, note=note)
            elif verb == "REJECT":
                table_proposals.reject(proposal, actor=request.user, note=note)
            else:
                return Response({"detail": "action은 APPROVE 또는 REJECT여야 합니다."},
                                status=http.HTTP_400_BAD_REQUEST)
        except table_proposals.ProposalError as exc:
            return Response({"detail": str(exc)}, status=http.HTTP_400_BAD_REQUEST)
        proposal.refresh_from_db()
        return Response(_proposal_row(proposal))

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
        return Response(self.get_serializer(_start(doc, is_reindex=True)).data)


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
            _replace_table_proposals(doc, request.data.get("tableProposals") or [])

        #  **적재는 수십 초~분이 걸리고 그동안 사용자는 화면을 떠난다** — 결과를 알 통로가
        #  알림뿐이다. 올린 사람에게 완료/실패를, 룰이 실제로 생겼으면 회계팀 전체에 알린다
        #  (자동 생성된 룰은 곧 전 정산의 판정 기준이 된다).
        #  actor를 넘기지 않는다 — 이 요청의 주체는 ai 서비스 계정이지 사람이 아니다.
        if state in (IngestStatus.DONE, IngestStatus.FAILED):
            notification_events.on_doc_ingested(doc, ok=state == IngestStatus.DONE)
        if state == IngestStatus.DONE and doc.rule_trigger:
            notification_events.on_rule_auto_created(doc, doc.rule_trigger)
        return Response({
            "ok": True, "status": doc.status,
            "clauses": doc.clauses.count(),
            "tableProposals": doc.table_proposals.count(),
        })


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
    empty = ("", "", None, None)
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
            # AI 분류는 매 적재마다 새로 온다(사람의 결정과 달리 이월하지 않는다) —
            # 문서가 바뀌었는데 옛 분류를 물려주면 그게 곧 틀린 제안이 된다.
            triage_kind=_choice(row.get("triageKind"), ClauseKind),
            triage_priority=_choice(row.get("triagePriority"), ClausePriority),
            triage_reason=str(row.get("triageReason") or "")[:2000],
            triage_summary=str(row.get("triageSummary") or "")[:300],
            triaged_at=timezone.now() if row.get("triageKind") else None,
            decision=kept.get(str(row.get("articleLabel") or ""), empty)[0],
            decision_reason=kept.get(str(row.get("articleLabel") or ""), empty)[1],
            decided_by_id=kept.get(str(row.get("articleLabel") or ""), empty)[2],
            decided_at=kept.get(str(row.get("articleLabel") or ""), empty)[3],
        )
        for index, row in enumerate(rows)
        if row.get("articleLabel")
    ])


class DecisionCaseListView(APIView):
    """GET /api/policy-docs/cases/ — 결정 사례를 **월별로 묶어** 돌려준다(S-05 트리의 「결정 사례」).

    ## 왜 `PolicyDoc`으로 만들지 않는가

    사례는 문서가 아니다. 이미 결정 시점에 `case_history`에 적재돼 있어서 문서 파이프라인
    (파싱 → 청킹 → 임베딩 → `policy_docs`)에 태우면 **같은 내용이 두 컬렉션에 이중 적재**되고
    검색이 자기 자신과 겹친다. 게다가 `PolicyDoc`은 파일(FileField) 전제라 원문보기·재색인
    버튼이 전부 빈 껍데기가 된다.

    그래서 트리에 자리만 만들고(사람이 찾는 분류), 내용은 `DecisionCase`를 직접 읽는다.

    ## 왜 월별인가

    1건 = 1항목이면 트리가 금세 수백 줄이 된다. 반대로 전부 한 덩어리면 "언제 결정한
    사례인가"를 못 고른다. 결정은 **월 단위로 몰려서 검토·집계**되므로(팀 통계·검토 이력이
    이미 이번 달 기준이다) 월이 자연스러운 묶음이다.

    인가는 `rule_view` — 사례는 판정의 근거 코퍼스라 규정 문서와 같은 권한으로 묶는다.
    """
    permission_classes = [CanViewRule]

    def get(self, request):
        month = (request.query_params.get("month") or "").strip()
        qs = DecisionCase.objects.select_related("decided_by", "settlement").order_by("-decided_at")

        #  월 목록은 **항상 전체 기준**으로 낸다 — 선택한 달만 보이면 다른 달로 못 넘어간다.
        months: dict[str, dict] = {}
        for case in qs:
            key = case.decided_at.strftime("%Y-%m")
            row = months.setdefault(key, {"key": key, "count": 0, "indexed": 0})
            row["count"] += 1
            row["indexed"] += bool(case.indexed_at)

        listed = [c for c in qs if not month or c.decided_at.strftime("%Y-%m") == month]
        return Response({
            "months": sorted(months.values(), key=lambda m: m["key"], reverse=True),
            "month": month,
            "cases": [_case_row(c) for c in listed],
            "total": qs.count(),
        })


def _case_row(case) -> dict:
    return {
        "id": case.pk,
        "caseId": case.case_id,
        "category": case.category,
        "outcome": case.outcome,
        "expected": case.expected,
        "divergedFrom": case.diverged_from,
        "reason": case.reason,
        "text": case.text,
        "facts": case.facts,
        "ruleFlags": case.rule_flags,
        "citation": case.citation,
        # **누가 결정했는가** — 사례를 읽는 사람의 첫 질문이다.
        "decidedBy": (case.decided_by.first_name or case.decided_by.username) if case.decided_by_id else "",
        "decidedAt": case.decided_at,
        "settlementId": case.settlement_id,
        # 적재 상태를 감추지 않는다 — 안 올라간 사례는 검색에 안 잡힌다(재적재 대상).
        "indexed": bool(case.indexed_at),
        "indexError": case.index_error,
    }


def _choice(raw, choices_cls) -> str:
    """모르는 값은 조용히 버린다 — LLM이 없는 코드를 내도 적재가 깨지면 안 된다."""
    value = str(raw or "").strip().upper()
    return value if value in set(choices_cls.values) else ""


@transaction.atomic
def _replace_table_proposals(doc: PolicyDoc, rows: list[dict]) -> None:
    """별표 후보를 새 적재 결과로 교체하되 **사람이 이미 처리한 것은 건드리지 않는다**.

    승인된 제안을 지우면 `PolicyTable`에 남은 실물과의 연결(무엇을 보고 승인했나)이
    끊긴다. 반려한 제안을 지우면 재색인 때마다 같은 표가 승인 대기로 되살아나 담당자가
    같은 판단을 반복한다 — 조항 결정을 이월하는 것과 같은 이유다.

    같은 표인지는 `source_chunk_id`로 본다. 청크 id는 문서 해시+블록 순번이라 같은 문서를
    다시 넣으면 같은 값이 나온다(재색인이 멱등 upsert인 것과 같은 근거).

    **한 별표에서 표 여러 개가 나온다**(값 열이 여럿인 표 — 2026-08-25). 그래서 추출이
    `chunkId`에 표 key를 덧붙여 보낸다(`c1,c2#lodging_limit_table`). 안 그러면 셋이 같은
    id를 갖게 되고, **하나를 반려하면 나머지 둘의 결정까지 그 id로 이월된다.**
    """
    #  이월하는 것은 **사람이 내린 결정**뿐이다. `SKIPPED`는 AI 판단이라 다시 계산한다 —
    #  모델·프롬프트가 나아지면 예전에 건너뛴 표가 후보가 될 수 있어야 한다.
    handled = set(
        doc.table_proposals.filter(status__in=(
            TableProposalStatus.APPROVED, TableProposalStatus.REJECTED,
        )).values_list("source_chunk_id", flat=True)
    )
    doc.table_proposals.filter(status__in=(
        TableProposalStatus.PENDING, TableProposalStatus.SKIPPED,
    )).delete()

    PolicyTableProposal.objects.bulk_create([
        PolicyTableProposal(
            doc=doc,
            source_chunk_id=str(row.get("chunkId") or "")[:64],
            source_label=str(row.get("label") or "")[:100],
            citation=str(row.get("citation") or "")[:300],
            page_start=int(row.get("pageStart") or 0),
            page_end=int(row.get("pageEnd") or 0),
            raw_markdown=str(row.get("rawMarkdown") or ""),
            key=str(row.get("key") or "")[:64],
            title=str(row.get("title") or "")[:200],
            key_axes=row.get("keyAxes") or [],
            payload=row.get("payload") or {},
            strict_keys=bool(row.get("strictKeys")),
            # 시행일이 없으면 **승인 자체가 막힌다**(`table_proposals.validate`). 업로드
            # 화면이 문서 시행일을 받지 않아 실제로 전건이 그 상태였다 — 적재일로 채우고
            # 사람이 승인 화면에서 고치게 한다(빈칸이면 고칠 것이 있다는 것조차 안 보인다).
            effective_date=(
                row.get("effectiveDate") or doc.effective_date or timezone.localdate()
            ),
            confidence=float(row.get("confidence") or 0.0),
            comment=str(row.get("comment") or ""),
            usage_note=str(row.get("usageNote") or ""),
            checks=row.get("checks") or [],
            skip_reason=str(row.get("skipReason") or ""),
            #  AI가 표가 아니라고 본 건 승인 대기에 섞지 않는다 — 대기 목록은
            #  "사람이 판단해야 할 것"만 담아야 의미가 있다.
            status=(TableProposalStatus.SKIPPED if row.get("skipped")
                    else TableProposalStatus.PENDING),
            notes=str(row.get("notes") or "")[:2000],
        )
        for row in rows
        if str(row.get("chunkId") or "") not in handled
    ])

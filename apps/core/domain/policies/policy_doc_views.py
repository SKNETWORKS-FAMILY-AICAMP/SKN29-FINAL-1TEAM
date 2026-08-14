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
from django.utils import timezone
from rest_framework import status as http
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from domain.common.permissions import CanViewRule

from .models import IngestStatus, PolicyDoc
from .scope import normalize_scope
from .serializers import PolicyDocSerializer

logger = logging.getLogger(__name__)

# 적재 요청은 "접수"만 확인하면 된다 — 실제 작업은 ai가 백그라운드로 돌린다.
_DISPATCH_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
ALLOWED_SUFFIXES = (".pdf",)


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
            uploaded_by=request.user if request.user.is_authenticated else None,
        )
        _start(doc)
        return Response(self.get_serializer(doc).data, status=http.HTTP_201_CREATED)

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
        return Response({"ok": True, "status": doc.status})

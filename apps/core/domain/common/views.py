"""공통 뷰 — 헬스체크, 역할별 대시보드 지표, AI-LAB 프록시."""
import logging

import httpx
from django.conf import settings
from django.db import connection
from django.db.models import Count, Sum
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from domain.accounts.models import Capability
from domain.common.permissions import CanUseAiLab
from domain.settlements.models import Settlement
from domain.settlements.models import SettlementStatus as S

logger = logging.getLogger(__name__)


@api_view(["GET"])
@permission_classes([AllowAny])
def health(_request):
    """서비스 + DB 연결 상태 확인."""
    db_ok = True
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:  # noqa: BLE001
        db_ok = False
    return Response({"status": "ok", "service": "core", "db": db_ok})


class DashboardView(APIView):
    """GET /api/dashboard/{role}/ — 역할별 관심 지표 (FR-DB).

    계산 가능한 값은 DB 집계, 나머지는 placeholder. (거버넌스는 프론트에서 빈 껍데기)
    """
    permission_classes = [AllowAny]

    def get(self, _request, role):
        role = (role or "").upper()
        # 거버넌스(임원) 지표는 열람 권한 보유자만 — 나머지 역할 KPI는 개방(스캐폴드)
        if role == "EXECUTIVE":
            u = getattr(_request, "user", None)
            if not (u and u.is_authenticated and u.has_capability(Capability.GOVERNANCE_VIEW)):
                return Response({"detail": "거버넌스 대시보드 열람 권한이 필요합니다."}, status=403)
        qs = Settlement.objects.all()
        total = qs.count()
        total_amount = qs.aggregate(v=Sum("transaction__amount"))["v"] or 0
        by_status = {r["status"]: r["n"] for r in qs.values("status").annotate(n=Count("id"))}

        if role == "EMPLOYEE":
            kpis = {
                "thisMonthAmount": int(total_amount),
                "unsubmitted": by_status.get(S.DRAFT, 0),
                "returned": by_status.get(S.RETURNED, 0),
                "avgApprovalDays": 2.4,
            }
        elif role == "TEAM_LEAD":
            anomalous = qs.filter(status__in=[S.IN_REVIEW, S.RETURNED, S.REJECT]).count()
            kpis = {"totalAmount": int(total_amount), "anomalous": anomalous, "normal": total - anomalous}
        elif role == "ACCOUNTANT":
            reviewed = qs.exclude(status__in=[S.DRAFT, S.SUBMITTED]).count()
            kpis = {
                "autoProcessRate": round(reviewed / total, 2) if total else 0,
                "reviewPending": by_status.get(S.IN_REVIEW, 0),
                "avgReviewMinutes": 3.1,
            }
        elif role == "EXECUTIVE":
            kpis = {
                "totalAmount": int(total_amount),
                "budgetBurnRate": 0.78,
                "autoProcessRate": 0.68,
                "policyViolationSuspected": by_status.get(S.REJECT, 0),
            }
        else:
            return Response({"detail": f"알 수 없는 역할: {role}"}, status=400)

        return Response({"role": role, "kpis": kpis, "byStatus": by_status})


class AiLabProxyView(APIView):
    """GET/POST /api/ai-lab/{subpath} → FastAPI `/lab/{subpath}` (AI-LAB 관리자 실험 화면).

    FastAPI는 내부 전용이므로(CLAUDE.md §1) 관리자 화면도 Django를 거친다. 여기서 하는 일은
    **인가(Capability `ai_lab`)와 전달뿐**이다 — 응답 가공은 하지 않는다. 화면이 보는 것과
    FastAPI가 실제로 낸 것이 달라지면 실험 도구로서 값을 잃기 때문이다.

    실패는 감추지 않고 그대로 올린다: 연결 실패는 503, 나머지는 FastAPI의 상태코드·본문 그대로.
    (정산 경로의 `draft-suggest`와 반대다 — 그쪽은 폴백이 목적이고, 여기는 진단이 목적이다.)
    """
    permission_classes = [CanUseAiLab]
    # LLM·임베딩 호출이 얹히므로 일반 API보다 넉넉하게. 그래도 무한 대기는 두지 않는다.
    TIMEOUT = httpx.Timeout(90.0, connect=5.0)

    def get(self, request, subpath):
        return self._forward("GET", request, subpath)

    def post(self, request, subpath):
        return self._forward("POST", request, subpath)

    @classmethod
    def _forward(cls, method, request, subpath):
        url = f"{settings.AI_BASE_URL}/lab/{subpath.lstrip('/')}"
        body = request.data if (method == "POST" and isinstance(request.data, (dict, list))) else None
        try:
            resp = httpx.request(
                method, url, params=request.query_params.dict(), json=body, timeout=cls.TIMEOUT
            )
        except Exception as exc:  # noqa: BLE001  # 미기동·타임아웃·DNS 등
            logger.warning("AI-LAB 프록시 실패 %s: %s", url, exc)
            return Response(
                {"detail": f"AI 서비스({settings.AI_BASE_URL})에 연결하지 못했습니다 — {type(exc).__name__}: {exc}"},
                status=503,
            )
        try:
            payload = resp.json()
        except ValueError:
            payload = {"detail": resp.text[:2000]}
        return Response(payload, status=resp.status_code)

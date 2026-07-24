"""공통 뷰 — 헬스체크, 역할별 대시보드 지표."""
from django.db import connection
from django.db.models import Count, Sum
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from domain.settlements.models import Settlement
from domain.settlements.models import SettlementStatus as S


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

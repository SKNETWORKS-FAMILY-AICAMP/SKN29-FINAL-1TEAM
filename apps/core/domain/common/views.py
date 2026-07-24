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

    프론트 KPI 카드에 대응. 계산 가능한 값은 DB에서 집계, 나머지는 placeholder.
    """
    permission_classes = [AllowAny]

    def get(self, _request, role):
        role = (role or "").upper()
        qs = Settlement.objects.all()
        total_amount = qs.aggregate(v=Sum("transaction__amount"))["v"] or 0
        by_status = {r["status"]: r["n"] for r in qs.values("status").annotate(n=Count("id"))}

        if role == "EMPLOYEE":
            data = {
                "이번달_사용액": int(total_amount),
                "미제출_건수": by_status.get(S.DRAFT, 0),
                "보완요청_건수": by_status.get(S.RETURNED, 0),
                "평균_승인소요일": 2.4,  # placeholder
            }
        elif role == "TEAM_LEAD":
            anomalous = qs.filter(status__in=[S.IN_REVIEW, S.RETURNED, S.REJECT]).count()
            data = {
                "총_취합액": int(total_amount),
                "이상_건": anomalous,
                "정상_건": qs.count() - anomalous,
                "제출_리드타임": None,  # placeholder
            }
        elif role == "ACCOUNTANT":
            reviewed = qs.exclude(status__in=[S.DRAFT, S.SUBMITTED]).count()
            data = {
                "자동처리율": round(reviewed / qs.count(), 2) if qs.count() else 0,
                "검토_대기": by_status.get(S.IN_REVIEW, 0),
                "평균_검토시간_분": 3.1,  # placeholder
                "확정_건": by_status.get(S.CONFIRMED, 0) + by_status.get(S.ERP_VOUCHER_DRAFTED, 0),
            }
        elif role == "EXECUTIVE":
            data = {
                "총_지출액": int(total_amount),
                "예산_소진율": 0.78,  # placeholder(예산 도메인 도입 시 계산)
                "자동처리율": 0.68,   # placeholder
                "정책위반_의심": by_status.get(S.REJECT, 0),
            }
        else:
            return Response({"detail": f"알 수 없는 역할: {role}"}, status=400)

        return Response({"role": role, "kpis": data, "by_status": by_status})

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import ErpVoucher
from .serializers import ErpVoucherSerializer


class ErpVoucherViewSet(viewsets.ReadOnlyModelViewSet):
    """GET /api/erp/vouchers/ · /{id}/ · /by-settlement/{settlement_id}/

    전표(안)는 정산 확정(`CONFIRMED → ERP_VOUCHER_DRAFTED`) 때 서비스 레이어가 만든다
    (`settlements/services.py::draft_voucher`). 화면은 **정산 id만 들고 있으므로**
    전표 id를 모른 채 조회할 수 있어야 한다 — 그래서 `by-settlement`를 둔다.
    `?settlement=<id>` 필터만 두면 "없음"과 "빈 목록"을 화면이 다시 구분해야 한다.
    """
    queryset = ErpVoucher.objects.select_related("settlement", "settlement__transaction").all()
    serializer_class = ErpVoucherSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        if (sid := self.request.query_params.get("settlement")):
            qs = qs.filter(settlement_id=sid)
        return qs

    @action(detail=False, methods=["get"], url_path=r"by-settlement/(?P<settlement_id>[0-9]+)")
    def by_settlement(self, request, settlement_id=None):
        voucher = self.get_queryset().filter(settlement_id=settlement_id).first()
        if voucher is None:
            # 확정 전이거나 전표 생성 단계를 아직 안 지난 건이다. 빈 껍데기를 돌려주면
            # 화면이 "전표가 있는데 비어 있다"로 그린다 — 없으면 없다고 말한다.
            return Response({"detail": "이 정산에는 아직 생성된 ERP 전표(안)가 없습니다."}, status=404)
        return Response(self.get_serializer(voucher).data)

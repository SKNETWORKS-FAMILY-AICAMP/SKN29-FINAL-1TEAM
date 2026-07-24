from rest_framework import viewsets

from .models import ErpVoucher
from .serializers import ErpVoucherSerializer


class ErpVoucherViewSet(viewsets.ReadOnlyModelViewSet):
    """GET /api/erp/vouchers/{id}/ (ERP 전표(안) 조회)."""
    queryset = ErpVoucher.objects.select_related("settlement").all()
    serializer_class = ErpVoucherSerializer

from rest_framework import viewsets

from .models import Receipt, Transaction
from .serializers import ReceiptSerializer, TransactionSerializer


class TransactionViewSet(viewsets.ModelViewSet):
    """GET /api/transactions/ · POST /api/transactions/ (거래 조회/수집)."""
    queryset = Transaction.objects.select_related("card").all()
    serializer_class = TransactionSerializer


class ReceiptViewSet(viewsets.ModelViewSet):
    """POST /api/receipts/ (증빙 업로드). 비전 판독·매칭은 ai(FastAPI) 담당."""
    queryset = Receipt.objects.all()
    serializer_class = ReceiptSerializer

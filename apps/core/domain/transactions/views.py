from rest_framework import viewsets
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .features import build_tx_features
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


class TxFeaturesView(APIView):
    """GET /api/internal/tx-features/<tx_id>/ — 이상탐지 입력용 15개 원본 피처 조립(Django 내부 read API).

    FastMCP `get_tx_features`가 이 API만 거친다(관계형 데이터 Django 경유 원칙, CLAUDE.md §1).
    원-핫 인코딩·모델 정렬 등 "판단 없는 변환"은 여기서 하지 않고 AI 쪽(`app.ml.features`)에 맡긴다.
    """
    permission_classes = [AllowAny]

    def get(self, request, tx_id):
        tx = Transaction.objects.select_related("card").filter(pk=tx_id).first()
        if tx is None:
            return Response({"detail": "거래를 찾을 수 없습니다."}, status=404)
        return Response({"tx_id": tx.pk, "features": build_tx_features(tx)})

from datetime import timedelta

from django.utils import timezone
from rest_framework import viewsets
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from domain.common.permissions import CanViewRule

from .features import build_tx_features
from . import industry
from .models import MerchantCategory, MerchantSource, Receipt, Transaction
from .serializers import ReceiptSerializer, TransactionSerializer

# 가맹점 업종 캐시 유효기간(§7-1, 요구사항 §9 Open Issue #12 — 2026-08-18 30일로 확정).
MERCHANT_CACHE_TTL = timedelta(days=30)


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


class MerchantCategoryLookupView(APIView):
    """GET /api/internal/merchant-category/<normalized_name>/ — 가맹점 업종 캐시 조회(§7-1).

    FastMCP `classify_merchant`의 1차 소스(source=CACHE). `resolved_at`이
    `MERCHANT_CACHE_TTL`(30일)을 넘긴 행은 만료로 보고 미스(`hit: false`)로 취급한다 —
    호출부는 그대로 카카오 재조회로 넘어간다. 캐시에 아예 없는 것과 만료된 것을 구분할
    필요는 없다(둘 다 "다시 조회해야 함"이라는 같은 결론).
    """
    permission_classes = [AllowAny]

    def get(self, request, normalized_name):
        hit = MerchantCategory.objects.filter(normalized_name=normalized_name).first()
        if hit is None or (timezone.now() - hit.resolved_at) > MERCHANT_CACHE_TTL:
            return Response({"hit": False})
        return Response({
            "hit": True,
            "industry_code": hit.industry_code,
            "industry_label": hit.industry_label,
            "confidence": hit.confidence,
            "source": hit.source,
        })


class MerchantCategoryUpsertView(APIView):
    """POST /api/internal/merchant-category/ — 카카오+LLM 재분류 결과 캐시 적재(ai → core 쓰기).

    다른 내부 read API(`TxFeaturesView` 등)는 `AllowAny`지만 이건 **쓰기**다 —
    `IngestCallbackView`와 동일하게 ai 서비스 계정 JWT(capability `rule_view`)를 요구한다.
    `resolved_at`은 `auto_now=True`라 upsert마다 자동 갱신되고, 그게 곧 TTL 기산점이다.
    """
    permission_classes = [CanViewRule]

    def post(self, request):
        name = str(request.data.get("normalized_name") or "").strip()
        if not name:
            return Response({"detail": "normalized_name이 필요합니다."}, status=400)
        # 어휘 게이트 — ai가 보낸 표기를 정본으로 접고, 접히지 않으면 **거부**한다.
        #  ai(`app/schemas.py`)는 이 표를 미러할 뿐 강제받지 않으므로, 양쪽이 어긋나면
        #  여기서 400으로 드러나야 한다. 조용히 저장하면 그 값이 그대로 판정 사실이 된다.
        raw_industry = request.data.get("industry_code") or request.data.get("industry_label")
        code, label = industry.resolve(raw_industry)
        if not code:
            return Response(
                {"detail": f"정본 업종 어휘가 아닙니다: {raw_industry!r} "
                           f"(허용: {', '.join(industry.LABEL_BY_CODE)})"},
                status=400,
            )
        obj, _ = MerchantCategory.objects.update_or_create(
            normalized_name=name,
            defaults=dict(
                place_id=str(request.data.get("place_id") or ""),
                industry_code=code,
                industry_label=label,
                source=request.data.get("source") or MerchantSource.KAKAO,
                confidence=float(request.data.get("confidence") or 0.0),
                raw=request.data.get("raw") or {},
            ),
        )
        return Response({
            "normalized_name": obj.normalized_name,
            "industry_code": obj.industry_code,
            "industry_label": obj.industry_label,
            "confidence": obj.confidence,
            "source": obj.source,
        })

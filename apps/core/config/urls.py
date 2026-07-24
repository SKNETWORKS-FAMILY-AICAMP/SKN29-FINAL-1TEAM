"""Core URL 라우팅 (대외 REST, 기술명세서 §6.1)."""
from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from domain.common.views import DashboardView, health
from domain.erp.views import ErpVoucherViewSet
from domain.policies.views import RuleGraphViewSet
from domain.settlements.views import SettlementViewSet
from domain.transactions.views import ReceiptViewSet, TransactionViewSet

router = DefaultRouter()
router.register("transactions", TransactionViewSet)
router.register("receipts", ReceiptViewSet)
router.register("settlements", SettlementViewSet)
router.register("rules", RuleGraphViewSet)          # 룰 그래프(최종 상태 도메인)
router.register("erp/vouchers", ErpVoucherViewSet)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", health, name="health"),
    path("api/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/dashboard/<str:role>/", DashboardView.as_view(), name="dashboard"),
    path("api/", include(router.urls)),
]

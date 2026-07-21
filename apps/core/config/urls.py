"""Core URL 라우팅 (대외 REST, 기술명세서 §6.1)."""
from django.contrib import admin
from django.urls import path
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)

from domain.common.views import health

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", health, name="health"),
    path("api/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    # TODO(도메인 API): /api/transactions, /api/settlements, /api/rules,
    #   /api/settlements/{id}/confirm, /api/dashboard/{role}, /api/erp/vouchers ...
]

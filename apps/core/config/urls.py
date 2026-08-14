"""Core URL 라우팅 (대외 REST, 기술명세서 §6.1)."""
from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from domain.accounts.views import CsrfView, LoginView, LogoutView, MeView
from domain.common.views import AiLabProxyView, DashboardView, health
from domain.erp.views import ErpVoucherViewSet
from domain.policies.policy_doc_views import IngestCallbackView, PolicyDocViewSet
from domain.policies.rule_agent_v0_views import EvalContextSchemaView
from domain.policies.views import PolicyLookupView, RuleContextView, RuleGraphViewSet
from domain.risk_review_v0.views import ReviewDecisionView, ReviewListView   # v0 격리 서브패키지
from domain.settlements.views import SettlementSummaryView, SettlementViewSet, TeamBudgetView
from domain.transactions.views import ReceiptViewSet, TransactionViewSet, TxFeaturesView

router = DefaultRouter()
router.register("transactions", TransactionViewSet)
router.register("receipts", ReceiptViewSet)
router.register("settlements", SettlementViewSet)
router.register("rules", RuleGraphViewSet)          # 룰 그래프(최종 상태 도메인)
router.register("policy-docs", PolicyDocViewSet)    # RAG 소스 규정 문서(업로드·적재)
router.register("erp/vouchers", ErpVoucherViewSet)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", health, name="health"),
    # 세션 로그인(JWT 대신)
    path("api/auth/csrf/", CsrfView.as_view(), name="csrf"),
    path("api/auth/login/", LoginView.as_view(), name="session_login"),
    path("api/auth/logout/", LogoutView.as_view(), name="session_logout"),
    path("api/me/", MeView.as_view(), name="me"),
    # JWT(보류 — 병행 유지)
    path("api/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/dashboard/<str:role>/", DashboardView.as_view(), name="dashboard"),
    path("api/team-budget/", TeamBudgetView.as_view(), name="team_budget"),
    # AI-LAB(관리자) — AI 기능 독립 실행. FastAPI `/lab/*`로 전달, 인가는 Capability `ai_lab`.
    path("api/ai-lab/<path:subpath>", AiLabProxyView.as_view(), name="ai_lab_proxy"),
    # 내부 전용 read API — FastAPI(ai)의 FastMCP 도구가 관계형 데이터를 Django 경유로 조회(CLAUDE.md §1)
    path("api/internal/policies/<str:category>/", PolicyLookupView.as_view(), name="internal_policy"),
    path("api/internal/rule-context/<int:settlement_id>/", RuleContextView.as_view(), name="internal_rule_context"),
    path("api/internal/tx-features/<int:tx_id>/", TxFeaturesView.as_view(), name="internal_tx_features"),
    path("api/internal/settlement-summary/<int:settlement_id>/", SettlementSummaryView.as_view(), name="internal_settlement_summary"),
    path("api/internal/rule-agent-v0/eval-context-schema/", EvalContextSchemaView.as_view(), name="internal_eval_context_schema"),
    # 적재 결과 회신(ai → core). read 계열과 달리 **쓰기**라 서비스 계정 인증을 요구한다.
    path("api/internal/policy-docs/<int:pk>/ingest-result/", IngestCallbackView.as_view(), name="internal_ingest_result"),
    path("api/", include(router.urls)),
    # Review List v0 — 독립 개발 서브패키지(domain/risk_review_v0). v1에서 정식 URL 네임스페이스로
    # 정리 예정, 지금은 v0 전용 경로로만 노출(메인 라우팅 정식 편입 전).
    path("api/risk-review-v0/reviews/", ReviewListView.as_view(), name="risk_review_v0_list"),
    path("api/risk-review-v0/reviews/<int:settlement_id>/decision/", ReviewDecisionView.as_view(), name="risk_review_v0_decision"),
]

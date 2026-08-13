# apps/core/domain/policies/rule_agent_v0/urls.py
"""v0 전용 urlpatterns. 메인 urls.py에서 include 1줄만 추가하면 된다:

    path("api/internal/rule-agent-v0/",
         include("domain.policies.rule_agent_v0.urls")),

제거할 때도 이 폴더 삭제 + urls.py의 위 1줄 삭제로 끝난다.
"""
from django.urls import path

from .views import EvalContextSchemaView, RuleGraphDraftCreateView

urlpatterns = [
    path("eval-context-schema/", EvalContextSchemaView.as_view()),
    path("rule-graphs/drafts/", RuleGraphDraftCreateView.as_view()),
]

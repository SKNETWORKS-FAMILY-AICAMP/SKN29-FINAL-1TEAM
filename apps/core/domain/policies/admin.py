from django.contrib import admin

from .models import (
    PolicyDoc, PolicyTable, RuleGraph, RuleGraphVersion, RuleHit, RuleNode, RuleRouting,
)


class RuleNodeInline(admin.TabularInline):
    model = RuleNode
    extra = 0


class RuleRoutingInline(admin.TabularInline):
    model = RuleRouting
    extra = 0


@admin.register(RuleGraph)
class RuleGraphAdmin(admin.ModelAdmin):
    list_display = ("id", "family_key", "name", "scope", "status", "version", "activated_at")
    list_filter = ("status", "scope")
    inlines = [RuleNodeInline, RuleRoutingInline]


@admin.register(PolicyTable)
class PolicyTableAdmin(admin.ModelAdmin):
    """규정 별표를 회계 담당자가 직접 확인·개정하는 창구.

    개정은 기존 행 수정이 아니라 **새 effective_date 행 추가**로 한다(구행에 superseded_date).
    `source_clause`를 반드시 채워 "이 숫자가 규정 어디서 왔는지"를 남긴다.
    """
    list_display = ("key", "title", "effective_date", "superseded_date", "source_clause")
    list_filter = ("key", "effective_date")
    search_fields = ("key", "title", "source_clause")


admin.site.register(PolicyDoc)
admin.site.register(RuleGraphVersion)
admin.site.register(RuleHit)

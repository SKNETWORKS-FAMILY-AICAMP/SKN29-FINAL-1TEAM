from django.contrib import admin

from .models import (
    Policy, PolicyDoc, RuleGraph, RuleGraphVersion, RuleHit, RuleNode, RuleRouting,
)


class RuleNodeInline(admin.TabularInline):
    model = RuleNode
    extra = 0


class RuleRoutingInline(admin.TabularInline):
    model = RuleRouting
    extra = 0


@admin.register(RuleGraph)
class RuleGraphAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "scope", "status", "version", "activated_at")
    list_filter = ("status", "scope")
    inlines = [RuleNodeInline, RuleRoutingInline]


admin.site.register(Policy)
admin.site.register(PolicyDoc)
admin.site.register(RuleGraphVersion)
admin.site.register(RuleHit)

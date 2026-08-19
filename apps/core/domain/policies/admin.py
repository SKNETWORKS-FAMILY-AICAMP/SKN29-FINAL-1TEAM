from django.contrib import admin

from .models import (
    PolicyClause, PolicyDoc, PolicyFolder, PolicyTable, RuleFlag, RuleGraph,
    RuleGraphVersion, RuleHit, RuleNode, RuleRouting,
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
# 폴더는 사람이 손으로 정리하는 분류라 admin에서 만드는 게 가장 빠르다(화면에도 생성 API가 있다).
admin.site.register(PolicyFolder)
# 조항은 적재가 만들지만, 결정(규칙 생성 안 함 + 사유)을 admin에서 되돌려야 할 때가 있다.
admin.site.register(PolicyClause)


@admin.register(RuleFlag)
class RuleFlagAdmin(admin.ModelAdmin):
    """네임드 플래그 레지스트리 — 판정 사유 코드의 표기·분류.

    ⚠️ **`code`는 데이터 계약이다.** Risk Review 프롬프트 입력이자 룰 정밀도 집계의 키라,
    바꾸면 과거 `rule_hits`·통계와 비교가 끊긴다. 표기를 고치려면 `label`을 쓴다.
    행이 **행동을 갖지 않는다**는 것도 중요하다 — 상태는 `decision`이 정한다(`flags.py`).
    """
    list_display = ("code", "label", "category", "severity", "owner", "is_system", "is_active")
    list_filter = ("category", "severity", "owner", "is_system", "is_active")
    list_editable = ("label", "severity", "owner", "is_active")
    search_fields = ("code", "label", "description")
    readonly_fields = ("code", "is_system")   # 계약이라 화면에서 못 바꾼다(코드/시드로만)

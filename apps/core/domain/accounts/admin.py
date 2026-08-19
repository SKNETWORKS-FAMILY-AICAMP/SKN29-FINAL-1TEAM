from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import UserChangeForm

from .models import Capability, JobTitle, Position, Team, User


class UserCapabilityForm(UserChangeForm):
    """extra_capabilities(JSON 리스트)를 체크박스로 편집 — 사용자별 기능 권한 부여 UI."""
    extra_capabilities = forms.MultipleChoiceField(
        choices=Capability.choices,
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="추가 부여 기능 권한",
        help_text="역할 기본값에 더해 개별 부여한다. 유효 능력 = 역할 기본 ∪ 이 값.",
    )

    class Meta(UserChangeForm.Meta):
        model = User
        fields = "__all__"

    def clean_extra_capabilities(self):
        return list(self.cleaned_data.get("extra_capabilities") or [])


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """Django 기본 UserAdmin 확장 — role/team + 기능 권한(extra_capabilities) 편집·유효능력 표시."""
    form = UserCapabilityForm
    list_display = ("username", "role", "job_title", "position", "team", "capabilities_display", "is_staff", "is_superuser")
    list_filter = ("role", "job_title", "position", "is_staff", "is_superuser")
    readonly_fields = ("capabilities_display",)
    fieldsets = DjangoUserAdmin.fieldsets + (
        ("정산 플랫폼 · 조직", {
            "fields": ("team", "job_title", "position"),
            "description": "한도·결재권은 <b>직책</b>이 정한다(「직급체계」§1.1). 직급은 처우 축이라 판정에 쓰이지 않는다.",
        }),
        ("정산 플랫폼 · 권한", {"fields": ("role", "extra_capabilities", "capabilities_display")}),
    )
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        ("정산 플랫폼", {"fields": ("role", "team", "job_title", "position")}),
    )

    @admin.display(description="유효 기능 권한 (역할기본 ∪ 추가부여)")
    def capabilities_display(self, obj):
        return ", ".join(obj.capabilities) if (obj and obj.pk) else "-"


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "bu", "is_submission_unit")


class OrgCodeAdmin(admin.ModelAdmin):
    """직책·직급 기준 코드. `name`이 규정 별표의 룩업 키라 표기 변경은 파급이 있다.

    표기를 바꾸면 `tiger_tables.py` 별표 payload의 키와 어긋나 한도가 **조용히**
    와일드카드로 떨어진다(에러도 플래그도 없다). `org_codes.check_table_keys()`로 대조한다.
    """
    list_display = ("rank", "name", "code", "is_active")
    list_editable = ("name", "is_active")
    ordering = ("rank",)


@admin.register(JobTitle)
class JobTitleAdmin(OrgCodeAdmin):
    """직책 — 결재권·카드한도의 축(별표1의 행)."""


@admin.register(Position)
class PositionAdmin(OrgCodeAdmin):
    """직급 — 처우 축. 판정에 쓰이지 않는다."""
    list_display = ("rank", "name", "code", "assignable_titles", "is_active")

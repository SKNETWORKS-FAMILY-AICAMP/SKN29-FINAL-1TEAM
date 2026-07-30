from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import UserChangeForm

from .models import Capability, Team, User


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
    list_display = ("username", "role", "team", "capabilities_display", "is_staff", "is_superuser")
    list_filter = ("role", "is_staff", "is_superuser")
    readonly_fields = ("capabilities_display",)
    fieldsets = DjangoUserAdmin.fieldsets + (
        ("정산 플랫폼 · 권한", {"fields": ("role", "team", "extra_capabilities", "capabilities_display")}),
    )
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        ("정산 플랫폼", {"fields": ("role", "team")}),
    )

    @admin.display(description="유효 기능 권한 (역할기본 ∪ 추가부여)")
    def capabilities_display(self, obj):
        return ", ".join(obj.capabilities) if (obj and obj.pk) else "-"


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "bu", "is_submission_unit")

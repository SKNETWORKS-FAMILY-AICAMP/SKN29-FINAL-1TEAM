from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import Team, User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """Django 기본 UserAdmin 확장 — 커스텀 필드(role/team) 노출 + 비밀번호 해시 처리."""
    list_display = ("username", "role", "team", "is_staff", "is_superuser")
    list_filter = ("role", "is_staff", "is_superuser")
    fieldsets = DjangoUserAdmin.fieldsets + (
        ("정산 플랫폼", {"fields": ("role", "team")}),
    )
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        ("정산 플랫폼", {"fields": ("role", "team")}),
    )


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "bu", "is_submission_unit")

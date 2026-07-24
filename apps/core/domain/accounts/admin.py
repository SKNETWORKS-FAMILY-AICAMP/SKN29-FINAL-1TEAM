from django.contrib import admin

from .models import Team, User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("username", "role", "team", "is_staff")
    list_filter = ("role",)


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "bu", "is_submission_unit")

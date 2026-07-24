"""조직/사용자/권한 (기술명세서 §3.1)."""
from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.TextChoices):
    EMPLOYEE = "EMPLOYEE", "사용자(임직원)"
    TEAM_LEAD = "TEAM_LEAD", "팀장(제출 단위)"
    ACCOUNTANT = "ACCOUNTANT", "회계 담당자"
    EXECUTIVE = "EXECUTIVE", "회계·운영 상부"


class Team(models.Model):
    """제출 단위(조직도 팀이 아니라 정산을 취합해 올리는 단위, 1인도 가능)."""
    name = models.CharField(max_length=100)
    bu = models.CharField("본부", max_length=100, blank=True)
    is_submission_unit = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class User(AbstractUser):
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.EMPLOYEE)
    team = models.ForeignKey(
        Team, null=True, blank=True, on_delete=models.SET_NULL, related_name="members"
    )

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"

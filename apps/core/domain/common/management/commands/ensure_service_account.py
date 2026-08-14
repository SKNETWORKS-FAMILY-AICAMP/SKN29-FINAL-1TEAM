"""Rule Agent용 서비스 계정 생성·갱신 (멱등).

Rule Agent는 사람 세션 없이 룰 콘솔 API(`POST /api/rules/drafts/` 등)에 DRAFT를
써야 한다. 그 API들은 `CanViewRule`(capability `rule_view`)을 요구하므로 **그 하나만
가진 전용 계정**을 둔다 — 회계 담당자 계정을 빌려 쓰면 감사로그의 actor가 사람으로
찍혀 "누가 만든 룰인지"가 흐려진다.

    docker compose exec core python manage.py ensure_service_account

비밀번호는 `RULE_AGENT_SERVICE_PASSWORD`(레포 루트 `.env`)에서 읽는다. FastAPI가 같은
값으로 `/api/auth/token/`에 로그인해 JWT를 받는다(`agents/rule_agent_v0/django_client.py`).
`seed`가 비슈퍼유저를 전부 지우므로 seed 후에는 이 명령을 다시 돌려야 한다
(`seed`도 끝에서 이 로직을 호출한다).
"""
import os

from django.core.management.base import BaseCommand

from domain.accounts.models import Capability, Role, User

SERVICE_USERNAME = os.environ.get("RULE_AGENT_SERVICE_USER", "rule-agent")
SERVICE_CAPABILITIES = [Capability.RULE_VIEW.value]


def ensure_service_account(password: str | None = None) -> tuple[User, bool, bool]:
    """(user, created, password_set) — 비밀번호가 주어지지 않으면 기존 값을 유지한다."""
    password = password if password is not None else os.environ.get("RULE_AGENT_SERVICE_PASSWORD", "")
    user, created = User.objects.get_or_create(
        username=SERVICE_USERNAME,
        defaults={
            "role": Role.EMPLOYEE,          # 역할 기본 능력 없음 — 아래 extra만 갖는다
            "first_name": "Rule Agent",
            "is_active": True,
            "extra_capabilities": SERVICE_CAPABILITIES,
        },
    )
    # 능력은 항상 재설정한다 — 권한이 늘어난 채로 굳는 걸 막는다(최소 권한 유지).
    if user.extra_capabilities != SERVICE_CAPABILITIES or user.role != Role.EMPLOYEE:
        user.extra_capabilities = SERVICE_CAPABILITIES
        user.role = Role.EMPLOYEE
        user.save(update_fields=["extra_capabilities", "role"])

    password_set = False
    if password:
        user.set_password(password)
        user.save(update_fields=["password"])
        password_set = True
    elif created:
        user.set_unusable_password()
        user.save(update_fields=["password"])
    return user, created, password_set


class Command(BaseCommand):
    help = "Rule Agent 서비스 계정(rule-agent)을 생성/갱신한다 (capability: rule_view)"

    def handle(self, *args, **options):
        user, created, password_set = ensure_service_account()
        self.stdout.write(
            f"{'생성' if created else '갱신'}: {user.username} "
            f"(capabilities={sorted(user.capabilities)})"
        )
        if not password_set:
            self.stdout.write(self.style.WARNING(
                "RULE_AGENT_SERVICE_PASSWORD 가 비어 있어 비밀번호를 설정하지 않았다 — "
                "FastAPI가 로그인하지 못해 룰 생성이 403으로 실패한다. "
                "레포 루트 `.env`에 값을 넣고 다시 실행할 것"
            ))

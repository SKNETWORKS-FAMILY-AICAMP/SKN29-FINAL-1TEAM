"""ai(FastAPI)가 core에 쓰기를 할 때 쓰는 **단일 서비스 계정** 생성·갱신 (멱등).

    docker compose exec core python manage.py ensure_service_account
    docker compose exec core python manage.py ensure_service_account --check   # 진단만

**Agent마다 계정을 나누지 않는다.** ai에서 core로 나가는 쓰기는 전부 이 계정 하나를 쓴다
(룰 그래프 DRAFT 저장, 규정 적재 결과 회신). 그 경로들이 요구하는 권한이 같고(`rule_view`),
계정을 늘리면 비밀번호를 늘린 만큼 어긋날 자리가 늘어난다.

권한은 `rule_view` **하나뿐**이다 — 회계 검토·룰 활성까지 딸려오면 Agent가 스스로 승인까지
할 수 있게 된다. 사람 계정을 빌려 쓰지 않는 이유는 감사로그의 actor가 사람으로 찍혀
"누가 만든 룰인지"가 흐려지기 때문이다.

비밀번호는 `AI_SERVICE_PASSWORD`(구 `RULE_AGENT_SERVICE_PASSWORD`)에서 읽는다. ai 컨테이너가
**같은 값**으로 `/api/auth/token/`에 로그인해 JWT를 받는다 — 양쪽이 다르면 401이 난다.
`seed`가 비슈퍼유저를 전부 지우므로 seed도 이 로직을 호출한다.
"""
import os

from django.core.management.base import BaseCommand, CommandError

from domain.accounts.models import Capability, Role, User

# 새 이름을 먼저 보고 구 이름으로 폴백한다 — 이름이 `RULE_AGENT_*`라 "Agent마다 계정이
# 따로인가?"라는 오해를 만들었다. 기존 `.env`를 깨지 않으려고 둘 다 받는다.
SERVICE_USERNAME = (
    os.environ.get("AI_SERVICE_USER")
    or os.environ.get("RULE_AGENT_SERVICE_USER")
    or "rule-agent"
)
PASSWORD_ENV = ("AI_SERVICE_PASSWORD", "RULE_AGENT_SERVICE_PASSWORD")
SERVICE_CAPABILITIES = [Capability.RULE_VIEW.value]


def service_password() -> str:
    for key in PASSWORD_ENV:
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return ""


def ensure_service_account(password: str | None = None) -> tuple[User, bool, bool]:
    """(user, created, password_set). 비밀번호가 비면 **설정하지 않는다**(기존 값 유지).

    호출부가 빈 비밀번호를 그냥 넘겼는지 알 수 있도록 `password_set`을 돌려준다 —
    관리 명령은 그 경우 에러로 끝낸다(아래 `Command.handle`).
    """
    password = password if password is not None else service_password()
    user, created = User.objects.get_or_create(
        username=SERVICE_USERNAME,
        defaults={
            "role": Role.EMPLOYEE,          # 역할 기본 능력 없음 — 아래 extra만 갖는다
            "first_name": "AI Service",
            "is_active": True,
            "extra_capabilities": SERVICE_CAPABILITIES,
        },
    )
    # 능력·활성 상태는 항상 재설정한다 — 권한이 늘어난 채로 굳거나 비활성으로 남는 걸 막는다.
    changed = []
    if user.extra_capabilities != SERVICE_CAPABILITIES:
        user.extra_capabilities = SERVICE_CAPABILITIES
        changed.append("extra_capabilities")
    if user.role != Role.EMPLOYEE:
        user.role = Role.EMPLOYEE
        changed.append("role")
    if not user.is_active:
        # 비활성 계정은 SimpleJWT가 "No active account found"로 거절한다 — 조용히 못 고치게 둔다.
        user.is_active = True
        changed.append("is_active")
    if changed:
        user.save(update_fields=changed)

    password_set = False
    if password:
        user.set_password(password)
        user.save(update_fields=["password"])
        password_set = True
    return user, created, password_set


def diagnose() -> list[str]:
    """무엇이 어긋났는지 사람이 읽을 수 있게. 401이 났을 때 여기부터 본다."""
    lines = [f"계정명       {SERVICE_USERNAME}"]
    env_used = next((k for k in PASSWORD_ENV if os.environ.get(k, "").strip()), None)
    lines.append(f"비밀번호 env {env_used or '(없음 — ' + ' / '.join(PASSWORD_ENV) + ' 둘 다 비어 있다)'}")

    user = User.objects.filter(username=SERVICE_USERNAME).first()
    if user is None:
        lines.append("계정 상태     ❌ 없음 — `manage.py ensure_service_account`를 실행할 것")
        return lines

    lines.append(f"계정 상태     ✅ 존재 (id={user.pk}, active={user.is_active})")
    lines.append(f"capabilities {sorted(user.capabilities)}")
    if not user.has_usable_password():
        lines.append(
            "비밀번호      ❌ 사용 불가(unusable) — 비밀번호 없이 계정이 만들어졌다. "
            "`.env`에 AI_SERVICE_PASSWORD를 넣고 다시 실행할 것"
        )
    elif env_used and user.check_password(os.environ[env_used]):
        lines.append("비밀번호      ✅ env 값과 일치 — ai가 로그인할 수 있다")
    elif env_used:
        lines.append(
            "비밀번호      ❌ env 값과 **불일치** — core 계정이 다른 비밀번호로 만들어졌다. "
            "`manage.py ensure_service_account`를 다시 실행하면 env 값으로 덮어쓴다"
        )
    else:
        lines.append("비밀번호      ⚠️ env가 비어 있어 대조할 수 없다")

    if Capability.RULE_VIEW.value not in user.capabilities:
        lines.append("권한          ❌ rule_view 없음 — 로그인은 되어도 403이 난다")
    return lines


class Command(BaseCommand):
    help = "ai(FastAPI)용 서비스 계정을 생성/갱신한다 (capability: rule_view 하나만)"

    def add_arguments(self, parser):
        parser.add_argument("--check", action="store_true", help="변경 없이 진단만 출력")

    def handle(self, *args, **options):
        if options["check"]:
            for line in diagnose():
                self.stdout.write(line)
            return

        password = service_password()
        if not password:
            # 예전에는 경고만 찍고 로그인 불가 계정을 만들었다. 그러면 나중에 ai가
            # "No active account found"라는 **원인과 동떨어진** 401을 받는다 — 여기서 멈춘다.
            raise CommandError(
                "AI_SERVICE_PASSWORD 가 비어 있다 — 로그인할 수 없는 계정을 만들지 않고 멈춘다.\n"
                "  1) 레포 루트 `.env`에 `AI_SERVICE_PASSWORD=<임의의 값>` 추가\n"
                "  2) docker compose up -d --force-recreate core ai   (env 변경은 컨테이너 재생성 필요)\n"
                "  3) docker compose exec core python manage.py ensure_service_account"
            )

        user, created, _ = ensure_service_account(password)
        self.stdout.write(self.style.SUCCESS(
            f"{'생성' if created else '갱신'}: {user.username} (capabilities={sorted(user.capabilities)})"
        ))
        for line in diagnose():
            self.stdout.write("  " + line)

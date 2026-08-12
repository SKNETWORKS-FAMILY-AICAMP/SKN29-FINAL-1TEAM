"""규정 별표(PolicyTable) 단독 적재 — `_context/policy-domain.md` §2.

`seed`가 전체 시연 데이터를 다시 깔지 않고도 임계값만 갱신할 수 있게 분리해 둔다.
값 정의는 `domain/policies/tiger_tables.py` 한 곳뿐이다.
"""
from django.core.management.base import BaseCommand

from domain.policies.models import PolicyTable
from domain.policies.tiger_tables import upsert_all


class Command(BaseCommand):
    help = "규정 별표(PolicyTable)를 적재/갱신한다."

    def handle(self, *args, **options):
        count = upsert_all()
        self.stdout.write(self.style.SUCCESS(
            f"별표 {count}종 적재 완료 (총 {PolicyTable.objects.count()}행)"
        ))

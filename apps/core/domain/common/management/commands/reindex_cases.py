"""아직 Chroma에 안 올라간 결정 사례를 몰아서 적재한다.

    docker compose exec core python manage.py reindex_cases [--limit 100] [--list]

사례는 결정 시점에 커밋 후 자동 적재되지만, 그때 ai가 꺼져 있었거나 임베딩이 실패하면
`indexed_at`이 빈 채로 남는다(결정 자체는 이미 확정됐다 — 적재 실패로 되돌리지 않는다).
그 밀린 것들을 되살리는 관리자 경로다.
"""
from django.core.management.base import BaseCommand

from domain.risk import case_index
from domain.risk.models import DecisionCase


class Command(BaseCommand):
    help = "미적재 결정 사례를 case_history에 올린다"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100, help="한 번에 처리할 최대 건수")
        parser.add_argument("--list", action="store_true", help="적재하지 않고 밀린 목록만 출력")

    def handle(self, *args, **options):
        pending = DecisionCase.objects.filter(indexed_at__isnull=True)
        if options["list"]:
            self.stdout.write(f"미적재 사례 {pending.count()}건")
            for case in pending[: options["limit"]]:
                mark = f" (실패: {case.index_error[:60]})" if case.index_error else ""
                self.stdout.write(f"  {case.case_id}  {case.expected}→{case.outcome}{mark}")
            return

        tried, ok = case_index.reindex_pending(options["limit"])
        if tried == 0:
            self.stdout.write(self.style.SUCCESS("밀린 사례가 없습니다."))
            return
        style = self.style.SUCCESS if ok == tried else self.style.WARNING
        self.stdout.write(style(f"적재 시도 {tried}건 / 성공 {ok}건"))
        if ok < tried:
            self.stdout.write("실패 사유는 `--list`로 확인하세요(ai 기동·OPENAI_API_KEY 점검).")

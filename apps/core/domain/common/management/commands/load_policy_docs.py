"""얼려 둔 규정문서 적재 결과를 되살린다 — `dump_policy_docs`의 짝.

    docker compose exec core python manage.py load_policy_docs
    docker compose exec core python manage.py load_policy_docs --in /data/var/policy_docs

`seed_adopted`가 끝에서 이걸 부른다(덤프가 있을 때만). 없으면 조용히 넘어간다 —
규정 문서는 **한 번 진짜로 돌려야 생기는 것**이라 시드가 대신 만들 수 없고, 없다고
시드를 실패시킬 일도 아니다(문서 없이도 나머지 화면은 다 산다).

## 지우고 다시 넣는다

`PolicyDoc`을 **통째로 비운 뒤** 넣는다. 문서·조항·별표는 서로 id로 엮여 있어서 부분 갱신을
하면 조항이 옛 문서에 붙거나 별표가 지워진 조항을 가리킨다. 시드가 부르는 경로이므로
「다시 돌리면 처음부터」가 맞다.

## 벡터는 여기서 복원되지 않는다

`PolicyClause.chunk_ids`는 Chroma 문서 id다. 이 커맨드는 그 **번호만** 되살리고 벡터는
안 되살린다 — 둘은 별개 저장소이고 Django는 Chroma에 직접 쓰지 않는다(기술명세서 §5.1).
그래서 끝에 **무엇을 더 복원해야 하는지 출력한다.** 안 하면 문서 화면은 멀쩡히 뜨는데
그 조항을 근거로 끌어오는 검색만 조용히 빈손이 된다.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from domain.policies.models import (
    PolicyClause, PolicyDoc, PolicyFolder, PolicyTable, PolicyTableProposal,
)

from .dump_policy_docs import DEFAULT_OUT, FORMAT_VERSION

#: 날짜로 되돌릴 필드. JSON에는 문자열로 들어 있다.
DATE_FIELDS = {"effective_date", "superseded_date"}


def _dates(row: dict) -> dict:
    return {k: (dt.date.fromisoformat(v) if k in DATE_FIELDS and v else v)
            for k, v in row.items()}


class Command(BaseCommand):
    help = "덤프해 둔 규정문서 적재 결과를 되살린다(벡터는 ai의 snapshot restore로)"

    def add_arguments(self, parser):
        parser.add_argument("--in", dest="in_dir", default=DEFAULT_OUT,
                            help=f"덤프 디렉터리 (기본 {DEFAULT_OUT})")
        parser.add_argument("--quiet-missing", action="store_true",
                            help="덤프가 없어도 경고 없이 넘어간다(시드가 부를 때)")

    def handle(self, *args, **options):
        path = Path(options["in_dir"])
        if not path.is_absolute():
            path = Path(settings.BASE_DIR) / path
        fixture = path / "fixture.json"
        if not fixture.exists():
            if options["quiet_missing"]:
                return
            raise CommandError(
                f"덤프가 없다: {fixture}\n"
                "규정 문서는 한 번 실제로 적재해야 생긴다 — 화면에서 문서를 올려 적재가 끝난 뒤 "
                "`manage.py dump_policy_docs`로 얼려 둘 것."
            )
        payload = json.loads(fixture.read_text(encoding="utf-8"))
        if payload.get("format") != FORMAT_VERSION:
            #  **폴백하지 않는다.** 반쯤 읽어 들인 규정 문서는 화면에서 정상처럼 보인다.
            raise CommandError(
                f"덤프 형식이 다르다(파일 {payload.get('format')} / 코드 {FORMAT_VERSION}). "
                "덤프를 다시 뜰 것."
            )

        verbosity = int(options.get("verbosity", 1))
        with transaction.atomic():
            PolicyTableProposal.objects.all().delete()
            PolicyTable.objects.all().delete()
            PolicyClause.objects.all().delete()
            PolicyDoc.objects.all().delete()
            PolicyFolder.objects.all().delete()

            folders = self._folders(payload.get("folders") or [])
            docs = self._docs(payload["docs"], folders, path / "files")
            self._link_superseded(payload["docs"], docs)
            tables = self._tables(payload.get("tables") or [], docs)
            self._proposals(payload["docs"], docs, tables)

        if not verbosity:
            return
        chroma = payload.get("chroma") or {}
        self.stdout.write(self.style.SUCCESS(
            f"규정문서 복원 <- {path}\n"
            f"  문서 {PolicyDoc.objects.count()} / 조항 {PolicyClause.objects.count()} / "
            f"별표 {PolicyTable.objects.count()} / 제안 {PolicyTableProposal.objects.count()}"
        ))
        #  **여기서 멈추면 반쪽이다.** 조항의 `chunk_ids`는 되살아났지만 그 청크의 벡터는
        #  Chroma에 있고 이 커맨드는 거기 쓰지 않는다.
        self.stdout.write(self.style.WARNING(
            "  벡터는 아직 복원되지 않았다 — 검색은 이 문서들을 못 찾는다:\n"
            "    docker compose exec ai python -m app.rag.embedding.snapshot restore "
            "--in /data/rag_snapshot\n"
            f"    (필요 컬렉션: {', '.join(chroma.get('collections') or []) or '-'} / "
            f"doc_id {len(chroma.get('doc_ids') or [])}종)"
        ))

    # ── 조립 ─────────────────────────────────────────────────────────────
    def _folders(self, rows: list[dict]) -> dict[str, PolicyFolder]:
        """부모가 먼저 만들어지도록 두 바퀴 돈다(덤프 순서를 믿지 않는다)."""
        made: dict[str, PolicyFolder] = {}
        for row in rows:
            if not row["parent"]:
                made[row["name"]] = PolicyFolder.objects.create(
                    name=row["name"], order=row["order"])
        for row in rows:
            if row["parent"] and row["name"] not in made:
                made[row["name"]] = PolicyFolder.objects.create(
                    name=row["name"], order=row["order"], parent=made.get(row["parent"]))
        return made

    def _docs(self, rows: list[dict], folders: dict, files_dir: Path) -> dict[str, PolicyDoc]:
        made: dict[str, PolicyDoc] = {}
        for row in rows:
            fields = {k: v for k, v in row.items()
                      if k not in ("clauses", "proposals", "folder", "superseded_by", "file_name")}
            doc = PolicyDoc.objects.create(
                folder=folders.get(row["folder"]), **_dates(fields))
            name = row.get("file_name")
            if name and (files_dir / name).exists():
                with open(files_dir / name, "rb") as handle:
                    doc.file.save(name, File(handle), save=True)
            #  `indexed_at`은 `auto_now_add`가 아니라 평범한 컬럼이지만, 덤프 시점을
            #  그대로 옮기면 "3개월 전에 적재된 문서"가 된다. 복원 시각으로 둔다 —
            #  이 문서는 방금 이 환경에 들어온 게 맞다.
            PolicyClause.objects.bulk_create([
                PolicyClause(doc=doc, **_dates(clause)) for clause in row["clauses"]
            ])
            made[row["title"]] = doc
        return made

    def _link_superseded(self, rows: list[dict], docs: dict[str, PolicyDoc]) -> None:
        """구판 → 현행본 참조는 문서가 다 만들어진 뒤에 잇는다."""
        for row in rows:
            target = docs.get(row.get("superseded_by") or "")
            if target is not None:
                doc = docs[row["title"]]
                doc.superseded_by = target
                doc.save(update_fields=["superseded_by"])

    def _tables(self, rows: list[dict], docs: dict[str, PolicyDoc]) -> dict[str, PolicyTable]:
        made: dict[str, PolicyTable] = {}
        for row in rows:
            fields = {k: v for k, v in row.items() if k != "doc"}
            table = PolicyTable.objects.create(
                source_doc=docs.get(row.get("doc") or ""), **_dates(fields))
            made[table.key] = table
        return made

    def _proposals(self, rows: list[dict], docs: dict, tables: dict) -> None:
        for row in rows:
            doc = docs[row["title"]]
            for proposal in row["proposals"]:
                fields = {k: v for k, v in proposal.items() if k != "approved_key"}
                PolicyTableProposal.objects.create(
                    doc=doc,
                    #  승인된 제안은 만들어진 별표를 가리킨다. 이 고리가 끊기면 화면이
                    #  "승인됨"이라고만 하고 **무엇이 저장됐는지 못 보여준다**.
                    approved_table=tables.get(proposal.get("approved_key") or ""),
                    **_dates(fields),
                )

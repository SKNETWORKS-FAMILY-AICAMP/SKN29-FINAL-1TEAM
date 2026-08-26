"""**실제로 돌린 규정문서 적재 결과**를 파일로 얼려 둔다 — 시드가 그걸 다시 얹는다.

    docker compose exec core python manage.py dump_policy_docs
    docker compose exec core python manage.py dump_policy_docs --out /data/var/policy_docs

## 왜 필요한가 — 시드가 만들 수 없는 것

`seed_clean`은 규정 문서를 **하나도 만들지 않는다**(만들 수가 없다). 문서 하나가 화면에
뜨려면 파싱·프로파일 판정·조 단위 청킹·임베딩·Chroma upsert·조항 분류(triage)·별표 추출이
차례로 돌아야 하고, 그중 **분류와 별표 추출은 LLM 호출이며 청킹 결과는 파서 버전에 딸려
있다.** 시드가 그 결과를 손으로 적으면 두 가지가 어긋난다.

  · 조항 본문·페이지·`chunk_ids`가 **실제 파싱 결과와 다른 값**이 된다. `chunk_ids`는
    Chroma 문서 id라, 손으로 지어내면 조항에서 근거 청크로 가는 길이 끊긴다.
  · 분류·우선순위·별표 후보가 **모델이 실제로 낸 판단과 다른 값**이 된다. 그러면 화면에서
    "AI가 이렇게 봤다"고 보여주는 것이 사실이 아니게 된다.

그래서 **한 번은 진짜로 돌리고, 그 결과를 얼려서 재생한다.** 파서·모델·비용을 매번 태우지
않으면서 화면에는 진짜 산출물이 뜬다.

## 벡터는 여기 없다 — 두 절반을 같이 옮겨야 한다

이 덤프는 **Postgres 절반**이다(문서 메타·조항·별표·제안). 검색에 쓰이는 **청크 벡터는
Chroma에 있고 별개 저장소**라 여기 들어오지 않는다. 둘은 `PolicyClause.chunk_ids`로
이어져 있어서, 한쪽만 옮기면 **에러 없이 조용히 반쪽이 된다** — 문서 화면은 멀쩡히 뜨는데
그 조항을 근거로 끌어오는 검색이 아무것도 못 찾는다.

벡터 쪽은 이미 있는 CLI로 뜬다(재임베딩 0회·과금 0):

    docker compose exec ai python -m app.rag.embedding.snapshot dump    --out /data/rag_snapshot
    docker compose exec ai python -m app.rag.embedding.snapshot restore --in  /data/rag_snapshot

**같은 시점에 뜨고 같이 복원한다.** 덤프에 `doc_id`와 컬렉션을 적어 두고, 복원할 때
`load_policy_docs`가 무엇을 같이 되살려야 하는지 출력한다.

## 원본 파일

`PolicyDoc.file`(업로드 원본)은 media 볼륨에 있고 JSON에 담을 수 없다. `files/`에 복사해
같이 옮긴다 — 없으면 화면의 「원본 열기」가 죽는다.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from domain.policies.models import (
    PolicyClause, PolicyDoc, PolicyFolder, PolicyTable, PolicyTableProposal,
)

#: 기본 산출 경로. `var/`는 시드 산출물이 모이는 자리다(`adopted_golden.json`과 같은 급).
DEFAULT_OUT = "var/policy_docs"

#: 덤프 형식 버전. 필드를 늘리면 올리고, 로더가 모르는 버전이면 **폴백하지 않고 멈춘다** —
#  반쯤 읽어 들인 규정 문서는 화면에서 정상처럼 보이므로 조용한 실패가 가장 나쁘다.
FORMAT_VERSION = 1

#: 사람·시각처럼 **이 저장소 밖에서 의미가 없는 것**은 담지 않는다. 로더가 다시 붙인다.
#  (`uploaded_by`/`decided_by`는 시드가 만든 사용자를 가리키므로 id를 옮기면 엉뚱한
#  사람이 된다. `id`도 마찬가지 — 로더가 새로 딴다.)
DOC_FIELDS = (
    "title", "category", "version", "effective_date", "file_size", "status", "doc_id",
    "profile", "profile_hint", "collection", "chunk_count", "leaf_count", "error",
    "rule_trigger", "rule_scope",
)
CLAUSE_FIELDS = (
    "order", "article_no", "article_label", "article_title", "citation", "body",
    "page_start", "page_end", "chunk_ids", "triage_kind", "triage_priority",
    "triage_reason", "triage_summary", "decision", "decision_reason",
)
TABLE_FIELDS = ("key", "title", "key_axes", "payload", "strict_keys", "effective_date",
                "superseded_date")
PROPOSAL_FIELDS = (
    "source_chunk_id", "source_label", "citation", "page_start", "page_end", "raw_markdown",
    "key", "title", "key_axes", "payload", "strict_keys", "effective_date", "confidence",
    "notes", "comment", "usage_note", "checks", "skip_reason", "status", "review_note",
)


def _values(obj, fields) -> dict:
    out = {}
    for name in fields:
        value = getattr(obj, name)
        out[name] = value.isoformat() if hasattr(value, "isoformat") else value
    return out


class Command(BaseCommand):
    help = "규정문서 적재 결과(Postgres 절반)를 파일로 덤프한다 — 벡터는 ai의 snapshot CLI로"

    def add_arguments(self, parser):
        parser.add_argument("--out", default=DEFAULT_OUT, help=f"덤프 디렉터리 (기본 {DEFAULT_OUT})")
        parser.add_argument("--no-files", action="store_true",
                            help="원본 파일을 복사하지 않는다(메타만 옮길 때)")

    def handle(self, *args, **options):
        out = Path(options["out"])
        if not out.is_absolute():
            out = Path(settings.BASE_DIR) / out
        docs = list(PolicyDoc.objects.select_related("folder").order_by("id"))
        if not docs:
            self.stdout.write(self.style.WARNING(
                "적재된 규정 문서가 없다 — 화면에서 문서를 올려 적재를 끝낸 뒤 다시 실행할 것."
            ))
            return

        out.mkdir(parents=True, exist_ok=True)
        files_dir = out / "files"
        payload = {
            "format": FORMAT_VERSION,
            #  **벡터 쪽에 무엇이 있어야 하는지**를 같이 적는다. 로더가 이걸 그대로 출력해
            #  "이것도 복원해야 한다"를 말해 준다(§모듈 docstring).
            "chroma": {
                "collections": sorted({d.collection for d in docs if d.collection}),
                "doc_ids": sorted({d.doc_id for d in docs if d.doc_id}),
            },
            "folders": self._folders(),
            "docs": [],
            "tables": [_values(t, TABLE_FIELDS) | {"doc": self._doc_key(t.source_doc),
                                                  "source_clause": t.source_clause}
                      for t in PolicyTable.objects.select_related("source_doc").order_by("id")],
        }

        copied = 0
        for doc in docs:
            row = _values(doc, DOC_FIELDS)
            row["folder"] = doc.folder.name if doc.folder else ""
            row["superseded_by"] = self._doc_key(doc.superseded_by)
            row["clauses"] = [_values(c, CLAUSE_FIELDS)
                              for c in doc.clauses.all().order_by("order", "id")]
            row["proposals"] = [
                _values(p, PROPOSAL_FIELDS) | {"approved_key": (p.approved_table.key
                                                               if p.approved_table_id else "")}
                for p in doc.table_proposals.select_related("approved_table").order_by("id")
            ]
            row["file_name"] = ""
            if doc.file and not options["no_files"]:
                source = Path(doc.file.path)
                if source.exists():
                    files_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, files_dir / source.name)
                    row["file_name"] = source.name
                    copied += 1
                else:
                    #  **감추지 않는다.** 원본이 없으면 복원본의 「원본 열기」가 죽는데,
                    #  그건 복원할 때가 아니라 시연 중에 드러난다.
                    self.stdout.write(self.style.WARNING(
                        f"  원본 없음: {doc.title} ({doc.file.name})"
                    ))
            payload["docs"].append(row)

        (out / "fixture.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

        clauses = sum(len(d["clauses"]) for d in payload["docs"])
        proposals = sum(len(d["proposals"]) for d in payload["docs"])
        self.stdout.write(self.style.SUCCESS(
            f"규정문서 덤프 -> {out}\n"
            f"  문서 {len(docs)} / 조항 {clauses} / 별표 제안 {proposals} / "
            f"확정 별표 {len(payload['tables'])} / 원본 파일 {copied}"
        ))
        self.stdout.write(
            "  벡터는 이 덤프에 없다. 같은 시점에 함께 뜰 것:\n"
            "    docker compose exec ai python -m app.rag.embedding.snapshot dump "
            "--out /data/rag_snapshot\n"
            f"  (컬렉션 {', '.join(payload['chroma']['collections']) or '-'} / "
            f"doc_id {len(payload['chroma']['doc_ids'])}종)"
        )

    def _folders(self) -> list[dict]:
        """폴더는 **이름으로 잇는다** — id는 복원 때 새로 딴다."""
        return [{"name": f.name, "parent": f.parent.name if f.parent else "", "order": f.order}
                for f in PolicyFolder.objects.select_related("parent").order_by("id")]

    @staticmethod
    def _doc_key(doc) -> str:
        """문서 간 참조는 제목으로 잇는다(같은 회사 안에서 유일하다)."""
        return doc.title if doc is not None else ""

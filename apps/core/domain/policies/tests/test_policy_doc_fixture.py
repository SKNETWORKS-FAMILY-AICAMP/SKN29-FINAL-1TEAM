"""규정문서 적재 결과 덤프·복원 왕복 회귀.

시드가 만들 수 없는 것을 옮기는 경로다 — 파싱·청킹·임베딩·조항 분류·별표 추출이 다 돌아야
생기고 그중 둘은 LLM 호출이라, **한 번 진짜로 돌린 결과를 얼려서 재생**한다.

여기서 고정하는 계약 넷:

① **id가 아니라 이름으로 잇는다.** 복원하면 id가 새로 딸리므로, 폴더·구판 참조·승인된
   별표를 id로 적어 두면 엉뚱한 행을 가리킨다.
② **`chunk_ids`가 그대로 온다.** Chroma 문서 id라 값이 하나만 달라져도 조항에서 근거
   청크로 가는 길이 끊긴다 — 그리고 그건 검색이 빈손일 때야 드러난다.
③ **승인된 제안 → 별표 고리가 유지된다.** 끊기면 화면이 "승인됨"이라고만 하고 무엇이
   저장됐는지 못 보여준다.
④ **형식 버전이 다르면 멈춘다.** 반쯤 읽어 들인 규정 문서는 화면에서 정상처럼 보인다.
"""
from __future__ import annotations

import datetime as dt
import json
import shutil
import tempfile
from pathlib import Path

from django.core.management import CommandError, call_command
from django.test import TestCase

from domain.policies.models import (
    IngestStatus, PolicyClause, PolicyDoc, PolicyFolder, PolicyTable, PolicyTableProposal,
    TableProposalStatus,
)


class PolicyDocFixtureTests(TestCase):
    def setUp(self):
        self.out = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.out, True)

        root = PolicyFolder.objects.create(name="사내규정")
        child = PolicyFolder.objects.create(name="비용", parent=root, order=1)
        old = PolicyDoc.objects.create(title="회식_사용규정 v1", status=IngestStatus.DONE,
                                       doc_id="aaa111", collection="policy_docs")
        self.doc = PolicyDoc.objects.create(
            title="회식_사용규정", category="회식", version="2.0", folder=child,
            effective_date=dt.date(2026, 3, 1), status=IngestStatus.DONE,
            doc_id="bbb222", profile="regulation", collection="policy_docs",
            chunk_count=41, leaf_count=38, rule_scope="회식",
            rule_trigger={"status": "OK", "graph": "회식 검증 그래프"},
        )
        old.superseded_by = self.doc
        old.save(update_fields=["superseded_by"])

        PolicyClause.objects.create(
            doc=self.doc, order=0, article_no=10, article_label="제10조",
            article_title="(1인당 한도)", citation="회식_사용규정 제10조",
            body="① 회식비는 1인당 5만원을 초과할 수 없다.",
            page_start=3, page_end=3, chunk_ids=["bbb222#c012", "bbb222#c013"],
            triage_kind="RULE", triage_priority="P1", triage_reason="한도 조항",
            triage_summary="1인당 5만원 상한",
        )
        PolicyClause.objects.create(
            doc=self.doc, order=1, article_label="제11조", body="② 주류만으로 구성할 수 없다.",
            chunk_ids=["bbb222#c020"], decision="SKIP", decision_reason="룰로 만들지 않음",
        )
        table = PolicyTable.objects.create(
            key="dining_per_person_limit", title="별표1 1인당 한도",
            key_axes=["user.job_title"], payload={"부서장": 70000, "*": 50000},
            source_doc=self.doc, source_clause="회식_사용규정 제10조",
            effective_date=dt.date(2026, 3, 1),
        )
        PolicyTableProposal.objects.create(
            doc=self.doc, source_chunk_id="bbb222#t001", source_label="별표1",
            citation="회식_사용규정 별표1", raw_markdown="| 직책 | 한도 |\n|---|---|",
            key="dining_per_person_limit", title="별표1 1인당 한도",
            key_axes=["user.job_title"], payload={"부서장": 70000, "*": 50000},
            effective_date=dt.date(2026, 3, 1), confidence=0.88,
            comment="직책별로 갈리는 표입니다.", status=TableProposalStatus.APPROVED,
            approved_table=table,
        )

    def _round_trip(self):
        call_command("dump_policy_docs", "--out", str(self.out), verbosity=0)
        PolicyDoc.objects.all().delete()
        PolicyFolder.objects.all().delete()
        PolicyTable.objects.all().delete()
        self.assertEqual(PolicyClause.objects.count(), 0)
        call_command("load_policy_docs", "--in", str(self.out), verbosity=0)

    # ── ① 이름으로 잇는다 ────────────────────────────────────────────────
    def test_문서와_조항이_그대로_돌아온다(self):
        self._round_trip()
        doc = PolicyDoc.objects.get(title="회식_사용규정")
        self.assertEqual(doc.chunk_count, 41)
        self.assertEqual(doc.effective_date, dt.date(2026, 3, 1))
        self.assertEqual(doc.rule_trigger["graph"], "회식 검증 그래프")
        self.assertEqual(doc.clauses.count(), 2)

    def test_폴더_계층이_이름으로_이어진다(self):
        self._round_trip()
        doc = PolicyDoc.objects.get(title="회식_사용규정")
        self.assertEqual(doc.folder.name, "비용")
        self.assertEqual(doc.folder.parent.name, "사내규정")

    def test_구판이_현행본을_가리킨다(self):
        self._round_trip()
        old = PolicyDoc.objects.get(title="회식_사용규정 v1")
        self.assertEqual(old.superseded_by.title, "회식_사용규정")

    # ── ② 청크 id ────────────────────────────────────────────────────────
    def test_chunk_ids가_한_글자도_안_바뀐다(self):
        """Chroma 문서 id다. 달라지면 조항에서 근거 청크로 가는 길이 끊기는데,
        그건 화면이 아니라 **검색이 빈손일 때** 드러난다."""
        self._round_trip()
        clause = PolicyClause.objects.get(article_label="제10조")
        self.assertEqual(clause.chunk_ids, ["bbb222#c012", "bbb222#c013"])

    def test_사람의_결정이_보존된다(self):
        """`decision`은 사람이 「이건 룰로 만들지 않겠다」고 정한 것이다 — AI 분류와 다른 축."""
        self._round_trip()
        clause = PolicyClause.objects.get(article_label="제11조")
        self.assertEqual(clause.decision, "SKIP")
        self.assertEqual(clause.decision_reason, "룰로 만들지 않음")
        self.assertEqual(PolicyClause.objects.get(article_label="제10조").triage_priority, "P1")

    # ── ③ 별표 고리 ──────────────────────────────────────────────────────
    def test_승인된_제안이_별표를_가리킨다(self):
        self._round_trip()
        proposal = PolicyTableProposal.objects.get(key="dining_per_person_limit")
        self.assertEqual(proposal.status, TableProposalStatus.APPROVED)
        self.assertIsNotNone(proposal.approved_table)
        self.assertEqual(proposal.approved_table.payload, {"부서장": 70000, "*": 50000})
        self.assertEqual(proposal.approved_table.source_doc.title, "회식_사용규정")

    def test_별표_축과_값이_그대로다(self):
        """축 표기가 한 글자만 달라져도 룩업이 조용히 와일드카드로 떨어진다."""
        self._round_trip()
        table = PolicyTable.objects.get(key="dining_per_person_limit")
        self.assertEqual(table.key_axes, ["user.job_title"])
        self.assertEqual(table.effective_date, dt.date(2026, 3, 1))

    # ── 벡터가 따로라는 사실을 덤프가 들고 있다 ──────────────────────────
    def test_덤프가_복원해야_할_벡터를_적어_둔다(self):
        """두 절반이 따로 산다 — 한쪽만 옮기면 **에러 없이 조용히** 반쪽이 된다."""
        call_command("dump_policy_docs", "--out", str(self.out), verbosity=0)
        payload = json.loads((self.out / "fixture.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["chroma"]["collections"], ["policy_docs"])
        self.assertEqual(sorted(payload["chroma"]["doc_ids"]), ["aaa111", "bbb222"])

    # ── ④ 형식 버전 ──────────────────────────────────────────────────────
    def test_형식_버전이_다르면_멈춘다(self):
        call_command("dump_policy_docs", "--out", str(self.out), verbosity=0)
        path = self.out / "fixture.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["format"] = 99
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(CommandError):
            call_command("load_policy_docs", "--in", str(self.out), verbosity=0)

    def test_덤프가_없으면_시드는_그냥_넘어간다(self):
        """규정 문서는 한 번 진짜로 돌려야 생긴다 — 없다고 시드를 실패시킬 일이 아니다."""
        call_command("load_policy_docs", "--in", str(self.out / "없음"),
                     quiet_missing=True, verbosity=0)
        with self.assertRaises(CommandError):
            call_command("load_policy_docs", "--in", str(self.out / "없음"), verbosity=0)

    def test_복원은_기존_문서를_지우고_넣는다(self):
        """부분 갱신을 하면 조항이 옛 문서에 붙는다. 시드가 부르는 경로라 「처음부터」가 맞다."""
        call_command("dump_policy_docs", "--out", str(self.out), verbosity=0)
        call_command("load_policy_docs", "--in", str(self.out), verbosity=0)
        call_command("load_policy_docs", "--in", str(self.out), verbosity=0)
        self.assertEqual(PolicyDoc.objects.count(), 2)
        self.assertEqual(PolicyClause.objects.count(), 2)
        self.assertEqual(PolicyTableProposal.objects.count(), 1)

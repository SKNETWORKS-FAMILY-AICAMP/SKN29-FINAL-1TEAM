"""별표 승인 + 조항 분류 회귀.

여기서 고정하는 계약 넷:

① **미승인 임계값은 판정에 새지 않는다.** 제안이 `PolicyTable`과 별도 모델인 이유가
   그것이고, 모델을 갈라 둔 것만으로는 부족하다 — 승인 전에 `policy_fields()`에 안
   나타나는지를 실제로 확인한다.

② **축은 승인에서 막힌다.** 스키마에 없는 축은 `strict_keys=False` 표를 조용히 기본값으로
   떨어뜨린다(값도 나오고 에러도 없다). 경고가 아니라 거부여야 한다.

③ **사람이 처리한 것은 재색인이 지우지 않는다.** 승인된 제안을 지우면 실물과의 연결이
   끊기고, 반려한 제안을 지우면 같은 표가 매번 되살아난다.

④ **분류는 제안이지 차단이 아니다.** `SKIP`으로 분류된 조항에서도 룰 생성을 부를 수 있다.
"""
from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from domain.accounts.models import Capability
from domain.policies import table_proposals
from domain.policies.context_builder import load_tables, policy_fields
from domain.policies.models import (
    ClauseKind, ClausePriority, PolicyClause, PolicyDoc, PolicyTable,
    PolicyTableProposal, TableProposalStatus,
)
from domain.policies.policy_doc_views import _replace_clauses, _replace_table_proposals

EFF = date(2026, 1, 1)
User = get_user_model()


def make_proposal(doc, **over) -> PolicyTableProposal:
    defaults = dict(
        source_chunk_id="c1", source_label="별표1", raw_markdown="| 직책 | 한도 |",
        key="welfare_limit_table", title="복리후생비 한도",
        key_axes=["user.job_title"], payload={"부서장": 200_000, "*": 100_000},
        effective_date=EFF, confidence=0.8,
    )
    defaults.update(over)
    return PolicyTableProposal.objects.create(doc=doc, **defaults)


class ProposalBase(TestCase):
    def setUp(self):
        self.doc = PolicyDoc.objects.create(title="법인카드 사용규정", status="DONE")


class ValidationTests(ProposalBase):
    """② 승인 검사"""

    def test_정상_제안은_통과한다(self):
        self.assertEqual(table_proposals.validate(make_proposal(self.doc)), [])

    def test_스키마에_없는_축은_거부된다(self):
        p = make_proposal(self.doc, key_axes=["user.position"])
        problems = table_proposals.validate(p)
        self.assertTrue(any("user.position" in x for x in problems))
        with self.assertRaises(table_proposals.ProposalError):
            table_proposals.approve(p)
        # 거부됐으면 실물이 생기지 않아야 한다.
        self.assertFalse(PolicyTable.objects.filter(key=p.key).exists())

    def test_key_표기_규칙(self):
        for bad in ("Welfare", "복리후생", "a", "with-dash"):
            with self.subTest(key=bad):
                problems = table_proposals.validate(make_proposal(self.doc, key=bad, source_chunk_id=bad))
                self.assertTrue(any("표기 규칙" in x for x in problems))

    def test_축_깊이와_payload_구조가_맞아야_한다(self):
        shallow = make_proposal(self.doc, key_axes=["user.job_title", "trip.trip_type"])
        self.assertTrue(any("얕습니다" in x for x in table_proposals.validate(shallow)))

        deep = make_proposal(self.doc, source_chunk_id="c2", key_axes=[],
                             payload={"부서장": {"국내": 1}})
        self.assertTrue(table_proposals.validate(deep))

    def test_축_없는_표는_value_형태여야_한다(self):
        p = make_proposal(self.doc, key_axes=[], payload={"*": 50_000})
        self.assertTrue(any("value" in x for x in table_proposals.validate(p)))
        p.payload = {"value": 50_000}
        self.assertEqual(table_proposals.validate(p), [])

    def test_시행일이_없으면_거부된다(self):
        p = make_proposal(self.doc, effective_date=None)
        self.assertTrue(any("시행일" in x for x in table_proposals.validate(p)))


class ApprovalTests(ProposalBase):
    """① 승인해야 판정에 들어간다"""

    def test_승인_전에는_판정_변수가_아니다(self):
        make_proposal(self.doc)
        self.assertNotIn("welfare_limit", policy_fields(load_tables(EFF)))

    def test_승인하면_판정_변수가_된다(self):
        p = make_proposal(self.doc)
        table = table_proposals.approve(p)
        self.assertEqual(table.key, "welfare_limit_table")
        self.assertEqual(policy_fields(load_tables(EFF)).get("welfare_limit"), "welfare_limit_table")
        p.refresh_from_db()
        self.assertEqual(p.status, TableProposalStatus.APPROVED)
        self.assertEqual(p.approved_table_id, table.pk)
        # 출처가 남아야 "이 임계값이 어느 문서에서 왔나"를 되짚을 수 있다.
        self.assertEqual(table.source_doc_id, self.doc.pk)

    def test_개정은_새_행이고_구행은_대체된다(self):
        table_proposals.approve(make_proposal(self.doc))
        later = make_proposal(
            self.doc, source_chunk_id="c2", effective_date=date(2026, 7, 1),
            payload={"부서장": 300_000, "*": 150_000},
        )
        table_proposals.approve(later)
        rows = PolicyTable.objects.filter(key="welfare_limit_table").order_by("effective_date")
        self.assertEqual(rows.count(), 2)          # UPDATE가 아니라 INSERT
        self.assertEqual(rows[0].superseded_date, date(2026, 7, 1))
        # 지금 시점에 유효한 것은 새 행이다.
        self.assertEqual(load_tables(date(2026, 8, 1))["welfare_limit_table"].payload["*"], 150_000)
        # 개정 전 지출은 개정 전 한도로 재현된다.
        self.assertEqual(load_tables(date(2026, 3, 1))["welfare_limit_table"].payload["*"], 100_000)

    def test_반려는_사유가_필수다(self):
        p = make_proposal(self.doc)
        with self.assertRaises(table_proposals.ProposalError):
            table_proposals.reject(p, note="  ")
        table_proposals.reject(p, note="결재선 서식이라 임계값이 없음")
        p.refresh_from_db()
        self.assertEqual(p.status, TableProposalStatus.REJECTED)
        self.assertNotIn("welfare_limit", policy_fields(load_tables(EFF)))


class ReindexTests(ProposalBase):
    """③ 재색인이 사람의 처리를 지우지 않는다"""

    def test_승인_반려한_제안은_남고_대기중인_것만_교체된다(self):
        approved = make_proposal(self.doc, source_chunk_id="keep-approved")
        table_proposals.approve(approved)
        rejected = make_proposal(self.doc, source_chunk_id="keep-rejected", key="other_table")
        table_proposals.reject(rejected, note="임계값 아님")
        make_proposal(self.doc, source_chunk_id="stale-pending", key="stale_table")

        _replace_table_proposals(self.doc, [
            {"chunkId": "keep-approved", "key": "welfare_limit_table", "label": "별표1"},
            {"chunkId": "keep-rejected", "key": "other_table", "label": "별표2"},
            {"chunkId": "fresh", "key": "new_table", "label": "별표3", "payload": {"value": 1}},
        ])

        rows = {p.source_chunk_id: p for p in self.doc.table_proposals.all()}
        self.assertEqual(set(rows), {"keep-approved", "keep-rejected", "fresh"})
        self.assertEqual(rows["keep-approved"].status, TableProposalStatus.APPROVED)
        self.assertEqual(rows["keep-rejected"].status, TableProposalStatus.REJECTED)
        # 승인 실물은 그대로 살아 있다.
        self.assertTrue(PolicyTable.objects.filter(key="welfare_limit_table").exists())

    def test_조항_분류는_매_적재마다_새로_온다(self):
        """사람의 결정과 달리 이월하지 않는다 — 문서가 바뀌었는데 옛 분류를 물려주면
        그게 곧 틀린 제안이 된다."""
        _replace_clauses(self.doc, [{
            "articleLabel": "제9조", "triageKind": "RULE", "triagePriority": "AUTO",
            "triageSummary": "1인당 한도 초과 검사", "triageReason": "한도가 명시돼 있다",
        }])
        clause = self.doc.clauses.get()
        self.assertEqual(clause.triage_kind, ClauseKind.RULE)
        self.assertEqual(clause.triage_priority, ClausePriority.AUTO)
        self.assertIsNotNone(clause.triaged_at)

        _replace_clauses(self.doc, [{"articleLabel": "제9조"}])
        self.assertEqual(self.doc.clauses.get().triage_kind, "")

    def test_시행일이_없으면_적재일로_채운다(self):
        """시행일이 비면 **승인 자체가 막힌다**. 업로드가 문서 시행일을 받지 않아 실제로
        전건이 그 상태였다 — 빈 채로 두면 화면에도 「고칠 것이 있다」가 안 보인다."""
        _replace_table_proposals(self.doc, [
            {"chunkId": "c9", "key": "new_table", "label": "별표9", "payload": {"value": 1}},
        ])
        self.assertEqual(self.doc.table_proposals.get().effective_date, timezone.localdate())

    def test_모르는_분류값은_버리고_적재는_계속된다(self):
        _replace_clauses(self.doc, [
            {"articleLabel": "제1조", "triageKind": "WHATEVER", "triagePriority": "P9"},
        ])
        clause = self.doc.clauses.get()
        self.assertEqual(clause.triage_kind, "")
        self.assertEqual(clause.triage_priority, "")


class ApiTests(ProposalBase):
    """④ 분류는 차단이 아니다 + API 가드"""

    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user("acc", password="p", first_name="회계")
        self.user.extra_capabilities = [Capability.RULE_VIEW]
        self.user.save()
        self.client.force_login(self.user)

    def test_제안_목록에_축_후보가_함께_온다(self):
        make_proposal(self.doc)
        res = self.client.get(f"/api/policy-docs/{self.doc.pk}/table-proposals/")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(len(body["proposals"]), 1)
        paths = {a["path"] for a in body["axisOptions"]}
        self.assertIn("user.job_title", paths)
        # 축 후보에 `policy.*`·감사 섹션은 없다 — 별표의 축이 될 수 없다.
        self.assertFalse(any(p.startswith(("policy.", "tables.", "meta.")) for p in paths))

    def test_승인_전에_문제를_알려준다(self):
        make_proposal(self.doc, key_axes=["user.position"])
        body = self.client.get(f"/api/policy-docs/{self.doc.pk}/table-proposals/").json()
        self.assertTrue(body["proposals"][0]["problems"])
        self.assertEqual(body["proposals"][0]["policyVar"], "policy.welfare_limit")

    def test_승인_API가_사유_전부를_돌려준다(self):
        p = make_proposal(self.doc, key="BAD", key_axes=["user.position"])
        res = self.client.post(
            f"/api/policy-docs/{self.doc.pk}/table-proposals/{p.pk}/decision/",
            {"action": "APPROVE"}, content_type="application/json",
        )
        self.assertEqual(res.status_code, 400)
        detail = res.json()["detail"]
        self.assertIn("표기 규칙", detail)
        self.assertIn("user.position", detail)

    def test_승인이_화면에서_고친_값을_함께_받는다(self):
        """따로 저장하지 않고 승인을 누르면 서버가 옛 값으로 검사해 400이 난다 — 화면에는
        고친 값이 그대로 보이므로 왜 막혔는지 알 수 없는 자리가 된다."""
        p = make_proposal(self.doc, key_axes=["user.position"], effective_date=None)
        res = self.client.post(
            f"/api/policy-docs/{self.doc.pk}/table-proposals/{p.pk}/decision/",
            {"action": "APPROVE", "keyAxes": ["user.job_title"], "effectiveDate": "2026-01-01"},
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200, res.json())
        table = PolicyTable.objects.get(key="welfare_limit_table")
        self.assertEqual(table.key_axes, ["user.job_title"])
        self.assertEqual(table.effective_date, EFF)

    def test_반려는_고친_값을_반영하지_않는다(self):
        """반려는 값을 쓰지 않는다 — 손대면 「무엇을 보고 반려했나」가 흐려진다."""
        p = make_proposal(self.doc)
        res = self.client.post(
            f"/api/policy-docs/{self.doc.pk}/table-proposals/{p.pk}/decision/",
            {"action": "REJECT", "note": "서식이라 임계값 없음", "title": "바꿔치기"},
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        p.refresh_from_db()
        self.assertEqual(p.title, "복리후생비 한도")

    def test_처리된_제안은_수정할_수_없다(self):
        p = make_proposal(self.doc)
        table_proposals.approve(p)
        res = self.client.post(
            f"/api/policy-docs/{self.doc.pk}/table-proposals/{p.pk}/",
            {"title": "바꿔치기"}, content_type="application/json",
        )
        self.assertEqual(res.status_code, 400)
        p.refresh_from_db()
        self.assertEqual(p.title, "복리후생비 한도")

    def test_SKIP으로_분류된_조항도_룰_생성을_부를_수_있다(self):
        """분류는 제안이지 차단이 아니다 — 400/403이 아니라 AI 호출까지 간다."""
        self.doc.rule_scope = "식대"
        self.doc.save()
        clause = PolicyClause.objects.create(
            doc=self.doc, article_label="제3조", article_title="(정의)", body="용어의 뜻은…",
            triage_kind=ClauseKind.INFO, triage_priority=ClausePriority.SKIP,
        )
        res = self.client.post(
            f"/api/policy-docs/{self.doc.pk}/clauses/{clause.pk}/generate-rule/",
            {}, content_type="application/json",
        )
        # ai가 안 떠 있으므로 503이 정상 — 인가·분류로 막히지 않았다는 뜻이다.
        self.assertEqual(res.status_code, 503)
        self.assertIn("연결하지 못했습니다", res.json()["detail"])

    def test_비용분류가_없으면_무엇을_해야_하는지_알려준다(self):
        clause = PolicyClause.objects.create(doc=self.doc, article_label="제3조")
        res = self.client.post(
            f"/api/policy-docs/{self.doc.pk}/clauses/{clause.pk}/generate-rule/",
            {}, content_type="application/json",
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("비용분류", res.json()["detail"])

"""규정 문서 적재 API 회귀 테스트.

고정하는 계약:
  ① **인가** — 규정 코퍼스를 바꾸는 일이라 `rule_view` 없이는 조회도 못 한다.
  ② **업로드는 접수까지** — ai 호출은 실패해도 파일을 되돌리지 않고 FAILED로 남긴다.
  ③ **콜백은 인증된 쓰기** — 익명이 적재 상태를 조작할 수 없다.
  ④ **PDF만** — 파싱 파이프라인이 PDF 전용이라 다른 형식은 접수 단계에서 막는다.
"""
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from domain.accounts.models import Role, User
from domain.common.management.commands.ensure_service_account import (
    SERVICE_USERNAME, ensure_service_account,
)
from domain.policies.models import (
    ClauseDecision, IngestStatus, PolicyClause, PolicyDoc, PolicyFolder, RuleGraph, RuleNode,
)
from domain.policies.policy_doc_views import _replace_clauses


def pdf(name="규정.pdf"):
    return SimpleUploadedFile(name, b"%PDF-1.4 fake", content_type="application/pdf")


@override_settings(MEDIA_ROOT="/tmp/skn-test-media")
class PolicyDocUploadTests(TestCase):
    def setUp(self):
        ensure_service_account(password="pw")
        self.client = APIClient()
        self.client.login(username=SERVICE_USERNAME, password="pw")

    def test_upload_creates_doc_and_dispatches(self):
        with patch("domain.policies.policy_doc_views._dispatch", return_value="") as dispatch:
            resp = self.client.post("/api/policy-docs/", {"file": pdf(), "title": "법인카드 사용규정",
                                                          "ruleScope": "기업업무추진비"}, format="multipart")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["status"], IngestStatus.PENDING)
        # 규정 표기가 Category 값으로 접혀 저장돼야 룰 트리거 대상이 맞는다.
        self.assertEqual(resp.data["ruleScope"], "접대")
        dispatch.assert_called_once()

    def test_dispatch_failure_keeps_the_file_and_marks_failed(self):
        """ai가 안 떠 있다고 업로드를 되돌리면 사용자는 올린 걸 또 올려야 한다."""
        with patch("domain.policies.policy_doc_views._dispatch", return_value="연결 실패"):
            resp = self.client.post("/api/policy-docs/", {"file": pdf()}, format="multipart")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["status"], IngestStatus.FAILED)
        self.assertIn("연결 실패", resp.data["error"])
        doc = PolicyDoc.objects.get(pk=resp.data["id"])
        self.assertTrue(doc.file)          # 파일은 남아 있어 재색인이 가능하다

    def test_non_pdf_is_rejected_before_dispatch(self):
        bad = SimpleUploadedFile("규정.docx", b"x", content_type="application/msword")
        with patch("domain.policies.policy_doc_views._dispatch") as dispatch:
            resp = self.client.post("/api/policy-docs/", {"file": bad}, format="multipart")
        self.assertEqual(resp.status_code, 400)
        dispatch.assert_not_called()

    def test_reembed_restarts_and_clears_previous_result(self):
        with patch("domain.policies.policy_doc_views._dispatch", return_value=""):
            created = self.client.post("/api/policy-docs/", {"file": pdf()}, format="multipart")
        doc = PolicyDoc.objects.get(pk=created.data["id"])
        PolicyDoc.objects.filter(pk=doc.pk).update(
            status=IngestStatus.FAILED, error="이전 실패", rule_trigger={"status": "NOT_IMPLEMENTED"},
        )
        with patch("domain.policies.policy_doc_views._dispatch", return_value="") as dispatch:
            resp = self.client.post(f"/api/policy-docs/{doc.pk}/reembed/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], IngestStatus.PENDING)
        self.assertEqual(resp.data["error"], "")
        dispatch.assert_called_once()


@override_settings(MEDIA_ROOT="/tmp/skn-test-media")
class PolicyDocAuthorizationTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_anonymous_cannot_list(self):
        self.assertEqual(self.client.get("/api/policy-docs/").status_code, 403)

    def test_user_without_rule_view_cannot_list(self):
        User.objects.create_user("nobody", password="pw", role=Role.EMPLOYEE)
        self.client.login(username="nobody", password="pw")
        self.assertEqual(self.client.get("/api/policy-docs/").status_code, 403)

    def test_accountant_can_list(self):
        # 회계 담당자는 역할 기본으로 rule_view를 갖는다.
        User.objects.create_user("acc", password="pw", role=Role.ACCOUNTANT)
        self.client.login(username="acc", password="pw")
        self.assertEqual(self.client.get("/api/policy-docs/").status_code, 200)


@override_settings(MEDIA_ROOT="/tmp/skn-test-media")
class IngestCallbackTests(TestCase):
    def setUp(self):
        self.doc = PolicyDoc.objects.create(title="법인카드 사용규정", status=IngestStatus.PENDING)
        ensure_service_account(password="pw")
        self.client = APIClient()

    def _url(self):
        return f"/api/internal/policy-docs/{self.doc.pk}/ingest-result/"

    def test_anonymous_callback_is_rejected(self):
        """내부 read API와 달리 이건 쓰기다 — 열어두면 적재 상태를 외부에서 조작할 수 있다."""
        resp = self.client.post(self._url(), {"status": "DONE"}, format="json")
        self.assertEqual(resp.status_code, 403)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.status, IngestStatus.PENDING)

    def test_service_account_records_success(self):
        self.client.login(username=SERVICE_USERNAME, password="pw")
        resp = self.client.post(self._url(), {
            "status": "DONE", "docId": "abc123", "profile": "REGULATION",
            "collection": "policy_docs", "chunkCount": 103, "leafCount": 90,
            "ruleTrigger": {"status": "NOT_IMPLEMENTED", "detail": "룰 자동 생성은 개발 중입니다"},
        }, format="json")
        self.assertEqual(resp.status_code, 200)

        self.doc.refresh_from_db()
        self.assertEqual(self.doc.status, IngestStatus.DONE)
        self.assertEqual(self.doc.chunk_count, 103)
        self.assertEqual(self.doc.leaf_count, 90)
        self.assertEqual(self.doc.collection, "policy_docs")
        self.assertIsNotNone(self.doc.indexed_at)
        # 트리거 틀이 돌려준 "개발 중" 안내가 그대로 화면까지 간다.
        self.assertEqual(self.doc.rule_trigger["status"], "NOT_IMPLEMENTED")

    def test_failure_reason_is_kept(self):
        self.client.login(username=SERVICE_USERNAME, password="pw")
        self.client.post(self._url(), {"status": "FAILED", "error": "청크가 0개입니다"}, format="json")
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.status, IngestStatus.FAILED)
        self.assertIn("청크가 0개", self.doc.error)
        self.assertIsNone(self.doc.indexed_at)

    def test_unknown_status_is_rejected(self):
        self.client.login(username=SERVICE_USERNAME, password="pw")
        resp = self.client.post(self._url(), {"status": "WAT"}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_clauses_are_stored_on_success(self):
        self.client.login(username=SERVICE_USERNAME, password="pw")
        self.client.post(self._url(), {
            "status": "DONE", "clauses": [
                {"articleLabel": "제9조", "articleTitle": "(사용 한도)", "articleNo": 9,
                 "citation": "법인카드_사용규정 제9조", "body": "### 제9조", "order": 0,
                 "chunkIds": ["c1", "c2"]},
                # 조 라벨이 없는 행(별표 등)은 조항이 되지 않는다.
                {"articleLabel": "", "body": "별표1"},
            ],
        }, format="json")
        self.assertEqual(self.doc.clauses.count(), 1)
        clause = self.doc.clauses.first()
        self.assertEqual(clause.article_label, "제9조")
        self.assertEqual(clause.chunk_ids, ["c1", "c2"])


@override_settings(MEDIA_ROOT="/tmp/skn-test-media")
class ClauseDecisionTests(TestCase):
    """조항 상태는 저장하지 않고 계산한다 — 룰은 나중에 생기고 지워진다."""

    def setUp(self):
        self.doc = PolicyDoc.objects.create(title="법인카드 사용규정", status=IngestStatus.DONE)
        self.clause = PolicyClause.objects.create(
            doc=self.doc, article_label="제9조", article_title="(사용 한도)",
            citation="법인카드_사용규정 제9조", body="### 제9조 ...",
        )
        ensure_service_account(password="pw")
        self.client = APIClient()
        self.client.login(username=SERVICE_USERNAME, password="pw")

    def _decide(self, decision, reason=None):
        return self.client.post(
            f"/api/policy-docs/{self.doc.pk}/clauses/{self.clause.pk}/decision/",
            {"decision": decision, **({"reason": reason} if reason else {})}, format="json",
        )

    def test_untouched_clause_needs_review(self):
        resp = self.client.get(f"/api/policy-docs/{self.doc.pk}/clauses/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data[0]["ruleStatus"], "NEEDS_REVIEW")

    def test_linked_when_a_rule_node_cites_it(self):
        """상태가 계산값이라, 룰을 만들기만 해도 조항이 '규칙 연결됨'이 된다."""
        graph = RuleGraph.objects.create(name="법인카드 한도", scope="접대", entry_node_key="n1")
        RuleNode.objects.create(
            graph=graph, node_key="n1", condition=True, condition_text="1회 300만원 초과 시",
            action={"decision": "REVIEW", "title": "한도 초과", "source_clause": "법인카드_사용규정 제9조"},
        )
        resp = self.client.get(f"/api/policy-docs/{self.doc.pk}/clauses/")
        row = resp.data[0]
        self.assertEqual(row["ruleStatus"], "LINKED")
        self.assertEqual(row["linkedRules"][0]["graphName"], "법인카드 한도")
        self.assertEqual(row["linkedRules"][0]["conditionText"], "1회 300만원 초과 시")

    def test_skip_requires_a_reason(self):
        # 나중에 "왜 이 조항엔 규칙이 없지"를 묻는 사람이 반드시 나온다.
        self.assertEqual(self._decide("SKIP").status_code, 400)
        self.clause.refresh_from_db()
        self.assertEqual(self.clause.decision, "")

    def test_skip_with_reason_is_recorded(self):
        resp = self._decide("SKIP", "예외 승인 절차라 담당자 확인이 더 적절해요")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["ruleStatus"], "SKIPPED")
        self.clause.refresh_from_db()
        self.assertEqual(self.clause.decision, ClauseDecision.SKIP)
        self.assertIsNotNone(self.clause.decided_at)
        self.assertEqual(self.clause.decided_by.username, SERVICE_USERNAME)

    def test_reset_returns_to_needs_review(self):
        self._decide("SKIP", "사유")
        resp = self._decide("RESET")
        self.assertEqual(resp.data["ruleStatus"], "NEEDS_REVIEW")
        self.clause.refresh_from_db()
        self.assertEqual(self.clause.decision_reason, "")

    def test_reembed_keeps_the_human_decision(self):
        """재색인은 흔하다 — 그때마다 사람의 판단이 날아가면 같은 검토를 반복하게 된다."""
        self._decide("SKIP", "담당자 확인이 더 적절해요")
        _replace_clauses(self.doc, [
            {"articleLabel": "제9조", "articleTitle": "(사용 한도)", "body": "개정된 본문", "order": 0},
            {"articleLabel": "제10조", "body": "새 조항", "order": 1},
        ])
        kept = self.doc.clauses.get(article_label="제9조")
        self.assertEqual(kept.decision, ClauseDecision.SKIP)
        self.assertEqual(kept.decision_reason, "담당자 확인이 더 적절해요")
        self.assertEqual(kept.body, "개정된 본문")          # 본문은 새것으로 교체
        self.assertEqual(self.doc.clauses.get(article_label="제10조").decision, "")


@override_settings(MEDIA_ROOT="/tmp/skn-test-media")
class FolderTreeTests(TestCase):
    def setUp(self):
        ensure_service_account(password="pw")
        self.client = APIClient()
        self.client.login(username=SERVICE_USERNAME, password="pw")
        self.root = PolicyFolder.objects.create(name="사용정책")
        self.child = PolicyFolder.objects.create(name="법인카드", parent=self.root)

    def test_tree_counts_documents_including_children(self):
        PolicyDoc.objects.create(title="법인카드 사용규정", folder=self.child)
        PolicyDoc.objects.create(title="정책 개요", folder=self.root)
        resp = self.client.get("/api/policy-docs/folders/")
        self.assertEqual(resp.status_code, 200)
        root = resp.data["folders"][0]
        self.assertEqual(root["name"], "사용정책")
        self.assertEqual(root["docCount"], 2)          # 자기 1 + 하위 1
        self.assertEqual(root["children"][0]["docCount"], 1)

    def test_unfiled_documents_are_not_hidden(self):
        """폴더에 안 넣었다고 목록에서 사라지면 문서를 잃어버린다."""
        PolicyDoc.objects.create(title="미분류 규정")
        resp = self.client.get("/api/policy-docs/folders/")
        self.assertEqual([d["title"] for d in resp.data["unfiled"]], ["미분류 규정"])

    def test_move_document_between_folders(self):
        doc = PolicyDoc.objects.create(title="출장비 지침")
        resp = self.client.post(f"/api/policy-docs/{doc.pk}/move/", {"folderId": self.child.pk}, format="json")
        self.assertEqual(resp.status_code, 200)
        doc.refresh_from_db()
        self.assertEqual(doc.folder_id, self.child.pk)

        self.client.post(f"/api/policy-docs/{doc.pk}/move/", {"folderId": None}, format="json")
        doc.refresh_from_db()
        self.assertIsNone(doc.folder_id)

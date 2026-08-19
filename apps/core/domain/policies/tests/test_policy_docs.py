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

    def test_upload_accepts_profile_hint_and_folder(self):
        """문서 유형·폴더를 업로드 시 함께 정한다 — 올린 뒤 다시 손볼 일이 없게."""
        folder = PolicyFolder.objects.create(name="사용정책")
        with patch("domain.policies.policy_doc_views._dispatch", return_value="") as dispatch:
            resp = self.client.post("/api/policy-docs/", {
                "file": pdf(), "title": "법인세법", "profileHint": "LAW",
                "folderId": folder.pk,
            }, format="multipart")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["profileHint"], "LAW")
        self.assertEqual(resp.data["folderId"], folder.pk)
        # 지정값이 ai로 전달돼야 컬렉션 라우팅이 바뀐다(LAW → tax_refs).
        self.assertEqual(dispatch.call_args.args[0].profile_hint, "LAW")

    def test_unknown_profile_hint_is_rejected(self):
        with patch("domain.policies.policy_doc_views._dispatch") as dispatch:
            resp = self.client.post("/api/policy-docs/",
                                    {"file": pdf(), "profileHint": "WAT"}, format="multipart")
        self.assertEqual(resp.status_code, 400)
        dispatch.assert_not_called()

    def test_non_pdf_is_rejected_before_dispatch(self):
        bad = SimpleUploadedFile("규정.docx", b"x", content_type="application/msword")
        with patch("domain.policies.policy_doc_views._dispatch") as dispatch:
            resp = self.client.post("/api/policy-docs/", {"file": bad}, format="multipart")
        self.assertEqual(resp.status_code, 400)
        dispatch.assert_not_called()

    def test_html_disguised_as_pdf_is_rejected(self):
        """확장자는 이름일 뿐이다 — `inline`으로 되돌려줄 파일이라 내용을 확인한다."""
        evil = SimpleUploadedFile(
            "규정.pdf", b"<html><script>alert(1)</script></html>", content_type="application/pdf",
        )
        with patch("domain.policies.policy_doc_views._dispatch") as dispatch:
            resp = self.client.post("/api/policy-docs/", {"file": evil}, format="multipart")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("PDF 형식과 다릅니다", resp.data["detail"])
        dispatch.assert_not_called()
        self.assertFalse(PolicyDoc.objects.exists())   # 저장도 되지 않는다

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
class DocumentFileTests(TestCase):
    """원본 PDF 서빙 — `MEDIA_URL`로 열지 않고 인가를 태운 `/api/` 경로로 내보낸다."""

    def setUp(self):
        ensure_service_account(password="pw")
        self.client = APIClient()
        self.client.login(username=SERVICE_USERNAME, password="pw")
        with patch("domain.policies.policy_doc_views._dispatch", return_value=""):
            resp = self.client.post("/api/policy-docs/", {"file": pdf(), "title": "법인카드 사용규정"},
                                    format="multipart")
        self.doc_id = resp.data["id"]

    def _url(self, download=False):
        return f"/api/policy-docs/{self.doc_id}/file/" + ("?download=1" if download else "")

    def test_serves_pdf_inline(self):
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        # inline이라야 새 탭에서 브라우저 내장 뷰어가 렌더한다(attachment면 다운로드된다).
        self.assertIn("inline", resp["Content-Disposition"])
        self.assertEqual(b"".join(resp.streaming_content), b"%PDF-1.4 fake")

    def test_inline_response_forbids_mime_sniffing(self):
        """inline + 업로드 파일은 저장형 XSS의 고전 조합 — 스니핑을 막아야 한다."""
        resp = self.client.get(self._url())
        self.assertEqual(resp["X-Content-Type-Options"], "nosniff")

    def test_download_flag_switches_to_attachment(self):
        resp = self.client.get(self._url(download=True))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("attachment", resp["Content-Disposition"])

    def test_requires_rule_view(self):
        """규정 원문은 사내 문서다 — 목록만 막고 원본이 열려 있으면 통제가 무의미하다."""
        self.client.logout()
        self.assertEqual(self.client.get(self._url()).status_code, 403)

        User.objects.create_user("nobody", password="pw", role=Role.EMPLOYEE)
        self.client.login(username="nobody", password="pw")
        self.assertEqual(self.client.get(self._url()).status_code, 403)

    def test_missing_file_reports_reason(self):
        """DB엔 있는데 볼륨에서 사라진 경우 — 빈 화면 대신 사유를 준다."""
        doc = PolicyDoc.objects.create(title="파일 없는 문서")
        resp = self.client.get(f"/api/policy-docs/{doc.pk}/file/")
        self.assertEqual(resp.status_code, 404)
        self.assertIn("원본 파일이 없습니다", resp.data["detail"])


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
            "ruleTrigger": {"status": "DRAFT_SAVED", "detail": "자동 생성 완료 — 그래프 #7 (DRAFT)"},
        }, format="json")
        self.assertEqual(resp.status_code, 200)

        self.doc.refresh_from_db()
        self.assertEqual(self.doc.status, IngestStatus.DONE)
        self.assertEqual(self.doc.chunk_count, 103)
        self.assertEqual(self.doc.leaf_count, 90)
        self.assertEqual(self.doc.collection, "policy_docs")
        self.assertIsNotNone(self.doc.indexed_at)
        # 트리거 결과는 뭉개지 않고 그대로 저장돼 화면까지 간다(성공/건너뜀/실패 구분).
        self.assertEqual(self.doc.rule_trigger["status"], "DRAFT_SAVED")

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

    def test_rename_folder(self):
        resp = self.client.post(f"/api/policy-docs/folders/{self.child.pk}/",
                                 {"name": "법인카드 규정"}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.child.refresh_from_db()
        self.assertEqual(self.child.name, "법인카드 규정")

    def test_rename_rejects_duplicate_in_same_parent(self):
        PolicyFolder.objects.create(name="출장", parent=self.root)
        resp = self.client.post(f"/api/policy-docs/folders/{self.child.pk}/",
                                 {"name": "출장"}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_delete_empty_folder(self):
        empty = PolicyFolder.objects.create(name="빈 폴더")
        resp = self.client.delete(f"/api/policy-docs/folders/{empty.pk}/")
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(PolicyFolder.objects.filter(pk=empty.pk).exists())

    def test_delete_refuses_when_not_empty(self):
        """문서는 SET_NULL로 살아남지만, 정리해 둔 분류가 한 번의 클릭으로 날아가면 안 된다."""
        PolicyDoc.objects.create(title="문서", folder=self.child)
        resp = self.client.delete(f"/api/policy-docs/folders/{self.child.pk}/")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("문서 1건", resp.data["detail"])
        self.assertTrue(PolicyFolder.objects.filter(pk=self.child.pk).exists())

        # 하위 폴더가 있어도 마찬가지(CASCADE로 통째로 지워지는 걸 막는다).
        resp = self.client.delete(f"/api/policy-docs/folders/{self.root.pk}/")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("하위 폴더 1개", resp.data["detail"])

    def test_move_document_between_folders(self):
        doc = PolicyDoc.objects.create(title="출장비 지침")
        resp = self.client.post(f"/api/policy-docs/{doc.pk}/move/", {"folderId": self.child.pk}, format="json")
        self.assertEqual(resp.status_code, 200)
        doc.refresh_from_db()
        self.assertEqual(doc.folder_id, self.child.pk)

        self.client.post(f"/api/policy-docs/{doc.pk}/move/", {"folderId": None}, format="json")
        doc.refresh_from_db()
        self.assertIsNone(doc.folder_id)

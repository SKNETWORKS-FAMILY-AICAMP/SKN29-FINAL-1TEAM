from django.db import IntegrityError, transaction
from django.test import TestCase

from domain.policies.models import RuleGraph, RuleGraphStatus, RuleNode
from domain.policies.services import activate, create_draft_version, create_graph_draft


class RuleGraphVersioningTests(TestCase):
    def setUp(self):
        self.active = RuleGraph.objects.create(
            name="식대 검증",
            scope="식대",
            status=RuleGraphStatus.ACTIVE,
            version=1,
            entry_node_key="entry",
        )
        RuleNode.objects.create(
            graph=self.active,
            node_key="entry",
            condition=True,
            action={"decision": "PASS"},
        )

    def test_existing_graph_is_cloned_as_next_draft_version(self):
        draft = create_draft_version(self.active)
        self.assertEqual(draft.family_key, self.active.family_key)
        self.assertEqual(draft.version, 2)
        self.assertEqual(draft.status, RuleGraphStatus.DRAFT)
        self.assertEqual(list(draft.nodes.values_list("node_key", flat=True)), ["entry"])
        self.active.refresh_from_db()
        self.assertEqual(self.active.status, RuleGraphStatus.ACTIVE)

    def test_only_one_active_graph_is_allowed_per_scope(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                RuleGraph.objects.create(name="다른 식대", scope="식대", status=RuleGraphStatus.ACTIVE)

    def test_activate_archives_previous_scope_version(self):
        draft = create_draft_version(self.active)
        activate(draft)
        self.active.refresh_from_db()
        draft.refresh_from_db()
        self.assertEqual(self.active.status, RuleGraphStatus.ARCHIVED)
        self.assertEqual(draft.status, RuleGraphStatus.ACTIVE)

    def test_new_graph_scope_must_be_real_category(self):
        with self.assertRaises(ValueError):
            create_graph_draft("후정산", "후정산")

import uuid

from django.db import migrations, models
from django.db.models import Q


def assign_family_keys(apps, schema_editor):
    RuleGraph = apps.get_model("policies", "RuleGraph")
    for graph in RuleGraph.objects.filter(family_key__isnull=True).iterator():
        graph.family_key = uuid.uuid4()
        graph.save(update_fields=["family_key"])


def normalize_legacy_scopes(apps, schema_editor):
    RuleGraph = apps.get_model("policies", "RuleGraph")
    valid = {"GLOBAL", "업무활성", "회의", "식대", "출장", "접대", "비품"}
    aliases = {"기업업무추진비": "접대", "회식": "식대"}
    for graph in RuleGraph.objects.exclude(scope__in=valid).iterator():
        # 결제수단 등 과거 mock scope는 비용분류가 아니므로 일반 업무활성으로 수렴한다.
        graph.scope = aliases.get(graph.scope, "업무활성")
        graph.save(update_fields=["scope"])


def deduplicate_active_scopes(apps, schema_editor):
    RuleGraph = apps.get_model("policies", "RuleGraph")
    active_scopes = RuleGraph.objects.filter(status="ACTIVE").values_list("scope", flat=True).distinct()
    for scope in active_scopes:
        active = RuleGraph.objects.filter(scope=scope, status="ACTIVE").order_by("-version", "-id")
        keep = active.first()
        if keep:
            active.exclude(pk=keep.pk).update(status="ARCHIVED")


def normalize_version_and_routing_constraints(apps, schema_editor):
    RuleGraphVersion = apps.get_model("policies", "RuleGraphVersion")
    RuleRouting = apps.get_model("policies", "RuleRouting")
    graph_ids = RuleGraphVersion.objects.filter(is_active=True).values_list("graph_id", flat=True).distinct()
    for graph_id in graph_ids:
        active = RuleGraphVersion.objects.filter(graph_id=graph_id, is_active=True).order_by("-version", "-id")
        keep = active.first()
        if keep:
            active.exclude(pk=keep.pk).update(is_active=False)

    seen = set()
    duplicate_ids = []
    for route in RuleRouting.objects.order_by("id").iterator():
        key = (route.graph_id, route.from_node_key, route.on_result, route.priority)
        if key in seen:
            duplicate_ids.append(route.id)
        else:
            seen.add(key)
    if duplicate_ids:
        RuleRouting.objects.filter(id__in=duplicate_ids).delete()


class Migration(migrations.Migration):
    dependencies = [("policies", "0002_rulehit_eval_context")]

    operations = [
        migrations.AddField(
            model_name="rulegraph",
            name="family_key",
            field=models.UUIDField(db_index=True, null=True),
        ),
        migrations.RunPython(assign_family_keys, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="rulegraph",
            name="family_key",
            field=models.UUIDField(db_index=True, default=uuid.uuid4),
        ),
        migrations.AlterField(
            model_name="rulegraph",
            name="scope",
            field=models.CharField(
                choices=[
                    ("GLOBAL", "공통 필수 게이트"),
                    ("업무활성", "업무활성"),
                    ("회의", "회의"),
                    ("식대", "식대"),
                    ("출장", "출장"),
                    ("접대", "접대"),
                    ("비품", "비품"),
                ],
                default="GLOBAL",
                max_length=20,
            ),
        ),
        migrations.RunPython(normalize_legacy_scopes, migrations.RunPython.noop),
        migrations.RunPython(deduplicate_active_scopes, migrations.RunPython.noop),
        migrations.RunPython(normalize_version_and_routing_constraints, migrations.RunPython.noop),
        migrations.AlterUniqueTogether(name="rulegraphversion", unique_together=set()),
        migrations.AddConstraint(
            model_name="rulegraph",
            constraint=models.UniqueConstraint(
                fields=("family_key", "version"), name="uq_rulegraph_family_version"
            ),
        ),
        migrations.AddConstraint(
            model_name="rulegraph",
            constraint=models.UniqueConstraint(
                condition=Q(status="ACTIVE"), fields=("scope",), name="uq_rulegraph_active_scope"
            ),
        ),
        migrations.AddConstraint(
            model_name="rulegraph",
            constraint=models.CheckConstraint(
                condition=Q(scope__in=["GLOBAL", "업무활성", "회의", "식대", "출장", "접대", "비품"]),
                name="ck_rulegraph_scope",
            ),
        ),
        migrations.AddConstraint(
            model_name="rulegraphversion",
            constraint=models.UniqueConstraint(
                fields=("graph", "version"), name="uq_graph_snapshot_version"
            ),
        ),
        migrations.AddConstraint(
            model_name="rulegraphversion",
            constraint=models.UniqueConstraint(
                condition=Q(is_active=True), fields=("graph",), name="uq_graph_active_snapshot"
            ),
        ),
        migrations.AddConstraint(
            model_name="rulerouting",
            constraint=models.UniqueConstraint(
                fields=("graph", "from_node_key", "on_result", "priority"),
                name="uq_rule_routing_priority",
            ),
        ),
    ]

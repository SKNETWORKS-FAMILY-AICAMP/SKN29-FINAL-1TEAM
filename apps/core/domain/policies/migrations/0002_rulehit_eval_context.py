from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("policies", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="rulehit",
            name="eval_context",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="rulehit",
            name="flags",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="rulehit",
            name="eval_context_schema_version",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="rulehit",
            name="builder_version",
            field=models.CharField(blank=True, max_length=20),
        ),
    ]

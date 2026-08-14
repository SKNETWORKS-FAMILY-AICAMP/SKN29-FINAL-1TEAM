"""2/3 — RuleGraph.scope 데이터 이관 (0009에서 넓힌 제약 안에서 실행, 0011에서 좁힌다).

① '업무활성' → 'TEST_DEMO': '업무활성'이 Category에서 폐지되고 '회식'으로 대체되며,
   남아있던 유일한 '업무활성' scope 그래프(seed_rules.py TEST 픽스처, "규정 근거 없음"
   구조 검증용)가 진짜 카테고리 이름과 충돌하게 됐다.
② 회식비 검증 그래프의 '식대' → '회식': '회식'이 Category.MEAL의 별칭으로 식대 scope에
   얹혀가던 시절 만들어진 그래프라 지금은 scope="식대"인데, '회식'이 독립 카테고리가 된
   지금은 제자리(scope="회식")로 옮겨야 순수 식대 정산이 회식 전용 룰에 잘못 걸리지 않는다.
둘 다 `seed_rules.py`를 재실행해도 같은 값으로 맞춰진다 — 이 마이그레이션은 재실행 없이도
기존 DB가 즉시 정합을 갖추게 한다.
"""
from django.db import migrations


def rename_scope(apps, schema_editor):
    RuleGraph = apps.get_model('policies', 'RuleGraph')
    RuleGraph.objects.filter(scope='업무활성').update(scope='TEST_DEMO')
    RuleGraph.objects.filter(scope='식대', name='회식비 검증 그래프').update(scope='회식')


def reverse(apps, schema_editor):
    RuleGraph = apps.get_model('policies', 'RuleGraph')
    RuleGraph.objects.filter(scope='TEST_DEMO').update(scope='업무활성')
    RuleGraph.objects.filter(scope='회식', name='회식비 검증 그래프').update(scope='식대')


class Migration(migrations.Migration):

    dependencies = [
        ('policies', '0009_widen_rulegraph_scope_constraint'),
    ]

    operations = [
        migrations.RunPython(rename_scope, reverse),
    ]
